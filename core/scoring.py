from math import hypot

from core.models import Breakdown, Parameters


def wind_gate(wind_u, wind_v, params: Parameters):
    if wind_u is None or wind_v is None:
        return None, ["wind_unavailable"]
    speed = hypot(wind_u, wind_v)
    return speed, [] if params.wind_min_ms <= speed <= params.wind_max_ms else ["wind_out_of_range"]


def score(contrast_db, elongation, area_km2, coast_km, wind_speed, flags):
    parts = Breakdown(
        contrast=35 * min(max(contrast_db / 8, 0), 1),
        shape=15 * min(max((elongation - 1) / 4, 0), 1),
        size=15 * min(max(area_km2 / 0.5, 0), 1),
        wind=25 if wind_speed is not None and not any(f.startswith("wind_") for f in flags) else 0,
        offshore=10 * min(max((coast_km or 0) / 5, 0), 1),
    )
    total = round(sum(parts.model_dump().values()), 1)
    total = min(total, 39 if "wind_out_of_range" in flags else 49 if "wind_unavailable" in flags else 100)
    return total, "High" if total >= 70 else "Medium" if total >= 40 else "Low", parts
