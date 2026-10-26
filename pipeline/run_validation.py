"""Search real catalogs and process case-scoped Sentinel-1 RTC/GRD scenes.

The runner uses only source-published case coordinates and a 60 x 60 km maximum
AOI. It checkpoints results under validation/results/cases/, records failures,
and does not claim a detector outcome when raster processing fails.
"""

from __future__ import annotations

import argparse
import json
import logging
import re
from datetime import UTC, datetime, timedelta
from math import hypot
from pathlib import Path
from typing import Any

import requests
import yaml
from pyproj import Geod
from pystac import Item
from pystac_client import Client
from shapely.geometry import shape

from core import conditions
from core.engine import process_arrays
from core.loading import load
from core.models import Parameters

ROOT = Path(__file__).resolve().parents[1]
OUT = ROOT / "validation" / "results" / "cases"
CATALOGS = {
    "Planetary Computer": "https://planetarycomputer.microsoft.com/api/stac/v1",
    "Copernicus Data Space": "https://catalogue.dataspace.copernicus.eu/stac",
}
ASF = "https://api.daac.asf.alaska.edu/services/search/param"
EP = {
    "Planetary Computer STAC": CATALOGS["Planetary Computer"],
    "Copernicus Data Space STAC": CATALOGS["Copernicus Data Space"],
    "Copernicus Data Space OData": "https://catalogue.dataspace.copernicus.eu/odata/v1/Products?$top=1",
    "ASF search": ASF + "?platform=SENTINEL-1&processingLevel=GRD_HD&output=json&maxResults=1",
    "Open-Meteo forecast": "https://api.open-meteo.com/v1/forecast?latitude=3&longitude=101&current=wind_speed_10m",
    "Open-Meteo marine": "https://marine-api.open-meteo.com/v1/marine?latitude=3&longitude=101&current=ocean_current_velocity",
}


def connectivity():
    OUT.mkdir(parents=True, exist_ok=True)
    endpoints: dict[str, Any] = {}
    report: dict[str, Any] = {"checked_at_utc": datetime.now(UTC).isoformat(), "endpoints": endpoints}
    for name, url in EP.items():
        try:
            r = requests.get(url, timeout=(8, 20), headers={"User-Agent": "SelatCandidateReview/0.1"})
            endpoints[name] = {"http_status": r.status_code, "ok": r.ok}
            print(f"{name}: HTTP {r.status_code}", flush=True)
        except Exception as exc:
            endpoints[name] = {"http_status": None, "error": f"{type(exc).__name__}: {exc}"}
            print(f"{name}: NO HTTP RESPONSE — {type(exc).__name__}: {exc}", flush=True)
    (OUT.parent / "connectivity-latest.json").write_text(json.dumps(report, indent=2), encoding="utf-8")
    return report


def catalog_items(url: str, bbox: list[float], start: datetime, end: datetime) -> list[Item]:
    c = Client.open(url, timeout=25)
    found: list[Item] = []
    # Query only analysis-ready Sentinel-1 RTC and GRD products. Other S1
    # collections (ETAD, SLC, mosaics) are not detector inputs and can trigger
    # needless catalog traffic and rate limiting.
    try:
        advertised = {collection.id.lower(): collection.id for collection in c.get_collections()}
    except Exception as exc:
        raise RuntimeError(f"Could not list STAC collections at {url}: {exc}") from exc
    collection_ids = [
        advertised[name] for name in ("sentinel-1-rtc", "sentinel-1-grd") if name in advertised
    ]
    if not collection_ids:
        raise RuntimeError(f"No Sentinel-1 RTC or GRD collection advertised by STAC catalog {url}")
    for collection_id in collection_ids:
        try:
            items = list(
                c.search(
                    collections=[collection_id],
                    bbox=bbox,
                    datetime=f"{start.isoformat()}/{end.isoformat()}",
                    limit=100,
                ).items()
            )
        except Exception as exc:
            raise RuntimeError(f"{collection_id}: {exc}") from exc
        if items:
            return items
    return found


