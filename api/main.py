"""Versioned API for real Sentinel-1 candidate analysis and review assets."""

import asyncio
import json
import logging
import os
import re
import secrets
import threading
from contextlib import contextmanager
from datetime import UTC, datetime, timedelta
from pathlib import Path
from typing import Any

import yaml
from fastapi import BackgroundTasks, FastAPI, HTTPException, Query, Request, Response
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import StreamingResponse
from slowapi import Limiter, _rate_limit_exceeded_handler
from slowapi.errors import RateLimitExceeded
from slowapi.util import get_remote_address
from sqlalchemy import create_engine, text

from core import conditions
from core.config import ROOT, Zones, zones
from core.engine import analyze, cache_key, write_result
from core.models import (
    AnalyzeRequest,
    ArchiveGeoJSON,
    ArchiveIndex,
    HealthResponse,
    HistoryResponse,
    Job,
    LiveConditionsResponse,
    PixelResponse,
    ProfileResponse,
    Result,
    SceneList,
    ValidationCasesResponse,
    validate_bbox,
)
from core.scenes import search

logging.basicConfig(level=os.getenv("LOG_LEVEL", "INFO"), format="%(asctime)s %(levelname)s %(message)s")
log = logging.getLogger("selat-watch")
VAR = Path(os.getenv("APP_DATA_DIR", str(Path(__file__).parent / "var")))
VAR.mkdir(parents=True, exist_ok=True)
DB = VAR / "jobs.sqlite3"
RESULTS = VAR / "results"
ARCHIVE = ROOT / "data" / "archive"
lock = threading.Lock()
active = 0
jobs: dict[str, dict[str, Any]] = {}
cache: dict[str, tuple[Result, dict[str, bytes]]] = {}
vessels: list[dict[str, Any]] = []
engine = create_engine(f"sqlite:///{DB.as_posix()}", connect_args={"check_same_thread": False})


@contextmanager
def db():
    with engine.begin() as connection:
        connection.execute(
            text("CREATE TABLE IF NOT EXISTS cache (key TEXT PRIMARY KEY, result TEXT NOT NULL)")
        )
        connection.execute(
            text(
                "CREATE TABLE IF NOT EXISTS job_state (id TEXT PRIMARY KEY, status TEXT NOT NULL, updated TEXT NOT NULL, data_json TEXT NOT NULL)"
            )
        )
        yield connection


def _assets_for(key: str) -> dict[str, bytes]:
    return {
        path.name[len(key) + 1 :]: path.read_bytes() for path in RESULTS.glob(f"{key}-*") if path.is_file()
    }


def get_result(key: str):
    if key in cache:
        return cache[key]
    with db() as connection:
        row = connection.execute(text("SELECT result FROM cache WHERE key=:key"), {"key": key}).fetchone()
    path = RESULTS / f"{key}.json"
    if row:
        result = Result.model_validate_json(row[0])
    elif path.exists():
        result = Result.model_validate_json(path.read_text(encoding="utf-8"))
    else:
        return None
    pair = (result, _assets_for(key))
    cache[key] = pair
    return pair


def update_job(job_id, **updates):
    jobs[job_id].update(updates)
    with db() as connection:
        connection.execute(
            text("INSERT OR REPLACE INTO job_state VALUES (:id,:status,:updated,:data_json)"),
            {
                "id": job_id,
                "status": jobs[job_id]["status"],
                "updated": datetime.now(UTC).isoformat(),
                "data_json": json.dumps(jobs[job_id]),
            },
        )


