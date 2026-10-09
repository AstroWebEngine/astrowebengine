# test_mcp_server.py
"""MCP endpoint: auth, and the creator loop check -> save -> activate -> read back."""
import json
import os
import uuid
import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from database import SessionLocal
from auth import init_default_configs
from models import User, ApiToken
from game_definition import (build_default_definition, set_game_definition,
                             get_game_definition, clear_persisted_definition, clear_mod_base)
import api_tokens
import definition_service as ds
import mcp_server

H = {"Accept": "application/json, text/event-stream", "Content-Type": "application/json"}


@pytest.fixture(scope="module")
def client():
    app = FastAPI()
    mcp_server.mount_mcp(app)
    with TestClient(app) as c:  # runs startup -> MCP session manager
        yield c


@pytest.fixture
def admin_token():
    db = SessionLocal(); init_default_configs(db)
    u = User(username=f"mcp_admin_{uuid.uuid4().hex[:8]}", hashed_password="x", is_admin=True)
    db.add(u); db.commit()
    row, raw = api_tokens.create_token(db, u, "test-claude")
    yield raw, row.id, u.id
    db.query(ApiToken).filter(ApiToken.user_id == u.id).delete()
    db.query(User).filter(User.id == u.id).delete()
    db.commit()
    clear_persisted_definition(db)
    clear_mod_base()
    set_game_definition(build_default_definition())
    db.close()


@pytest.fixture
def cleanup_files():
    made = []
    yield made
    for name in made:
        p = os.path.join(ds.DEFINITIONS_DIR, f"{name}.json")
        if os.path.exists(p):
            os.remove(p)


def call(client, raw, tool, args=None):
    r = client.post("/mcp", headers={**H, "Authorization": f"Bearer {raw}"},
                    json={"jsonrpc": "2.0", "id": 1, "method": "tools/call",
                          "params": {"name": tool, "arguments": args or {}}})
    assert r.status_code == 200, r.text
    res = r.json()["result"]
    text = res["content"][0]["text"] if res["content"] else ""
    return res["isError"], (json.loads(text) if not res["isError"] else text)


def _named(name):
    d = build_default_definition()
    d["meta"] = {**d["meta"], "name": name}
    return d


def test_no_token_is_401(client):
    r = client.post("/mcp", headers=H, json={"jsonrpc": "2.0", "id": 1, "method": "tools/list"})
    assert r.status_code == 401


def test_revoked_token_is_401(client, admin_token):
    raw, tid, uid = admin_token
    db = SessionLocal(); api_tokens.revoke_token(db, db.get(User, uid), tid); db.close()
    r = client.post("/mcp", headers={**H, "Authorization": f"Bearer {raw}"},
                    json={"jsonrpc": "2.0", "id": 1, "method": "tools/list"})
    assert r.status_code == 401


def test_tool_list_has_no_universe_tools(client, admin_token):
    raw = admin_token[0]
    r = client.post("/mcp", headers={**H, "Authorization": f"Bearer {raw}"},
                    json={"jsonrpc": "2.0", "id": 1, "method": "tools/list"})
    names = {t["name"] for t in r.json()["result"]["tools"]}
    assert names == {"get_engine_guide", "get_schema", "list_building_blocks", "get_active_definition",
                     "check_definition", "save_definition", "activate_definition", "list_mods", "apply_mod"}


def test_get_schema_every_section(client, admin_token):
    import schema_doc
    for s in schema_doc.SECTIONS:
        err, out = call(client, admin_token[0], "get_schema", {"section": s})
        assert not err and out["section"] == s and out["text"].startswith(f"## {s}")
    err, out = call(client, admin_token[0], "get_schema", {"section": "nope"})
    assert err and "ships" in out


def test_full_creator_loop(client, admin_token, cleanup_files):
    raw = admin_token[0]
    name = f"ai_test_{uuid.uuid4().hex[:6]}"; cleanup_files.append(name)
    d = _named("AI Loop Game")
    err, chk = call(client, raw, "check_definition", {"definition": d})
    assert not err and chk["ok"] and "definition" not in chk
    err, saved = call(client, raw, "save_definition", {"filename": name, "definition": d})
    assert not err and saved["path"].endswith(f"{name}.json")
    err, act = call(client, raw, "activate_definition", {"filename": name})
    assert not err and act["ok"] and act["name"] == "AI Loop Game"
    err, meta = call(client, raw, "get_active_definition", {"section": "meta"})
    assert not err and meta["meta"]["name"] == "AI Loop Game"


