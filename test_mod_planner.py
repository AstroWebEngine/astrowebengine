"""One planner for changing the mod selection: preview first, then apply exactly
that preview or nothing.

Before this, the admin panel saved the selection (enable / ruleset) and applied
it in a second request, so a failed apply left the saved selection describing a
game the server wasn't running. plan() changes nothing; apply() recomputes the
plan, refuses if anything moved since the preview, and only then saves the
selection and activates the result together.
"""
import json
import os
from tempfile import TemporaryDirectory

import pytest

import mod_loader as ml
import mod_planner as mp
from database import SessionLocal
from auth import init_default_configs
from game_definition import get_game_definition, set_game_definition, load_definition_from_file


@pytest.fixture
def db(mod_state):
    s = SessionLocal(); init_default_configs(s)
    base = load_definition_from_file("game_definitions/classic_space.json")
    set_game_definition(base)
    from game_definition import persist_mod_base
    persist_mod_base(base)
    ml.set_mod_enabled(s, "__none__", False)
    from auth import set_config
    set_config(s, "enabled_mods", ""); set_config(s, "active_ruleset_mod", "")
    yield s
    s.close()


@pytest.fixture
def mods_dir(monkeypatch):
    with TemporaryDirectory() as root:
        monkeypatch.setattr(ml, "MODS_DIR", root)
        yield root


def _mod(root, mod_id, overlay, **manifest):
    d = os.path.join(root, mod_id); os.makedirs(d)
    m = {"id": mod_id, "name": mod_id, "version": "1.0", "kind": "content",
         "definition": "definition.json", "engine_api": "1.0", **manifest}
    json.dump(m, open(os.path.join(d, "manifest.json"), "w"))
    json.dump(overlay, open(os.path.join(d, "definition.json"), "w"))


def _new_ship():
    ship = dict(next(iter(load_definition_from_file("game_definitions/classic_space.json")["ships"].values())))
    ship["name"] = "Planner Test Ship"
    return ship


def test_plan_changes_nothing(db, mods_dir):
    _mod(mods_dir, "extra_ship", {"ships": {"planner_ship": _new_ship()}})
    before = get_game_definition()
    plan = mp.plan(db, enable=["extra_ship"])
    assert plan["ok"] and plan["changes"]["ships"]["added"] == ["planner_ship"]
    assert get_game_definition() is before
    assert ml.get_enabled_mod_ids(db) == []


def test_apply_saves_selection_and_activates_together(db, mods_dir, monkeypatch):
    _mod(mods_dir, "extra_ship", {"ships": {"planner_ship": _new_ship()}})
    plan = mp.plan(db, enable=["extra_ship"])
    result = mp.apply(db, plan["plan_id"], enable=["extra_ship"])
    assert result["ok"]
    assert ml.get_enabled_mod_ids(db) == ["extra_ship"]
    assert "planner_ship" in get_game_definition()["ships"]


def test_failed_plan_saves_nothing(db, mods_dir):
    _mod(mods_dir, "needs_core", {"combat": {}}, requires=["core_pack"])
    plan = mp.plan(db, enable=["needs_core"])
    assert not plan["ok"] and any("core_pack" in e for e in plan["errors"])
    with pytest.raises(mp.PlanRejected):
        mp.apply(db, plan["plan_id"], enable=["needs_core"])
    assert ml.get_enabled_mod_ids(db) == []


def test_stale_plan_is_refused(db, mods_dir):
    _mod(mods_dir, "a_mod", {"combat": {"loot_percent": 0.2}})
    _mod(mods_dir, "b_mod", {"combat": {"loot_percent": 0.3}})
    plan = mp.plan(db, enable=["a_mod"])
    mp.apply(db, mp.plan(db, enable=["b_mod"])["plan_id"], enable=["b_mod"])   # state moves on
    with pytest.raises(mp.PlanRejected, match="changed since"):
        mp.apply(db, plan["plan_id"], enable=["a_mod"])


def test_disable_removes_the_overlay(db, mods_dir):
    _mod(mods_dir, "extra_ship", {"ships": {"planner_ship": _new_ship()}})
    mp.apply(db, mp.plan(db, enable=["extra_ship"])["plan_id"], enable=["extra_ship"])
    plan = mp.plan(db, disable=["extra_ship"])
    assert plan["changes"]["ships"]["removed"] == ["planner_ship"]
    mp.apply(db, plan["plan_id"], disable=["extra_ship"])
    assert "planner_ship" not in get_game_definition()["ships"]
    assert ml.get_enabled_mod_ids(db) == []


def test_engine_flag_changes_are_listed(db, mods_dir):
    _mod(mods_dir, "slow_combat", {"engine": {"combat_max_rounds": 9}})
    plan = mp.plan(db, enable=["slow_combat"])
    assert plan["changes"]["engine"]["combat_max_rounds"]["new"] == 9


def test_unknown_mod_is_an_error(db, mods_dir):
    plan = mp.plan(db, enable=["nope"])
    assert not plan["ok"] and any("nope" in e for e in plan["errors"])


def test_strict_refuses_non_content_and_blocked(db, mods_dir, monkeypatch):
    _mod(mods_dir, "behave", {}, kind="behavioral")
    assert not mp.plan(db, enable=["behave"], strict=True)["ok"]
    _mod(mods_dir, "go_multi", {"engine": {"resource_model": "multi"}})
    import definition_service as ds
    monkeypatch.setattr(mp, "has_universe", lambda _db: True)
    plan = mp.plan(db, enable=["go_multi"], strict=True)
    assert not plan["ok"] and plan["blocked"]
    plan_lenient = mp.plan(db, enable=["go_multi"])
    assert plan_lenient["blocked"] and plan_lenient["ok"]   # admin: warned, operator decides


def test_plan_output_is_json_safe(db, mods_dir):
    _mod(mods_dir, "extra_ship", {"ships": {"planner_ship": _new_ship()}})
    json.dumps(mp.plan(db, enable=["extra_ship"]))


def test_admin_plan_then_apply_over_http(db, mods_dir):
    import uuid
    from fastapi import FastAPI
    from fastapi.testclient import TestClient
    from auth import create_access_token
    from models import User
    from routes_admin import register_admin_routes
    _mod(mods_dir, "extra_ship", {"ships": {"planner_ship": _new_ship()}})
    app = FastAPI(); register_admin_routes(app); client = TestClient(app)
    u = User(username=f"plan_admin_{uuid.uuid4().hex[:6]}", hashed_password="x", is_admin=True)
    db.add(u); db.commit()
    try:
        h = {"Authorization": f"Bearer {create_access_token({'sub': str(u.id)})}"}
        body = {"enable": ["extra_ship"]}
        plan = client.post("/api/admin/mods/plan", json=body, headers=h).json()
        assert plan["ok"] and ml.get_enabled_mod_ids(db) == []
        stale = client.post("/api/admin/mods/apply-plan", json={**body, "plan_id": "0" * 16}, headers=h)
        assert stale.status_code == 409
        r = client.post("/api/admin/mods/apply-plan", json={**body, "plan_id": plan["plan_id"]}, headers=h)
        assert r.status_code == 200 and ml.get_enabled_mod_ids(db) == ["extra_ship"]
    finally:
        db.delete(u); db.commit()
