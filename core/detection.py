import numpy as np
from rasterio.features import shapes
from scipy.ndimage import binary_dilation, uniform_filter
from shapely.geometry import shape
from skimage.morphology import binary_closing, binary_opening, disk, remove_small_objects

from core.models import Parameters


def to_db(power):
    a = np.asarray(power, dtype=np.float32)
    out = np.full_like(a, np.nan)
    np.log10(a, out=out, where=np.isfinite(a) & (a > 0))
    return out * 10


def lee_filter(power, size: int = 5):
    """Local moment Lee equivalent; noise ratio estimated from median variance/mean²."""
    valid = np.isfinite(power) & (power > 0)
    count = uniform_filter(valid.astype(float), size)
    mean = uniform_filter(np.where(valid, power, 0).astype(float), size) / np.maximum(count, 1e-9)
    second = uniform_filter(np.where(valid, power * power, 0).astype(float), size) / np.maximum(count, 1e-9)
    variance = np.maximum(second - mean * mean, 0)
    ratios = variance[valid] / np.maximum(mean[valid] ** 2, 1e-12)
    noise_ratio = float(np.median(ratios)) if ratios.size else 0
    weight = np.clip((variance - noise_ratio * mean**2) / np.maximum(variance, 1e-12), 0, 1)
    return np.where(valid, mean + weight * (power - mean), np.nan).astype(np.float32)


def dark_mask(db, sea, params: Parameters):
    valid = sea & np.isfinite(db)
    weights = uniform_filter(valid.astype(float), params.window_pixels)
    mean = uniform_filter(np.where(valid, db, 0), params.window_pixels) / np.maximum(weights, 1e-9)
    second = uniform_filter(np.where(valid, db * db, 0), params.window_pixels) / np.maximum(weights, 1e-9)
    std = np.sqrt(np.maximum(second - mean * mean, 0))
    mask = valid & (weights > 0.5) & (db < mean - params.threshold_k * np.maximum(std, 0.5))
    mask &= (db >= params.dark_min_db) & (db <= params.dark_max_db)
    mask = binary_closing(binary_opening(mask, disk(1)), disk(2)) & valid
    minimum = int(np.ceil(params.min_area_km2 * 1e6 / params.resolution_m**2))
    return remove_small_objects(mask, min_size=minimum)


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
    return sorted(polygons, key=lambda g: g.area, reverse=True)


def contrast(db, pixels):
    ring = binary_dilation(pixels, iterations=8) & ~pixels & np.isfinite(db)
    inside = db[pixels & np.isfinite(db)]
    outside = db[ring]
    if not inside.size or not outside.size:
        return 0.0, 0.0
    return float(outside.mean() - inside.mean()), float(np.sqrt(outside.var() + inside.var()))
