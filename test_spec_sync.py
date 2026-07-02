#!/usr/bin/env python3
"""
Tests for definition -> runtime spec sync (apply_definition_specs).

Confirms a ruleset mod's content actually swaps the live spec structures, that
ALL_SHIP_TYPES is mutated in place (so existing imports see it), and that the
engine reverts to pristine defaults.

Run: python3 test_spec_sync.py
"""
import specs
from specs import ALL_SHIP_TYPES, SHIP_SPECS
from game_definition import set_game_definition, build_default_definition, load_definition_from_file


def _default():
    return build_default_definition()


def test_default_roster_is_pristine():
    set_game_definition(_default())
    assert "light_warship" in SHIP_SPECS
    assert "light_warship" in ALL_SHIP_TYPES
    assert "stealth_trader" not in SHIP_SPECS


def test_solar_empire_swaps_roster():
    se = load_definition_from_file("mods/solar_empire/definition.json")
    set_game_definition(se)
    # live spec dict now holds SE ships
    assert "scout_ship" in SHIP_SPECS
    assert "stealth_trader" in SHIP_SPECS
    assert "light_warship" not in SHIP_SPECS
    # canonical list reflects the new roster
    assert "scout_ship" in ALL_SHIP_TYPES
    assert SHIP_SPECS["scout_ship"]["name"] == "Scout Ship"
    # SE buildings + weapon types too
    assert "mining_facility" in specs.BUILDING_SPECS
    assert "plasma" in specs.WEAPON_TYPES


def test_all_ship_types_mutated_in_place():
    # the module-level list object identity must be stable across swaps so that
    # `from specs import ALL_SHIP_TYPES` references stay live
    obj_id = id(ALL_SHIP_TYPES)
    set_game_definition(load_definition_from_file("mods/solar_empire/definition.json"))
    assert id(ALL_SHIP_TYPES) == obj_id
    assert "scout_ship" in ALL_SHIP_TYPES
    set_game_definition(_default())
    assert id(ALL_SHIP_TYPES) == obj_id


def test_revert_to_default():
    set_game_definition(load_definition_from_file("mods/solar_empire/definition.json"))
    assert "scout_ship" in SHIP_SPECS
    set_game_definition(_default())
    assert "light_warship" in SHIP_SPECS
    assert "stealth_trader" not in SHIP_SPECS


def test_build_default_definition_is_pristine_after_swap():
    # even while SE is active, building the default must yield default ships
    set_game_definition(load_definition_from_file("mods/solar_empire/definition.json"))
    d = build_default_definition()
    assert "light_warship" in d["ships"]
    assert "stealth_trader" not in d["ships"]
    set_game_definition(_default())


def test_effective_spec_resolves_modded_ship():
    from database import SessionLocal
    from auth import init_default_configs, get_effective_ship_spec
    set_game_definition(load_definition_from_file("mods/solar_empire/definition.json"))
    db = SessionLocal(); init_default_configs(db)
    spec = get_effective_ship_spec(db, "scout_ship")
    assert spec.get("name") == "Scout Ship"
    db.close()
    set_game_definition(_default())


if __name__ == "__main__":
    try:
        tests = [v for k, v in sorted(globals().items()) if k.startswith("test_")]
        for t in tests:
            t()
            print(f"OK {t.__name__}")
        print("\n" + "=" * 60)
        print(" ALL SPEC-SYNC TESTS PASSED!")
        print("=" * 60)
    finally:
        set_game_definition(build_default_definition())  # leave pristine
