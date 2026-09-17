import pytest
from fastapi.testclient import TestClient

from app import app


@pytest.fixture
def client():
    return TestClient(app)


def test_wrong_password_rejected_no_cookie(client):
    r = client.post("/api/login", json={"password": "nope"})
    assert r.status_code == 401
    assert "pta_session" not in r.cookies


def test_protected_route_requires_session(client):
    r = client.get("/api/patients")
    assert r.status_code == 401


def test_correct_password_grants_access(client):
    r = client.post("/api/login", json={"password": "test-admin-password"})
    assert r.status_code == 200
    assert "pta_session" in r.cookies

    r2 = client.get("/api/patients")
    assert r2.status_code == 200


def test_logout_revokes_session(client):
    client.post("/api/login", json={"password": "test-admin-password"})
    assert client.get("/api/patients").status_code == 200

    client.post("/api/logout")
    r = client.get("/api/patients")
    assert r.status_code == 401


def test_health_stays_public(client):
    # the unauthenticated login screen needs to read manus/offline status
    r = client.get("/api/health")
    assert r.status_code == 200
    assert r.json()["auth_enabled"] is True
