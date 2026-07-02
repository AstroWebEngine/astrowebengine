#!/usr/bin/env python3
"""Showcase proof: the two public clones run on the same engine, differing only
by definition. classic_empire sits at one flag corner (single-resource /
simultaneous / level defenses); stellar_conquest at the opposite (multi-resource
/ rounds / count defenses). Both must discover, validate, flip their engine
flags, and resolve ship capabilities.

Run: python3 test_showcase_mods.py
"""
from types import SimpleNamespace

import pytest

import auth
from mod_loader import discover_mods, load_mod_definition
from game_definition import validate_definition, set_game_definition, build_default_definition


@pytest.fixture(autouse=True)
def _isolate():
    saved_cache, saved_loaded = auth._config_cache, auth._config_cache_loaded
    auth._config_cache, auth._config_cache_loaded = {}, True
    yield
    auth._config_cache, auth._config_cache_loaded = saved_cache, saved_loaded
    set_game_definition(build_default_definition())


def _mod(mod_id):
    m = {x["id"]: x for x in discover_mods()}.get(mod_id)
    assert m is not None, f"{mod_id} mod not discovered"
    assert m["errors"] == [], f"{mod_id} manifest errors: {m['errors']}"
    d = load_mod_definition(m)
    assert validate_definition(d) == [], f"{mod_id} definition invalid"
    return d


def _caps():
    from specs import SHIP_SPECS
    return ({k for k, s in SHIP_SPECS.items() if s.get("can_colonize")},
            {k for k, s in SHIP_SPECS.items() if s.get("can_recycle")},
            {k for k, s in SHIP_SPECS.items() if s.get("can_autoscout")})


def test_classic_empire_flag_corner():
    d = _mod("classic_empire")
    eng = d["engine"]
    assert eng["resource_model"] == "single"
    assert eng["defense_model"] == "level"
    assert eng["combat_max_rounds"] == 1
    set_game_definition(d)
    col, rec, sco = _caps()
    assert col and rec and sco, "classic_empire must resolve all three capabilities"


def test_stellar_conquest_flag_corner():
    d = _mod("stellar_conquest")
    eng = d["engine"]
    assert eng["resource_model"] == "multi"
    assert eng["resource_types"] == ["metal", "crystal", "deuterium"]
    assert eng["defense_model"] == "count"
    assert eng["combat_model"] == "rounds" and eng["combat_max_rounds"] == 6
    set_game_definition(d)
    col, rec, sco = _caps()
    assert col == {"settler"} and rec == {"reclaimer"} and sco == {"recon_drone"}


def test_stellar_conquest_differentiated_production():
    """The multi-resource economy must produce distinct metal/crystal/deuterium."""
    set_game_definition(_mod("stellar_conquest"))
    from game_logic import calc_base_stats
    planet = SimpleNamespace(area=20, fertility=1)
    buildings = [SimpleNamespace(building_type=b, level=l) for b, l in
                 [("metal_extractor", 5), ("crystal_extractor", 4), ("deuterium_synth", 3)]]
    colony = SimpleNamespace(planet=planet, buildings=buildings, id=1,
                             is_home_base=True, economy_penalty=0, _blv_cache=None)
    user = SimpleNamespace(id=1, colonies=[colony], research=[], commanders=[])
    income = calc_base_stats(colony, user, 1.0)["resource_income"]
    assert income == {"metal": 150, "crystal": 80, "deuterium": 30}


def test_two_clones_differ_only_by_definition():
    """Same engine, opposite flag corners — the whole point of the showcase."""
    classic = _mod("classic_empire")["engine"]
    stellar = _mod("stellar_conquest")["engine"]
    assert classic["resource_model"] != stellar["resource_model"]
    assert classic["defense_model"] != stellar["defense_model"]
    assert classic["combat_max_rounds"] != stellar["combat_max_rounds"]


def test_terrains_are_definition_driven():
    """Terrain display names sync from the definition like every other content
    category; definitions without a terrains section fall back to engine
    defaults (neutral names)."""
    from specs import PLANET_TYPE_STATS, apply_definition_specs

    custom = build_default_definition()
    custom["terrains"] = {"earthly": {**PLANET_TYPE_STATS["earthly"], "name": "Homeland"}}
    apply_definition_specs(custom)
    assert PLANET_TYPE_STATS["earthly"]["name"] == "Homeland"
    assert len(PLANET_TYPE_STATS) == 1  # full replacement, same as other categories

    set_game_definition(_mod("classic_empire"))  # no terrains section
    assert PLANET_TYPE_STATS["earthly"]["name"] == "Earthly"
    assert len(PLANET_TYPE_STATS) == 17


def test_homeworld_starter_buildings_survive_definition_swap():
    """Homeworld seeding reads start_level off the runtime specs — a definition
    that omits it silently spawns dead homeworlds (urban Lv0 → population 0)."""
    import json
    from pathlib import Path
    from specs import BUILDING_SPECS

    classic_json = json.loads(Path("game_definitions/classic_space.json").read_text())
    assert classic_json["buildings"]["urban_structures"].get("start_level") == 1

    for mod_id in ("classic_empire", "stellar_conquest"):
        set_game_definition(_mod(mod_id))
        starters = {k: s["start_level"] for k, s in BUILDING_SPECS.items() if s.get("start_level")}
        assert starters, f"{mod_id}: no building has start_level — homeworlds would seed empty"


if __name__ == "__main__":
    import sys
    sys.exit(pytest.main([__file__, "-q"]))
