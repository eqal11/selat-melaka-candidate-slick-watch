"""Real-scene dark-region detector with explicit stage counts."""

import math

import numpy as np
from rasterio.features import shapes
from scipy.ndimage import binary_dilation, label, uniform_filter
from shapely.geometry import shape
from skimage.morphology import binary_closing, binary_opening, disk

from core.models import Parameters


def to_db(power):
    values = np.asarray(power, dtype=np.float32)
    result = np.full_like(values, np.nan)
    np.log10(values, out=result, where=np.isfinite(values) & (values > 0))
    return result * 10


def lee_filter(power, size: int = 5):
    """Local moment Lee equivalent; noise ratio is median local CV squared."""
    valid = np.isfinite(power) & (power > 0)
    count = uniform_filter(valid.astype(np.float32), size, mode="nearest")
    mean = uniform_filter(np.where(valid, power, 0).astype(np.float32), size, mode="nearest") / np.maximum(
        count, 1e-9
    )
    second = uniform_filter(
        np.where(valid, power * power, 0).astype(np.float32), size, mode="nearest"
    ) / np.maximum(count, 1e-9)
    variance = np.maximum(second - mean * mean, 0)
    ratios = variance[valid] / np.maximum(mean[valid] ** 2, 1e-12)
    noise_ratio = float(np.median(ratios)) if ratios.size else 0.0
    weight = np.clip((variance - noise_ratio * mean**2) / np.maximum(variance, 1e-12), 0, 1)
    return np.where(valid, mean + weight * (power - mean), np.nan).astype(np.float32)


def local_dark_pixels(db, params: Parameters):
    valid = np.isfinite(db)
    weights = uniform_filter(valid.astype(np.float32), params.window_pixels, mode="nearest")
    mean = uniform_filter(
        np.where(valid, db, 0).astype(np.float32), params.window_pixels, mode="nearest"
    ) / np.maximum(weights, 1e-9)
    second = uniform_filter(
        np.where(valid, db * db, 0).astype(np.float32), params.window_pixels, mode="nearest"
    ) / np.maximum(weights, 1e-9)
    std = np.sqrt(np.maximum(second - mean * mean, 0))
    threshold = mean - params.threshold_k * np.maximum(std, 0.5)
    return (
        valid & (weights > 0.8) & (db < threshold) & (db >= params.dark_min_db) & (db <= params.dark_max_db)
    )


