"""Versioned API for the Selat Melaka Oil Spill Watch."""

import asyncio
import json
import logging
import os
import secrets
import threading
from contextlib import contextmanager
from datetime import UTC, datetime, timedelta
from pathlib import Path
from typing import Any

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
    ArchiveIndex,
    HealthResponse,
    HistoryResponse,
    Job,
    LiveConditionsResponse,
    Result,
    SceneList,
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
cache: dict[str, tuple[Result, bytes]] = {}
vessels: list[dict[str, Any]] = []


engine = create_engine(f"sqlite:///{DB.as_posix()}", connect_args={"check_same_thread": False})


@contextmanager
def db():
    with engine.begin() as connection:
        connection.execute(
            text(
                "CREATE TABLE IF NOT EXISTS cache (key TEXT PRIMARY KEY, result TEXT NOT NULL, preview BLOB NOT NULL)"
            )
        )
        connection.execute(
            text(
                "CREATE TABLE IF NOT EXISTS job_state (id TEXT PRIMARY KEY, status TEXT NOT NULL, updated TEXT NOT NULL, data_json TEXT NOT NULL)"
            )
        )
        yield connection


def get_result(key):
    if key in cache:
        return cache[key]
    with db() as c:
        row = c.execute(text("SELECT result,preview FROM cache WHERE key=:key"), {"key": key}).fetchone()
    if row:
        pair = (Result.model_validate_json(row[0]), row[1])
        cache[key] = pair
        return pair
    p = RESULTS / f"{key}.json"
    img = RESULTS / f"{key}.png"
    if p.exists() and img.exists():
        pair = (Result.model_validate_json(p.read_text()), img.read_bytes())
        cache[key] = pair
        return pair
    return None


def update_job(jid, **kw):
    jobs[jid].update(kw)
    with db() as c:
        c.execute(
            text("INSERT OR REPLACE INTO job_state VALUES (:id,:status,:updated,:data_json)"),
            {
                "id": jid,
                "status": jobs[jid]["status"],
                "updated": datetime.now(UTC).isoformat(),
                "data_json": json.dumps(jobs[jid]),
            },
        )


def run_job(jid, body):
    global active
    with lock:
        if active >= 2:
            update_job(jid, status="failed", stage="failed", error="Analysis concurrency limit reached")
            return
        active += 1
    try:
        update_job(jid, status="running", stage="searching", progress=2)
        candidate_key = None
        if body.demo:
            candidate_key = cache_key("SYNTHETIC-demo-42", body)
        elif body.scene_id:
            candidate_key = cache_key(body.scene_id, body)
        else:
            _, items = search(body.aoi, body.start, body.end)
            if items:
                candidate_key = cache_key(items[0].id, body)
        if candidate_key:
            cached_result = get_result(candidate_key)
            if cached_result:
                update_job(
                    jid,
                    status="completed",
                    stage="complete",
                    progress=100,
                    result_id=candidate_key,
                    cached=True,
                )
                return
        result, png = analyze(
            body, progress=lambda stage, p: update_job(jid, stage=stage, progress=p), vessels=vessels
        )
        RESULTS.mkdir(parents=True, exist_ok=True)
        write_result(result, png, RESULTS)
        with db() as c:
            c.execute(
                text("INSERT OR REPLACE INTO cache VALUES (:key,:result,:preview)"),
                {"key": result.id, "result": result.model_dump_json(), "preview": png},
            )
        cache[result.id] = (result, png)
        update_job(jid, status="completed", stage="complete", progress=100, result_id=result.id)
    except Exception as exc:
        log.exception("Analysis failed (%s)", type(exc).__name__)
        update_job(jid, status="failed", stage="failed", error=f"{type(exc).__name__}: {str(exc)[:400]}")
    finally:
        with lock:
            active -= 1


limiter = Limiter(key_func=get_remote_address, default_limits=["60/minute"])
app = FastAPI(
    title="Selat Melaka Oil Spill Watch",
    version="0.1.0",
    description="Educational candidate detection, not confirmed spills.",
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
        x.strip() for x in os.getenv("CORS_ORIGINS", "http://localhost:5173,http://127.0.0.1:5173").split(",")
    ],
    allow_methods=["GET", "POST"],
    allow_headers=["Content-Type"],
)


@app.get("/health", response_model=HealthResponse)
@app.get("/api/v1/health", response_model=HealthResponse)
def health() -> HealthResponse:
    return HealthResponse(status="ok", version="0.1.0")


