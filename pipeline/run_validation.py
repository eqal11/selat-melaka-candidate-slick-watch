"""Resumable, real-catalog scene search and detector validation runner.

This runner never manufactures a result. Each successful case search is checkpointed
under validation/results/cases/; detector execution is attempted only for AOIs accepted
by the application's study-area bounds. Global case AOIs are explicitly recorded as
not processable by the Strait-specific analysis schema pending a case-scoped extension.
"""

from __future__ import annotations

import argparse
import json
import logging
from datetime import UTC, datetime, timedelta
from pathlib import Path
from typing import Any

import requests
import yaml
from pystac import Item
from pystac_client import Client

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
    for query in ({"collections": ["sentinel-1-rtc"]}, {"collections": ["sentinel-1-grd"]}, {}):
        try:
            items = c.search(
                bbox=bbox, datetime=f"{start.isoformat()}/{end.isoformat()}", limit=100, **query
            ).items()
            found.extend(items)
        except Exception as exc:
            logging.warning("Catalog query %s failed: %s", url, exc)
    return found


def asf_records(bbox: list[float], start: datetime, end: datetime) -> list[dict[str, Any]]:
    west, south, east, north = bbox
    polygon = f"POLYGON(({west} {south},{east} {south},{east} {north},{west} {north},{west} {south}))"
    response = requests.get(
        ASF,
        params={
            "platform": "SENTINEL-1",
            "processingLevel": "GRD_HD",
            "intersectsWith": polygon,
            "start": start.date().isoformat(),
            "end": end.date().isoformat(),
            "output": "json",
            "maxResults": 100,
        },
        timeout=(8, 30),
        headers={"User-Agent": "SelatCandidateReview/0.2"},
    )
    response.raise_for_status()
    payload = response.json()
    source_records = payload if isinstance(payload, list) else payload.get("features", [])
    normalized = []
    for source in source_records:
        properties = source.get("properties", source)
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
    ap.add_argument("--resume", action="store_true", help="reuse case checkpoints")
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
    for case in case_file["cases"]:
        target = OUT / f"{case['id']}.json"
        if args.resume and target.exists():
            try:
                checkpoint = json.loads(target.read_text(encoding="utf-8"))
            except (OSError, json.JSONDecodeError):
                checkpoint = {}
            if checkpoint.get("status") in {
                "no_scene",
                "not_searchable_without_source_coordinates",
                "scenes_found_processing_unverified",
            }:
                print(f"RESUME {case['id']}: completed search checkpoint retained", flush=True)
                continue
            print(f"RESUME {case['id']}: retrying incomplete/failed checkpoint", flush=True)
        result = {
            "case_id": case["id"],
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
                lon, lat = map(float, point)
                bbox = [lon - 0.3, lat - 0.3, lon + 0.3, lat + 0.3]
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
                        found.extend((catalog, i) for i in catalog_items(url, bbox, start, end))
                    except Exception as exc:
                        result.setdefault("catalog_errors", []).append(
                            {"catalog": catalog, "error": f"{type(exc).__name__}: {exc}"}
                        )
                asf_matches: list[dict[str, Any]] = []
                try:
                    asf_matches = asf_records(bbox, start, end)
                except Exception as exc:
                    result.setdefault("catalog_errors", []).append(
                        {"catalog": "ASF", "error": f"{type(exc).__name__}: {exc}"}
                    )
                unique = {i.id: (cat, i) for cat, i in found}
                items = sorted(
                    unique.values(), key=lambda x: x[1].datetime or datetime.min.replace(tzinfo=UTC)
                )
                if sample and len(items) > sample:
                    items = [items[round(j * (len(items) - 1) / (sample - 1))] for j in range(sample)]
                if not items and not asf_matches:
                    result["status"] = "no_scene"
                    result["reason"] = (
                        "Catalog queries completed with no matching Sentinel-1 item."
                        if not result.get("catalog_errors")
                        else "No scene verified; one or more catalog queries failed."
                    )
                else:
                    result["status"] = "scenes_found_processing_unverified"
                    result["catalog_results"] = [
                        {
                            "scene_id": i.id,
                            "catalog": cat,
                            "acquisition_time_utc": i.datetime.isoformat() if i.datetime else None,
                            "time_gap_hours": abs(
                                (
                                    i.datetime
                                    - (
                                        datetime.fromisoformat(case["incident_date"]).replace(tzinfo=UTC)
                                        if case["category"] == "documented_spill"
                                        else start
                                    )
                                ).total_seconds()
                            )
                            / 3600
                            if i.datetime
                            else None,
                            "collection": i.collection_id,
                        }
                        for cat, i in items
                    ]
                    reference_time = (
                        datetime.fromisoformat(case["incident_date"]).replace(tzinfo=UTC)
                        if case["category"] == "documented_spill"
                        else start
                    )
                    existing_ids = {entry["scene_id"] for entry in result["catalog_results"]}
                    for record in asf_matches:
                        if record["scene_id"] in existing_ids:
                            continue
                        acquired = datetime.fromisoformat(record["acquisition_time_utc"])
                        record["time_gap_hours"] = abs((acquired - reference_time).total_seconds()) / 3600
                        result["catalog_results"].append(record)
                    result["reason"] = (
                        "Scene IDs are real STAC matches. Raster processing is not attempted by this global-case runner until case-scoped AOI bounds are enabled; no detector result is claimed."
                    )
        except Exception as exc:
            result["status"] = "error"
            result["reason"] = f"{type(exc).__name__}: {exc}"
        target.write_text(json.dumps(result, indent=2), encoding="utf-8")
        print(f"{case['id']}: {result['status']} · {len(result['catalog_results'])} scenes", flush=True)
    summary = {
        "run_at_utc": datetime.now(UTC).isoformat(),
        "cases": len(case_file["cases"]),
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
