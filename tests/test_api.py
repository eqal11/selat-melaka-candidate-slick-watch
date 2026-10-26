from fastapi.testclient import TestClient

from api.main import app

client = TestClient(app)


def test_health_zones_and_bbox_validation():
    assert client.get("/api/v1/health").json()["status"] == "ok"
    assert len(client.get("/api/v1/zones").json()["zones"]) == 3
    response = client.get("/api/v1/live/conditions", params={"bbox": "94,1,95,2"})
    assert response.status_code == 422


def test_analysis_requires_real_scene_or_valid_date_range():
    response = client.post("/api/v1/analyze", json={"aoi": [100.8, 2.65, 101.3, 3.15], "demo": True})
    assert response.status_code == 422
    assert "demo" in response.text


def test_history_contract_contains_only_real_archive():
    response = client.get("/api/v1/history", params={"zone": "central"})
    assert response.status_code == 200
    body = response.json()
    assert body["data_label"] == "REAL Sentinel-1"
    assert all(entry["data_label"] == "REAL Sentinel-1" for entry in body["entries"])


def test_validation_case_register_has_sources_and_no_invented_results():
    response = client.get("/api/v1/validation/cases")
    assert response.status_code == 200
    body = response.json()
    assert len(body["cases"]) >= 8
    incidents = [case for case in body["cases"] if case["category"] == "documented_spill"]
    seeps = [case for case in body["cases"] if case["category"] == "natural_seep"]
    assert len(incidents) >= 4 and len(seeps) >= 3
    assert all(len(case["sources"]) >= 2 for case in body["cases"])
    assert all(case["detector_result"] is None for case in body["cases"])
    assert all(case["scene_search"]["scene_id"] is None for case in body["cases"])
    import json
    from pathlib import Path

    static_register = json.loads(Path("web/public/validation-cases.json").read_text(encoding="utf-8"))
    assert static_register == body
