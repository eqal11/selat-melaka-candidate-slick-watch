from datetime import UTC, datetime

import numpy as np
import pytest
from pyproj import Transformer
from rasterio.features import rasterize
from rasterio.transform import from_origin
from shapely.ops import transform

from core.detection import candidate_components, lee_filter, local_dark_pixels, polygonize, to_db
from core.drift import forecast, integrate
from core.engine import _projected_preview, _webp
from core.loading import metric_grid
from core.models import AnalyzeRequest, Conditions, Parameters, validate_bbox
from core.scoring import score, wind_gate
from tests.synthetic_scene import scene


def test_db_conversion_and_nodata():
    assert np.allclose(to_db([1, 0.1, 0.01]), [0, -10, -20])
    assert np.isnan(to_db([0, -1, np.nan])).all()


def test_lee_filter_preserves_nodata():
    array = np.ones((20, 20), dtype="float32")
    array[0, :] = np.nan
    filtered = lee_filter(array)
    assert np.isnan(filtered[0]).all()
    assert np.allclose(filtered[1:], 1)


def test_polygonization_area_and_mask_alignment():
    mask = np.zeros((100, 100), dtype=bool)
    mask[10:30, 20:50] = True
    affine = from_origin(400000, 3000000, 30, 30)
    polygons = polygonize(mask, affine, tolerance_m=0)
    assert len(polygons) == 1
    assert polygons[0].area == 20 * 30 * 900
    roundtrip_mask = rasterize([(polygons[0], 1)], out_shape=mask.shape, transform=affine).astype(bool)
    mismatch = int(np.count_nonzero(mask ^ roundtrip_mask))
    assert mismatch == 0
    source = polygons[0]
    to_geo = Transformer.from_crs(32648, 4326, always_xy=True).transform
    to_metric = Transformer.from_crs(4326, 32648, always_xy=True).transform
    returned = transform(to_metric, transform(to_geo, source))
    mismatch_m = source.boundary.hausdorff_distance(returned.boundary)
    assert mismatch_m < 0.001
    assert returned.is_valid


def test_aoi_bounds_validation():
    for bbox in [(94, 1, 95, 2), (100, 2, 101, 3), (103, 1, 102, 2), (100, float("nan"), 100.1, 2)]:
        with pytest.raises(ValueError):
            validate_bbox(bbox)


def test_dates_and_unknown_option_rejected():
    with pytest.raises(ValueError):
        AnalyzeRequest(aoi=[100.8, 2.7, 101, 2.9], start="2025-01-01", end="2025-01-05")
    with pytest.raises(ValueError):
        AnalyzeRequest.model_validate({"aoi": [100.8, 2.7, 101, 2.9], "offline_mode": True})


def test_wind_gating_and_score_weights():
    speed, flags = wind_gate(1, 0, Parameters())
    assert flags == ["wind_out_of_range"]
    total, band, parts = score(8, 5, 1, 10, speed, flags)
    assert total == 39 and band == "Low" and parts.wind == 0
    total, band, parts = score(8, 5, 1, 10, 5, [])
    assert total == 100 and band == "High"
    assert sum(parts.model_dump().values()) == 100


def test_known_drift_vectors():
    assert integrate(0.3, -0.2, 6)[-1] == pytest.approx((6480, -4320))
    forcing = Conditions(
        time=datetime.now(UTC),
        longitude=101,
        latitude=3,
        wind_u_ms=10,
        wind_v_ms=0,
        current_u_ms=0,
        current_v_ms=0,
        wind_api="https://archive-api.open-meteo.com/v1/archive",
        current_api="https://marine-api.open-meteo.com/v1/marine",
    )
    result = forecast("candidate-1", 101, 3, 20, forcing)
    assert len(result.track.coordinates) == 97
    assert set(result.envelopes) == {"6", "12", "24"}
    assert result.track.coordinates[-1][0] > 101
    forcing.current_u_ms = None
    assert "current_unavailable" in forecast("candidate-1", 101, 3, 20, forcing).flags


def test_test_only_scene_fixture_and_detector():
    power, truth, _affine, _crs = scene()
    db = to_db(lee_filter(power))
    # Lower sigma is an isolated unit-test setting; production defaults are 3.5 sigma.
    parameters = Parameters(threshold_k=2.5, dark_min_db=-40)
    detected = local_dark_pixels(db, parameters)
    assert detected.shape == truth.shape
    assert int(detected.sum()) > 0


def test_real_sar_preview_georeferencing_and_fixed_stretch():
    bounds = (100.8, 2.65, 101.3, 3.15)
    crs, affine, width, height = metric_grid(bounds, 30)
    array = np.linspace(-25, 0, width * height, dtype=np.float32).reshape(height, width)
    preview, sampled = _webp(array, affine, crs, bounds, stretch="fixed")
    assert preview[:4] == b"RIFF"  # WebP container
    assert len(preview) < 3 * 1024 * 1024
    assert sampled.shape == (600, 600)
    assert np.nanmin(sampled) >= -25.01 and np.nanmax(sampled) <= 0.01
    same_stretch, _ = _webp(array, affine, crs, bounds, stretch="fixed")
    assert same_stretch == preview
    assert np.isfinite(sampled).mean() > 0.95
    assert _projected_preview(array, affine, crs, bounds).shape == (600, 600)


def test_memory_budget():
    from core.loading import check_budget

    with pytest.raises(MemoryError):
        check_budget(4000, 4000, Parameters(memory_mb=64))


def test_area_rejected_dark_component_is_kept_as_filtered():
    db = np.full((60, 60), -15.0, dtype=np.float32)
    db[20:24, 20:24] = -25.0
    raw_dark = np.zeros_like(db, dtype=bool)
    raw_dark[20:24, 20:24] = True
    sea = np.ones_like(raw_dark)
    protected = np.zeros_like(raw_dark)
    affine = from_origin(400000, 3000000, 30, 30)
    records, funnel = candidate_components(db, raw_dark, sea, protected, True, affine, Parameters())
    assert len(records) == 1
    assert records[0]["label"] == "filtered"
    assert records[0]["reason_code"] == "area_out_of_range"
    assert funnel["final_candidates"] == 0
    assert funnel["filtered_area"] == 1


def test_case_validation_aoi_scope_bypasses_study_box_but_keeps_size_cap():
    gulf_bbox = (-88.7428, 28.6022, -88.2428, 29.1022)
    with pytest.raises(ValueError, match="within lon 95-104.5"):
        validate_bbox(gulf_bbox)
    assert validate_bbox(gulf_bbox, study_area=False) == gulf_bbox
    oversized = (-89.0, 28.0, -88.0, 29.0)
    with pytest.raises(ValueError, match="60 x 60 km"):
        validate_bbox(oversized, study_area=False)
