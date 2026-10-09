"""definition_service is the one path both admin routes and MCP use to change rules."""
import uuid
import pytest

from database import SessionLocal
from auth import init_default_configs
from models import User
from game_definition import (build_default_definition, set_game_definition,
                             get_game_definition, clear_persisted_definition, clear_mod_base)
import definition_service as ds


@pytest.fixture
def db():
    s = SessionLocal(); init_default_configs(s)
    yield s
    clear_persisted_definition(s)
    clear_mod_base()
    set_game_definition(build_default_definition())
    s.close()


@pytest.fixture
def admin(db):
    u = User(username=f"ds_admin_{uuid.uuid4().hex[:8]}", hashed_password="x", is_admin=True)
    db.add(u); db.commit()
    yield u
    db.delete(u); db.commit()


def _named(name):
    d = build_default_definition()
    d["meta"] = {**d["meta"], "name": name}
    return d


def test_check_valid_definition(db):
    r = ds.check_definition(_named("Svc OK"), db)
    assert r["ok"] is True and r["errors"] == [] and r["definition"]["meta"]["name"] == "Svc OK"


def test_check_reports_validation_errors(db):
    d = _named("Svc Bad"); d["engine"]["resource_model"] = "banana"
    r = ds.check_definition(d, db)
    assert r["ok"] is False and any("resource_model" in e for e in r["errors"])


def test_check_rejects_extends_escaping_root(db):
    d = _named("Svc Escape"); d["extends"] = ["../../etc/passwd.json"]
    with pytest.raises(ds.DefinitionRejected) as exc:
        ds.check_definition(d, db)
    assert "Compile error" in str(exc.value)


def test_apply_sets_and_reports_roster_change(db, admin):
    d = _named("Svc Apply")
    first_ship = next(iter(d["ships"]))
    d["ships"] = {k: v for k, v in d["ships"].items() if k != first_ship}
    r = ds.apply_definition(d, db, admin, "test", actor_label="unit")
    assert r["ok"] and r["name"] == "Svc Apply" and r["roster_changed"] is True
    assert get_game_definition()["meta"]["name"] == "Svc Apply"


def test_apply_same_roster_reports_unchanged(db, admin):
    set_game_definition(build_default_definition())  # don't depend on test order
    r = ds.apply_definition(_named("Svc Same"), db, admin, "test")
    assert r["roster_changed"] is False


def test_apply_blocked_change_stays_blocked(db, admin, monkeypatch):
    monkeypatch.setattr(ds, "has_universe", lambda _db: True)
    d = _named("Svc Blocked")
    cur = get_game_definition()["engine"]["resource_model"]
    d["engine"]["resource_model"] = "multi" if cur == "single" else "single"
    with pytest.raises(ds.DefinitionRejected) as exc:
        ds.apply_definition(d, db, admin, "test")
    assert exc.value.blocked
    assert get_game_definition()["meta"]["name"] != "Svc Blocked"


def test_apply_invalid_raises_with_errors(db, admin):
    d = _named("Svc Invalid"); del d["ships"]
    with pytest.raises(ds.DefinitionRejected) as exc:
        ds.apply_definition(d, db, admin, "test")
    assert any("ships" in e for e in exc.value.errors)


def test_building_blocks_lists_fragments():
    bb = ds.list_building_blocks()
    assert any(f["filename"].startswith("fragments") for f in bb["fragments"])
    assert any(d["filename"] == "deep_frontier.json" for d in bb["definitions"])


def test_list_mods_shape(db):
    m = ds.list_mods(db)
    assert {"mods", "active_ruleset", "enabled"} <= set(m)
    assert any(x["id"] == "conquest" for x in m["mods"])


def test_unknown_mod_rejected(db):
    with pytest.raises(ds.DefinitionRejected):
        ds.set_mod_enabled_and_apply(db, "no_such_mod", True)


# ---------------------------------------------------------------- mods compose onto a recorded base

def _clean_mod_slate(db):
    import mod_loader as ml
    from auth import set_config
    set_config(db, "enabled_mods", "")
    ml.set_active_ruleset(db, "")
    db.commit()


def test_apply_definition_records_mod_base(mod_state, db, admin):
    from game_definition import load_mod_base
    ds.apply_definition(_named("Svc Base"), db, admin, "test")
    assert load_mod_base()["meta"]["name"] == "Svc Base"


