#!/usr/bin/env python3
"""
Tests for data-driven ship capabilities (colonize/recycle/autoscout).

A ruleset's own roster drives these features via spec flags instead of
hard-coded default ship keys.

Run: python3 test_capabilities.py
"""
from types import SimpleNamespace

from game_definition import set_game_definition, build_default_definition, load_definition_from_file
from database import SessionLocal
from auth import init_default_configs, ships_with_capability, fleet_capability_ship


def _db():
    db = SessionLocal(); init_default_configs(db); return db


def test_default_roster_capabilities():
    set_game_definition(build_default_definition())
    db = _db()
    assert ships_with_capability(db, "can_colonize") == ["colony_ship"]
    assert "utility_ship" in ships_with_capability(db, "can_recycle")
    assert "scout_ship" in ships_with_capability(db, "can_autoscout")
    db.close()


def test_classic_roster_capabilities():
    # Regression: the classic 20-ship roster must declare its colonizer/recycler/
    # scout via capability flags, or the (capability-driven) colonize/recycle/
    # autoscout paths break for BOTH human players and bots on classic.
    set_game_definition(load_definition_from_file("game_definitions/classic_space.json"))
    db = _db()
    assert ships_with_capability(db, "can_colonize") == ["medium_ship_3"]
    assert ships_with_capability(db, "can_recycle") == ["small_ship_6"]
    assert ships_with_capability(db, "can_autoscout") == ["small_ship_8"]
    db.close()
    set_game_definition(build_default_definition())


def test_solar_empire_capabilities():
    set_game_definition(load_definition_from_file("mods/solar_empire/definition.json"))
    db = _db()
    assert "stealth_trader" in ships_with_capability(db, "can_colonize")
    assert "scout_ship" in ships_with_capability(db, "can_autoscout")
    assert "harvester_mammoth" in ships_with_capability(db, "can_recycle")
    # default keys are not in the SE roster at all
    assert "medium_ship_3" not in ships_with_capability(db, "can_colonize")
    db.close()
    set_game_definition(build_default_definition())


def test_fleet_capability_ship_picks_present_ship():
    set_game_definition(build_default_definition())
    db = _db()

    class _Fleet:
        def __init__(self, **counts): self._c = counts
        def get_ship_count(self, k): return self._c.get(k, 0)

    # fleet with a colonizer
    f = _Fleet(colony_ship=2, light_warship=5)
    assert fleet_capability_ship(f, db, "can_colonize") == "colony_ship"
    # fleet without one
    f2 = _Fleet(light_warship=5)
    assert fleet_capability_ship(f2, db, "can_colonize") is None
    db.close()


def test_starter_buildings_are_data_driven():
    from auth import get_all_building_specs
    set_game_definition(build_default_definition())
    db = _db()
    bspecs = get_all_building_specs(db)
    assert bspecs["urban_structures"].get("start_level") == 1
    # buildings without the flag default to 0
    assert bspecs["solar_plants"].get("start_level", 0) == 0
    db.close()
    set_game_definition(load_definition_from_file("mods/solar_empire/definition.json"))
    db = _db()
    se = get_all_building_specs(db)
    assert se["organics_farm"].get("start_level") == 1
    assert "urban_structures" not in se  # default starter not in SE
    db.close()
    set_game_definition(build_default_definition())


def test_parameterized_colonize_capability():
    """A dict-valued `can_colonize` (Advanced Colony Ship) is still discovered as
    a colonizer (truthiness contract) and its params survive spec-sync."""
    import specs
    defn = build_default_definition()
    defn["ships"] = {
        **defn["ships"],
        "world_ship": {
            "name": "Advanced Colony Ship", "cost": 500, "attack": 2, "armour": 4,
            "shield": 0, "weapon": "laser",
            "can_colonize": {"starting_buildings": {"urban_structures": 3}},
        },
    }
    set_game_definition(defn)
    db = _db()
    # a dict is truthy, so it still registers as a colonizer
    assert "world_ship" in ships_with_capability(db, "can_colonize")
    # the founding params survive the sync into live specs
    cap = specs.SHIP_SPECS["world_ship"]["can_colonize"]
    assert isinstance(cap, dict) and cap["starting_buildings"]["urban_structures"] == 3
    # a fleet carrying it resolves to it
    f = SimpleNamespace(get_ship_count=lambda k: 1 if k == "world_ship" else 0)
    assert fleet_capability_ship(f, db, "can_colonize") == "world_ship"
    db.close()
    set_game_definition(build_default_definition())


if __name__ == "__main__":
    try:
        tests = [v for k, v in sorted(globals().items()) if k.startswith("test_")]
        for t in tests:
            t(); print(f"OK {t.__name__}")
        print("\n" + "=" * 60)
        print(" ALL CAPABILITY TESTS PASSED!")
        print("=" * 60)
    finally:
        set_game_definition(build_default_definition())
