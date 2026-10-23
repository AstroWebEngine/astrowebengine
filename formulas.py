"""Pure formula seams shared by quotes, charges and value calculations.

This module preserves the existing cost curve. It does not evaluate creator
expressions or load addons; those require a separately validated contract.
Costs remain scalar or resource maps, and rounding stays with the caller.
"""
from resources import scale_cost, total_cost_value


def level_cost(base_cost, cost_mult, current_level):
    """Unrounded price to advance from current_level to the next level."""
    return scale_cost(base_cost, cost_mult ** current_level)


def invested_level_value(base_cost, cost_mult, levels):
    """Raw value of all purchased levels under the current geometric curve.

    Preserve the closed form for today's curve, including its floating-point
    behavior. Creator curves must supply a matching cumulative-value contract
    before they can replace this curve.
    """
    base = total_cost_value(base_cost)
    if cost_mult == 1:
        return base * levels
    return base * (cost_mult ** levels - 1) / (cost_mult - 1)
