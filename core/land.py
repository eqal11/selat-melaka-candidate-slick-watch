import json
from functools import lru_cache

import numpy as np
from pyproj import Transformer
from rasterio.features import rasterize
from shapely.geometry import mapping, shape
from shapely.ops import transform, unary_union

from core.config import ROOT


@lru_cache(maxsize=8)
def projected_land(crs: str):
    path = ROOT / "data/land/natural-earth.geojson"
    if not path.exists():
        raise RuntimeError("Bundled Natural Earth mask missing; run python -m pipeline.fetch_land")
    features = json.loads(path.read_text())["features"]
    project = Transformer.from_crs(4326, crs, always_xy=True).transform
    return transform(project, unary_union([shape(f["geometry"]) for f in features]))


def sea_mask(shape_hw, affine, crs, buffer_m=1500):
    land = projected_land(str(crs))
    mask = rasterize(
        [(mapping(land.buffer(buffer_m)), 1)], out_shape=shape_hw, transform=affine, fill=0, dtype="uint8"
    )
    return ~mask.astype(np.bool_), land
