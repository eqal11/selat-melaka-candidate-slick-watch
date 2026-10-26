import hashlib
import io
import json
import time
from datetime import UTC, datetime
from math import pi, sqrt
from pathlib import Path
from typing import Callable

import numpy as np
from PIL import Image
from pyproj import Transformer
from rasterio.features import rasterize
from rasterio.transform import array_bounds, from_bounds
from rasterio.warp import Resampling, reproject, transform_bounds
from shapely.geometry import Point, mapping
from shapely.ops import transform

from core import __version__, conditions, synthetic
from core.config import ports
from core.detection import contrast, dark_mask, lee_filter, polygonize, to_db
from core.drift import forecast
from core.land import sea_mask
from core.loading import check_budget, load
from core.models import QA, AnalyzeRequest, Candidate, Candidates, Conditions, Result, utcnow
from core.scenes import search
from core.scoring import score, wind_gate


def cache_key(scene_id, request):
    content = {
        "scene": scene_id,
        "aoi": request.aoi,
        "parameters": request.parameters.model_dump(),
        "version": __version__,
    }
    return hashlib.sha256(json.dumps(content, sort_keys=True).encode()).hexdigest()[:24]


def preview_png(db, affine, crs, bounds):
    # Reproject into a north-up geographic image to match MapLibre image coordinates.
    target: np.ndarray = np.full((600, 600), np.nan, dtype="float32")
    reproject(
        db,
        target,
        src_transform=affine,
        src_crs=crs,
        src_nodata=np.nan,
        dst_transform=from_bounds(*bounds, 600, 600),
        dst_crs="EPSG:4326",
        dst_nodata=np.nan,
        resampling=Resampling.average,
    )
    shade = (np.clip((np.nan_to_num(target, nan=-30) + 30) / 25, 0, 1) * 255).astype("uint8")
    rgba = np.stack([shade, shade, shade, np.isfinite(target).astype("uint8") * 230], axis=-1)
    stream = io.BytesIO()
    Image.fromarray(rgba).save(stream, format="PNG")
    return stream.getvalue()


def process_arrays(
    power,
    affine,
    crs,
    aoi,
    acquired,
    scene_id,
    collection,
    params,
    forcing,
    progress: Callable = lambda *_: None,
    vessels=None,
    synthetic_data=False,
):
    began = time.perf_counter()
    check_budget(power.shape[1], power.shape[0], params)
    progress("detecting", 45)
    db = to_db(lee_filter(power))
    if synthetic_data:
        sea, land = np.ones(db.shape, dtype=bool), None
    else:
        sea, land = sea_mask(db.shape, affine, crs, params.coastal_buffer_m)
    valid = np.isfinite(db)
    mask = dark_mask(db, sea, params)
    polygons = polygonize(mask, affine, params.min_area_km2 * 1e6, params.resolution_m / 2)
    progress("filtering", 65)
    speed, wind_flags = wind_gate(forcing.wind_u_ms, forcing.wind_v_ms, params)
    flags = list(dict.fromkeys(forcing.flags + wind_flags))
    if collection == "sentinel-1-grd":
        flags += ["grd_fallback", "radiometry_uncalibrated"]
    if len(polygons) > 500:
        flags.append("candidate_limit_500")
    back = Transformer.from_crs(crs, 4326, always_xy=True).transform
    project = Transformer.from_crs(4326, crs, always_xy=True).transform
    label = "SYNTHETIC" if synthetic_data else "OBSERVATION"
    candidates = []
    drifts = []
    for index, geom in enumerate(polygons[:500]):
        pixels = rasterize([(mapping(geom), 1)], out_shape=db.shape, transform=affine).astype(bool)
        delta, std = contrast(np.where(sea, db, np.nan), pixels)
        area = geom.area / 1e6
        centroid = geom.centroid
        lon, lat = back(centroid.x, centroid.y)
        coast = None if land is None else centroid.distance(land) / 1000
        corners = list(geom.minimum_rotated_rectangle.exterior.coords)
        edges = [Point(corners[i]).distance(Point(corners[i + 1])) for i in range(4)]
        elongation = max(edges) / max(min(edges), 1)
        port = min(ports(), key=lambda p: centroid.distance(Point(*project(p["lon"], p["lat"]))))
        port_distance = centroid.distance(Point(*project(port["lon"], port["lat"]))) / 1000
        total, band, breakdown = score(delta, elongation, area, coast, speed, flags)
        nearby = []
        for vessel in vessels or []:
            dt = abs((acquired - datetime.fromisoformat(vessel["time"])).total_seconds())
            if dt <= 1800:
                distance = centroid.distance(Point(*project(vessel["longitude"], vessel["latitude"]))) / 1000
                nearby.append((distance, vessel["mmsi"]))
        nearest = min(nearby) if nearby else None
        cid = f"candidate-{index + 1}"
        properties = dict(
            id=cid,
            data_label=label,
            acquisition_time=acquired,
            area_km2=area,
            perimeter_km=geom.length / 1000,
            compactness=min(1, 4 * pi * geom.area / (geom.length**2)),
            elongation=elongation,
            contrast_db=delta,
            contrast_std_db=std,
            mean_db=float(db[pixels & valid].mean()),
            distance_to_coast_km=coast,
            nearest_port=port["name"],
            distance_to_port_km=port_distance,
            nearest_vessel=nearest[1] if nearest else None,
            vessel_distance_km=nearest[0] if nearest else None,
            score=total,
            band=band,
            breakdown=breakdown,
            flags=flags + ([] if nearest else ["ais_context_unavailable"]),
        )
        candidates.append(Candidate(geometry=mapping(transform(back, geom)), properties=properties))
        drifts.append(forecast(cid, lon, lat, sqrt(geom.area / pi), forcing))
    progress("drift", 85)
    coverage = float(valid.mean() * 100)
    if coverage < 80:
        flags.append("partial_aoi_coverage")
    qa = QA(
        valid_pixel_percent=coverage,
        aoi_coverage_percent=coverage,
        sea_pixel_percent=float(sea.mean() * 100),
        wind_available=speed is not None,
        data_age_hours=max(0, (utcnow() - acquired).total_seconds() / 3600),
        processing_seconds=time.perf_counter() - began,
        software_version=__version__,
        working_resolution_m=params.resolution_m,
        flags=flags,
    )
    result = Result(
        id="pending",
        scene_id=scene_id,
        collection=collection,
        acquisition_time=acquired,
        processed_at=utcnow(),
        data_label=label,
        aoi=aoi,
        parameters=params,
        candidates=Candidates(features=candidates),
        drift=drifts,
        conditions=forcing,
        qa=qa,
        total_area_km2=sum(c.properties.area_km2 for c in candidates),
        preview_bounds=aoi,
        preview_url=None,
    )
    return result, preview_png(db, affine, crs, aoi)


