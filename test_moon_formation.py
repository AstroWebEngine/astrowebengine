#!/usr/bin/env python3
"""Moon formation from combat debris ("moonshot").

Battle debris at a planet has a chance to coalesce into a moon owned by the
planet's owner. Gated by engine.moon_formation; chance scales with debris
value (moon_chance_per_100k_debris) up to moon_max_chance. One moon per slot.

Run: python3 test_moon_formation.py
"""
import pytest
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

import auth
from combat import _maybe_form_moon
from database import ModelBase
from game_definition import set_game_definition, build_default_definition
from models import Cluster, Galaxy, Region, StarSystem, Planet, Colony, User


GUARANTEED = {
    "moon_formation": True,
    "moon_chance_per_100k_debris": 1.0,
    "moon_max_chance": 1.0,
}


@pytest.fixture()
def db():
    saved_cache, saved_loaded = auth._config_cache, auth._config_cache_loaded
    auth._config_cache, auth._config_cache_loaded = {}, True
    set_game_definition(build_default_definition())
    eng = create_engine("sqlite:///:memory:")
    ModelBase.metadata.create_all(eng)
    s = sessionmaker(bind=eng)()
    yield s
    s.close()
    auth._config_cache, auth._config_cache_loaded = saved_cache, saved_loaded
    set_game_definition(build_default_definition())


def _world(db):
    cl = Cluster(name="A", cluster_index=0); db.add(cl); db.flush()
    gal = Galaxy(name="A00", cluster_id=cl.id, galaxy_index=0); db.add(gal); db.flush()
    reg = Region(name="00", galaxy_id=gal.id, grid_x=0, grid_y=0); db.add(reg); db.flush()
    sys_ = StarSystem(name="001", region_id=reg.id, star_type="orange"); db.add(sys_); db.flush()
    planet = Planet(name="A00:001:30", system_id=sys_.id, planet_type="earthly",
                    orbit_position=3, orbit_row=0, temperature=42, is_colonized=True)
    db.add(planet); db.flush()
    owner = User(username="Defender", email="d@x.com", hashed_password="x")
    db.add(owner); db.flush()
    db.add(Colony(planet_id=planet.id, user_id=owner.id, name="Home")); db.flush()
    return planet, owner


def test_moon_forms_and_belongs_to_planet_owner(db):
    planet, owner = _world(db)
    moon = _maybe_form_moon(db, planet, 500_000, owner, GUARANTEED)
    assert moon is not None
    assert moon.orbit_position == planet.orbit_position and moon.orbit_row == 1
    assert moon.name == "A00:001:31"  # same slot, next row coordinate
    assert moon.temperature == planet.temperature
    assert moon.is_colonized
    base = db.query(Colony).filter(Colony.planet_id == moon.id).one()
    assert base.user_id == owner.id and base.name == "Moon"
    # Moon starts empty — no starter building levels.
    assert all(b.level == 0 for b in base.buildings)


def test_one_moon_per_slot(db):
    planet, owner = _world(db)
    assert _maybe_form_moon(db, planet, 500_000, owner, GUARANTEED) is not None
    assert _maybe_form_moon(db, planet, 500_000, owner, GUARANTEED) is None


def test_disabled_by_default(db):
    planet, owner = _world(db)
    assert _maybe_form_moon(db, planet, 10**9, owner, {}) is None


def test_chance_scales_and_caps(db):
    planet, owner = _world(db)
    # Tiny debris with default tuning -> chance ~0; force the roll to be impossible.
    cfg = {"moon_formation": True, "moon_chance_per_100k_debris": 0.0, "moon_max_chance": 0.2}
    assert _maybe_form_moon(db, planet, 10**9, owner, cfg) is None


def test_min_chance_floor(db):
    """Classic rule: a chance below 1% never forms a moon, no matter the roll."""
    planet, owner = _world(db)
    cfg = {"moon_formation": True, "moon_chance_per_100k_debris": 0.001, "moon_max_chance": 0.2}
    for _ in range(50):  # chance = 0.005 < 0.01 floor -> deterministic no
        assert _maybe_form_moon(db, planet, 500_000, owner, cfg) is None


def test_moon_size_scales_with_chance(db):
    """Classic moon size: fields = rand(10..20) + 3 per % of chance."""
    planet, owner = _world(db)
    moon = _maybe_form_moon(db, planet, 500_000, owner, GUARANTEED)  # chance 1.0
    assert moon is not None
    assert 310 <= moon.area <= 320