def acquisition_key(scene_id: str) -> str:
    """Collapse RTC/GRD catalog representations of the same Sentinel-1 acquisition."""
    match = re.match(
        r"^(S1[A-Z]_[^_]+_[^_]+_[^_]+_\d{8}T\d{6}_\d{8}T\d{6}_\d+_[0-9A-F]+)",
        scene_id,
        re.IGNORECASE,
    )
    return match.group(1) if match else scene_id


PROCESSING_VERSION = 3


def case_aoi(point: list[float]) -> tuple[float, float, float, float]:
    """A compact 0.12-degree square context AOI, with a geodesic 60 km hard cap."""
    lon, lat = map(float, point)
    radius = 0.06
    bbox = (lon - radius, lat - radius, lon + radius, lat + radius)
    geod = Geod(ellps="WGS84")
    width = abs(geod.inv(bbox[0], lat, bbox[2], lat)[2])
    height = abs(geod.inv(lon, bbox[1], lon, bbox[3])[2])
    if width > 60_000 or height > 60_000:
        raise ValueError("Case processing AOI exceeds the 60 x 60 km cap")
    return bbox


def process_case_scene(item: Item, bbox: tuple[float, float, float, float]):
    params = Parameters.model_validate({})
    power, affine, crs = load(item, bbox, params)
    acquired = item.datetime
    if acquired is None:
        raise ValueError(f"STAC item {item.id} has no acquisition timestamp")
    forcing = conditions.fetch((bbox[0] + bbox[2]) / 2, (bbox[1] + bbox[3]) / 2, acquired)
    result, assets = process_arrays(
        power, affine, crs, bbox, acquired, item, params, forcing,
        ports_data=[], analysis_scope="validation_case"
    )
    if result.qa.valid_pixel_percent < 80 or result.qa.stac_footprint_overlap_percent < 80:
        raise RuntimeError(
            "Insufficient scene coverage: "
            f"valid pixels {result.qa.valid_pixel_percent:.1f}%, "
            f"STAC footprint overlap {result.qa.stac_footprint_overlap_percent:.1f}%; "
            "minimum required for a detector result is 80% for both."
        )
    return result, assets


def asf_records(bbox: list[float], start: datetime, end: datetime) -> list[dict[str, Any]]:
    west, south, east, north = bbox
    polygon = f"POLYGON(({west} {south},{east} {south},{east} {north},{west} {north},{west} {south}))"
    params: dict[str, str | int] = {
        "platform": "SENTINEL-1",
        "processingLevel": "GRD_HD",
        "intersectsWith": polygon,
        "start": start.date().isoformat(),
        "end": end.date().isoformat(),
        "output": "json",
        "maxResults": 100,
    }
    response = requests.get(
        ASF,
        params=params,
        timeout=(8, 30),
        headers={"User-Agent": "SelatCandidateReview/0.2"},
    )
    response.raise_for_status()
    payload = response.json()

    def records(value: Any):
        if isinstance(value, list):
            for element in value:
                yield from records(element)
        elif isinstance(value, dict):
            features = value.get("features")
            if isinstance(features, list):
                yield from records(features)
            else:
                yield value

    source_records = list(records(payload))
    normalized = []
    for source in source_records:
        properties = source.get("properties", source)
        if not isinstance(properties, dict):
            properties = source
        scene_id = properties.get("sceneName") or properties.get("granuleName") or properties.get("fileName")
        timestamp = properties.get("startTime") or properties.get("fileDate")
        if not scene_id or not timestamp:
            continue
        acquired = datetime.fromisoformat(str(timestamp).replace("Z", "+00:00")).astimezone(UTC)
        normalized.append(
            {
                "scene_id": str(scene_id),
                "catalog": "ASF",
                "acquisition_time_utc": acquired.isoformat(),
                "collection": properties.get("processingLevel"),
            }
        )
    return normalized