def analyze(request: AnalyzeRequest, progress: Callable = lambda *_: None, vessels=None):
    began = time.perf_counter()
    progress("searching", 5)
    if request.demo:
        power, _, affine, crs = synthetic.scene()
        aoi = transform_bounds(crs, 4326, *array_bounds(*power.shape, affine))
        acquired = datetime(2025, 1, 15, 4, 0, tzinfo=UTC)
        forcing = Conditions(
            time=acquired,
            longitude=(aoi[0] + aoi[2]) / 2,
            latitude=(aoi[1] + aoi[3]) / 2,
            wind_u_ms=4,
            wind_v_ms=1,
            current_u_ms=0.12,
            current_v_ms=-0.06,
            data_label="SYNTHETIC",
            flags=["synthetic_forcing"],
        )
        scene_id, collection = "SYNTHETIC-demo-42", "SYNTHETIC"
    else:
        listing, items = search(request.aoi, request.start, request.end, request.scene_id)
        if not items:
            raise RuntimeError(f"No VV scenes found; RTC search: {listing.coverage}")
        item = items[0]
        acquired = item.datetime
        scene_id, collection = item.id, item.collection_id
        progress("loading", 20)
        power, affine, crs = load(item, request.aoi, request.parameters)
        aoi = request.aoi
        forcing = conditions.fetch((aoi[0] + aoi[2]) / 2, (aoi[1] + aoi[3]) / 2, acquired)
    result, png = process_arrays(
        power,
        affine,
        crs,
        aoi,
        acquired,
        scene_id,
        collection,
        request.parameters,
        forcing,
        progress,
        vessels,
        request.demo,
    )
    result.id = cache_key(scene_id, request)
    result.preview_url = f"/api/v1/results/{result.id}/preview.png"
    result.qa.processing_seconds = time.perf_counter() - began
    return result, png


def write_result(result: Result, png: bytes, directory: Path):
    directory.mkdir(parents=True, exist_ok=True)
    target = directory / f"{result.id}.json"
    temporary = target.with_suffix(".tmp")
    temporary.write_text(result.model_dump_json(), encoding="utf-8")
    temporary.replace(target)
    (directory / f"{result.id}.png").write_bytes(png)