## ── Moon destruction ("destroy" mission) ──────────────────────────────────

from combat import attempt_moon_destruction
from models import Fleet, Building


def _destruction_definition(max_chance=True):
    """Definition with moon_destruction on and a destroyer-capable ship."""
    defn = build_default_definition()
    defn["engine"]["moon_destruction"] = True
    first_ship = next(iter(defn["ships"]))
    defn["ships"][first_ship]["can_destroy_moons"] = True
    set_game_definition(defn)
    return first_ship


def _moon_world(db):
    """A planet + its moon (both colonized by the defender) + attacker w/ fleet."""
    planet, owner = _world(db)
    moon = _maybe_form_moon(db, planet, 500_000, owner, GUARANTEED)
    assert moon is not None
    moon.area = 30  # realistic small moon (test helper made a max-chance giant)
    attacker = User(username="Attacker", email="a@x.com", hashed_password="x")
    db.add(attacker); db.flush()
    moon_base = db.query(Colony).filter(Colony.planet_id == moon.id).one()
    return planet, moon, moon_base, owner, attacker


def test_destruction_disabled_by_default(db):
    planet, moon, moon_base, owner, attacker = _moon_world(db)
    fleet = Fleet(name="RIPs", user_id=attacker.id, location_planet_id=moon.id)
    db.add(fleet); db.flush()
    res = attempt_moon_destruction(db, fleet, moon_base)
    assert res == {"chance": 0.0, "destroyed": False, "backfire_chance": 0.0, "destroyers_lost": 0}


def test_destruction_requires_capable_ships(db):
    _destruction_definition()
    planet, moon, moon_base, owner, attacker = _moon_world(db)
    fleet = Fleet(name="No RIPs", user_id=attacker.id, location_planet_id=moon.id)
    db.add(fleet); db.flush()
    res = attempt_moon_destruction(db, fleet, moon_base)
    assert res["chance"] == 0.0 and not res["destroyed"]


def test_destruction_formula_matches_classic(db):
    """chance = min(1, (1-0.01*sqrt(d))*sqrt(n)), d = 1000*sqrt(fields)."""
    import math
    ship = _destruction_definition()
    planet, moon, moon_base, owner, attacker = _moon_world(db)
    fleet = Fleet(name="RIPs", user_id=attacker.id, location_planet_id=moon.id)
    fleet.set_ship_count(ship, 4)
    db.add(fleet); db.flush()
    d = 1000.0 * math.sqrt(moon.area)
    expected = round(min(1.0, max(0.0, 1.0 - 0.01 * math.sqrt(d)) * 2.0), 4)
    res = attempt_moon_destruction(db, fleet, moon_base)
    assert res["chance"] == expected
    assert res["backfire_chance"] == round(min(1.0, 5e-5 * d), 4)


def test_destroyed_moon_cascade(db, monkeypatch):
    """A cracked moon takes its base and stationed fleets with it; visiting
    fleets are rerouted to the parent planet."""
    ship = _destruction_definition()
    planet, moon, moon_base, owner, attacker = _moon_world(db)
    stationed = Fleet(name="Defenders", user_id=owner.id, base_id=moon_base.id)
    db.add(stationed)
    rips = Fleet(name="RIPs", user_id=attacker.id, location_planet_id=moon.id)
    rips.set_ship_count(ship, 1000)
    db.add(rips); db.flush()
    moon_id, base_id = moon.id, moon_base.id

    import random
    monkeypatch.setattr(random, "random", lambda: 0.0)  # both rolls succeed
    res = attempt_moon_destruction(db, rips, moon_base)
    assert res["destroyed"] is True
    assert db.query(Planet).filter(Planet.id == moon_id).first() is None
    assert db.query(Colony).filter(Colony.id == base_id).first() is None
    assert db.query(Building).filter(Building.colony_id == base_id).count() == 0
    assert db.query(Fleet).filter(Fleet.name == "Defenders").first() is None  # died with the moon
    surviving = db.query(Fleet).filter(Fleet.name == "RIPs").one()
    assert surviving.location_planet_id == planet.id  # rerouted to the planet
    # Backfire also rolled (forced): all destroyer ships lost.
    assert res["destroyers_lost"] == 1000 and surviving.get_ship_count(ship) == 0


if __name__ == "__main__":
    import sys
    sys.exit(pytest.main([__file__, "-q"]))
