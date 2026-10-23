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


def test_enabled_mod_with_missing_definition_blocks_composition():
    """An enabled mod that can't load must fail the plan, not silently vanish -
    otherwise 'enabled' claims rules the running game doesn't have."""
    with TemporaryDirectory() as root:
        _write_mod(root, "missing_def", {
            "name": "Missing Definition", "version": "1", "kind": "content",
            "definition": "definition.json", "engine_api": "1.0",
        })
        defn, report = _compose_with_temp_mods(root, enabled=["missing_def"])
        assert any("missing_def" in e for e in report["errors"]), report
        assert report["applied"] == []


def _conflict_pair(root, declared_by):
    for mid, order, val in (("alpha", 10, 2), ("beta", 20, 99)):
        manifest = {"name": mid.title(), "version": "1", "kind": "content",
                    "definition": "definition.json", "engine_api": "1.0", "load_order": order}
        if mid == declared_by:
            manifest["conflicts"] = ["beta" if mid == "alpha" else "alpha"]
        _write_mod(root, mid, manifest, {"engine": {"construction_queue_max": val}})


def test_conflict_declared_by_earlier_mod_is_an_error():
    with TemporaryDirectory() as root:
        _conflict_pair(root, declared_by="alpha")
        defn, report = _compose_with_temp_mods(root, enabled=["alpha", "beta"])
        assert any("alpha" in e and "beta" in e and "conflict" in e for e in report["errors"]), report


def test_conflict_declared_by_later_mod_is_also_an_error():
    """Conflicts are symmetric: it doesn't matter which side declares it."""
    with TemporaryDirectory() as root:
        _conflict_pair(root, declared_by="beta")
        defn, report = _compose_with_temp_mods(root, enabled=["alpha", "beta"])
        assert any("conflict" in e for e in report["errors"]), report


def test_conflicting_mod_that_is_not_enabled_is_fine():
    with TemporaryDirectory() as root:
        _conflict_pair(root, declared_by="alpha")
        defn, report = _compose_with_temp_mods(root, enabled=["alpha"])
        assert report["errors"] == [] and report["applied"] == ["alpha"]


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
    # current engine API is 1.0
    assert ml._api_compatible("1.0") and ml._api_compatible("") and ml._api_compatible("^1.0")
    assert ml._api_compatible(">=1.0,<2") and ml._api_compatible("~1.0")
    assert not ml._api_compatible("2.0")
    assert not ml._api_compatible("1.99"), "a mod needing API 1.99 must not load on 1.0"
    assert not ml._api_compatible("^1.2") and not ml._api_compatible(">=1.1")
    assert not ml._api_compatible("banana")


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


# -- Dependencies, ordering, identity, containment ----------------------------

def _content(root, mod_id, requires=(), order=100, version="1.0", value=None, **extra):
    manifest = {"name": mod_id, "version": version, "kind": "content",
                "definition": "definition.json", "engine_api": "1.0",
                "load_order": order, "requires": list(requires), **extra}
    _write_mod(root, mod_id, manifest, {"combat": {"loot_percent": value if value is not None else 0.5}})


def test_missing_required_mod_is_an_error():
    with TemporaryDirectory() as root:
        _content(root, "needs_core", requires=["core_pack"])
        defn, report = _compose_with_temp_mods(root, enabled=["needs_core"])
        assert any("needs_core" in e and "core_pack" in e for e in report["errors"]), report


def test_required_mod_installed_but_not_enabled_is_an_error():
    with TemporaryDirectory() as root:
        _content(root, "core_pack")
        _content(root, "needs_core", requires=["core_pack"])
        defn, report = _compose_with_temp_mods(root, enabled=["needs_core"])
        assert any("core_pack" in e and "not enabled" in e for e in report["errors"]), report


def test_required_version_range_is_checked():
    with TemporaryDirectory() as root:
        _content(root, "core_pack", version="1.4")
        _content(root, "needs_new", requires=[{"id": "core_pack", "version": ">=2.0"}])
        defn, report = _compose_with_temp_mods(root, enabled=["core_pack", "needs_new"])
        assert any("core_pack" in e and ">=2.0" in e for e in report["errors"]), report


def test_dependencies_apply_before_dependants_regardless_of_load_order():
    with TemporaryDirectory() as root:
        _content(root, "base_rules", order=500, value=0.1)
        _content(root, "tweak", requires=["base_rules"], order=10, value=0.9)
        defn, report = _compose_with_temp_mods(root, enabled=["tweak", "base_rules"])
        assert report["errors"] == [], report
        assert report["applied"] == ["base_rules", "tweak"]
        assert defn["combat"]["loot_percent"] == 0.9


def test_dependency_cycle_is_reported_with_its_path():
    with TemporaryDirectory() as root:
        _content(root, "a_mod", requires=["b_mod"])
        _content(root, "b_mod", requires=["a_mod"])
        defn, report = _compose_with_temp_mods(root, enabled=["a_mod", "b_mod"])
        assert any("cycle" in e and "a_mod" in e and "b_mod" in e for e in report["errors"]), report


def test_ruleset_satisfies_a_requirement():
    with TemporaryDirectory() as root:
        _write_mod(root, "my_rules", {"name": "R", "version": "1.0", "kind": "ruleset",
                                      "definition": "definition.json", "engine_api": "1.0"},
                   load_definition_from_file("game_definitions/classic_space.json"))
        _content(root, "addon", requires=["my_rules"])
        defn, report = _compose_with_temp_mods(root, enabled=["addon"], ruleset="my_rules")
        assert report["errors"] == [], report


def test_duplicate_ids_are_rejected_at_discovery():
    with TemporaryDirectory() as root:
        _content(root, "first_dir")
        _write_mod(root, "second_dir", {"id": "first_dir", "name": "Copy", "version": "1",
                                        "kind": "content", "definition": "definition.json",
                                        "engine_api": "1.0"}, {"combat": {}})
        old = ml.MODS_DIR; ml.MODS_DIR = root
        try:
            found = [m for m in ml.discover_mods() if m["id"] == "first_dir"]
        finally:
            ml.MODS_DIR = old
        assert len(found) == 2 and all(any("duplicate" in e for e in m["errors"]) for m in found)


def test_definition_cannot_escape_into_a_sibling_with_a_shared_prefix():
    """mods/abc must not be able to load mods/abc_evil/definition.json."""
    with TemporaryDirectory() as root:
        _write_mod(root, "abc_evil", {"name": "E", "version": "1", "kind": "content",
                                      "definition": "definition.json", "engine_api": "1.0"},
                   {"combat": {"loot_percent": 1}})
        _write_mod(root, "abc", {"name": "A", "version": "1", "kind": "content",
                                 "definition": "../abc_evil/definition.json", "engine_api": "1.0"})
        defn, report = _compose_with_temp_mods(root, enabled=["abc"])
        assert any("escapes" in e for e in report["errors"]), report
        assert report["applied"] == []


def test_requires_entries_are_validated_in_the_manifest():
    base = {"id": "x", "name": "X", "version": "1", "kind": "content", "definition": "d.json"}
    assert ml.validate_manifest({**base, "requires": ["ok_id", {"id": "other", "version": ">=1"}]}) == []
    assert ml.validate_manifest({**base, "requires": [{"version": ">=1"}]})
    assert ml.validate_manifest({**base, "requires": [{"id": "y", "version": "lots"}]})
    assert ml.validate_manifest({**base, "requires": "not_a_list"})
    assert ml.validate_manifest({**base, "version": "one point oh"})