def candidate_components(
    db, raw_dark, sea, protected_mask, wind_ok, affine, params: Parameters, wind_available=True
):
    """Return shape-filtered candidates and a pixel/component funnel."""
    valid = np.isfinite(db)
    funnel = {
        "raw_dark_pixels": int(raw_dark.sum()),
        "after_land_mask_pixels": int((raw_dark & sea).sum()),
        "after_ship_platform_port_mask_pixels": 0,
        "after_wind_gate_pixels": 0,
        "wind_gate_removed_pixels": 0,
        "retained_wind_unknown_pixels": 0,
        "after_area_filter_components": 0,
        "after_shape_filter_candidates": 0,
        "final_candidates": 0,
        "filtered_dark_areas": 0,
        "filtered_area": 0,
        "filtered_contrast": 0,
        "filtered_shape": 0,
        "filtered_smooth_region": 0,
    }
    after_land = raw_dark & sea
    after_protected = after_land & ~protected_mask
    funnel["after_ship_platform_port_mask_pixels"] = int(after_protected.sum())
    # Preserve candidates if winds are out of range or unavailable. Score/flags explain why.
    after_wind = after_protected
    funnel["after_wind_gate_pixels"] = int(after_protected.sum() if wind_ok else 0)
    funnel["wind_gate_removed_pixels"] = int(after_protected.sum() if wind_available and not wind_ok else 0)
    funnel["retained_wind_unknown_pixels"] = int(after_protected.sum() if not wind_available else 0)
    merged = binary_closing(binary_opening(after_wind, disk(1)), disk(2)) & after_wind
    labels, component_count = label(merged)
    pixel_area = abs(affine.a * affine.e - affine.b * affine.d)
    min_pixels = max(1, math.ceil(params.min_area_km2 * 1e6 / pixel_area))
    max_pixels = math.floor(params.max_area_km2 * 1e6 / pixel_area)
    area_components = []
    for component_id in range(1, component_count + 1):
        component = labels == component_id
        pixels = int(component.sum())
        area_components.append((component, pixels))
    funnel["after_area_filter_components"] = sum(
        min_pixels <= pixels <= max_pixels for _, pixels in area_components
    )
    records = []
    for component, pixels in area_components:
        component_shapes = [
            shape(geometry)
            for geometry, value in shapes(component.astype("uint8"), mask=component, transform=affine)
            if value == 1
        ]
        if not component_shapes:
            continue
        geom = max(component_shapes, key=lambda item: item.area)
        area_m2 = pixels * pixel_area
        perimeter = geom.length
        if perimeter <= 0:
            continue
        compactness = min(1.0, 4 * math.pi * area_m2 / perimeter**2)
        rectangle = geom.minimum_rotated_rectangle
        coords = list(rectangle.exterior.coords)
        edges = [math.dist(coords[i], coords[i + 1]) for i in range(4)]
        elongation = max(edges) / max(min(edges), 1e-9)
        ring = (
            binary_dilation(component, iterations=max(1, round(240 / params.resolution_m)))
            & ~component
            & sea
            & valid
        )
        inside_values, outside_values = db[component & valid], db[ring]
        if not inside_values.size or not outside_values.size:
            continue
        contrast_db = float(outside_values.mean() - inside_values.mean())
        contrast_std = float(np.sqrt(outside_values.var() + inside_values.var()))
        area_km2 = area_m2 / 1e6
        smooth_large = area_km2 >= 1.0 and float(inside_values.std()) < 1.0
        reasons = []
        if not min_pixels <= pixels <= max_pixels:
            reasons.append("area_out_of_range")
            funnel["filtered_area"] += 1
        if contrast_db < params.min_contrast_db:
            reasons.append("contrast_below_minimum")
            funnel["filtered_contrast"] += 1
        if compactness < params.min_compactness or elongation > params.max_elongation:
            reasons.append("shape_out_of_range")
            funnel["filtered_shape"] += 1
        if smooth_large:
            reasons.append("large_smooth_region")
            funnel["filtered_smooth_region"] += 1
        if not reasons:
            funnel["after_shape_filter_candidates"] += 1
        else:
            funnel["filtered_dark_areas"] += 1
        records.append(
            {
                "geometry": geom,
                "pixels": component,
                "area_km2": area_km2,
                "perimeter_km": perimeter / 1000,
                "compactness": compactness,
                "elongation": elongation,
                "contrast_db": contrast_db,
                "contrast_std_db": contrast_std,
                "mean_db": float(inside_values.mean()),
                "label": "filtered" if reasons else "candidate",
                "reason_code": reasons[0] if reasons else None,
                "reason_codes": reasons,
            }
        )
    funnel["final_candidates"] = sum(record["label"] == "candidate" for record in records)
    return records, funnel


def polygonize(mask, affine, minimum_m2=0, tolerance_m=20):
    polygons = []
    for geometry, value in shapes(mask.astype("uint8"), mask=mask, transform=affine):
        if value != 1:
            continue
        geom = shape(geometry)
        if geom.area >= minimum_m2:
            simplified = geom.simplify(tolerance_m, preserve_topology=True)
            if simplified.is_valid and not simplified.is_empty:
                polygons.append(simplified)
    return sorted(polygons, key=lambda item: item.area, reverse=True)


def contrast(db, pixels):
    ring = binary_dilation(pixels, iterations=8) & ~pixels & np.isfinite(db)
    inside = db[pixels & np.isfinite(db)]
    outside = db[ring]
    if not inside.size or not outside.size:
        return 0.0, 0.0
    return float(outside.mean() - inside.mean()), float(np.sqrt(outside.var() + inside.var()))