def test_check_rejects_escaping_extends(client, admin_token):
    d = _named("Escape"); d["extends"] = ["../../etc/passwd.json"]
    err, out = call(client, admin_token[0], "check_definition", {"definition": d})
    assert not err and out["ok"] is False and any("escapes definition root" in e for e in out["errors"])


def test_save_refuses_path_tricks(client, admin_token):
    d = _named("Nope")
    for bad in ("../evil", "a/b", "UPPER", ""):
        err, out = call(client, admin_token[0], "save_definition", {"filename": bad, "definition": d})
        assert err, bad


def test_save_cannot_touch_bundled_definition(client, admin_token, cleanup_files):
    bundled = os.path.join(ds.DEFINITIONS_DIR, "classic_space.json")
    before = open(bundled, "rb").read()
    cleanup_files.append("ai_classic_space")
    err, out = call(client, admin_token[0], "save_definition",
                    {"filename": "classic_space", "definition": _named("Shadow")})
    assert not err and out["filename"] == "ai_classic_space.json"
    assert open(bundled, "rb").read() == before


def test_saved_draft_is_ai_prefixed_and_gitignored(client, admin_token, cleanup_files):
    import subprocess
    stem = f"plain_{uuid.uuid4().hex[:6]}"; cleanup_files.append(f"ai_{stem}")
    err, out = call(client, admin_token[0], "save_definition", {"filename": stem, "definition": _named("Plain")})
    assert not err and out["filename"] == f"ai_{stem}.json"
    assert os.path.exists(os.path.join(ds.DEFINITIONS_DIR, f"ai_{stem}.json"))
    assert not os.path.exists(os.path.join(ds.DEFINITIONS_DIR, f"{stem}.json"))
    # an already-prefixed name is not doubled
    err, out = call(client, admin_token[0], "save_definition", {"filename": f"ai_{stem}", "definition": _named("Plain")})
    assert not err and out["filename"] == f"ai_{stem}.json"
    repo = os.path.dirname(os.path.abspath(__file__))
    rel = os.path.relpath(os.path.join(ds.DEFINITIONS_DIR, f"ai_{stem}.json"), repo).replace(os.sep, "/")
    assert subprocess.run(["git", "check-ignore", "-q", rel], cwd=repo).returncode == 0
    assert subprocess.run(["git", "check-ignore", "-q", "game_definitions/ai_x.json"], cwd=repo).returncode == 0


def test_activate_by_plain_name_finds_ai_draft(client, admin_token, cleanup_files):
    stem = f"plain_{uuid.uuid4().hex[:6]}"; cleanup_files.append(f"ai_{stem}")
    assert not call(client, admin_token[0], "save_definition", {"filename": stem, "definition": _named("By Plain")})[0]
    for fn in (stem, f"{stem}.json"):
        err, act = call(client, admin_token[0], "activate_definition", {"filename": fn})
        assert not err and act["name"] == "By Plain", act


def test_save_treats_non_dict_json_as_not_owned(client, admin_token, cleanup_files):
    stem = f"ai_list_{uuid.uuid4().hex[:6]}"; cleanup_files.append(stem)
    with open(os.path.join(ds.DEFINITIONS_DIR, f"{stem}.json"), "w", encoding="utf-8") as f:
        json.dump([1, 2, 3], f)
    err, out = call(client, admin_token[0], "save_definition", {"filename": stem, "definition": _named("X")})
    assert err and "not created by the AI" in out


def test_save_can_overwrite_own_draft(client, admin_token, cleanup_files):
    name = f"ai_test_{uuid.uuid4().hex[:6]}"; cleanup_files.append(name)
    assert not call(client, admin_token[0], "save_definition", {"filename": name, "definition": _named("v1")})[0]
    assert not call(client, admin_token[0], "save_definition", {"filename": name, "definition": _named("v2")})[0]


def test_save_refuses_invalid(client, admin_token):
    d = _named("Bad"); del d["ships"]
    err, out = call(client, admin_token[0], "save_definition", {"filename": "ai_bad_x", "definition": d})
    assert err and "ships" in out
    assert not os.path.exists(os.path.join(ds.DEFINITIONS_DIR, "ai_bad_x.json"))
    assert not os.path.exists(os.path.join(ds.DEFINITIONS_DIR, "ai_ai_bad_x.json"))


