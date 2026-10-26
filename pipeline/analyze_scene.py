"""Run and archive one scene through the shared processing core."""

from __future__ import annotations

import argparse
import json
from datetime import UTC, datetime, timedelta

from core.config import ROOT, zones
from core.engine import analyze
from core.models import AnalyzeRequest, ArchiveEntry, ArchiveGeoJSON, ArchiveIndex


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--zone", choices=[zone.id for zone in zones().zones], required=True)
    parser.add_argument("--scene-id", help="Exact STAC scene ID; otherwise search the latest 14 days")
    parser.add_argument("--force", action="store_true", help="Reprocess a scene already in the archive")
    args = parser.parse_args()
    zone = next(item for item in zones().zones if item.id == args.zone)
    archive = ROOT / "data" / "archive"
    index_path = archive / "index.json"
    index = (
        ArchiveIndex.model_validate_json(index_path.read_text(encoding="utf-8"))
        if index_path.exists()
        else ArchiveIndex(entries=[])
    )
    if args.scene_id and not args.force and any(entry.scene_id == args.scene_id for entry in index.entries):
        print(f"Already archived: {args.scene_id}")
        return
    now = datetime.now(UTC)
    request = AnalyzeRequest(
        aoi=zone.bbox,
        scene_id=args.scene_id,
        start=None if args.scene_id else now - timedelta(days=14),
        end=None if args.scene_id else now,
    )
    result, assets = analyze(request)
    result.zone = zone.id
    folder = archive / zone.id / result.acquisition_time.date().isoformat()
    folder.mkdir(parents=True, exist_ok=True)
    target = folder / f"{result.id}.geojson"
    feature_collection = ArchiveGeoJSON.model_validate(
        {
            "type": "FeatureCollection",
            "data_label": "REAL Sentinel-1",
            "features": [feature.model_dump(mode="json") for feature in result.candidates.features],
        }
    )
    temporary = target.with_suffix(".tmp")
    temporary.write_text(feature_collection.model_dump_json(), encoding="utf-8")
    temporary.replace(target)
    (folder / f"{result.id}-raw.webp").write_bytes(assets["preview-raw-fixed.webp"])
    (folder / f"{result.id}-filtered.webp").write_bytes(assets["preview-filtered-fixed.webp"])
    entry = ArchiveEntry(
        id=result.id,
        zone=zone.id,
        scene_id=result.scene_id,
        acquisition_time=result.acquisition_time,
        satellite=result.satellite,
        orbit_direction=result.orbit_direction,
        polarization=result.polarization,
        stac_href=result.stac_href,
        count=len(result.candidates.features),
        total_area_km2=result.total_area_km2,
        path=target.relative_to(archive).as_posix(),
        preview_raw=(folder / f"{result.id}-raw.webp").relative_to(archive).as_posix(),
        preview_filtered=(folder / f"{result.id}-filtered.webp").relative_to(archive).as_posix(),
        preview_bounds=result.preview_bounds,
        scene_footprint=result.scene_footprint,
        coastline=result.coastline,
        qa=result.qa,
    )
    index.entries = [existing for existing in index.entries if existing.scene_id != result.scene_id]
    index.entries.append(entry)
    index_tmp = index_path.with_suffix(".tmp")
    index_tmp.write_text(index.model_dump_json(indent=2), encoding="utf-8")
    index_tmp.replace(index_path)
    total_bytes = sum(file.stat().st_size for file in archive.rglob("*") if file.is_file())
    if total_bytes > 50 * 1024 * 1024:
        raise RuntimeError(f"Archive exceeds 50 MB ({total_bytes} bytes)")
    print(
        json.dumps(
            {
                "zone": zone.id,
                "scene_id": result.scene_id,
                "acquisition_time": result.acquisition_time.isoformat(),
                "candidate_count": len(result.candidates.features),
                "total_area_km2": result.total_area_km2,
                "qa": result.qa.model_dump(mode="json"),
                "archive_file": str(target.relative_to(ROOT)),
                "archive_bytes": total_bytes,
            }
        )
    )


if __name__ == "__main__":
    main()