def test_disabling_mod_removes_its_rules(mod_state, db):
    from game_definition import persist_mod_base
    _clean_mod_slate(db)
    base = _named("Svc Mod Base")
    persist_mod_base(base)
    base_val = base["engine"].get("occupation_capture")
    assert base_val is not True  # conquest's overlay turns it on

    r = ds.set_mod_enabled_and_apply(db, "conquest", True)
    assert r["success"], r
    live = get_game_definition()
    assert live["engine"]["occupation_capture"] is True
    assert "conquest" in live["meta"]["active_mods"]

    r = ds.set_mod_enabled_and_apply(db, "conquest", False)
    assert r["success"], r
    live = get_game_definition()
    assert live["engine"].get("occupation_capture") == base_val
    assert "conquest" not in (live["meta"].get("active_mods") or [])
    assert live["meta"]["name"] == "Svc Mod Base"


def test_disable_without_mod_base_is_refused(mod_state, db):
    import mod_loader as ml
    from game_definition import clear_mod_base
    _clean_mod_slate(db)
    clear_mod_base()
    composed = _named("Svc Composed"); composed["meta"]["active_mods"] = ["conquest"]
    set_game_definition(composed)
    ml.set_mod_enabled(db, "conquest", True); db.commit()
    with pytest.raises(ds.DefinitionRejected, match="re-activate the base ruleset"):
        ds.set_mod_enabled_and_apply(db, "conquest", False)
    assert "conquest" in ml.get_enabled_mod_ids(db)


def test_composition_error_restores_enabled_flag(mod_state, db, monkeypatch):
    import mod_loader as ml
    from game_definition import persist_mod_base
    _clean_mod_slate(db)
    persist_mod_base(_named("Svc Err Base"))
    monkeypatch.setattr(ml, "apply_active_mods", lambda _db, _base: {"errors": ["boom"]})
    r = ds.set_mod_enabled_and_apply(db, "conquest", True)
    assert r["success"] is False
    assert "conquest" not in ml.get_enabled_mod_ids(db)


# ---------------------------------------------------------------- strict (AI assistant) mod toggles

def test_strict_refuses_non_content_mod(mod_state, db):
    import mod_loader as ml
    _clean_mod_slate(db)
    mod_id = next(m["id"] for m in ml.discover_mods() if m["manifest"].get("kind") != "content")
    with pytest.raises(ds.DefinitionRejected, match="Only content mods"):
        ds.set_mod_enabled_and_apply(db, mod_id, True, strict=True)
    assert mod_id not in ml.get_enabled_mod_ids(db)


def test_strict_blocks_setup_only_change_on_running_universe(mod_state, db, monkeypatch):
    import mod_loader as ml
    from game_definition import persist_mod_base
    _clean_mod_slate(db)
    base = _named("Svc Strict Base")
    persist_mod_base(base); set_game_definition(base)
    flipped = "multi" if base["engine"]["resource_model"] == "single" else "single"
    real_load = ml.load_mod_definition
    monkeypatch.setattr(ml, "load_mod_definition", lambda mod: (
        {"engine": {"resource_model": flipped}} if mod["id"] == "hardcore_rules" else real_load(mod)))
    monkeypatch.setattr(ds, "has_universe", lambda _db: True)
    with pytest.raises(ds.DefinitionRejected) as exc:
        ds.set_mod_enabled_and_apply(db, "hardcore_rules", True, strict=True)
    assert exc.value.blocked and "resource_model" in exc.value.blocked[0]
    assert "hardcore_rules" not in ml.get_enabled_mod_ids(db)
    assert get_game_definition()["meta"]["name"] == "Svc Strict Base"
    assert get_game_definition()["engine"]["resource_model"] == base["engine"]["resource_model"]


def test_strict_applies_safe_content_mod(mod_state, db):
    import mod_loader as ml
    from game_definition import persist_mod_base
    _clean_mod_slate(db)
    persist_mod_base(_named("Svc Strict OK"))
    r = ds.set_mod_enabled_and_apply(db, "conquest", True, strict=True)
    assert r["success"] and "conquest" in r["enabled"]
    assert get_game_definition()["engine"]["occupation_capture"] is True
    assert "conquest" in ml.get_enabled_mod_ids(db)


def test_env_definition_becomes_mod_base(mod_state, tmp_path):
    """A ruleset loaded from AWE_GAME_DEFINITION must replace any older recorded
    mod base - otherwise the next mod toggle composes onto a stale ruleset."""
    import json
    from game_definition import persist_mod_base, load_mod_base, activate_env_definition
    persist_mod_base(_named("Stale Base"))
    path = tmp_path / "env_rules.json"
    path.write_text(json.dumps(_named("Env Rules")), encoding="utf-8")
    activate_env_definition(str(path))
    assert get_game_definition()["meta"]["name"] == "Env Rules"
    assert load_mod_base()["meta"]["name"] == "Env Rules"
