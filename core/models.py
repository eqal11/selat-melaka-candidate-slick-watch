from __future__ import annotations

import math
from datetime import UTC, datetime, timedelta
from typing import Any, Literal

from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator
from pyproj import Geod
from shapely.geometry import shape

STUDY_BBOX = (95.0, 0.8, 104.5, 7.0)
GEOD = Geod(ellps="WGS84")


def utcnow() -> datetime:
    return datetime.now(UTC)


def utc(value: datetime) -> datetime:
    if value.tzinfo is None:
        raise ValueError("Timestamp must include timezone (use Z for UTC)")
    return value.astimezone(UTC)


def validate_bbox(value: tuple[float, float, float, float], limited: bool = True):
    w, s, e, n = value
    if not all(math.isfinite(v) for v in value):
        raise ValueError("Coordinates must be finite")
    if not (95 <= w < e <= 104.5 and 0.8 <= s < n <= 7):
        raise ValueError("AOI must be within lon 95-104.5, lat 0.8-7")
    width = abs(GEOD.inv(w, (s + n) / 2, e, (s + n) / 2)[2])
    height = abs(GEOD.inv(w, s, w, n)[2])
    if limited and (width > 60000 or height > 60000):
        raise ValueError("Maximum AOI is 60 x 60 km")
    return value


class Model(BaseModel):
    model_config = ConfigDict(extra="forbid", allow_inf_nan=False)


class Parameters(Model):
    resolution_m: int = Field(30, ge=20, le=40)
    window_pixels: int = Field(51, ge=15, le=151)
    threshold_k: float = Field(1.0, ge=0.5, le=4)
    min_area_km2: float = Field(0.025, ge=0.005, le=5)
    dark_min_db: float = Field(-35, ge=-50, le=-20)
    dark_max_db: float = Field(-17, ge=-25, le=-10)
    coastal_buffer_m: int = Field(1500, ge=1000, le=2000)
    wind_min_ms: float = Field(2, ge=0, le=8)
    wind_max_ms: float = Field(10, ge=8, le=20)
    memory_mb: int = Field(384, ge=64, le=512)

    @model_validator(mode="after")
    def ordered(self):
        if self.window_pixels % 2 != 1:
            raise ValueError("window_pixels must be odd")
        if self.dark_min_db >= self.dark_max_db or self.wind_min_ms >= self.wind_max_ms:
            raise ValueError("Parameter bounds must be increasing")
        return self


class AnalyzeRequest(Model):
    aoi: tuple[float, float, float, float]
    start: datetime | None = None
    end: datetime | None = None
    scene_id: str | None = Field(None, max_length=200, pattern=r"^[\w.:-]+$")
    demo: bool = False
    parameters: Parameters = Field(default_factory=Parameters)

    @field_validator("aoi")
    @classmethod
    def valid_aoi(cls, v):
        return validate_bbox(v)

    @field_validator("start", "end")
    @classmethod
    def valid_time(cls, v):
        return utc(v) if v else v

    @model_validator(mode="after")
    def dates(self):
        if self.demo:
            return self
        if not self.scene_id and (not self.start or not self.end):
            raise ValueError("Provide scene_id or both start and end")
        if (self.start is None) != (self.end is None):
            raise ValueError("Provide both start and end")
        if self.start and self.end:
            if self.start < datetime(2014, 1, 1, tzinfo=UTC):
                raise ValueError("Acquisition dates must be after 2014-01-01")
            if self.end > utcnow() + timedelta(minutes=5):
                raise ValueError("Future acquisition dates are not allowed")
            if not timedelta(0) < self.end - self.start <= timedelta(days=31):
                raise ValueError("Search interval must be positive and at most 31 days")
        return self


class Geometry(Model):
    type: Literal["Point", "LineString", "Polygon", "MultiPolygon"]
    coordinates: Any

    @model_validator(mode="after")
    def valid_geometry(self):
        geom = shape(self.model_dump())
        if geom.is_empty or not geom.is_valid:
            raise ValueError("Invalid or empty GeoJSON geometry")
        w, s, e, n = geom.bounds
        if not (-180 <= w <= e <= 180 and -90 <= s <= n <= 90):
            raise ValueError("Output must be EPSG:4326 longitude/latitude")
        return self


class Breakdown(Model):
    contrast: float = Field(ge=0, le=35)
    shape: float = Field(ge=0, le=15)
    size: float = Field(ge=0, le=15)
    wind: float = Field(ge=0, le=25)
    offshore: float = Field(ge=0, le=10)


