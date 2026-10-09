"""HTTP surface for admin API tokens (JWT admin auth, like other admin routes)."""
import uuid
import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from database import SessionLocal
from models import User, ApiToken
from auth import create_access_token
from routes_admin import register_admin_routes


@pytest.fixture(scope="module")
def client():
    app = FastAPI()
    register_admin_routes(app)
    return TestClient(app)


def _user(is_admin):
    db = SessionLocal()
    u = User(username=f"route_tok_{uuid.uuid4().hex[:8]}", hashed_password="x", is_admin=is_admin)
    db.add(u); db.commit(); db.refresh(u); db.close()
    return u


def _cleanup(u):
    db = SessionLocal()
    db.query(ApiToken).filter(ApiToken.user_id == u.id).delete()
    db.query(User).filter(User.id == u.id).delete()
    db.commit(); db.close()


def _auth(u):
    return {"Authorization": f"Bearer {create_access_token({'sub': str(u.id)})}"}


def test_create_list_revoke(client):
    u = _user(True)
    try:
        r = client.post("/api/admin/api-tokens", json={"name": "laptop"}, headers=_auth(u))
        assert r.status_code == 200, r.text
        body = r.json()
        assert body["token"].startswith("awe_") and body["name"] == "laptop"
        listed = client.get("/api/admin/api-tokens", headers=_auth(u)).json()["tokens"]
        assert [t["name"] for t in listed] == ["laptop"] and "token" not in listed[0]
        assert client.delete(f"/api/admin/api-tokens/{body['id']}", headers=_auth(u)).status_code == 200
        assert client.get("/api/admin/api-tokens", headers=_auth(u)).json()["tokens"][0]["revoked"] is True
        assert client.delete("/api/admin/api-tokens/999999999", headers=_auth(u)).status_code == 404
    finally:
        _cleanup(u)


def test_non_admin_forbidden(client):
    u = _user(False)
    try:
        r = client.post("/api/admin/api-tokens", json={"name": "x"}, headers=_auth(u))
        assert r.status_code == 403
    finally:
        _cleanup(u)


def test_empty_name_rejected(client):
    u = _user(True)
    try:
        r = client.post("/api/admin/api-tokens", json={"name": "  "}, headers=_auth(u))
        assert r.status_code == 400
    finally:
        _cleanup(u)


def test_definition_reset_records_default_as_mod_base(mod_state, client):
    from game_definition import load_mod_base, clear_mod_base, build_default_definition
    clear_mod_base()
    u = _user(True)
    try:
        r = client.post("/api/admin/game-definition/reset", headers=_auth(u))
        assert r.status_code == 200, r.text
        assert load_mod_base() == build_default_definition()
    finally:
        from models import EventLog
        db = SessionLocal(); db.query(EventLog).filter(EventLog.user_id == u.id).delete(); db.commit(); db.close()
        _cleanup(u)
