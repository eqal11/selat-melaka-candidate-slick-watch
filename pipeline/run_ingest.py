"""Connectivity gate and explicit local entry point for real archive ingestion."""

from __future__ import annotations

import argparse
import json
import logging
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

import requests

ROOT = Path(__file__).resolve().parents[1]
RESULTS = ROOT / "validation" / "results"
ENDPOINTS = {
    "Planetary Computer STAC": "https://planetarycomputer.microsoft.com/api/stac/v1",
    "Copernicus Data Space STAC": "https://catalogue.dataspace.copernicus.eu/stac",
    "Copernicus Data Space OData": "https://catalogue.dataspace.copernicus.eu/odata/v1/Products?$top=1",
    "ASF search": "https://api.daac.asf.alaska.edu/services/search/param?platform=SENTINEL-1&processingLevel=GRD_HD&output=json&maxResults=1",
    "Open-Meteo forecast": "https://api.open-meteo.com/v1/forecast?latitude=3&longitude=101&current=wind_speed_10m",
    "Open-Meteo marine": "https://marine-api.open-meteo.com/v1/marine?latitude=3&longitude=101&current=ocean_current_velocity",
}


def connectivity():
    RESULTS.mkdir(parents=True, exist_ok=True)
    endpoints: dict[str, Any] = {}
    out: dict[str, Any] = {"checked_at_utc": datetime.now(UTC).isoformat(), "endpoints": endpoints}
    session = requests.Session()
    for name, url in ENDPOINTS.items():
        try:
            response = session.get(url, timeout=(8, 20), headers={"User-Agent": "SelatCandidateReview/0.1"})
            endpoints[name] = {"http_status": response.status_code, "ok": response.ok}
            print(f"{name}: HTTP {response.status_code}", flush=True)
        except Exception as exc:
            endpoints[name] = {"http_status": None, "error": f"{type(exc).__name__}: {exc}"}
            print(f"{name}: NO HTTP RESPONSE — {type(exc).__name__}: {exc}", flush=True)
    target = RESULTS / "connectivity-latest.json"
    target.write_text(json.dumps(out, indent=2), encoding="utf-8")
    return out


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--dry-run", action="store_true", help="only check catalog and weather API connectivity"
    )
    parser.add_argument("--days", type=int, choices=range(1, 91), default=60)
    args = parser.parse_args()
    report = connectivity()
    if args.dry_run:
        if any(
            v.get("http_status") is None or v.get("http_status", 500) >= 500
            for v in report["endpoints"].values()
        ):
            raise SystemExit(
                "DRY RUN FAILED: one or more endpoints did not respond successfully; see validation/results/connectivity-latest.json"
            )
        return
    from pipeline.ingest import ingest

    print(json.dumps(ingest(args.days), indent=2), flush=True)


if __name__ == "__main__":
    try:
        main()
    except Exception as exc:
        logging.exception("INGEST FAILED: %s", exc)
        raise SystemExit(1) from exc
