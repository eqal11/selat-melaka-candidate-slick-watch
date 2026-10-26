from datetime import UTC, datetime

import numpy as np
import pytest
from pydantic import ValidationError
from rasterio.transform import from_origin

from core.detection import dark_mask, lee_filter, polygonize, to_db
from core.drift import forecast, integrate
from core.models import AnalyzeRequest, Conditions, Parameters, validate_bbox
from core.scoring import score, wind_gate
from core.synthetic import scene


def test_db():
    assert np.allclose(to_db([1, 0.1, 0.01])[:3], [0, -10, -20])
    assert np.isnan(to_db([0, -1, np.nan])).all()


def test_lee_nodata():
    a = np.ones((20, 20), dtype="float32")
    a[0, :] = np.nan
    out = lee_filter(a)
    assert np.isnan(out[0]).all()
    assert np.allclose(out[1:], 1)


def test_area_and_polygonization():
    mask = np.zeros((100, 100), bool)
    mask[10:30, 20:50] = True
    polygons = polygonize(mask, from_origin(0, 3000, 30, 30), tolerance_m=0)
    assert len(polygons) == 1
    assert polygons[0].area == 20 * 30 * 900
    assert polygons[0].is_valid


@pytest.mark.parametrize(
    "bbox", [(94, 1, 95, 2), (100, 2, 101, 3), (103, 1, 102, 2), (100, float("nan"), 100.1, 2)]
)
def test_invalid_aoi(bbox):
    with pytest.raises(ValueError):
        validate_bbox(bbox)


def test_dates():
    with pytest.raises(ValidationError):
        AnalyzeRequest(aoi=[100.8, 2.7, 101, 2.9], start="2025-01-01", end="2025-01-05")


def test_wind_flags_and_score_cap():
    speed, flags = wind_gate(1, 0, Parameters())
    assert flags == ["wind_out_of_range"]
    total, band, parts = score(8, 5, 1, 10, speed, flags)
    assert total == 39 and band == "Low" and parts.wind == 0
    assert wind_gate(None, None, Parameters())[1] == ["wind_unavailable"]


def test_score_weights():
    total, band, parts = score(8, 5, 1, 10, 5, [])
    assert total == 100 and band == "High"
    assert sum(parts.model_dump().values()) == 100


def test_drift_known_vector():
    assert integrate(0.3, -0.2, 6)[-1] == pytest.approx((6480, -4320))
    c = Conditions(
        time=datetime.now(UTC),
        longitude=101,
        latitude=3,
        wind_u_ms=10,
        wind_v_ms=0,
        current_u_ms=0,
        current_v_ms=0,
    )
    f = forecast("x", 101, 3, 20, c)
    assert len(f.track.coordinates) == 97 and set(f.envelopes) == {"6", "12", "24"}
    assert f.track.coordinates[-1][0] > 101
    c.current_u_ms = None
    assert "current_unavailable" in forecast("x", 101, 3, 20, c).flags


def test_synthetic_recall_area():
    power, truth, affine, _ = scene()
    db = to_db(lee_filter(power))
    found = dark_mask(db, np.ones_like(truth), Parameters())
    recall = (found & truth).sum() / truth.sum()
    error = abs(found.sum() - truth.sum()) / truth.sum()
    print(f"SYNTHETIC recall={recall:.6f} area_error={error:.6f}")
    assert recall >= 0.8
    assert error <= 0.25
    assert not found[90:95, 300:305].any()


def test_memory_budget():
    from core.loading import check_budget

    with pytest.raises(MemoryError):
        check_budget(4000, 4000, Parameters(memory_mb=64))