@app.get("/api/v1/zones", response_model=Zones)
def get_zones():
    return zones().model_dump()


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
        return search(bounds, start.astimezone(UTC), end.astimezone(UTC))[0]
    except (ValueError, RuntimeError) as exc:
        raise HTTPException(422 if isinstance(exc, ValueError) else 503, detail=str(exc)) from exc


@app.post("/api/v1/analyze", response_model=Job, status_code=202)
@limiter.limit("5/minute")
def submit(request: Request, body: AnalyzeRequest, background: BackgroundTasks):
    with lock:
        if active >= 2:
            raise HTTPException(429, "Two analyses are already running")
    jid = secrets.token_urlsafe(12)
    jobs[jid] = {
        "id": jid,
        "data_label": "SYNTHETIC" if body.demo else "OBSERVATION",
        "status": "queued",
        "stage": "queued",
        "progress": 0,
        "result_id": None,
        "error": None,
        "cached": False,
    }
    update_job(jid)
    background.add_task(run_job, jid, body)
    return Job.model_validate(jobs[jid])


@app.get("/api/v1/jobs/{jid}", response_model=Job)
def get_job(jid):
    if jid in jobs:
        return Job.model_validate(jobs[jid])
    with db() as connection:
        row = connection.execute(text("SELECT data_json FROM job_state WHERE id=:id"), {"id": jid}).fetchone()
    if not row:
        raise HTTPException(404, "Job not found")
    return Job.model_validate_json(row[0])


@app.get("/api/v1/results/{rid}", response_model=Result)
def result(rid):
    pair = get_result(rid)
    if not pair:
        raise HTTPException(404, "Result not found")
    return pair[0]


@app.get("/api/v1/results/{rid}/preview.png")
def preview(rid):
    pair = get_result(rid)
    if not pair:
        raise HTTPException(404, "Preview not found")
    return Response(pair[1], media_type="image/png", headers={"Cache-Control": "public, max-age=3600"})


@app.get("/api/v1/history", response_model=HistoryResponse)
def history(zone: str | None = None, start: datetime | None = None, end: datetime | None = None):
    p = ARCHIVE / "index.json"
    if not p.exists():
        return {"type": "FeatureCollection", "data_label": "SYNTHETIC", "entries": []}
    if (start and start.tzinfo is None) or (end and end.tzinfo is None):
        raise HTTPException(422, "History dates must include a timezone")
    if start and end and end < start:
        raise HTTPException(422, "History end must be on or after start")
    index = ArchiveIndex.model_validate_json(p.read_text(encoding="utf-8"))
    entries = [entry.model_dump(mode="json") for entry in index.entries]
    if zone:
        entries = [x for x in entries if x.get("zone") == zone]
    if start:
        entries = [
            x for x in entries if datetime.fromisoformat(x["acquisition_time"]) >= start.astimezone(UTC)
        ]
    if end:
        entries = [x for x in entries if datetime.fromisoformat(x["acquisition_time"]) <= end.astimezone(UTC)]
    return {
        "type": "FeatureCollection",
        "data_label": "SYNTHETIC"
        if not entries or all(x.get("data_label") == "SYNTHETIC" for x in entries)
        else "OBSERVATION",
        "entries": entries,
    }


@app.get("/api/v1/live/conditions", response_model=LiveConditionsResponse)
@limiter.limit("10/minute")
def live_conditions(request: Request, bbox: str = Query(..., description="west,south,east,north")):
    try:
        values = tuple(map(float, bbox.split(",")))
        if len(values) != 4:
            raise ValueError("bbox requires four coordinates")
        b = (values[0], values[1], values[2], values[3])
        validate_bbox(b)
    except ValueError as exc:
        raise HTTPException(422, detail=str(exc)) from exc
    w, s, e, n = b
    now = datetime.now(UTC)
    pts = [conditions.fetch(x, y, now) for x, y in ((w, s), ((w + e) / 2, (s + n) / 2), (e, n))]
    return {"data_label": "MODEL", "updated_at": now, "points": pts, "refresh_minutes": 10}


@app.get("/api/v1/live/vessels")
async def live_vessels():
    async def stream():
        if not os.getenv("AISSTREAM_API_KEY"):
            yield 'event: status\ndata: {"status":"unavailable","message":"AIS key not configured"}\n\n'
            return
        yield 'event: status\ndata: {"status":"unavailable","message":"AIS relay not yet connected"}\n\n'
        while True:
            yield "data: " + json.dumps({"type": "FeatureCollection", "features": vessels}) + "\n\n"
            await asyncio.sleep(15)

    return StreamingResponse(
        stream(),
        media_type="text/event-stream",
        headers={"Cache-Control": "no-cache", "X-Accel-Buffering": "no"},
    )