def run_job(job_id, body):
    global active
    with lock:
        if active >= 2:
            update_job(job_id, status="failed", stage="failed", error="Analysis concurrency limit reached")
            return
        active += 1
    try:
        update_job(job_id, status="running", stage="searching", progress=2)
        if body.scene_id:
            scene_id = body.scene_id
        else:
            listing, items = search(body.aoi, body.start, body.end)
            if not items:
                raise RuntimeError(
                    f"No Sentinel-1 scene found for this AOI and date range. STAC coverage: {listing.coverage}"
                )
            scene_id = items[0].id
        candidate_key = cache_key(scene_id, body)
        cached_result = get_result(candidate_key)
        if cached_result:
            update_job(
                job_id,
                status="completed",
                stage="complete",
                progress=100,
                result_id=candidate_key,
                cached=True,
            )
            return
        result, assets = analyze(
            body,
            progress=lambda stage, progress: update_job(job_id, stage=stage, progress=progress),
            vessels=vessels,
        )
        RESULTS.mkdir(parents=True, exist_ok=True)
        write_result(result, assets, RESULTS)
        with db() as connection:
            columns = {row[1] for row in connection.execute(text("PRAGMA table_info(cache)")).fetchall()}
            if "preview" in columns:
                connection.execute(
                    text("INSERT OR REPLACE INTO cache (key, result, preview) VALUES (:key,:result,:preview)"),
                    {"key": result.id, "result": result.model_dump_json(), "preview": assets["preview-filtered-fixed.webp"]},
                )
            else:
                connection.execute(
                    text("INSERT OR REPLACE INTO cache (key, result) VALUES (:key,:result)"),
                    {"key": result.id, "result": result.model_dump_json()},
                )
        cache[result.id] = (result, assets)
        update_job(job_id, status="completed", stage="complete", progress=100, result_id=result.id)
    except Exception as exc:
        log.exception("Real scene analysis failed (%s)", type(exc).__name__)
        update_job(job_id, status="failed", stage="failed", error=f"{type(exc).__name__}: {str(exc)[:600]}")
    finally:
        with lock:
            active -= 1


limiter = Limiter(key_func=get_remote_address, default_limits=["60/minute"])
app = FastAPI(
    title="Selat Melaka Oil Spill Watch",
    version="0.2.0",
    description="Real Sentinel-1 candidate slick analysis. No result confirms a spill.",
)
app.state.limiter = limiter
app.add_exception_handler(RateLimitExceeded, _rate_limit_exceeded_handler)


@app.middleware("http")
async def enforce_request_size(request: Request, call_next):
    content_length = request.headers.get("content-length")
    if content_length and int(content_length) > 262_144:
        return Response("Request body exceeds 256 KiB limit", status_code=413)
    return await call_next(request)


app.add_middleware(
    CORSMiddleware,
    allow_origins=[
        x.strip()
        for x in os.getenv(
            "CORS_ORIGINS",
            "http://localhost:5173,http://127.0.0.1:5173,http://localhost:5174,http://127.0.0.1:5174",
        ).split(",")
    ],
    allow_methods=["GET", "POST"],
    allow_headers=["Content-Type"],
)


@app.get("/health", response_model=HealthResponse)
@app.get("/api/v1/health", response_model=HealthResponse)
def health():
    return HealthResponse(status="ok", version="0.2.0")


@app.get("/api/v1/zones", response_model=Zones)
def get_zones():
    return zones().model_dump()


@app.get("/api/v1/validation/cases", response_model=ValidationCasesResponse)
def validation_cases():
    """Return source-linked case register; unrun cases never imply detector outcomes."""
    path = ROOT / "validation" / "cases.yaml"
    try:
        payload = yaml.safe_load(path.read_text(encoding="utf-8-sig"))
        return ValidationCasesResponse.model_validate(payload)
    except Exception as exc:
        log.exception("Validation case register could not be loaded")
        raise HTTPException(500, "Validation case register is invalid or unavailable") from exc


@app.get("/api/v1/scenes", response_model=SceneList)
@limiter.limit("10/minute")
def scenes(request: Request, bbox: str, start: datetime, end: datetime):
    try:
        bounds = tuple(map(float, bbox.split(",")))
        if len(bounds) != 4:
            raise ValueError("bbox requires four coordinates")
        validate_bbox(bounds)
        if start.tzinfo is None or end.tzinfo is None or end <= start or end - start > timedelta(days=31):
            raise ValueError("Use UTC dates within 31 days")
        if end > datetime.now(UTC) + timedelta(minutes=5):
            raise ValueError("End date cannot be in the future")
        return search(bounds, start.astimezone(UTC), end.astimezone(UTC))[0]
    except ValueError as exc:
        raise HTTPException(422, detail=str(exc)) from exc
    except RuntimeError as exc:
        raise HTTPException(503, detail=str(exc)) from exc


