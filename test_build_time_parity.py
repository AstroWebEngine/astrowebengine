"""Build times must track the reference implementation, and a ruleset must be
able to set them at all.

Two bugs met here. The engine read economy values from module constants and
never from the active definition, so `economy.construction_bonus_base` was
inert - a ruleset could not tune its own build times. And Deep Frontier's rate
was 40 against the reference's 2500, making the opening hour roughly 6x slower
than the game it reproduces, even at game_speed 10.

Reference (retro-game ItemTimeUtils.getBuildingTime):
    seconds = 1.44 * (metal + crystal) / (1 + robotics) / 2^nanite / speed

This engine:
    seconds = 3600 * cost / construction / speed

3600 / 2500 == 1.44, so a construction rate of 2500 reproduces it.
"""
import json
from pathlib import Path

import pytest

from resources import total_cost_value

ROOT = Path(__file__).parent
DF = json.loads((ROOT / "game_definitions" / "deep_frontier.json").read_text(encoding="utf-8"))
REFERENCE_DIVISOR = 2500          # 1.44 s per resource unit
SECONDS_PER_HOUR = 3600


def _rate(defn):
    e = defn["economy"]
    return e["construction_bonus_base"] + e["construction_bonus_homeworld"]


def test_engine_reads_economy_from_the_definition_not_a_constant():
    """The regression: economy values were module constants, so rulesets were mute."""
    import inspect
    import game_logic
    src = inspect.getsource(game_logic.calc_base_stats)
    assert "econ(" in src, "calc_base_stats must resolve economy via the definition"
    assert hasattr(game_logic, "econ") and hasattr(game_logic, "fleet_cfg")


def test_fresh_base_rate_matches_the_reference():
    assert _rate(DF) == REFERENCE_DIVISOR, (
        f"a fresh base builds at {_rate(DF)} against the reference's "
        f"{REFERENCE_DIVISOR}; the opening hour will be "
        f"{REFERENCE_DIVISOR / _rate(DF):.1f}x off")


@pytest.mark.parametrize("robotics", [0, 2, 5, 10])
def test_robotics_scales_the_divisor_like_the_reference(robotics):
    """There it divides by (1 + level); here industrial adds, so per_level must be the base rate."""
    per_level = DF["buildings"]["robotics_bay"]["contributions"]["industrial"]["per_level"]
    assert _rate(DF) + per_level * robotics == REFERENCE_DIVISOR * (1 + robotics)


@pytest.mark.parametrize("key", ["metal_extractor", "crystal_extractor", "solar_array"])
def test_first_builds_match_the_reference_within_a_hair(key):
    """Metal/crystal-only buildings should land on the reference exactly."""
    b = DF["buildings"][key]
    cost = b["base_cost"]
    ours = SECONDS_PER_HOUR * total_cost_value(cost) / _rate(DF)
    ref = 1.44 * (cost.get("metal", 0) + cost.get("crystal", 0))
    assert ours == pytest.approx(ref, rel=0.02)


def test_deuterium_is_the_only_known_divergence():
    """We count deuterium toward build time; the reference counts metal+crystal.

    Deuterium-priced buildings therefore run slightly longer here. Pinning it so
    the difference stays deliberate rather than drifting.
    """
    b = DF["buildings"]["robotics_bay"]
    cost = b["base_cost"]
    assert cost.get("deuterium", 0) > 0, "fixture no longer exercises the divergence"
    ours = SECONDS_PER_HOUR * total_cost_value(cost) / _rate(DF)
    ref = 1.44 * (cost.get("metal", 0) + cost.get("crystal", 0))
    assert 1.0 < ours / ref < 1.6


def test_opening_build_is_minutes_not_hours():
    """The complaint in plain terms: the first mine must be quick."""
    b = DF["buildings"]["metal_extractor"]
    seconds = SECONDS_PER_HOUR * total_cost_value(b["base_cost"]) / _rate(DF)
    assert seconds < 300, f"first Metal Extractor takes {seconds/60:.0f}m at speed 1"
