#!/usr/bin/env python3
"""
Tests for the AstroWebEngine mod loader (M1: content/ruleset packaging).

Run: python3 test_mod_loader.py
"""
import mod_loader as ml
from game_definition import load_definition_from_file
from database import SessionLocal
from auth import init_default_configs, set_config
import json
import os
from tempfile import TemporaryDirectory


def _base():
    return load_definition_from_file("game_definitions/classic_space.json")


def _write_mod(root, mod_id, manifest, definition=None, hooks=None):
    """Create a temporary mod directory for loader edge-case tests."""
    mod_dir = os.path.join(root, mod_id)
    os.makedirs(mod_dir, exist_ok=True)
    with open(os.path.join(mod_dir, "manifest.json"), "w", encoding="utf-8") as fh:
        if isinstance(manifest, str):
            fh.write(manifest)
        else:
            data = dict(manifest)
            data.setdefault("id", mod_id)
            json.dump(data, fh)
    if definition is not None:
        with open(os.path.join(mod_dir, "definition.json"), "w", encoding="utf-8") as fh:
            json.dump(definition, fh)
    if hooks is not None:
        hooks_dir = os.path.join(mod_dir, "hooks")
        os.makedirs(hooks_dir, exist_ok=True)
        with open(os.path.join(hooks_dir, "__init__.py"), "w", encoding="utf-8") as fh:
            fh.write(hooks)
    return mod_dir


def _compose_with_temp_mods(root, enabled=(), ruleset=""):
    old_dir = ml.MODS_DIR
    old_enabled = ml.get_enabled_mod_ids
    old_ruleset = ml.get_active_ruleset_id
    ml.MODS_DIR = root
    ml.get_enabled_mod_ids = lambda db: list(enabled)
    ml.get_active_ruleset_id = lambda db: ruleset
    try:
        return ml.compose_active_definition(None, _base())
    finally:
        ml.MODS_DIR = old_dir
        ml.get_enabled_mod_ids = old_enabled
        ml.get_active_ruleset_id = old_ruleset


def test_manifest_validation():
    assert ml.validate_manifest({"id": "x", "name": "X", "version": "1", "kind": "content", "definition": "d.json"}) == []
    errs = ml.validate_manifest({"id": "x"})
    assert any("name" in e for e in errs) and any("kind" in e for e in errs)
    assert ml.validate_manifest({"id": "x", "name": "X", "version": "1", "kind": "bogus", "definition": "d.json"})
    assert ml.validate_manifest({"id": "x", "name": "X", "version": "1", "kind": "content", "definition": "d.json", "engine_api": "2.0"})


def test_discovery_reports_bad_manifest_and_ignores_missing_manifest():
    with TemporaryDirectory() as root:
        _write_mod(root, "bad_json", "{ nope")
        os.makedirs(os.path.join(root, "no_manifest"), exist_ok=True)
        old_dir = ml.MODS_DIR
        ml.MODS_DIR = root
        try:
            found = {m["id"]: m for m in ml.discover_mods()}
        finally:
            ml.MODS_DIR = old_dir
        assert "bad_json" in found
        assert any("unreadable manifest" in e for e in found["bad_json"]["errors"])
        assert "no_manifest" not in found


def test_missing_definition_file_is_skipped_not_fatal():
    with TemporaryDirectory() as root:
        _write_mod(root, "missing_def", {
            "name": "Missing Definition", "version": "1", "kind": "content",
            "definition": "definition.json", "engine_api": "1.0",
        })
        defn, report = _compose_with_temp_mods(root, enabled=["missing_def"])
        assert report["errors"] == [], report
        assert report["applied"] == []
        assert report["skipped"] and report["skipped"][0]["id"] == "missing_def"
        assert defn["meta"]["name"] == "Classic Space"


def test_declared_conflict_skips_later_mod():
    with TemporaryDirectory() as root:
        _write_mod(root, "alpha", {
            "name": "Alpha", "version": "1", "kind": "content",
            "definition": "definition.json", "engine_api": "1.0",
            "conflicts": ["beta"], "load_order": 10,
        }, {"engine": {"construction_queue_max": 2}})
        _write_mod(root, "beta", {
            "name": "Beta", "version": "1", "kind": "content",
            "definition": "definition.json", "engine_api": "1.0",
            "load_order": 20,
        }, {"engine": {"construction_queue_max": 99}})
        defn, report = _compose_with_temp_mods(root, enabled=["alpha", "beta"])
        assert report["applied"] == ["alpha"]
        assert report["conflicts"] == ["beta"]
        assert defn["engine"]["construction_queue_max"] == 2