class CandidateProperties(Model):
    id: str
    label: Literal["candidate"] = "candidate"
    data_label: Literal["SYNTHETIC", "OBSERVATION"]
    acquisition_time: datetime
    area_km2: float = Field(gt=0)
    perimeter_km: float = Field(gt=0)
    compactness: float = Field(ge=0, le=1)
    elongation: float = Field(ge=1)
    contrast_db: float
    contrast_std_db: float = Field(ge=0)
    mean_db: float
    distance_to_coast_km: float | None = Field(None, ge=0)
    nearest_port: str
    distance_to_port_km: float = Field(ge=0)
    nearest_vessel: str | None = None
    vessel_distance_km: float | None = Field(None, ge=0)
    score: float = Field(ge=0, le=100)
    band: Literal["Low", "Medium", "High"]
    breakdown: Breakdown
    flags: list[str]
    _utc_time = field_validator("acquisition_time")(utc)


class Candidate(Model):
    type: Literal["Feature"] = "Feature"
    geometry: Geometry
    properties: CandidateProperties


class Candidates(Model):
    type: Literal["FeatureCollection"] = "FeatureCollection"
    features: list[Candidate] = Field(max_length=500)


class DriftForecast(Model):
    candidate_id: str
    track: Geometry
    envelopes: dict[str, Geometry]
    step_minutes: Literal[15] = 15
    flags: list[str]


class Conditions(Model):
    time: datetime
    longitude: float
    latitude: float
    wind_u_ms: float | None
    wind_v_ms: float | None
    current_u_ms: float | None
    current_v_ms: float | None
    flags: list[str] = Field(default_factory=list)
    data_label: Literal["SYNTHETIC", "MODEL"] = "MODEL"
    _utc_time = field_validator("time")(utc)


class QA(Model):
    valid_pixel_percent: float = Field(ge=0, le=100)
    aoi_coverage_percent: float = Field(ge=0, le=100)
    sea_pixel_percent: float = Field(ge=0, le=100)
    wind_available: bool
    data_age_hours: float = Field(ge=0)
    processing_seconds: float = Field(ge=0)
    software_version: str
    working_resolution_m: int
    flags: list[str]


class Result(Model):
    id: str
    scene_id: str
    collection: str
    zone: str | None = None
    acquisition_time: datetime
    processed_at: datetime
    data_label: Literal["SYNTHETIC", "OBSERVATION"]
    aoi: tuple[float, float, float, float]
    parameters: Parameters
    candidates: Candidates
    drift: list[DriftForecast]
    conditions: Conditions
    qa: QA
    total_area_km2: float = Field(ge=0)
    preview_bounds: tuple[float, float, float, float]
    preview_url: str | None
    notice: str = "Candidate detection, not confirmed spill. Educational and research use only; not for operational, legal or emergency decisions."
    _utc_times = field_validator("acquisition_time", "processed_at")(utc)

    @field_validator("aoi")
    @classmethod
    def valid_aoi(cls, v):
        return validate_bbox(v)


class Scene(Model):
    id: str
    collection: str
    acquisition_time: datetime
    footprint: Geometry
    flags: list[str]
    _utc_time = field_validator("acquisition_time")(utc)


class SceneList(Model):
    scenes: list[Scene]
    coverage: dict[str, Any]


class Job(Model):
    data_label: Literal["SYNTHETIC", "OBSERVATION"] | None = None
    id: str
    status: Literal["queued", "running", "completed", "failed", "cancelled"]
    stage: str
    progress: int = Field(ge=0, le=100)
    result_id: str | None = None
    error: str | None = None
    cached: bool = False


class ArchiveEntry(Model):
    id: str
    zone: str
    scene_id: str
    acquisition_time: datetime
    data_label: Literal["SYNTHETIC", "OBSERVATION"]
    count: int = Field(ge=0)
    total_area_km2: float = Field(ge=0)
    path: str
    qa: QA | None = None
    _utc_time = field_validator("acquisition_time")(utc)


class ArchiveIndex(Model):
    version: Literal[1] = 1
    entries: list[ArchiveEntry]


class ArchiveGeoJSON(Model):
    type: Literal["FeatureCollection"] = "FeatureCollection"
    data_label: Literal["SYNTHETIC", "OBSERVATION"]
    features: list[Candidate] = Field(max_length=500)


class HistoryResponse(Model):
    type: Literal["FeatureCollection"] = "FeatureCollection"
    data_label: Literal["SYNTHETIC", "OBSERVATION"]
    entries: list[ArchiveEntry]


class HealthResponse(Model):
    status: Literal["ok"]
    version: str


class LiveConditionsResponse(Model):
    data_label: Literal["MODEL"] = "MODEL"
    updated_at: datetime
    points: list[Conditions]
    refresh_minutes: Literal[10] = 10
    _utc_time = field_validator("updated_at")(utc)
