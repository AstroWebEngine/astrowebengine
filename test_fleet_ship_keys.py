#!/usr/bin/env python3
"""
Regression test for capital-ship accounting in combat.

Guards against the rename-era bug where attacking capital ships read as 0:
combat.py read attacker counts with raw ``getattr(fleet, ship_type)`` while
``ALL_SHIP_TYPES`` used canonical keys (capital_ship_1/2) that did not match the
stored representation. The defender path used ``Fleet.get_ship_count`` and was
unaffected, so only attackers silently lost their capital ships.

This test asserts the BEHAVIOUR via the public Fleet API (set_ship_count /
get_ship_count) so it stays valid regardless of the underlying column names.

Run: python3 test_fleet_ship_keys.py
"""
from models import Fleet
from specs import ALL_SHIP_TYPES

# capital_ship_1/2 are classic-roster keys; load the classic definition so the
# canonical roster includes them (the lean engine default does not).
from game_definition import set_game_definition, load_definition_from_file


def _load_classic():
    """Make the classic 20-ship roster the active definition.

    The active definition is global mutable state (``specs.ALL_SHIP_TYPES`` is
    updated in place), so any earlier test that swapped definitions would leak
    into ours. Re-loading classic before each test keeps this module order-
    independent under the full suite.
    """
    set_game_definition(load_definition_from_file("game_definitions/classic_space.json"))


_load_classic()

import pytest


@pytest.fixture(autouse=True)
def _classic_roster():
    _load_classic()
    yield


CAPITAL_KEYS = ["capital_ship_1", "capital_ship_2"]


def test_capital_keys_are_canonical_ship_types():
    for key in CAPITAL_KEYS:
        assert key in ALL_SHIP_TYPES, f"{key} missing from ALL_SHIP_TYPES"


def test_set_then_get_roundtrips():
    f = Fleet()
    f.set_ship_count("capital_ship_1", 3)
    f.set_ship_count("capital_ship_2", 2)
    assert f.get_ship_count("capital_ship_1") == 3
    assert f.get_ship_count("capital_ship_2") == 2


def test_attacker_read_path_sees_capital_ships():
    """Mirror the combat.py attacker gather loop and assert capital ships count.

    The historical bug used getattr(fleet, st); here we exercise the fixed path
    (get_ship_count) across every ship type, as resolve_battle does.
    """
    f = Fleet()
    f.set_ship_count("capital_ship_1", 4)
    counts = {st: float(f.get_ship_count(st)) for st in ALL_SHIP_TYPES}
    assert counts["capital_ship_1"] == 4.0, (
        "attacking capital ships must contribute to combat, not read as 0"
    )
    assert sum(counts.values()) == 4.0


def test_unset_capital_ships_are_zero_not_error():
    f = Fleet()
    for st in ALL_SHIP_TYPES:
        assert float(f.get_ship_count(st)) == 0.0


if __name__ == "__main__":
    tests = [v for k, v in sorted(globals().items()) if k.startswith("test_")]
    for t in tests:
        _load_classic()
        t()
        print(f"OK {t.__name__}")
    print("\n" + "=" * 60)
    print(" ALL CAPITAL-SHIP REGRESSION TESTS PASSED!")
    print("=" * 60)
