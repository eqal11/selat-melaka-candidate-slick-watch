"""Scheduled idempotent archive ingestion. Never writes on a failed scene."""

from __future__ import annotations

import json
import sys
from datetime import UTC, datetime, timedelta

from core.config import ROOT, zones
from core.engine import analyze
from core.models import AnalyzeRequest, ArchiveGeoJSON
from core.scenes import search

ARCHIVE = ROOT / "data" / "archive"


def main() -> None:
    ARCHIVE.mkdir(parents=True, exist_ok=True)
    index_path = ARCHIVE / "index.json"
    index = json.loads(index_path.read_text()) if index_path.exists() else {"version": 1, "entries": []}
    known = {entry["scene_id"] for entry in index["entries"]}
    end = datetime.now(UTC)
    start = end - timedelta(days=14)
    for zone in zones().zones:
        listing, items = search(zone.bbox, start, end)
        print(f"{zone.id}: {len(items)} scenes; RTC report={listing.coverage}", flush=True)
        for item in items:
            if item.id in known:
                continue
            request = AnalyzeRequest(aoi=zone.bbox, scene_id=item.id)
            result, _ = analyze(request)
            result.zone = zone.id
            day = result.acquisition_time.date().isoformat()
            folder = ARCHIVE / zone.id / day
            folder.mkdir(parents=True, exist_ok=True)
            relative = folder / f"{result.id}.geojson"
            collection = {
                "type": "FeatureCollection",
                "data_label": "OBSERVATION",
                "features": [feature.model_dump(mode="json") for feature in result.candidates.features],
            }
            temporary = relative.with_suffix(".tmp")
            validated = ArchiveGeoJSON.model_validate(collection)
            temporary.write_text(validated.model_dump_json(), encoding="utf-8")
            temporary.replace(relative)
            index["entries"].append(
                {
                    "id": result.id,
                    "zone": zone.id,
                    "scene_id": result.scene_id,
                    "acquisition_time": result.acquisition_time.isoformat(),
                    "data_label": "OBSERVATION",
                    "count": len(result.candidates.features),
                    "total_area_km2": result.total_area_km2,
                    "path": relative.relative_to(ARCHIVE).as_posix(),
                    "qa": result.qa.model_dump(mode="json"),
                }
            )
            known.add(item.id)
    temporary_index = index_path.with_suffix(".tmp")
    temporary_index.write_text(json.dumps(index, indent=2), encoding="utf-8")
    temporary_index.replace(index_path)
    size = sum(path.stat().st_size for path in ARCHIVE.rglob("*") if path.is_file())
    if size > 50 * 1024 * 1024:
        raise RuntimeError(f"Archive exceeds 50 MB ({size} bytes)")
    print(f"Archive size={size} bytes, entries={len(index['entries'])}")


if __name__ == "__main__":
    try:
        main()
    except Exception as exc:
        print(f"INGEST FAILED: {type(exc).__name__}: {exc}", file=sys.stderr)
        sys.exit(1)
