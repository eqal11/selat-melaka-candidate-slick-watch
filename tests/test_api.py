from fastapi.testclient import TestClient

from api.main import app

client = TestClient(app)


def test_health_zones_and_bbox_validation():
    assert client.get("/api/v1/health").json()["status"] == "ok"
    assert len(client.get("/api/v1/zones").json()["zones"]) == 3
    response = client.get("/api/v1/live/conditions", params={"bbox": "94,1,95,2"})
    assert response.status_code == 422


def test_offline_demo_analysis_response_contract():
    response = client.post(
        "/api/v1/analyze",
        json={"aoi": [100.8, 2.65, 101.3, 3.15], "demo": True},
    )
    assert response.status_code == 202
    state = client.get(f"/api/v1/jobs/{response.json()['id']}").json()
    assert state["status"] == "completed"
    payload = client.get(f"/api/v1/results/{state['result_id']}").json()
    assert response.json()["data_label"] == "SYNTHETIC"
    assert payload["data_label"] == "SYNTHETIC"
    assert payload["candidates"]["features"]
    assert all(feature["properties"]["label"] == "candidate" for feature in payload["candidates"]["features"])
    assert payload["qa"]["valid_pixel_percent"] > 0
    assert {key for drift in payload["drift"] for key in drift["envelopes"]} == {"6", "12", "24"}


def test_archive_history_is_schema_valid_and_real_scene_is_labelled():
    response = client.get("/api/v1/history", params={"zone": "central"})
    assert response.status_code == 200
    body = response.json()
    assert body["data_label"] == "OBSERVATION"
    assert body["entries"]
    entry = body["entries"][0]
    assert entry["data_label"] == "OBSERVATION"
    assert entry["qa"]["flags"] == ["candidate_limit_500"]
