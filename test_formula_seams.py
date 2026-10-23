"""Cost lifecycle parity; no live server or game state needed."""
from types import SimpleNamespace

import pytest
import formulas
import game_logic as logic


def test_resource_map_and_cumulative_value():
    base = {"ore": 80, "gas": 20}
    assert formulas.level_cost(base, 1.5, 2) == {"ore": 180, "gas": 45}
    assert base == {"ore": 80, "gas": 20}
    assert formulas.invested_level_value(base, 1.5, 3) == 475
    assert formulas.invested_level_value(base, 1, 3) == 300
    assert formulas.invested_level_value(base, 1.5, 0) == 0


def test_building_quote_keeps_discount_and_time_order(monkeypatch):
    monkeypatch.setattr(logic, "get_effective_building_spec", lambda *_: {
        "base_cost": {"ore": 101, "gas": 23}, "cost_mult": 1.5})
    monkeypatch.setattr(logic, "get_commander_level_at_base", lambda *_: 2)
    monkeypatch.setattr(logic, "get_commander_bonus", lambda *_: .01)
    monkeypatch.setattr(logic, "econ", lambda _, default: default)
    cost, seconds = logic.calc_building_cost(None, "yard", 1,
        {"construction": 10}, 1, colony_id=7)
    # Time uses the unrounded discounted resource total; each debit rounds up.
    assert cost == {"ore": 149, "gas": 34}
    assert seconds == 65621


def test_research_quote_and_invested_value(monkeypatch):
    monkeypatch.setattr(logic, "get_effective_research_spec", lambda *_: {
        "base_cost": {"ore": 80, "gas": 20}, "cost_mult": 1.5})
    monkeypatch.setattr(logic, "econ", lambda _, default: default)
    assert logic.calc_research_cost(None, "drive", 2, 1, 10) == (
        {"ore": 180, "gas": 45}, 81000)
    user = SimpleNamespace(research=[SimpleNamespace(level=3, tech_type="drive")])
    assert logic.calc_tech_cost(user, None) == 475


def test_defense_models_keep_level_and_batch_prices(monkeypatch):
    import game_definition
    monkeypatch.setattr(logic, "get_effective_defense_spec", lambda *_: {
        "cost": {"ore": 80, "gas": 20}, "cost_mult": 1.5})
    monkeypatch.setattr(game_definition, "get_game_definition",
        lambda: {"engine": {"defense_model": "level"}})
    assert logic.calc_defense_cost(None, "turret", 2, 2, count=4) == (
        {"ore": 180, "gas": 45}, 563, 1)
    monkeypatch.setattr(game_definition, "get_game_definition",
        lambda: {"engine": {"defense_model": "count"}})
    assert logic.calc_defense_cost(None, "turret", 2, 2, count=4) == (
        {"ore": 320, "gas": 80}, 1000, 4)


def test_refund_uses_removed_levels_and_current_curve(monkeypatch):
    monkeypatch.setattr(logic, "get_effective_building_spec", lambda *_: {
        "base_cost": {"ore": 80, "gas": 20}, "cost_mult": 1.5})
    assert logic.structure_refund_value(None, "building", "yard", 3, 1) == pytest.approx(
        375 * logic.STRUCTURE_DOWNGRADE_REFUND_PERCENT)
    assert logic.structure_refund_value(None, "building", "yard", 1, 1) == 0
