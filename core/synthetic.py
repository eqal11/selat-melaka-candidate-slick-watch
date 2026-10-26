"""SYNTHETIC deterministic fixture; not an incident or satellite observation."""

import numpy as np
from rasterio.transform import from_origin


def scene(seed=42):
    rng = np.random.default_rng(seed)
    h, w, resolution = 512, 640, 30
    y, x = np.mgrid[:h, :w]
    truth = ((x - 210) / 64) ** 2 + ((y - 240) / 13) ** 2 < 1
    truth |= ((x - 445) / 42) ** 2 + ((y - 325) / 11) ** 2 < 1
    background = 10 ** (-13 / 10) * np.ones((h, w))
    background[truth] = 10 ** (-25 / 10)
    power = background * rng.gamma(6, 1 / 6, size=(h, w))
    power[90:95, 300:305] = 1.5
    affine = from_origin(705000, 325000, resolution, resolution)
    return power.astype(np.float32), truth, affine, "EPSG:32647"
