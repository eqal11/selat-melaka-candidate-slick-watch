import json
from pathlib import Path

from pydantic import Field

from core.models import Model, validate_bbox

ROOT = Path(__file__).resolve().parents[1]


class Zone(Model):
    id: str
    name: str
    bbox: tuple[float, float, float, float]


class Zones(Model):
    zones: list[Zone] = Field(min_length=3)


def zones() -> Zones:
    parsed = Zones.model_validate_json((ROOT / "data/zones.json").read_text())
    for zone in parsed.zones:
        validate_bbox(zone.bbox)
    return parsed


def ports():
    return json.loads((ROOT / "data/ports.json").read_text())
