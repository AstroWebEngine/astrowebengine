#!/usr/bin/env python3
"""Cargo-raid plunder + post-battle rebuild factors (classic formulas,
verified against an open-source reference implementation).

Plunder (engine plunder_model "cargo"): the winner steals from the defender's
stockpile, capped by surviving cargo capacity (ship spec `cargo`), with the
classic fill order — 1/3 capacity metal, 1/2 remainder crystal, rest
deuterium, then refill passes at 1/2. Rebuild (engine rebuild_model
"binomial"): destroyed units rebuild stochastically instead of a flat %.

Run: python3 test_raid_rebuild.py
"""
import json

import pytest
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

import auth
from combat import _plunder_resources, _rebuild_count, _raid_plunder
from database import ModelBase
from game_definition import set_game_definition, build_default_definition
from models import Fleet, User
from resources import get_user_resources
from specs import ALL_SHIP_TYPES

TYPES = ["metal", "crystal", "deuterium"]


# ── Fill order (pure function) ─────────────────────────────────────────────

def test_plunder_fill_order_capacity_limited():
    taken = _plunder_resources({"metal": 100_000, "crystal": 100_000, "deuterium": 100_000}, 30_000, TYPES)
    assert taken == {"metal": 10000.0, "crystal": 10000.0, "deuterium": 10000.0}


def test_plunder_takes_all_when_capacity_abundant():
    taken = _plunder_resources({"metal": 900, "crystal": 600, "deuterium": 300}, 10**9, TYPES)
    assert taken == {"metal": 900.0, "crystal": 600.0, "deuterium": 300.0}


def test_plunder_single_resource_cannot_fill_everything():
    """Classic quirk: a metal-only target with 60k capacity yields only 40k —
    1/3 pass (20k) + 1/2 refill (20k); the remaining capacity stays unused."""
    taken = _plunder_resources({"metal": 90_000, "crystal": 0, "deuterium": 0}, 60_000, TYPES)
    assert taken == {"metal": 40000.0}


# ── Rebuild factors ─────────────────────────────────────────────────────────

def test_rebuild_fixed_is_deterministic():
    assert _rebuild_count(100, 0.7, "fixed") == 70.0
    assert _rebuild_count(0, 0.7, "fixed") == 0.0
    assert _rebuild_count(100, 0.0, "binomial") == 0.0


def test_rebuild_binomial_bounds():
    for _ in range(200):
        n = _rebuild_count(100, 0.7, "binomial")
        assert 0.0 <= n <= 100.0 and n == int(n)
    assert _rebuild_count(50, 1.0, "binomial") == 50.0  # factor 1.0 -> no variance


# ── Raid end-to-end ─────────────────────────────────────────────────────────

@pytest.fixture()
def db():
    saved_cache, saved_loaded = auth._config_cache, auth._config_cache_loaded
    auth._config_cache, auth._config_cache_loaded = {}, True
    eng = create_engine("sqlite:///:memory:")
    ModelBase.metadata.create_all(eng)
    s = sessionmaker(bind=eng)()
    yield s
    s.close()
    auth._config_cache, auth._config_cache_loaded = saved_cache, saved_loaded
    set_game_definition(build_default_definition())


def test_raid_plunder_end_to_end(db):
    defn = build_default_definition()
    defn["engine"]["resource_model"] = "multi"
    defn["engine"]["resource_types"] = TYPES
    hauler = next(iter(defn["ships"]))
    defn["ships"][hauler]["cargo"] = 5000
    set_game_definition(defn)

    attacker = User(username="A", email="a@raid.com", hashed_password="x")
    defender = User(username="D", email="d@raid.com", hashed_password="x")
    defender.resources_json = json.dumps({"metal": 60000, "crystal": 30000, "deuterium": 12000})
    db.add_all([attacker, defender]); db.flush()
    fleet = Fleet(name="Raiders", user_id=attacker.id)
    fleet.set_ship_count(hauler, 2)  # 10k cargo capacity
    db.add(fleet); db.flush()

    specs = {st: {"cargo": 5000 if st == hauler else 0} for st in ALL_SHIP_TYPES}
    raid = _raid_plunder(db, attacker, defender, fleet, specs, {"plunder_percent": 0.5})

    # Plunderable pool (1 base): 30000/15000/6000; capacity 10000 with the
    # classic fill order -> 3333 metal, 3333 crystal, 3334 deuterium.
    assert raid == {"metal": 3333.0, "crystal": 3333.0, "deuterium": 3334.0}
    assert get_user_resources(defender)["metal"] == 60000 - 3333
    assert get_user_resources(attacker)["metal"] == 3333


def test_raid_needs_cargo_capacity(db):
    defn = build_default_definition()
    defn["engine"]["resource_model"] = "multi"
    defn["engine"]["resource_types"] = TYPES
    set_game_definition(defn)
    attacker = User(username="A2", email="a2@raid.com", hashed_password="x")
    defender = User(username="D2", email="d2@raid.com", hashed_password="x")
    defender.resources_json = json.dumps({"metal": 60000, "crystal": 30000, "deuterium": 12000})
    db.add_all([attacker, defender]); db.flush()
    fleet = Fleet(name="NoCargo", user_id=attacker.id)
    db.add(fleet); db.flush()
    specs = {st: {"cargo": 0} for st in ALL_SHIP_TYPES}
    assert _raid_plunder(db, attacker, defender, fleet, specs, {"plunder_percent": 0.5}) is None


if __name__ == "__main__":
    import sys
    sys.exit(pytest.main([__file__, "-q"]))
