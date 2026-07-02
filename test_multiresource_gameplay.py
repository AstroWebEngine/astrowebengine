#!/usr/bin/env python3
"""Multi-resource gameplay hardening: the full loop must work (and bots must not
crash) on a definition with real per-resource dict costs (stellar_conquest).

stellar_conquest is the first definition with metal/crystal/deuterium dict costs,
which exposed scalar-assuming `count * cost` / `bot.credits < cost` spots. These
tests drive the human build path AND a bot construct/tick on multi-resource and
assert no crash + correct per-resource deduction.

Run: python3 test_multiresource_gameplay.py
"""
import json

import pytest
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

from database import ModelBase
from models import (User, Cluster, Galaxy, Region, StarSystem, Planet, Colony,
                    Building, Research, Fleet)
from game_definition import (set_game_definition, build_default_definition,
                             load_definition_from_file)
import auth
from datetime import datetime


STELLAR = "mods/stellar_conquest/definition.json"


@pytest.fixture()
def db():
    eng = create_engine("sqlite:///:memory:")
    ModelBase.metadata.create_all(eng)
    session = sessionmaker(bind=eng)()
    auth.init_default_configs(session)
    set_game_definition(load_definition_from_file(STELLAR))
    yield session
    session.close()
    set_game_definition(build_default_definition())


def _universe(db):
    cl = Cluster(name="A", cluster_index=0); db.add(cl); db.flush()
    gal = Galaxy(name="A00", cluster_id=cl.id, galaxy_index=0); db.add(gal); db.flush()
    reg = Region(name="00", galaxy_id=gal.id, grid_x=0, grid_y=0); db.add(reg); db.flush()
    sysrow = StarSystem(name="00", region_id=reg.id); db.add(sysrow); db.flush()
    p = Planet(name="A00:00:00:1", system_id=sysrow.id, orbit_position=1,
               planet_type="Earthly", area=100, fertility=10,
               metal=5, crystal=5, gas=5, solar=5)
    db.add(p); db.flush()
    return p


def _bot_with_colony(db, planet, resources=None):
    res = resources or {"metal": 100000, "crystal": 100000, "deuterium": 100000}
    bot = User(username="npc1", hashed_password="x", is_bot=True, bot_strategy="balanced",
               resources_json=json.dumps(res), credits=0, score=10,
               last_collected=datetime.utcnow())
    db.add(bot); db.flush()
    planet.is_colonized = True
    col = Colony(planet_id=planet.id, user_id=bot.id, name="NPC Home",
                 is_home_base=True, last_collected=datetime.utcnow())
    db.add(col); db.flush()
    # Starter buildings so the colony is functional (mirrors a real homeworld).
    from specs import BUILDING_SPECS, DEFENSE_SPECS, RESEARCH_SPECS
    for bt, spec in BUILDING_SPECS.items():
        db.add(Building(colony_id=col.id, building_type=bt, level=spec.get("start_level", 0)))
    for dt in DEFENSE_SPECS:
        db.add(Defense_row(db, col.id, dt))
    for tt in RESEARCH_SPECS:
        db.add(Research(user_id=bot.id, tech_type=tt, level=0))
    db.add(Fleet(name="Home Fleet", user_id=bot.id, base_id=col.id))
    db.commit()
    return bot, col


def Defense_row(db, colony_id, defense_type):
    from models import Defense
    return Defense(colony_id=colony_id, defense_type=defense_type, level=0)


# ── Human-facing build paths ─────────────────────────────────────────────

def test_building_cost_is_per_resource_dict(db):
    from game_logic import calc_building_cost, calc_base_stats
    p = _universe(db)
    bot, col = _bot_with_colony(db, p)
    stats = calc_base_stats(col, bot, 1.0)
    cost, _t = calc_building_cost(db, "metal_extractor", 0, stats, 1.0)
    assert isinstance(cost, dict)
    assert cost.get("metal", 0) > 0 and cost.get("crystal", 0) > 0


def test_count_defense_cost_is_per_resource_dict(db):
    from game_logic import calc_defense_cost
    _universe(db)
    cost, build_time, units = calc_defense_cost(db, "rocket_turret", 0, 1.0, count=3)
    assert isinstance(cost, dict)
    assert cost.get("metal", 0) == 6000  # 2000 metal * 3 (count model, flat)


