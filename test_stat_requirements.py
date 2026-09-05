"""Scale requirements: `stat_req` on a spec.

The engine could express tech prerequisites and building levels but not "this
needs an enormous power supply". A ruleset wanting that had nowhere to put it,
so graviton_theory - whose only job is unlocking the apex hull - shipped as
free in every definition that carried it, including the faithful reference.
"""
import json
from pathlib import Path

import pytest

from game_logic import unmet_stat_requirements

ROOT = Path(__file__).parent
STATS = {"energy": 1000, "energy_used": 400,      # 600 free
         "area": 95, "area_used": 82,             # 13 free
         "population": 60, "pop_used": 25,        # 35 free
         "research": 940}                          # no _used counterpart


def test_absent_requirement_is_met():
    assert unmet_stat_requirements({}, STATS) == []
    assert unmet_stat_requirements({"stat_req": {}}, STATS) == []


def test_requirement_measured_on_free_not_total():
    """600 free of 1000 total: a 700 requirement is unmet even though total clears it."""
    assert unmet_stat_requirements({"stat_req": {"energy": 500}}, STATS) == []
    unmet = unmet_stat_requirements({"stat_req": {"energy": 700}}, STATS)
    assert unmet == [("energy", 700.0, 600.0)]


def test_population_uses_its_oddly_named_counterpart():
    """Upstream spells it pop_used, not population_used."""
    assert unmet_stat_requirements({"stat_req": {"population": 30}}, STATS) == []
    assert unmet_stat_requirements({"stat_req": {"population": 40}}, STATS)


def test_rate_stats_have_no_used_counterpart():
    """research has no research_used, so it is measured raw."""
    assert unmet_stat_requirements({"stat_req": {"research": 900}}, STATS) == []
    assert unmet_stat_requirements({"stat_req": {"research": 1200}}, STATS)


def test_several_requirements_all_reported():
    unmet = unmet_stat_requirements({"stat_req": {"energy": 9999, "area": 9999}}, STATS)
    assert {u[0] for u in unmet} == {"energy", "area"}


@pytest.mark.parametrize("bad", [0, -5, None, "lots"])
def test_junk_and_zero_requirements_are_ignored(bad):
    assert unmet_stat_requirements({"stat_req": {"energy": bad}}, STATS) == []


def test_missing_stat_counts_as_zero_available():
    assert unmet_stat_requirements({"stat_req": {"nonexistent": 1}}, STATS)


def test_graviton_gates_on_power_not_price():
    """The ruleset now expresses the barrier the reference actually uses."""
    d = json.loads((ROOT / "game_definitions" / "deep_frontier.json").read_text(encoding="utf-8"))
    g = d["research"]["graviton_theory"]
    assert g["stat_req"]["energy"] > 0
    from resources import total_cost_value
    assert total_cost_value(g["base_cost"]) == 0, "the reference charges no resources for this"
    # and it must be reachable: the best plant has to be able to supply it
    best = max((b.get("contributions", {}).get("energy", {}).get("per_level", 0)
                for b in d["buildings"].values()), default=0)
    assert best > 0, "nothing produces energy, so the requirement is unreachable"
