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


def test_rapid_fire_targets_all_resolve(compiled):
    """A rapid-fire key naming a unit that doesn't exist is silently dead weight."""
    known = set(compiled["ships"]) | set(compiled["defenses"])
    tables = {k: v["rapid_fire"] for k, v in compiled["ships"].items() if v.get("rapid_fire")}
    assert tables, "the ruleset declares round combat but no counters"
    for hull, table in tables.items():
        unknown = set(table) - known
        assert not unknown, f"{hull} rapid-fires at nonexistent {unknown}"
        assert all(int(n) > 1 for n in table.values()), f"{hull} has a no-op entry"


def test_shield_bouncing_is_on(compiled):
    assert compiled["engine"]["shield_bounce_threshold"] == pytest.approx(0.01)


def test_the_cheap_swarm_cannot_hurt_the_apex_hull(compiled):
    """With bouncing on, the top hull's shields put it out of a swarm's reach."""
    import combat
    ships = compiled["ships"]
    threshold = compiled["engine"]["shield_bounce_threshold"]
    apex = max(ships.values(), key=lambda s: s.get("shield", 0))
    swarm = ships["interceptor"]
    assert combat._single_attack_damage(
        swarm["attack"], swarm["weapon"], apex["shield"],
        bounce_threshold=threshold) == 0.0


def test_energy_is_actually_consumed(compiled):
    """A ruleset that ships power plants must have something drawing on them.

    energy_req defaulted to 0 on every building, so Solar Arrays and Fusion
    Plants produced energy nothing could spend - the mechanic existed on the
    generation side only. game_logic sums energy_req * level for the used figure.
    """
    buildings = compiled["buildings"]
    producers = [k for k, v in buildings.items()
                 if "energy" in (v.get("contributions") or {})]
    consumers = [k for k, v in buildings.items() if v.get("energy_req", 0) > 0]
    assert producers, "no building produces energy"
    assert consumers, "energy is produced but nothing consumes it - the plants are decorative"


def test_energy_budget_is_satisfiable(compiled):
    """Producers must be able to outrun consumers, or the economy cannot start."""
    buildings = compiled["buildings"]
    per_level_out = max(
        (v.get("contributions", {}).get("energy", {}).get("per_level", 0) for v in buildings.values()),
        default=0)
    per_level_in = max((v.get("energy_req", 0) for v in buildings.values()), default=0)
    assert per_level_out >= per_level_in, (
        f"the best power plant makes {per_level_out}/level but the hungriest building "
        f"wants {per_level_in}/level, so energy can never keep up")
