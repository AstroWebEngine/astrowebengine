#!/usr/bin/env python3
"""Per-resource production for multi-resource economies (metal/crystal/deuterium).

Proves a building contribution can target a named resource and that
calc_base_stats surfaces a per-resource income dict in multi-resource mode
(single-resource mode is unaffected — income flows through `economy`).

Run: python3 test_resource_production.py
"""
from types import SimpleNamespace

import pytest

import auth
import game_logic
from game_logic import _evaluate_contributions, calc_base_stats
from game_definition import set_game_definition, build_default_definition


def test_contribution_can_target_a_resource():
    # A building whose contribution names a resource accumulates into that stat.
    specs = {
        "metal_mine":   {"contributions": {"metal":   {"type": "flat", "per_level": 30}}},
        "crystal_mine": {"contributions": {"crystal": {"type": "flat", "per_level": 20}}},
        "synthesizer":  {"contributions": {"deuterium": {"type": "flat", "per_level": 10}}},
    }
    planet = {"fertility": 1}
    s = _evaluate_contributions(
        {"metal_mine": 3, "crystal_mine": 2, "synthesizer": 4}, planet, specs)
    assert s["metal"] == 90
    assert s["crystal"] == 40
    assert s["deuterium"] == 40


def _multi_def():
    d = build_default_definition()
    d["engine"]["resource_model"] = "multi"
    d["engine"]["resource_types"] = ["metal", "crystal", "deuterium"]
    d["buildings"] = {
        "metal_mine":   {"name": "Metal Mine", "base_cost": 1, "cost_mult": 1.5,
                          "time": 60, "contributions": {"metal": {"type": "flat", "per_level": 30}}},
        "crystal_mine": {"name": "Crystal Mine", "base_cost": 1, "cost_mult": 1.6,
                          "time": 60, "contributions": {"crystal": {"type": "flat", "per_level": 20}}},
        "synthesizer":  {"name": "Synthesizer", "base_cost": 1, "cost_mult": 1.5,
                          "time": 60, "contributions": {"deuterium": {"type": "flat", "per_level": 10}}},
    }
    return d


def _colony_user():
    planet = SimpleNamespace(area=10, fertility=1)
    buildings = [
        SimpleNamespace(building_type="metal_mine", level=3),
        SimpleNamespace(building_type="crystal_mine", level=2),
        SimpleNamespace(building_type="synthesizer", level=4),
    ]
    colony = SimpleNamespace(planet=planet, buildings=buildings, id=1,
                             is_home_base=True, economy_penalty=0, _blv_cache=None)
    user = SimpleNamespace(id=1, colonies=[colony], research=[], commanders=[])
    return colony, user


@pytest.fixture(autouse=True)
def _restore_definition():
    # Stub the config cache so get_config(None, ...) (via get_all_building_specs)
    # doesn't try to hit the DB — these are pure-spec calculation tests.
    saved_cache, saved_loaded = auth._config_cache, auth._config_cache_loaded
    auth._config_cache, auth._config_cache_loaded = {}, True
    yield
    auth._config_cache, auth._config_cache_loaded = saved_cache, saved_loaded
    set_game_definition(build_default_definition())


def test_calc_base_stats_surfaces_resource_income():
    set_game_definition(_multi_def())
    colony, user = _colony_user()
    stats = calc_base_stats(colony, user, game_speed=1.0)
    assert stats["resource_income"] == {"metal": 90, "crystal": 40, "deuterium": 40}


def test_resource_income_scales_with_game_speed():
    set_game_definition(_multi_def())
    colony, user = _colony_user()
    stats = calc_base_stats(colony, user, game_speed=5.0)
    assert stats["resource_income"] == {"metal": 450, "crystal": 200, "deuterium": 200}


def test_single_resource_mode_has_empty_resource_income():
    set_game_definition(build_default_definition())  # single-resource default
    colony, user = _colony_user()
    stats = calc_base_stats(colony, user, game_speed=1.0)
    assert stats["resource_income"] == {}


def test_fleet_value_handles_multi_resource_dict_costs():
    # Regression: _fleet_value (and the combat/player-stats value math) multiplied
    # ship count by spec["cost"], which is a DICT in multi-resource mode — a 500
    # in /api/player/stats. It must collapse the cost to a scalar total.
    import combat
    from game_definition import load_definition_from_file
    set_game_definition(load_definition_from_file("mods/stellar_conquest/definition.json"))

    class _Fleet:
        def __init__(self, counts):
            self._c = counts
        def get_ship_count(self, st):
            return self._c.get(st, 0)

    # interceptor cost = metal 3000 + crystal 1000 = 4000 total; 2 of them.
    fleet = _Fleet({"interceptor": 2})
    assert combat._fleet_value(fleet, None) == 2 * 4000


if __name__ == "__main__":
    import sys
    sys.exit(pytest.main([__file__, "-q"]))