@app.post("/api/v1/analyze", response_model=Job, status_code=202)
@limiter.limit("5/minute")
def submit(request: Request, body: AnalyzeRequest, background: BackgroundTasks):
    with lock:
        if active >= 2:
            raise HTTPException(429, "Two analyses are already running")
    job_id = secrets.token_urlsafe(12)
    jobs[job_id] = {
        "id": job_id,
        "data_label": "REAL Sentinel-1",
        "status": "queued",
        "stage": "queued",
        "progress": 0,
        "result_id": None,
        "error": None,
        "cached": False,
    }
    update_job(job_id)
    background.add_task(run_job, job_id, body)
    return Job.model_validate(jobs[job_id])


@app.get("/api/v1/jobs/{job_id}", response_model=Job)
def get_job(job_id: str):
    if job_id in jobs:
        return Job.model_validate(jobs[job_id])
    with db() as connection:
        row = connection.execute(
            text("SELECT data_json FROM job_state WHERE id=:id"), {"id": job_id}
        ).fetchone()
    if not row:
        raise HTTPException(404, "Job not found")
    return Job.model_validate_json(row[0])


@app.get("/api/v1/results/{result_id}", response_model=Result)
def result(result_id: str):
    pair = get_result(result_id)
    if not pair:
        raise HTTPException(404, "Result not found; run a real Sentinel-1 analysis first")
    return pair[0]


@app.get("/api/v1/results/{result_id}/{asset_name}")
def result_asset(result_id: str, asset_name: str):
    if not re.fullmatch(
        r"(?:preview-(?:raw|filtered)-(?:fixed|auto)|mask-(?:land|ship|wind-removed))\.webp|pixel-grid\.npz",
        asset_name,
    ):
        raise HTTPException(404, "Review asset not found")
    pair = get_result(result_id)
    if not pair or asset_name not in pair[1]:
        raise HTTPException(404, "Review asset not available for this real result")
    media_type = "image/webp" if asset_name.endswith(".webp") else "application/octet-stream"
    return Response(
        pair[1][asset_name], media_type=media_type, headers={"Cache-Control": "public, max-age=3600"}
    )


@app.get("/api/v1/results/{result_id}/pixel", response_model=PixelResponse)
def pixel(result_id: str, lon: float, lat: float, variant: str = "raw"):
    if variant not in {"raw", "filtered"}:
        raise HTTPException(422, "variant must be raw or filtered")
    pair = get_result(result_id)
    if not pair:
        raise HTTPException(404, "Result not found")
    result, assets = pair
    west, south, east, north = result.preview_bounds
    if not west <= lon <= east or not south <= lat <= north:
        raise HTTPException(422, "Pixel lies outside the AOI")
    import io

    import numpy as np

    grid = np.load(io.BytesIO(assets["pixel-grid.npz"]))
    values = grid[f"{variant}_db"]
    col = min(values.shape[1] - 1, int((lon - west) / (east - west) * values.shape[1]))
    row = min(values.shape[0] - 1, int((north - lat) / (north - south) * values.shape[0]))
    value = float(values[row, col])
    from pyproj import Geod

    width_m = abs(Geod(ellps="WGS84").inv(west, (south + north) / 2, east, (south + north) / 2)[2])
    height_m = abs(Geod(ellps="WGS84").inv((west + east) / 2, south, (west + east) / 2, north)[2])
    resolution_m = float((width_m / values.shape[1] + height_m / values.shape[0]) / 2)
    return {
        "longitude": lon,
        "latitude": lat,
        "variant": variant,
        "backscatter_db": value if np.isfinite(value) else None,
        "resolution_m": resolution_m,
        "scene_id": result.scene_id,
    }