def main():
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--dry-run", action="store_true", help="connectivity only")
    ap.add_argument("--resume", action="store_true", help="reuse completed case checkpoints")
    ap.add_argument("--case-id", help="run one case ID from validation/cases.yaml")
    ap.add_argument("--search-only", action="store_true", help="search catalogs without raster processing")
    ap.add_argument("--seep-start", default="2017-01-01")
    ap.add_argument("--seep-end", default=datetime.now(UTC).date().isoformat())
    args = ap.parse_args()
    net = connectivity()
    if args.dry_run:
        if any(
            v.get("http_status") is None or v.get("http_status", 500) >= 500
            for v in net["endpoints"].values()
        ):
            raise SystemExit("DRY RUN FAILED: see validation/results/connectivity-latest.json")
        return
    case_file = yaml.safe_load((ROOT / "validation" / "cases.yaml").read_text(encoding="utf-8"))
    OUT.mkdir(parents=True, exist_ok=True)
    cases = case_file["cases"]
    if args.case_id:
        cases = [case for case in cases if case["id"] == args.case_id]
        if not cases:
            raise SystemExit(f"Unknown case ID: {args.case_id}")
    for case in cases:
        target = OUT / f"{case['id']}.json"
        if args.resume and target.exists():
            try:
                checkpoint = json.loads(target.read_text(encoding="utf-8"))
            except (OSError, json.JSONDecodeError):
                checkpoint = {}
            checkpoint_current = checkpoint.get("processing_version") == PROCESSING_VERSION
            if checkpoint.get("status") == "not_searchable_without_source_coordinates" or (
                checkpoint_current
                and (
                    checkpoint.get("status") == "processed"
                    or (checkpoint.get("status") == "no_scene" and not checkpoint.get("catalog_errors"))
                )
            ):
                print(f"RESUME {case['id']}: completed search checkpoint retained", flush=True)
                continue
            print(f"RESUME {case['id']}: retrying incomplete/failed checkpoint", flush=True)
        result = {
            "case_id": case["id"],
            "processing_version": PROCESSING_VERSION,
            "status": "searching",
            "source_urls": [x["url"] for x in case.get("sources", [])],
            "catalog_results": [],
            "detector_result": None,
        }
        try:
            point = case.get("location_coordinates")
            if not point:
                result["status"] = "not_searchable_without_source_coordinates"
                result["reason"] = (
                    "No published numeric source coordinate in cases.yaml; no coordinates were inferred."
                )
            else:
                bbox_case = case_aoi(point)
                lon, lat = map(float, point)
                discovery_bbox = [lon - 0.3, lat - 0.3, lon + 0.3, lat + 0.3]
                if case["category"] == "natural_seep":
                    start = datetime.fromisoformat(args.seep_start).replace(tzinfo=UTC)
                    end = datetime.fromisoformat(args.seep_end).replace(tzinfo=UTC) + timedelta(days=1)
                    sample = 10
                else:
                    incident = datetime.fromisoformat(case["incident_date"]).replace(tzinfo=UTC)
                    start = incident - timedelta(days=3)
                    end = incident + timedelta(days=3)
                    sample = None
                found: list[tuple[str, Item]] = []
                for catalog, url in CATALOGS.items():
                    try:
                        found.extend((catalog, i) for i in catalog_items(url, discovery_bbox, start, end))
                    except Exception as exc:
                        result.setdefault("catalog_errors", []).append(
                            {"catalog": catalog, "error": f"{type(exc).__name__}: {exc}"}
                        )
                asf_matches: list[dict[str, Any]] = []
                try:
                    asf_matches = asf_records(discovery_bbox, start, end)
                except Exception as exc:
                    result.setdefault("catalog_errors", []).append(
                        {"catalog": "ASF", "error": f"{type(exc).__name__}: {exc}"}
                    )
                # Keep the wider discovery results here. STAC footprints can be
                # coarser than the actual RTC coverage; raster valid-pixel QA below
                # is the authoritative coverage gate for a case AOI.
                items_by_id = {item.id: item for _, item in found}
                merged: dict[str, dict[str, Any]] = {}
                for catalog, item in found:
                    if not item.datetime:
                        continue
                    record: dict[str, Any] = {
                        "scene_id": item.id,
                        "catalog": catalog,
                        "acquisition_time_utc": item.datetime.isoformat(),
                        "collection": item.collection_id,
                    }
                    key = acquisition_key(item.id)
                    current = merged.get(key)
                    # Prefer RTC for analysis, then retain GRD as fallback.
                    rank = (0 if "rtc" in str(item.collection_id).lower() else 1, catalog)
                    if current is None or rank < current["_rank"]:
                        record["_rank"] = rank
                        merged[key] = record
                for record in asf_matches:
                    key = acquisition_key(str(record["scene_id"]))
                    merged.setdefault(key, record)
                records = sorted(
                    merged.values(), key=lambda r: r["acquisition_time_utc"]
                )
                if sample and len(records) > sample:
                    records = [
                        records[round(j * (len(records) - 1) / (sample - 1))]
                        for j in range(sample)
                    ]
                if not records:
                    result["status"] = "no_scene"
                    result["reason"] = (
                        "Catalog queries completed with no matching Sentinel-1 item."
                        if not result.get("catalog_errors")
                        else "No scene verified; one or more catalog queries failed."
                    )
                else:
                    result["status"] = "scenes_found_processing_unverified"
                    reference_time = (
                        datetime.fromisoformat(case["incident_date"]).replace(tzinfo=UTC)
                        if case["category"] == "documented_spill"
                        else None
                    )
                    for record in records:
                        acquired = datetime.fromisoformat(str(record["acquisition_time_utc"]))
                        record["time_gap_hours"] = (
                            abs((acquired - reference_time).total_seconds()) / 3600
                            if reference_time
                            else None
                        )
                        record.pop("_rank", None)
                    result["catalog_results"] = records
                    detector_results = []
                    if not args.search_only:
                        for record in records:
                            selected_item = items_by_id.get(str(record["scene_id"]))
                            if selected_item is None:
                                detector_results.append({
                                    "scene_id": record["scene_id"],
                                    "status": "not_processed",
                                    "reason": "Selected catalog record has no matching Planetary Computer STAC item/assets.",
                                })
                                continue
                            try:
                                analysis, assets = process_case_scene(selected_item, bbox_case)
                                case_folder = OUT / case["id"]
                                case_folder.mkdir(parents=True, exist_ok=True)
                                safe_scene = re.sub(r"[^A-Za-z0-9_.-]", "_", selected_item.id)
                                result_path = case_folder / f"{safe_scene}.json"
                                payload = {
                                    "case_id": case["id"],
                                    "data_label": "REAL Sentinel-1",
                                    "analysis_scope": analysis.analysis_scope,
                                    "scene_id": analysis.scene_id,
                                    "acquisition_time_utc": analysis.acquisition_time.isoformat(),
                                    "satellite": analysis.satellite,
                                    "orbit_direction": analysis.orbit_direction,
                                    "polarization": analysis.polarization,
                                    "stac_href": analysis.stac_href,
                                    "preview_bounds": analysis.preview_bounds,
                                    "case_aoi": bbox_case,
                                    "source_urls": [source["url"] for source in case.get("sources", [])],
                                    "reported_extent": case.get("reported_extent"),
                                    "time_gap_hours": record.get("time_gap_hours"),
                                    "detected": any(
                                        feature.properties.label == "candidate"
                                        for feature in analysis.candidates.features
                                    ),
                                    "candidate_count": sum(
                                        feature.properties.label == "candidate"
                                        for feature in analysis.candidates.features
                                    ),
                                    "candidate_distances_to_reported_location_km": [
                                        {
                                            "candidate_id": feature.properties.id,
                                            "distance_km": Geod(ellps="WGS84").inv(
                                                float(point[0]), float(point[1]),
                                                shape(feature.geometry.model_dump()).centroid.x,
                                                shape(feature.geometry.model_dump()).centroid.y,
                                            )[2] / 1000,
                                        }
                                        for feature in analysis.candidates.features
                                        if feature.properties.label == "candidate"
                                    ],
                                    "wind_speed_ms": (
                                        hypot(analysis.conditions.wind_u_ms, analysis.conditions.wind_v_ms)
                                        if analysis.conditions.wind_u_ms is not None
                                        and analysis.conditions.wind_v_ms is not None
                                        else None
                                    ),
                                    "conditions": analysis.conditions.model_dump(mode="json"),
                                    "total_candidate_area_km2": analysis.total_area_km2,
                                    "funnel": analysis.qa.funnel,
                                    "qa": analysis.qa.model_dump(mode="json"),
                                    "candidates": [feature.model_dump(mode="json") for feature in analysis.candidates.features],
                                    "reason": "Detector output is from the displayed real Sentinel-1 pixels. Reported extent is descriptive only, not a georeferenced polygon; IoU is not computed.",
                                }
                                result_path.write_text(json.dumps(payload, indent=2), encoding="utf-8")
                                (case_folder / f"{safe_scene}-raw.webp").write_bytes(assets["preview-raw-fixed.webp"])
                                (case_folder / f"{safe_scene}-filtered.webp").write_bytes(assets["preview-filtered-fixed.webp"])
                                detector_results.append({
                                    "scene_id": selected_item.id,
                                    "status": "processed",
                                    "detected": payload["detected"],
                                    "candidate_count": payload["candidate_count"],
                                    "result_file": result_path.relative_to(ROOT).as_posix(),
                                    "wind_speed_ms": payload["wind_speed_ms"],
                                    "funnel": payload["funnel"],
                                })
                                print(
                                    f"  processed {item.id}: {payload['candidate_count']} candidates",
                                    flush=True,
                                )
                            except Exception as exc:
                                coverage_error = "Insufficient scene coverage:" in str(exc)
                                detector_results.append({
                                    "scene_id": selected_item.id,
                                    "status": "insufficient_coverage" if coverage_error else "processing_error",
                                    "error": f"{type(exc).__name__}: {exc}",
                                })
                                logging.exception("Scene processing failed for %s", selected_item.id)
                    result["detector_results"] = detector_results
                    result["status"] = (
                        "processed"
                        if detector_results and all(row["status"] == "processed" for row in detector_results)
                        else "insufficient_coverage"
                        if detector_results and all(row["status"] == "insufficient_coverage" for row in detector_results)
                        else "scenes_found_processing_unverified"
                    )
                    result["reason"] = (
                        "Scene discovery and detector processing were attempted for catalog items with usable "
                        "Planetary Computer assets. Search-only mode was selected."
                        if args.search_only
                        else "No candidate is a confirmed spill; detector results are heuristic candidate slicks."
                    )
        except Exception as exc:
            result["status"] = "error"
            result["reason"] = f"{type(exc).__name__}: {exc}"
        target.write_text(json.dumps(result, indent=2), encoding="utf-8")
        print(f"{case['id']}: {result['status']} · {len(result['catalog_results'])} scenes", flush=True)
    summary = {
        "run_at_utc": datetime.now(UTC).isoformat(),
        "processing_version": PROCESSING_VERSION,
        "cases": len(cases),
        "results": [
            json.loads(p.read_text(encoding="utf-8"))
            for p in sorted(OUT.glob("*.json"))
            if p.name != "connectivity-latest.json"
        ],
    }
    (OUT.parent / "validation-latest.json").write_text(json.dumps(summary, indent=2), encoding="utf-8")


if __name__ == "__main__":
    try:
        main()
    except Exception as exc:
        logging.exception("VALIDATION FAILED: %s", exc)
        raise SystemExit(1) from exc
