import pytest
from cloudpilot.db.database import Database


def test_liveness_does_not_depend_on_database(client):
    response = client.get("/api/v1/health/live")
    assert response.status_code == 200
    assert response.json() == {"status": "alive"}
    assert response.headers["X-Request-ID"]


@pytest.mark.parametrize("available,status", [(True, 200), (False, 503)])
def test_readiness_checks_database(client, monkeypatch, available, status):
    monkeypatch.setattr(Database, "reachable", lambda self: available)
    response = client.get("/api/v1/health/ready")
    assert response.status_code == status
    assert response.json()["status"] == ("ready" if available else "not_ready")
    assert response.json()["components"]["postgresql"]["status"] == (
        "available" if available else "unavailable"
    )


def test_unreachable_database_does_not_leak_details(client, settings):
    response = client.get("/api/v1/health/ready")
    assert response.status_code == 503
    assert settings.database_url.get_secret_value() not in response.text
    assert "tester" not in response.text


def test_info_returns_actual_component_state(client, monkeypatch):
    monkeypatch.setattr(Database, "reachable", lambda self: True)
    response = client.get("/api/v1/system/info")
    data = response.json()
    assert response.status_code == 200
    assert data["name"] == "CloudPilot AI"
    assert data["version"] == "0.1.0"
    assert data["environment"] == "testing"
    assert data["components"]["postgresql"]["status"] == "available"
    assert data["components"]["ai_agent"]["status"] == "planned"
    assert "database_url" not in response.text


def test_info_is_usable_when_database_is_down(client, monkeypatch):
    monkeypatch.setattr(Database, "reachable", lambda self: False)
    response = client.get("/api/v1/system/info")
    assert response.status_code == 200
    assert response.json()["components"]["postgresql"]["status"] == "unavailable"


def test_unknown_route_uses_error_contract(client):
    response = client.get("/not-found")
    assert response.status_code == 404
    assert response.json()["error"]["message"] == "Not found"
    assert response.json()["error"]["request_id"] == response.headers["X-Request-ID"]


def test_unexpected_error_is_redacted(client, monkeypatch):
    def fail(self):
        raise RuntimeError("sensitive connection details")

    monkeypatch.setattr(Database, "reachable", fail)
    response = client.get("/api/v1/system/info")
    assert response.status_code == 500
    assert response.json()["error"]["code"] == "internal_error"
    assert "sensitive" not in response.text


def test_cors_rejects_untrusted_origin(client):
    response = client.options(
        "/api/v1/system/info",
        headers={"Origin": "https://untrusted.example", "Access-Control-Request-Method": "GET"},
    )
    assert response.status_code == 400
    assert "access-control-allow-origin" not in response.headers


def test_swagger_and_openapi(client):
    assert client.get("/docs").status_code == 200
    paths = client.get("/openapi.json").json()["paths"]
    assert "/api/v1/health/live" in paths
    assert "/api/v1/health/ready" in paths
    assert "/api/v1/system/info" in paths
