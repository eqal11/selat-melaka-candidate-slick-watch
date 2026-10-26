from datetime import UTC, datetime
from math import cos, radians, sin

import numpy as np

from core.http import get_json
from core.models import Conditions, utcnow


def vector(speed, direction, wind=False):
    sign = -1 if wind else 1
    return sign * speed * sin(radians(direction)), sign * speed * cos(radians(direction))


def interpolate(hourly, speed_name, direction_name, when, wind=False):
    times = hourly.get("time", [])
    values = []
    for i, t in enumerate(times):
        speed, direction = hourly[speed_name][i], hourly[direction_name][i]
        if speed is not None and direction is not None:
            values.append(
                (datetime.fromisoformat(t).replace(tzinfo=UTC).timestamp(), *vector(speed, direction, wind))
            )
    stamp = when.timestamp()
    if not values or stamp < values[0][0] or stamp > values[-1][0]:
        return None, None
    ts, u, v = zip(*values, strict=True)
    return float(np.interp(stamp, ts, u)), float(np.interp(stamp, ts, v))


def fetch(lon, lat, when):
    flags = []
    wu = wv = cu = cv = None
    past = (utcnow() - when).total_seconds() / 86400
    params = {
        "latitude": lat,
        "longitude": lon,
        "timezone": "GMT",
        "wind_speed_unit": "ms",
        "start_date": when.date().isoformat(),
        "end_date": when.date().isoformat(),
    }
    try:
        url = (
            "https://archive-api.open-meteo.com/v1/archive"
            if past > 5
            else "https://api.open-meteo.com/v1/forecast"
        )
        weather = get_json(url, {**params, "hourly": "wind_speed_10m,wind_direction_10m"})
        wu, wv = interpolate(weather["hourly"], "wind_speed_10m", "wind_direction_10m", when, True)
    except (RuntimeError, KeyError, ValueError):
        flags.append("wind_unavailable")
    try:
        marine = get_json(
            "https://marine-api.open-meteo.com/v1/marine",
            {**params, "cell_selection": "sea", "hourly": "ocean_current_velocity,ocean_current_direction"},
        )
        cu, cv = interpolate(marine["hourly"], "ocean_current_velocity", "ocean_current_direction", when)
    except (RuntimeError, KeyError, ValueError):
        flags.append("current_unavailable")
    if wu is None and "wind_unavailable" not in flags:
        flags.append("wind_unavailable")
    if cu is None and "current_unavailable" not in flags:
        flags.append("current_unavailable")
    return Conditions(
        time=when,
        longitude=lon,
        latitude=lat,
        wind_u_ms=wu,
        wind_v_ms=wv,
        current_u_ms=cu,
        current_v_ms=cv,
        flags=flags,
    )
