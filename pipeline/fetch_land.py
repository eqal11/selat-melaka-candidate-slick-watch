import hashlib
import io
import json
import zipfile

import httpx
import shapefile
from shapely.geometry import box, mapping, shape

from core.config import ROOT

URL = "https://naturalearth.s3.amazonaws.com/10m_physical/ne_10m_land.zip"


def main():
    response = httpx.get(URL, timeout=120, follow_redirects=True)
    response.raise_for_status()
    target = ROOT / "work/ne_land"
    target.mkdir(parents=True, exist_ok=True)
    with zipfile.ZipFile(io.BytesIO(response.content)) as bundle:
        for name in bundle.namelist():
            if "/" not in name and chr(92) not in name and name.startswith("ne_10m_land."):
                (target / name).write_bytes(bundle.read(name))
    reader = shapefile.Reader(str(target / "ne_10m_land.shp"))
    clip = box(94, -1, 106, 9)
    features = []
    for item in reader.shapes():
        geom = shape(item.__geo_interface__)
        if geom.intersects(clip):
            clipped = geom.intersection(clip).simplify(0.00015, preserve_topology=True)
            features.append(
                {
                    "type": "Feature",
                    "properties": {"source": "Natural Earth 1:10m land"},
                    "geometry": mapping(clipped),
                }
            )
    (ROOT / "data/land/natural-earth.geojson").write_text(
        json.dumps({"type": "FeatureCollection", "features": features}, separators=(",", ":"))
    )
    (ROOT / "data/land/SOURCE.json").write_text(
        json.dumps(
            {
                "url": URL,
                "sha256": hashlib.sha256(response.content).hexdigest(),
                "license": "public domain",
                "clip": [94, -1, 106, 9],
                "simplification_degrees": 0.00015,
            },
            indent=2,
        )
    )
    print(f"Bundled {len(features)} land polygons")


if __name__ == "__main__":
    main()
