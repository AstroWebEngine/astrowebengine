"""Player-level maths must survive per-resource costs.

calc_tech_cost multiplied a research spec's base_cost by a float. Under a
multi-resource ruleset that cost is a {resource: amount} dict, so the
arithmetic raised TypeError and took /api/player/stats and the leaderboard
down with it - a 500 on two endpoints the client calls constantly, in a
ruleset the tests otherwise fully covered.

Found by playing the game, not by the suite: nothing exercised the level
calculation against a multi-resource roster.
"""
import pytest

from resources import total_cost_value


class _Research:
    def __init__(self, tech_type, level):
        self.tech_type, self.level = tech_type, level


class _User:
    def __init__(self, research):
        self.research = research


def _calc(monkeypatch, spec):
    import game_logic
    monkeypatch.setattr(game_logic, "get_effective_research_spec", lambda db, k: spec)
    return game_logic.calc_tech_cost(_User([_Research("energy_theory", 3)]), db=None)


def test_scalar_cost_still_works(monkeypatch):
    assert _calc(monkeypatch, {"base_cost": 100, "cost_mult": 2.0}) == pytest.approx(700.0)


def test_per_resource_cost_does_not_raise(monkeypatch):
    """The regression: a dict base_cost used to raise TypeError."""
    spec = {"base_cost": {"metal": 60, "crystal": 40}, "cost_mult": 2.0}
    assert _calc(monkeypatch, spec) == pytest.approx(700.0)


def test_dict_and_equivalent_scalar_agree(monkeypatch):
    """A split cost should value the same as its total, or levels jump on a swap."""
    scalar = _calc(monkeypatch, {"base_cost": 90, "cost_mult": 1.5})
    split = _calc(monkeypatch, {"base_cost": {"metal": 50, "crystal": 30, "deuterium": 10},
                                "cost_mult": 1.5})
    assert scalar == pytest.approx(split)


def test_cost_mult_of_one_handles_dicts(monkeypatch):
    """The linear branch does its own multiplication and needed the same fix."""
    spec = {"base_cost": {"metal": 10, "crystal": 5}, "cost_mult": 1}
    assert _calc(monkeypatch, spec) == pytest.approx(45.0)


def test_shipped_multiresource_ruleset_has_dict_research_costs():
    """Guard the fixture: if Deep Frontier ever went scalar these tests go quiet."""
    import json
    from pathlib import Path
    d = json.loads((Path(__file__).parent / "game_definitions" / "deep_frontier.json")
                   .read_text(encoding="utf-8"))
    costs = [s.get("base_cost") for s in d["research"].values()]
    assert any(isinstance(c, dict) for c in costs), "no per-resource research cost to regress on"
    # graviton_theory intentionally costs no resources - its barrier is a
    # stat_req on energy - so require a positive cost only where one is charged.
    priced = [c for c in costs if c is not None and total_cost_value(c) > 0]
    assert len(priced) >= len(costs) - 1
