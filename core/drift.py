from math import cos, radians, sin

from pyproj import CRS, Transformer
from shapely.geometry import LineString, MultiPoint, mapping
from shapely.ops import transform

from core.models import Conditions, DriftForecast


def local_crs(lon, lat):
    return CRS.from_proj4(f"+proj=aeqd +lat_0={lat} +lon_0={lon} +datum=WGS84 +units=m")


def integrate(u, v, hours, step_seconds=900):
    return [(u * i * step_seconds, v * i * step_seconds) for i in range(int(hours * 3600 / step_seconds) + 1)]


def forecast(candidate_id, lon, lat, radius_m, conditions: Conditions):
    flags = []
    wu, wv = conditions.wind_u_ms, conditions.wind_v_ms
    if wu is None or wv is None:
        flags.append("wind_unavailable")
    wu, wv = wu or 0, wv or 0
    missing = conditions.current_u_ms is None or conditions.current_v_ms is None
    if missing:
        flags.append("current_unavailable")
    cu, cv = conditions.current_u_ms or 0, conditions.current_v_ms or 0
    back = Transformer.from_crs(local_crs(lon, lat), 4326, always_xy=True).transform
    nominal = integrate(cu + 0.03 * wu, cv + 0.03 * wv, 24)
    envelopes = {}
    for hours in (6, 12, 24):
        points = []
        for windage in (0.02, 0.03, 0.04):
            for deviation in (-20, 0, 20):
                a = radians(deviation)
                u = cu + windage * (wu * cos(a) - wv * sin(a))
                v = cv + windage * (wu * sin(a) + wv * cos(a))
                points.append((u * hours * 3600, v * hours * 3600))
        growth_ms = 0.20 if missing else 0.05
        if "wind_unavailable" in flags:
            growth_ms += 0.3
        envelope = MultiPoint(points).convex_hull.buffer(max(radius_m, 30) + growth_ms * hours * 3600)
        envelopes[str(hours)] = mapping(transform(back, envelope.simplify(30)))
    return DriftForecast(
        candidate_id=candidate_id,
        track=mapping(LineString([back(x, y) for x, y in nominal])),
        envelopes=envelopes,
        flags=flags,
    )
