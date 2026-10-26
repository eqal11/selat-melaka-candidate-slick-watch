"""Traceable real-scene analysis and georeferenced review assets."""

import hashlib
import io
import json
import time
from math import sqrt
from pathlib import Path
from typing import Callable

import numpy as np
from PIL import Image
from pyproj import Transformer
from rasterio.enums import Resampling
from rasterio.features import rasterize
from rasterio.transform import array_bounds, from_bounds
from rasterio.warp import reproject
from scipy.ndimage import binary_dilation
from shapely.geometry import Point, box, mapping, shape
from shapely.ops import transform

from core import __version__, conditions
from core.config import ports
from core.detection import candidate_components, lee_filter, local_dark_pixels, to_db
from core.drift import forecast
from core.land import sea_mask
from core.loading import check_budget, load
from core.models import QA, AnalyzeRequest, Candidate, Candidates, Geometry, Result, utcnow
from core.scenes import search, search_optical
from core.scoring import score, wind_gate

PREVIEW_SIZE = 600
FIXED_MIN_DB = -25.0
FIXED_MAX_DB = 0.0


def cache_key(scene_id, request):
    content = {
        "scene": scene_id,
        "aoi": request.aoi,
        "parameters": request.parameters.model_dump(),
        "version": __version__,
    }
    return hashlib.sha256(json.dumps(content, sort_keys=True).encode()).hexdigest()[:24]


def _projected_preview(array, affine, crs, bounds, nearest=False):
    target: np.ndarray = np.full((PREVIEW_SIZE, PREVIEW_SIZE), np.nan, dtype=np.float32)
    reproject(
        np.asarray(array, dtype=np.float32),
        target,
        src_transform=affine,
        src_crs=crs,
        src_nodata=np.nan,
        dst_transform=from_bounds(*bounds, PREVIEW_SIZE, PREVIEW_SIZE),
        dst_crs="EPSG:4326",
        dst_nodata=np.nan,
        resampling=Resampling.nearest if nearest else Resampling.average,
    )
    return target


def _webp(array, affine, crs, bounds, *, kind="gray", stretch="fixed"):
    target = _projected_preview(array, affine, crs, bounds, nearest=kind != "gray")
    valid = np.isfinite(target)
    if kind == "gray":
        if stretch == "fixed":
            low, high = FIXED_MIN_DB, FIXED_MAX_DB
        else:
            low, high = (
                (float(np.nanpercentile(target[valid], 2)), float(np.nanpercentile(target[valid], 98)))
                if valid.any()
                else (FIXED_MIN_DB, FIXED_MAX_DB)
            )
            high = max(high, low + 0.1)
        shade = (np.clip((np.nan_to_num(target, nan=low) - low) / (high - low), 0, 1) * 255).astype("uint8")
        rgba = np.stack([shade, shade, shade, valid.astype("uint8") * 255], axis=-1)
    else:
        mask = valid & (target > 0.5)
        rgba = np.zeros((PREVIEW_SIZE, PREVIEW_SIZE, 4), dtype="uint8")
        color = [208, 132, 72, 100] if kind == "land" else [255, 72, 38, 140]
        rgba[mask] = color
    stream = io.BytesIO()
    Image.fromarray(rgba).save(stream, format="WEBP", quality=88, method=6)
    return stream.getvalue(), target


def _port_platform_mask(shape_hw, affine, crs, params):
    project = Transformer.from_crs(4326, crs, always_xy=True).transform
    protected = []
    for port in ports():
        point = Point(*project(port["lon"], port["lat"]))
        protected.append(mapping(point.buffer(params.port_buffer_m)))
    assets_path = Path(__file__).resolve().parents[1] / "data" / "offshore_assets.geojson"
    if assets_path.exists():
        features = json.loads(assets_path.read_text(encoding="utf-8")).get("features", [])
        for feature in features:
            geom = transform(project, shape(feature["geometry"]))
            protected.append(mapping(geom.buffer(params.port_buffer_m)))
    return rasterize(protected, out_shape=shape_hw, transform=affine, fill=0, dtype="uint8").astype(bool)


