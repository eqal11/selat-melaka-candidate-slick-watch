from datetime import datetime

import planetary_computer
import pystac
from pystac_client import Client
from pystac_client.stac_api_io import StacApiIO
from requests.adapters import Retry
from shapely.geometry import box, shape

from core.models import Scene, SceneList, validate_bbox

STAC_URL = "https://planetarycomputer.microsoft.com/api/stac/v1"


def client():
    io = StacApiIO(
        timeout=20, max_retries=Retry(total=2, backoff_factor=0.5, status_forcelist=[429, 500, 502, 503, 504])
    )
    return Client.open(STAC_URL, stac_io=io)


def search(bbox, start: datetime | None, end: datetime | None, scene_id=None):
    validate_bbox(bbox)
    catalog = client()
    queries = {"bbox": list(bbox), "max_items": 60, "limit": 60}
    if scene_id:
        queries["ids"] = [scene_id]
    else:
        if start is None or end is None:
            raise ValueError("Provide a date range or scene ID")
        queries["datetime"] = f"{start.isoformat()}/{end.isoformat()}"
    rtc = list(catalog.search(collections=["sentinel-1-rtc"], **queries).items())
    aoi = box(*bbox)

    def coverage(item):
        return shape(item.geometry).intersection(aoi).area / aoi.area

    good = [i for i in rtc if coverage(i) >= 0.8 and "vv" in i.assets]
    metadata = {
        "rtc_items": len(rtc),
        "rtc_usable_items": len(good),
        "minimum_footprint_fraction": 0.8,
        "note": "Footprint coverage; valid ocean pixels are assessed after loading",
        "truncated_at": 60,
    }
    items = good
    if not good:
        if scene_id and scene_id.endswith("_rtc"):
            queries["ids"] = [scene_id[:-4]]
        items = [
            i for i in catalog.search(collections=["sentinel-1-grd"], **queries).items() if "vv" in i.assets
        ]
        metadata["fallback"] = "sentinel-1-grd"
    items.sort(key=lambda i: i.datetime or datetime.min, reverse=True)
    scenes = [
        Scene(
            id=i.id,
            collection=i.collection_id,
            acquisition_time=i.datetime,
            footprint=i.geometry,
            flags=[] if i.collection_id == "sentinel-1-rtc" else ["grd_fallback", "radiometry_uncalibrated"],
        )
        for i in items
    ]
    return SceneList(scenes=scenes, coverage=metadata), items


def signed(item: pystac.Item):
    # Requests signing is bounded independently of STAC retries.
    import requests
    from urllib3.util.retry import Retry as HTTPRetry

    with requests.Session() as session:
        session.mount(
            "https://",
            __import__("requests").adapters.HTTPAdapter(max_retries=HTTPRetry(total=2, backoff_factor=0.5)),
        )
    return planetary_computer.sign(item)
