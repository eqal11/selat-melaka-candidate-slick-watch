"""Sentinel-1 and optional Sentinel-2 STAC discovery."""

from datetime import datetime, timedelta
from typing import Any

import planetary_computer
import pystac
from pystac_client import Client
from pystac_client.stac_api_io import StacApiIO
from requests.adapters import Retry
from shapely.geometry import box, shape

from core.models import OpticalScene, Scene, SceneList, validate_bbox

STAC_URL = "https://planetarycomputer.microsoft.com/api/stac/v1"


def client():
    io = StacApiIO(
        timeout=20,
        max_retries=Retry(total=2, backoff_factor=0.5, status_forcelist=[429, 500, 502, 503, 504]),
    )
    try:
        return Client.open(STAC_URL, stac_io=io)
    except Exception as exc:
        raise RuntimeError(f"Planetary Computer unreachable: {type(exc).__name__}: {exc}") from exc


def _metadata(item):
    props = item.properties
    platform = str(props.get("platform", "")).lower()
    satellite = platform.replace("sentinel-1", "S1").upper()
    if satellite not in {"S1A", "S1B", "S1C", "S1D"}:
        raise RuntimeError(f"Sentinel-1 satellite metadata missing or unsupported for STAC item {item.id}")
    orbit = str(props.get("sat:orbit_state", "")).upper()
    if orbit not in {"ASCENDING", "DESCENDING"}:
        raise RuntimeError(f"Sentinel-1 orbit direction missing for STAC item {item.id}")
    polarizations = [str(value).upper() for value in props.get("sar:polarizations", [])]
    if "VV" not in polarizations:
        raise RuntimeError(f"VV polarization unavailable for STAC item {item.id}")
    return satellite, orbit, polarizations, item.get_self_href()


def search(bbox, start: datetime | None, end: datetime | None, scene_id=None):
    validate_bbox(bbox)
    if not scene_id and (start is None or end is None):
        raise ValueError("Provide a date range or scene ID")
    try:
        catalog = client()
        queries: dict[str, Any] = {"bbox": list(bbox), "max_items": 120, "limit": 120}
        if scene_id:
            queries["ids"] = [scene_id]
        else:
            assert start is not None and end is not None
            queries["datetime"] = f"{start.isoformat()}/{end.isoformat()}"
        rtc = list(catalog.search(collections=["sentinel-1-rtc"], **queries).items())
        aoi = box(*bbox)

        def coverage(item):
            return shape(item.geometry).intersection(aoi).area / aoi.area

        good = [item for item in rtc if coverage(item) >= 0.8 and "vv" in item.assets]
        metadata = {
            "rtc_items": len(rtc),
            "rtc_usable_items": len(good),
            "minimum_footprint_fraction": 0.8,
            "note": "STAC footprint overlap; valid AOI pixels are measured after loading",
        }
        items = good
        if not good:
            if scene_id and scene_id.endswith("_rtc"):
                queries["ids"] = [scene_id[:-4]]
            items = [
                item
                for item in catalog.search(collections=["sentinel-1-grd"], **queries).items()
                if "vv" in item.assets and coverage(item) >= 0.8
            ]
            metadata["fallback"] = "sentinel-1-grd"
        items.sort(key=lambda item: item.datetime or datetime.min, reverse=True)
        scenes = []
        for item in items:
            if item.datetime is None:
                continue
            satellite, orbit, polarizations, href = _metadata(item)
            scenes.append(
                Scene(
                    id=item.id,
                    collection=item.collection_id,
                    satellite=satellite,
                    orbit_direction=orbit,
                    polarization=polarizations,
                    stac_href=href,
                    acquisition_time=item.datetime,
                    footprint=item.geometry,
                    flags=[]
                    if item.collection_id == "sentinel-1-rtc"
                    else ["grd_fallback", "radiometry_uncalibrated"],
                )
            )
        return SceneList(scenes=scenes, coverage=metadata), items
    except (ValueError, RuntimeError):
        raise
    except Exception as exc:
        raise RuntimeError(f"Planetary Computer unreachable: {type(exc).__name__}: {exc}") from exc


def search_optical(bbox, acquired: datetime) -> tuple[OpticalScene | None, str]:
    """Return a real S2 L2A footprint with <=30% cloud within one day, or None."""
    try:
        catalog = client()
        start, end = acquired - timedelta(days=1), acquired + timedelta(days=1)
        aoi = box(*bbox)
        items = catalog.search(
            collections=["sentinel-2-l2a"],
            bbox=list(bbox),
            datetime=f"{start.isoformat()}/{end.isoformat()}",
            query={"eo:cloud_cover": {"lt": 30}},
            max_items=40,
        ).items()
        matches = []
        for item in items:
            cloud = item.properties.get("eo:cloud_cover")
            if cloud is None or not 0 <= float(cloud) < 30 or item.datetime is None:
                continue
            if shape(item.geometry).intersection(aoi).area / aoi.area < 0.8:
                continue
            matches.append(item)
        if not matches:
            return None, "none"
        item = min(matches, key=lambda value: abs((value.datetime - acquired).total_seconds()))
        return OpticalScene(
            id=item.id,
            acquisition_time=item.datetime,
            cloud_percent=float(item.properties["eo:cloud_cover"]),
            stac_href=item.get_self_href(),
        ), "available"
    except Exception:
        # Optical is optional; never represent an unreachable catalogue as confirmed absence.
        return None, "unavailable"


def signed(item: pystac.Item):
    # Sign asset URLs server-side only; STAC item links stay public and unsigned.
    return planetary_computer.sign(item)