def _alignment_error_m(shape_hw, affine, crs, bounds):
    west, south, east, north = bounds
    tx = Transformer.from_crs(4326, crs, always_xy=True)
    expected = [tx.transform(x, y) for x, y in ((west, south), (west, north), (east, south), (east, north))]
    actual_bounds = array_bounds(shape_hw[0], shape_hw[1], affine)
    actual = [
        (actual_bounds[0], actual_bounds[1]),
        (actual_bounds[0], actual_bounds[3]),
        (actual_bounds[2], actual_bounds[1]),
        (actual_bounds[2], actual_bounds[3]),
    ]
    # Loading reprojects to a rectangular projected AOI; this reports maximum corner residual.
    return max(
        sqrt((ex - ax) ** 2 + (ey - ay) ** 2) for (ex, ey), (ax, ay) in zip(expected, actual, strict=True)
    )


def process_arrays(
    power,
    affine,
    crs,
    aoi,
    acquired,
    item,
    params,
    forcing,
    progress: Callable = lambda *_: None,
    vessels=None,
):
    began = time.perf_counter()
    check_budget(power.shape[1], power.shape[0], params)
    progress("detecting", 45)
    raw_db = to_db(power)
    filtered_db = to_db(lee_filter(power))
    project_aoi = Transformer.from_crs(4326, crs, always_xy=True).transform
    aoi_projected = transform(project_aoi, box(*aoi))
    inside_aoi = rasterize(
        [mapping(aoi_projected)], out_shape=filtered_db.shape, transform=affine, fill=0, dtype="uint8"
    ).astype(bool)
    raw_db[~inside_aoi] = np.nan
    filtered_db[~inside_aoi] = np.nan
    valid = np.isfinite(filtered_db) & inside_aoi
    sea, land = sea_mask(filtered_db.shape, affine, crs, params.coastal_buffer_m)
    sea &= inside_aoi
    ports_platforms = _port_platform_mask(filtered_db.shape, affine, crs, params)
    bright = (filtered_db >= params.bright_target_db) & sea
    halo_pixels = max(1, round(params.ship_halo_m / params.resolution_m))
    bright_halo = binary_dilation(bright, iterations=halo_pixels)
    protected = bright_halo | ports_platforms
    raw_dark = local_dark_pixels(filtered_db, params)
    wind_speed, wind_flags = wind_gate(forcing.wind_u_ms, forcing.wind_v_ms, params)
    wind_available = wind_speed is not None
    wind_ok = bool(wind_available and params.wind_min_ms <= wind_speed <= params.wind_max_ms)
    records, funnel = candidate_components(
        filtered_db, raw_dark, sea, protected, wind_ok, affine, params, wind_available
    )
    if not wind_ok:
        reason = "wind_out_of_range" if wind_available else "wind_unavailable"
        for record in records:
            if record["label"] == "candidate":
                record["label"] = "filtered"
                record["reason_code"] = reason
                record["reason_codes"].append(reason)
                funnel["filtered_dark_areas"] += 1
                funnel["filtered_wind"] = funnel.get("filtered_wind", 0) + 1
        funnel["final_candidates"] = 0
    progress("filtering", 65)
    flags = list(dict.fromkeys(forcing.flags + wind_flags))
    if item.collection_id == "sentinel-1-grd":
        flags.extend(["grd_fallback", "radiometry_uncalibrated"])
    if not ports_platforms.any():
        flags.append("offshore_platform_mask_unavailable")
    back = Transformer.from_crs(crs, 4326, always_xy=True).transform
    project = Transformer.from_crs(4326, crs, always_xy=True).transform
    candidates, drifts, scored_records = [], [], []
    for record in records:
        geom = record["geometry"]
        area = record["area_km2"]
        centroid = geom.centroid
        lon, lat = back(centroid.x, centroid.y)
        coast = centroid.distance(land) / 1000
        port = min(ports(), key=lambda value: centroid.distance(Point(*project(value["lon"], value["lat"]))))
        port_distance = centroid.distance(Point(*project(port["lon"], port["lat"]))) / 1000
        total, band, breakdown = score(
            record["contrast_db"], record["elongation"], area, coast, wind_speed, flags
        )
        nearby = []
        for vessel in vessels or []:
            from datetime import datetime

            stamp = datetime.fromisoformat(vessel["time"])
            if abs((acquired - stamp).total_seconds()) <= 1800:
                distance = centroid.distance(Point(*project(vessel["longitude"], vessel["latitude"]))) / 1000
                nearby.append((distance, vessel["mmsi"]))
        nearest = min(nearby) if nearby else None
        record["score"], record["band"], record["breakdown"] = total, band, breakdown
        record["coast_km"], record["port_name"], record["port_distance_km"] = (
            coast,
            port["name"],
            port_distance,
        )
        record["nearest_vessel"] = nearest
        scored_records.append(record)
    scored_records.sort(key=lambda value: value["score"], reverse=True)
    satellite, orbit, polarization, stac_href = (
        str(item.properties.get("platform", "")).lower().replace("sentinel-1", "S1").upper(),
        str(item.properties.get("sat:orbit_state", "")).upper(),
        [str(value).upper() for value in item.properties.get("sar:polarizations", [])],
        item.get_self_href(),
    )
    if (
        satellite not in {"S1A", "S1B", "S1C", "S1D"}
        or orbit not in {"ASCENDING", "DESCENDING"}
        or "VV" not in polarization
    ):
        raise RuntimeError(f"Scene trace metadata incomplete for STAC item {item.id}")
    for index, record in enumerate(scored_records):
        geom = record["geometry"]
        centroid = geom.centroid
        lon, lat = back(centroid.x, centroid.y)
        is_filtered = record["label"] == "filtered"
        feature_flags = flags + record["reason_codes"] + ([] if record["nearest_vessel"] else ["ais_context_unavailable"])
        properties = dict(
            id=f"{'filtered' if is_filtered else 'candidate'}-{index + 1}",
            label=record["label"],
            reason_code=record["reason_code"],
            reason_codes=record["reason_codes"],
            data_label="REAL Sentinel-1",
            acquisition_time=acquired,
            area_km2=record["area_km2"],
            perimeter_km=record["perimeter_km"],
            compactness=record["compactness"],
            elongation=record["elongation"],
            contrast_db=record["contrast_db"],
            contrast_std_db=record["contrast_std_db"],
            mean_db=record["mean_db"],
            distance_to_coast_km=record["coast_km"],
            nearest_port=record["port_name"],
            distance_to_port_km=record["port_distance_km"],
            nearest_vessel=record["nearest_vessel"][1] if record["nearest_vessel"] else None,
            vessel_distance_km=record["nearest_vessel"][0] if record["nearest_vessel"] else None,
            score=record["score"],
            band=record["band"],
            breakdown=record["breakdown"],
            flags=feature_flags,
        )
        if is_filtered:
            base = properties["score"]
            scale = min(1.0, 19.0 / max(base, 1e-9))
            properties["breakdown"] = properties["breakdown"].model_copy(
                update={key: round(value * scale, 2) for key, value in properties["breakdown"].model_dump().items()}
            )
            properties["score"] = round(sum(properties["breakdown"].model_dump().values()), 1)
            properties["band"] = "Low"
        candidates.append(Candidate(geometry=mapping(transform(back, geom)), properties=properties))
        if not is_filtered:
            drifts.append(forecast(properties["id"], lon, lat, sqrt(geom.area / np.pi), forcing))
    progress("drift", 85)

    coverage = float(valid.sum() / max(inside_aoi.sum(), 1) * 100)
    if coverage < 80:
        flags.append("partial_aoi_coverage")
    coast_tx = Transformer.from_crs(4326, crs, always_xy=True).transform
    aoi_projected = transform(coast_tx, box(*aoi))
    footprint_projected = transform(coast_tx, shape(item.geometry))
    footprint_overlap = min(100.0, max(0.0, 100 * aoi_projected.intersection(footprint_projected).area / max(aoi_projected.area, 1e-9)))
    qa = QA(
        valid_pixel_percent=coverage,
        aoi_coverage_percent=coverage,
        sea_pixel_percent=float(sea.sum() / max(inside_aoi.sum(), 1) * 100),
        wind_available=wind_available,
        data_age_hours=max(0, (utcnow() - acquired).total_seconds() / 3600),
        processing_seconds=time.perf_counter() - began,
        software_version=__version__,
        working_resolution_m=params.resolution_m,
        flags=list(dict.fromkeys(flags)),
        funnel=funnel,
        raster_bounds_offset_m=_alignment_error_m(power.shape, affine, crs, aoi),
        stac_footprint_overlap_percent=footprint_overlap,
    )
    coastline_projected = land.boundary.intersection(aoi_projected).simplify(40, preserve_topology=True)
    coastline = transform(back, coastline_projected) if not coastline_projected.is_empty else None
    optical_scene, optical_status = search_optical(aoi, acquired)
    result = Result(
        id="pending",
        scene_id=item.id,
        satellite=satellite,
        orbit_direction=orbit,
        polarization=polarization,
        stac_href=stac_href,
        collection=item.collection_id,
        scene_footprint=Geometry.model_validate(
            {"type": item.geometry["type"], "coordinates": item.geometry["coordinates"]}
        ),
        optical_scene=optical_scene,
        optical_status=optical_status,
        zone=None,
        acquisition_time=acquired,
        processed_at=utcnow(),
        data_label="REAL Sentinel-1",
        aoi=aoi,
        parameters=params,
        candidates=Candidates(features=candidates),
        drift=drifts,
        conditions=forcing,
        qa=qa,
        total_area_km2=sum(
            value.properties.area_km2 for value in candidates if value.properties.label == "candidate"
        ),
        preview_bounds=aoi,
        preview_urls={},
        coastline=Geometry.model_validate(mapping(coastline)) if coastline is not None else None,
    )
    # Store the exact arrays used for detection plus georeferenced, decimated review imagery.
    assets = {}
    pixel_grids = {}
    for variant, array in (("raw", raw_db), ("filtered", filtered_db)):
        for stretch in ("fixed", "auto"):
            data, projected = _webp(array, affine, crs, aoi, stretch=stretch)
            assets[f"preview-{variant}-{stretch}.webp"] = data
            pixel_grids[f"{variant}_db"] = projected
    for layer_name, layer in (
        ("land", ~sea),
        ("ship", protected),
        ("wind-removed", raw_dark & sea & ~protected if not wind_ok else np.zeros_like(sea)),
    ):
        data, _ = _webp(
            layer.astype(np.float32), affine, crs, aoi, kind="mask" if layer_name == "land" else "bright"
        )
        assets[f"mask-{layer_name}.webp"] = data
    buffer = io.BytesIO()
    np.savez_compressed(
        buffer,
        raw_db=pixel_grids["raw_db"],
        filtered_db=pixel_grids["filtered_db"],
        bounds=np.asarray(aoi, dtype=np.float64),
    )
    assets["pixel-grid.npz"] = buffer.getvalue()
    result.id = cache_key(item.id, AnalyzeRequest(aoi=aoi, scene_id=item.id, parameters=params))
    result.preview_urls = {
        name: f"/api/v1/results/{result.id}/{name}"
        for name in assets
        if name.startswith("preview-") or name.startswith("mask-")
    }
    result.qa.processing_seconds = time.perf_counter() - began
    return result, assets