def test_load_order_ties_resolve_by_mod_id():
    with TemporaryDirectory() as root:
        _write_mod(root, "aaa", {
            "name": "AAA", "version": "1", "kind": "content",
            "definition": "definition.json", "engine_api": "1.0",
            "load_order": 100,
        }, {"combat": {"loot_percent": 0.11}})
        _write_mod(root, "bbb", {
            "name": "BBB", "version": "1", "kind": "content",
            "definition": "definition.json", "engine_api": "1.0",
            "load_order": 100,
        }, {"combat": {"loot_percent": 0.88}})
        defn, report = _compose_with_temp_mods(root, enabled=["bbb", "aaa"])
        assert report["applied"] == ["aaa", "bbb"]
        assert defn["combat"]["loot_percent"] == 0.88


def test_invalid_composed_definition_reports_errors_and_does_not_install():
    from game_definition import set_game_definition, get_game_definition
    with TemporaryDirectory() as root:
        _write_mod(root, "bad_ship", {
            "name": "Bad Ship", "version": "1", "kind": "content",
            "definition": "definition.json", "engine_api": "1.0",
        }, {"ships": {"broken_ship": {"name": "Broken"}}})
        old_active = get_game_definition()
        set_game_definition(_base())
        old_dir = ml.MODS_DIR
        old_enabled = ml.get_enabled_mod_ids
        old_ruleset = ml.get_active_ruleset_id
        ml.MODS_DIR = root
        ml.get_enabled_mod_ids = lambda db: ["bad_ship"]
        ml.get_active_ruleset_id = lambda db: ""
        try:
            report = ml.apply_active_mods(None, _base())
            assert report["errors"], report
            assert any("ships.broken_ship missing required field" in e for e in report["errors"])
            assert "broken_ship" not in get_game_definition()["ships"]
        finally:
            ml.MODS_DIR = old_dir
            ml.get_enabled_mod_ids = old_enabled
            ml.get_active_ruleset_id = old_ruleset
            set_game_definition(old_active)


def test_api_compatibility():
    assert ml._api_compatible("1.0") and ml._api_compatible("^1.2") and ml._api_compatible("")
    assert not ml._api_compatible("2.0")


def test_discovery_finds_sample_mods():
    ids = {m["id"]: m for m in ml.discover_mods()}
    assert "solar_empire" in ids and ids["solar_empire"]["manifest"]["kind"] == "ruleset"
    assert "hardcore_rules" in ids and ids["hardcore_rules"]["manifest"]["kind"] == "content"
    for m in ids.values():
        assert not m["errors"], f"{m['id']} manifest invalid: {m['errors']}"


def test_compose_ruleset_plus_overlay():
    db = SessionLocal(); init_default_configs(db)
    set_config(db, "active_ruleset_mod", "solar_empire")
    set_config(db, "enabled_mods", "hardcore_rules")
    defn, report = ml.compose_active_definition(db, _base())
    assert report["errors"] == [], report["errors"]
    assert report["ruleset"] == "solar_empire"
    assert report["applied"] == ["hardcore_rules"]
    # ruleset content present
    assert "stealth_trader" in defn["ships"]
    # overlay applied (child wins)
    assert defn["engine"]["defense_repair_percent"] == 0.0
    assert defn["combat"]["loot_percent"] == 0.35
    assert defn["engine"]["construction_queue_max"] == 3
    # base display identity preserved, mods recorded
    assert defn["meta"]["name"] == "Solar Empire"
    assert defn["meta"]["active_mods"] == ["hardcore_rules"]
    set_config(db, "active_ruleset_mod", ""); set_config(db, "enabled_mods", ""); db.close()


def test_overlay_only_onto_fallback_validates():
    db = SessionLocal(); init_default_configs(db)
    set_config(db, "active_ruleset_mod", "")
    set_config(db, "enabled_mods", "hardcore_rules")
    defn, report = ml.compose_active_definition(db, _base())
    assert report["errors"] == [], report["errors"]
    assert report["ruleset"] is None
    assert defn["combat"]["loot_percent"] == 0.35
    assert defn["meta"]["name"] == "Classic Space"  # fallback base name preserved
    set_config(db, "enabled_mods", ""); db.close()


def test_disabled_mod_not_applied():
    db = SessionLocal(); init_default_configs(db)
    set_config(db, "active_ruleset_mod", ""); set_config(db, "enabled_mods", "")
    defn, report = ml.compose_active_definition(db, _base())
    assert report["applied"] == []
    assert defn["combat"]["loot_percent"] == 0.2  # classic default, overlay NOT applied
    db.close()


if __name__ == "__main__":
    tests = [v for k, v in sorted(globals().items()) if k.startswith("test_")]
    for t in tests:
        t()
        print(f"OK {t.__name__}")
    print("\n" + "=" * 60)
    print(" ALL MOD-LOADER TESTS PASSED!")
    print("=" * 60)
