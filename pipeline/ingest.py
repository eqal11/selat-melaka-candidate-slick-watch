"""Idempotently archive real Sentinel-1 observations and matching SAR previews."""

from __future__ import annotations

import argparse
import json
import sys
import tempfile
from datetime import UTC, datetime, timedelta
from pathlib import Path

from core.config import ROOT, zones
from core.engine import analyze
from core.models import AnalyzeRequest, ArchiveEntry, ArchiveGeoJSON, ArchiveIndex
from core.scenes import search

ARCHIVE = ROOT / "data" / "archive"


def ingest(days: int = 60) -> dict:
    ARCHIVE.mkdir(parents=True, exist_ok=True)
    index_path = ARCHIVE / "index.json"
    index = (
        ArchiveIndex.model_validate_json(index_path.read_text(encoding="utf-8"))
        if index_path.exists()
        else ArchiveIndex(entries=[])
    )
    known = {(entry.zone, entry.scene_id) for entry in index.entries}
    end = datetime.now(UTC)
    start = end - timedelta(days=days)
    staged_entries: list[ArchiveEntry] = []
    total_items = 0
    stage = Path(tempfile.mkdtemp(prefix="archive-stage-", dir=ROOT / "work"))
    staged_files: list[Path] = []
    for zone in zones().zones:
        listing, items = search(zone.bbox, start, end)
        print(f"{zone.id}: {len(items)} scenes; coverage={listing.coverage}", flush=True)
        total_items += len(items)
        for item in items:
            if (zone.id, item.id) in known:
                continue
            result, assets = analyze(AnalyzeRequest(aoi=zone.bbox, scene_id=item.id))
            result.zone = zone.id
            folder = stage / zone.id / result.acquisition_time.date().isoformat()
            folder.mkdir(parents=True, exist_ok=True)
            filename = f"{result.id}"
            collection = ArchiveGeoJSON.model_validate(
                {
                    "type": "FeatureCollection",
                    "data_label": "REAL Sentinel-1",
                    "features": [feature.model_dump(mode="json") for feature in result.candidates.features],
                }
            )
            geojson_path = folder / f"{filename}.geojson"
            geojson_path.write_text(collection.model_dump_json(), encoding="utf-8")
            staged_files.append(geojson_path)
            raw_name, filtered_name = f"{filename}-raw.webp", f"{filename}-filtered.webp"
            (folder / raw_name).write_bytes(assets["preview-raw-fixed.webp"])
            (folder / filtered_name).write_bytes(assets["preview-filtered-fixed.webp"])
            staged_files.extend([folder / raw_name, folder / filtered_name])
            entry = ArchiveEntry(
                id=result.id,
                zone=zone.id,
                scene_id=result.scene_id,
                satellite=result.satellite,
                orbit_direction=result.orbit_direction,
                polarization=result.polarization,
                stac_href=result.stac_href,
                acquisition_time=result.acquisition_time,
                count=len(result.candidates.features),
                total_area_km2=result.total_area_km2,
                path=(
                    Path(zone.id) / result.acquisition_time.date().isoformat() / geojson_path.name
                ).as_posix(),
                preview_raw=(
                    Path(zone.id) / result.acquisition_time.date().isoformat() / raw_name
                ).as_posix(),
                preview_filtered=(
                    Path(zone.id) / result.acquisition_time.date().isoformat() / filtered_name
                ).as_posix(),
                preview_bounds=result.preview_bounds,
                scene_footprint=result.scene_footprint,
                coastline=result.coastline,
                qa=result.qa,
            )
            staged_entries.append(entry)
            known.add((zone.id, item.id))
            print(
                f"{zone.id} {item.id}: candidates={len(result.candidates.features)} area_km2={result.total_area_km2:.3f} funnel={result.qa.funnel}",
                flush=True,
            )
    # Check the cap before touching the permanent archive; a failed run leaves it unchanged.
    existing_bytes = sum(path.stat().st_size for path in ARCHIVE.rglob("*") if path.is_file())
    staged_bytes = sum(path.stat().st_size for path in staged_files)
    if existing_bytes + staged_bytes > 50 * 1024 * 1024:
        raise RuntimeError(
            f"Archive would exceed 50 MB ({existing_bytes + staged_bytes} bytes); no files were committed"
        )
    # Commit staged files only if every requested scene completed successfully.
    for source in staged_files:
        relative = source.relative_to(stage)
        target = ARCHIVE / relative
        target.parent.mkdir(parents=True, exist_ok=True)
        source.replace(target)
    index.entries.extend(staged_entries)
    index.entries.sort(key=lambda entry: (entry.acquisition_time, entry.zone, entry.scene_id))
    size = sum(
        path.stat().st_size for path in ARCHIVE.rglob("*") if path.is_file() and path.name != "index.json"
    )
    if size > 50 * 1024 * 1024:
        raise RuntimeError(f"Archive exceeds 50 MB ({size} bytes); no index was updated")
    temporary_index = index_path.with_suffix(".tmp")
    temporary_index.write_text(index.model_dump_json(indent=2), encoding="utf-8")
    temporary_index.replace(index_path)
    return {
        "scenes_considered": total_items,
        "new_entries": len(staged_entries),
        "archive_bytes": size,
        "days": days,
    }


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--days", type=int, choices=range(1, 91), default=60)
    args = parser.parse_args()
    print(json.dumps(ingest(args.days), indent=2), flush=True)


if __name__ == "__main__":
    try:
        main()
    except Exception as exc:
        print(f"INGEST FAILED: {type(exc).__name__}: {exc}", file=sys.stderr)
        raise SystemExit(1) from exc