@app.get("/api/v1/results/{result_id}/profile/{candidate_id}", response_model=ProfileResponse)
def candidate_profile(result_id: str, candidate_id: str):
    pair = get_result(result_id)
    if not pair:
        raise HTTPException(404, "Result not found")
    result, assets = pair
    candidate = next(
        (item for item in result.candidates.features if item.properties.id == candidate_id), None
    )
    if candidate is None:
        raise HTTPException(404, "Candidate not found in this real scene")
    import io

    import numpy as np
    from shapely.geometry import Point, shape

    grid = np.load(io.BytesIO(assets["pixel-grid.npz"]))
    raw, filtered = grid["raw_db"], grid["filtered_db"]
    west, south, east, north = result.preview_bounds
    geometry = shape(candidate.geometry.model_dump())
    center = geometry.centroid
    west_g, south_g, east_g, north_g = geometry.bounds
    # Cross-section through centroid, extended to 1.5 times the candidate's long dimension.
    half = max(east_g - west_g, north_g - south_g) * 0.75
    y = center.y
    samples = []
    inside_values = []
    for fraction in np.linspace(-1, 1, 41):
        lon = min(east, max(west, center.x + half * fraction))
        lat = min(north, max(south, y))
        col = min(raw.shape[1] - 1, max(0, int((lon - west) / (east - west) * raw.shape[1])))
        row = min(raw.shape[0] - 1, max(0, int((north - lat) / (north - south) * raw.shape[0])))
        point = Point(lon, lat)
        raw_value, filtered_value = float(raw[row, col]), float(filtered[row, col])
        is_inside = geometry.covers(point)
        if is_inside and np.isfinite(filtered_value):
            inside_values.append(filtered_value)
        samples.append(
            {
                "longitude": lon,
                "raw_db": raw_value if np.isfinite(raw_value) else None,
                "filtered_db": filtered_value if np.isfinite(filtered_value) else None,
                "inside": is_inside,
            }
        )
    return {
        "result_id": result_id,
        "candidate_id": candidate_id,
        "scene_id": result.scene_id,
        "samples": samples,
        "mean_inside_db": float(np.mean(inside_values)) if inside_values else candidate.properties.mean_db,
        "mean_ring_db": candidate.properties.mean_db + candidate.properties.contrast_db,
        "profile_note": "41-pixel decimated cross-section through candidate centroid; ring mean from detector's 240 m surrounding ring.",
    }


def _archive_entry(result_id: str):
    index_path = ARCHIVE / "index.json"
    if not index_path.exists():
        return None
    index = ArchiveIndex.model_validate_json(index_path.read_text(encoding="utf-8"))
    return next((entry for entry in index.entries if entry.id == result_id), None)


@app.get("/api/v1/history", response_model=HistoryResponse)
def history(zone: str | None = None, start: datetime | None = None, end: datetime | None = None):
    index_path = ARCHIVE / "index.json"
    if not index_path.exists():
        return {"type": "FeatureCollection", "data_label": "REAL Sentinel-1", "entries": []}
    if (start and start.tzinfo is None) or (end and end.tzinfo is None):
        raise HTTPException(422, "History dates must include a timezone")
    if start and end and end < start:
        raise HTTPException(422, "History end must be on or after start")
    index = ArchiveIndex.model_validate_json(index_path.read_text(encoding="utf-8"))
    entries = index.entries
    if zone:
        entries = [entry for entry in entries if entry.zone == zone]
    if start:
        entries = [entry for entry in entries if entry.acquisition_time >= start.astimezone(UTC)]
    if end:
        entries = [entry for entry in entries if entry.acquisition_time <= end.astimezone(UTC)]
    return {
        "type": "FeatureCollection",
        "data_label": "REAL Sentinel-1",
        "entries": [entry.model_dump(mode="json") for entry in entries],
    }


