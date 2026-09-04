"""Deep Frontier: multi-resource industry and round combat on a hierarchical map.

The ruleset is a deliberate cross of two axes the engine treats independently,
so these tests pin the combination rather than any single flag: it must keep
the multi-resource/round-combat side while running the deeper map with varied
worlds. The uniform-world flags are the easy thing to reintroduce by accident,
since the ruleset it was derived from sets all three.
"""
import io
import json
from pathlib import Path

import pytest

import game_definition as gd
import specs

DEFINITION = Path(__file__).parent / "game_definitions" / "deep_frontier.json"


@pytest.fixture(scope="module")
def compiled():
    raw = json.load(io.open(DEFINITION, encoding="utf-8"))
    return gd.compile_definition(raw, base_dir=str(DEFINITION.parent))


def test_definition_compiles_and_validates(compiled):
    assert gd.validate_definition(compiled) in (None, [], {})


def test_multi_resource_economy(compiled):
    engine = compiled["engine"]
    assert engine["resource_model"] == "multi"
    assert engine["resource_types"] == ["metal", "crystal", "deuterium"]


def test_round_based_combat_with_unit_defenses(compiled):
    engine = compiled["engine"]
    assert engine["combat_model"] == "rounds"
    assert engine["combat_max_rounds"] == 6
    assert engine["defense_model"] == "count"
    assert engine["defense_repair_percent"] == pytest.approx(0.7)


def test_hierarchical_map(compiled):
    engine = compiled["engine"]
    assert engine["map_depth"] == 4
    assert engine["map_levels"] == ["galaxy", "region", "system", "orbit"]


def test_worlds_are_varied_not_uniform(compiled):
    """The point of the deeper map is that where you settle matters.

    universe.py only builds identical slots when world_model == "uniform", so
    the flag must be absent, and the 2-terrain override must not come along
    with it or every planet ends up mining the same thing.
    """
    engine = compiled["engine"]
    assert engine.get("world_model") != "uniform"
    for flag in ("uniform_positions", "uniform_terrain"):
        assert flag not in engine, f"{flag} would pin every world to one profile"
    assert not compiled.get("terrains"), "terrain override would mask the engine's varied set"


def test_varied_terrains_differentiate_the_multi_resource_economy(compiled):
    """A metal/crystal economy is only interesting if terrains yield differently."""
    terrains = specs.PLANET_TYPE_STATS
    assert len(terrains) > 2
    yields = {(t.get("metal"), t.get("crystal")) for t in terrains.values()}
    assert len(yields) > 1, "every terrain yields the same, so settling choice is moot"
    for key in ("metal", "crystal"):
        assert all(key in t for t in terrains.values()), f"{key} missing from a terrain"


def test_moon_formation_survives_the_map_swap(compiled):
    engine = compiled["engine"]
    assert engine["moon_formation"] is True
    assert engine["moon_destruction"] is True
    assert engine["moon_terrain"] in specs.PLANET_TYPE_STATS


def test_content_is_present_and_named(compiled):
    for section in ("ships", "buildings", "research", "defenses"):
        items = compiled.get(section) or {}
        assert items, f"{section} is empty"
        for key, spec in items.items():
            name = (spec.get("name") or "").strip()
            assert name, f"{section}.{key} has no name"
            assert not name[-1].isdigit() or not name[:-1].strip().endswith(
                ("Ship", "Building", "Defense", "Tech")
            ), f"{section}.{key} still has a placeholder name: {name!r}"
