from fastapi.testclient import TestClient
from server.app import app


def test_healthz_reports_service_ready():
    response = TestClient(app).get("/healthz")
    assert response.status_code == 200
    assert response.json() == {"status": "ok"}