def analyze(request: AnalyzeRequest, progress: Callable = lambda *_: None, vessels=None):
    progress("searching", 5)
    listing, items = search(request.aoi, request.start, request.end, request.scene_id)
    if not items:
        raise RuntimeError(
            f"No Sentinel-1 scene found for this AOI and date range. STAC coverage: {listing.coverage}"
        )
    item = items[0]
    acquired = item.datetime
    progress("loading", 20)
    power, affine, crs = load(item, request.aoi, request.parameters)
    forcing = conditions.fetch(
        (request.aoi[0] + request.aoi[2]) / 2, (request.aoi[1] + request.aoi[3]) / 2, acquired
    )
    return process_arrays(
        power, affine, crs, request.aoi, acquired, item, request.parameters, forcing, progress, vessels
    )


def write_result(result: Result, assets: dict[str, bytes], directory: Path):
    directory.mkdir(parents=True, exist_ok=True)
    temporary = directory / f"{result.id}.tmp"
    temporary.write_text(result.model_dump_json(), encoding="utf-8")
    temporary.replace(directory / f"{result.id}.json")
    for name, content in assets.items():
        target_tmp = directory / f"{result.id}-{name}.tmp"
        target_tmp.write_bytes(content)
        target_tmp.replace(directory / f"{result.id}-{name}")