def test_can_afford_and_deduct_per_resource(db):
    from resources import can_afford, deduct_cost, get_user_resources
    p = _universe(db)
    bot, col = _bot_with_colony(db, p, resources={"metal": 100, "crystal": 50, "deuterium": 0})
    assert can_afford(bot, {"metal": 60, "crystal": 15})
    assert not can_afford(bot, {"metal": 60, "crystal": 200})
    deduct_cost(bot, {"metal": 60, "crystal": 15})
    r = get_user_resources(bot)
    assert r["metal"] == 40 and r["crystal"] == 35


# ── Bot paths (must not crash on dict costs) ─────────────────────────────

def test_bot_constructs_multiresource_building_and_deducts(db):
    from bot_logic import _bot_try_construct
    from resources import get_user_resources
    p = _universe(db)
    bot, col = _bot_with_colony(db, p)
    before = dict(get_user_resources(bot))
    # Force the bot to build a stellar_conquest building (real dict cost).
    # robotics_bay starts at level 0; build toward level 1.
    _bot_try_construct(bot, col, db, 1.0, [("robotics_bay", 1)], datetime.utcnow())
    after = get_user_resources(bot)
    # It should have queued+charged the active item (per-resource deduction).
    assert after["metal"] < before["metal"]
    assert after["crystal"] < before["crystal"]


def test_bot_tick_does_not_crash_on_multi_resource(db):
    # _tick_single_bot propagates exceptions (tick_bots swallows them), so call it
    # directly to assert the whole bot tick path is multi-resource safe.
    from bot_logic import _tick_single_bot
    p = _universe(db)
    bot, col = _bot_with_colony(db, p)
    _tick_single_bot(bot, db, 1.0, datetime.utcnow())  # must not raise


def test_seed_starting_resources_multi(db):
    # New users in a multi-resource economy must get a starting stash, else they
    # (and bots) have 0 of every resource and can never build.
    from resources import seed_starting_resources, get_user_resources
    u = User(username="fresh", hashed_password="x")
    db.add(u); db.flush()
    seed_starting_resources(u)
    r = get_user_resources(u)
    assert r["metal"] > 0 and r["crystal"] > 0 and r["deuterium"] > 0


def test_effective_build_order_is_roster_derived(db):
    # On a non-classic roster the classic build order is empty; the effective
    # order must be derived from the active roster so bots aren't inert.
    from bot_logic import _effective_build_order, BUILD_ORDER_BALANCED
    order_keys = {k for k, _ in _effective_build_order(db, list(BUILD_ORDER_BALANCED))}
    assert "metal_extractor" in order_keys
    assert "robotics_bay" in order_keys
    # No classic key leaks in (they don't exist in stellar_conquest).
    assert "urban_structures" not in order_keys


def test_bot_builds_combat_ship_on_multiresource_roster(db):
    from models import ShipQueue, Building, Research
    from bot_logic import _bot_try_build_ships
    from resources import get_user_resources
    p = _universe(db)
    bot, col = _bot_with_colony(db, p)
    # Enable ship-building: a shipyard + the cheapest combat ship's tech.
    sy = next(b for b in col.buildings if b.building_type == "shipyard")
    sy.level = 2
    cd = next(r for r in bot.research if r.tech_type == "combustion_drive")
    cd.level = 5
    db.commit()
    before = dict(get_user_resources(bot))

    _bot_try_build_ships(bot, col, db, 1.0, datetime.utcnow())

    queued = db.query(ShipQueue).filter(ShipQueue.colony_id == col.id).all()
    assert queued, "bot should queue a combat ship from the active roster"
    # A real combat ship from stellar_conquest, charged per-resource.
    assert queued[0].ship_type in {"interceptor", "light_hauler", "recon_drone", "strike_fighter"}
    after = get_user_resources(bot)
    assert after["metal"] < before["metal"] or after["crystal"] < before["crystal"]


if __name__ == "__main__":
    import sys
    sys.exit(pytest.main([__file__, "-q"]))