def test_activate_needs_exactly_one_source(client, admin_token):
    before = get_game_definition()["meta"]["name"]
    assert call(client, admin_token[0], "activate_definition", {})[0]
    assert call(client, admin_token[0], "activate_definition",
                {"filename": "deep_frontier", "definition": _named("x")})[0]
    assert get_game_definition()["meta"]["name"] == before


def test_activate_blocked_change_stays_blocked(client, admin_token, monkeypatch):
    monkeypatch.setattr(ds, "has_universe", lambda _db: True)
    d = _named("Blocked")
    cur = get_game_definition()["engine"]["resource_model"]
    d["engine"]["resource_model"] = "multi" if cur == "single" else "single"
    err, out = call(client, admin_token[0], "activate_definition", {"definition": d})
    assert err and "blocked" in out.lower()
    assert get_game_definition()["meta"]["name"] != "Blocked"


def test_roster_change_mentions_launch(client, admin_token):
    d = _named("Roster")
    d["ships"] = dict(list(d["ships"].items())[1:])
    err, out = call(client, admin_token[0], "activate_definition", {"definition": d})
    assert not err and out["roster_changed"] and "Launch" in out["next_step"]


def _event_rows(user_id, event_type):
    from models import EventLog
    db = SessionLocal()
    try:
        return [e.message for e in db.query(EventLog).filter(
            EventLog.user_id == user_id, EventLog.event_type == event_type).all()]
    finally:
        db.close()


def _purge_events(user_id):
    from models import EventLog
    db = SessionLocal()
    db.query(EventLog).filter(EventLog.user_id == user_id).delete()
    db.commit(); db.close()


def test_save_definition_logs_event(client, admin_token, cleanup_files):
    raw, _tid, uid = admin_token
    name = f"ai_log_{uuid.uuid4().hex[:6]}"; cleanup_files.append(name)
    try:
        err, _ = call(client, raw, "save_definition", {"filename": name, "definition": _named("Log")})
        assert not err
        assert any(name in m and "test-claude" in m for m in _event_rows(uid, "game_definition_draft_mcp"))
    finally:
        _purge_events(uid)


def test_apply_mod_logs_event(mod_state, client, admin_token):
    from game_definition import persist_mod_base
    raw, _tid, uid = admin_token
    err, mods = call(client, raw, "list_mods")
    assert not err and mods["mods"]
    mod_id = next(m["id"] for m in mods["mods"] if m["kind"] == "content")
    persist_mod_base(build_default_definition())
    try:
        err, _ = call(client, raw, "apply_mod", {"mod_id": mod_id, "enabled": False})
        assert not err
        assert any(mod_id in m and "test-claude" in m for m in _event_rows(uid, "mod_apply_mcp"))
    finally:
        _purge_events(uid)


def test_lowercase_bearer_scheme_accepted(client, admin_token):
    r = client.post("/mcp", headers={**H, "Authorization": f"bearer {admin_token[0]}"},
                    json={"jsonrpc": "2.0", "id": 1, "method": "tools/list"})
    assert r.status_code == 200 and r.json()["result"]["tools"]


def test_token_verified_once_per_tool_call(client, admin_token, monkeypatch):
    calls = []
    real = api_tokens.verify_token
    monkeypatch.setattr(api_tokens, "verify_token", lambda db, raw: calls.append(raw) or real(db, raw))
    err, _ = call(client, admin_token[0], "list_mods")
    assert not err and len(calls) == 1


def test_session_rechecks_admin_for_guard_actor(admin_token):
    _raw, tid, uid = admin_token
    db = SessionLocal(); db.get(User, uid).is_admin = False; db.commit(); db.close()
    with pytest.raises(ValueError, match="Unauthorized"):
        with mcp_server._session({"user_id": uid, "token_id": tid, "token_name": "t"}):
            pass


def test_apply_mod_refuses_non_content_mod(mod_state, client, admin_token):
    import mod_loader as ml
    mod_id = next(m["id"] for m in ml.discover_mods() if m["manifest"].get("kind") != "content")
    err, out = call(client, admin_token[0], "apply_mod", {"mod_id": mod_id, "enabled": True})
    assert err and "Only content mods" in out