@app.get("/api/v1/history/{result_id}/candidates.geojson")
def history_candidates(result_id: str):
    entry = _archive_entry(result_id)
    if not entry:
        raise HTTPException(404, "Archived real observation not found")
    path = ARCHIVE / entry.path
    if not path.exists():
        raise HTTPException(404, "Archived candidate polygons not found")
    return ArchiveGeoJSON.model_validate_json(path.read_text(encoding="utf-8")).model_dump(mode="json")


@app.get("/api/v1/history/{result_id}/map")
def history_map(result_id: str):
    entry = _archive_entry(result_id)
    if not entry:
        raise HTTPException(404, "Archived real observation not found")
    geojson_path = ARCHIVE / entry.path
    if not geojson_path.exists():
        raise HTTPException(404, "Archived candidate polygons not found")
    return {
        "id": entry.id,
        "scene_id": entry.scene_id,
        "satellite": entry.satellite,
        "orbit_direction": entry.orbit_direction,
        "polarization": entry.polarization,
        "stac_href": entry.stac_href,
        "acquisition_time": entry.acquisition_time,
        "data_label": "REAL Sentinel-1",
        "preview_bounds": entry.preview_bounds
        or next(zone.bbox for zone in zones().zones if zone.id == entry.zone),
        "scene_footprint": entry.scene_footprint.model_dump(mode="json") if entry.scene_footprint else None,
        "coastline": entry.coastline.model_dump(mode="json") if entry.coastline else None,
        "drift": [],
        "is_history": True,
        "preview_urls": {
            "preview-raw-fixed.webp": f"/api/v1/history/{entry.id}/raw.webp",
            "preview-filtered-fixed.webp": f"/api/v1/history/{entry.id}/filtered.webp",
        },
        "candidates": ArchiveGeoJSON.model_validate_json(geojson_path.read_text(encoding="utf-8")).model_dump(
            mode="json"
        ),
    }


@app.get("/api/v1/history/{result_id}/{variant}.webp")
def history_preview(result_id: str, variant: str):
    if variant not in {"raw", "filtered"}:
        raise HTTPException(422, "variant must be raw or filtered")
    entry = _archive_entry(result_id)
    if not entry:
        raise HTTPException(404, "Archived real observation not found")
    relative = entry.preview_raw if variant == "raw" else entry.preview_filtered
    path = (ARCHIVE / relative).resolve()
    if not path.is_relative_to(ARCHIVE.resolve()) or not path.exists():
        raise HTTPException(404, "Archived SAR image not found")
    return Response(
        path.read_bytes(), media_type="image/webp", headers={"Cache-Control": "public, max-age=3600"}
    )


@app.get("/api/v1/live/conditions", response_model=LiveConditionsResponse)
@limiter.limit("10/minute")
def live_conditions(request: Request, bbox: str = Query(..., description="west,south,east,north")):
    try:
        values = tuple(map(float, bbox.split(",")))
        if len(values) != 4:
            raise ValueError("bbox requires four coordinates")
        bounds = (values[0], values[1], values[2], values[3])
        validate_bbox(bounds)
    except ValueError as exc:
        raise HTTPException(422, detail=str(exc)) from exc
    west, south, east, north = bounds
    now = datetime.now(UTC)
    points = [
        conditions.fetch(x, y, now)
        for x, y in ((west, south), ((west + east) / 2, (south + north) / 2), (east, north))
    ]
    return {"data_label": "MODEL", "updated_at": now, "points": points, "refresh_minutes": 10}


@app.get("/api/v1/live/vessels")
async def live_vessels():
    async def stream():
        if not os.getenv("AISSTREAM_API_KEY"):
            yield 'event: status\ndata: {"status":"unavailable","message":"AIS key not configured"}\n\n'
            return
        yield 'event: status\ndata: {"status":"unavailable","message":"AIS relay not connected"}\n\n'
        while True:
            yield "data: " + json.dumps({"type": "FeatureCollection", "features": vessels}) + "\n\n"
            await asyncio.sleep(15)

    return StreamingResponse(
        stream(),
        media_type="text/event-stream",
        headers={"Cache-Control": "no-cache", "X-Accel-Buffering": "no"},
    )
