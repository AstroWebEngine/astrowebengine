"""Wormhole semantics — what CROSSING a galaxy via a wormhole costs and does.

Orthogonal to the galaxy_network topology (which decides WHERE links are and how
far). This decides what a wormhole hop MEANS.

engine.wormhole_model:
  - "jumpgate" (default): wormholes behave like a Jump Gate — a speed bonus on a
    normal distance-based trip (the distance-based model).
  - "natural": a flat travel time regardless of distance, plus optional traverse
    damage (the flat-time wormhole that "kept scouts out").
  - "none": wormhole travel disabled.

Config:
  - wormhole_flat_travel_hours (default 12): flat time for a natural-wormhole hop.
  - wormhole_damage_percent  (default 0): fraction of EACH ship type lost when
    crossing a natural wormhole. 0 = no damage. Any value > 0 destroys at least
    one of every ship type present (the anti-scout bite); a real fleet just pays
    the percentage.
"""
import math

from auth import get_config, get_config_float


def wormhole_model(db) -> str:
    return (get_config(db, "wormhole_model", "jumpgate") or "jumpgate").strip()


def is_natural(db) -> bool:
    return wormhole_model(db) == "natural"


def flat_travel_seconds(db, game_speed: float) -> float:
    hours = get_config_float(db, "wormhole_flat_travel_hours", 12.0)
    return max(10.0, hours * 3600.0 / max(game_speed, 0.0001))


def damage_percent(db) -> float:
    return min(1.0, max(0.0, get_config_float(db, "wormhole_damage_percent", 0.0)))


def compute_losses(ship_counts: dict, pct: float) -> dict:
    """Pure: {ship_type: destroyed} for a `pct` traverse hit. ceil so any pct > 0
    costs at least one of every present ship type (anti-scout)."""
    if pct <= 0:
        return {}
    losses = {}
    for st, count in ship_counts.items():
        if count <= 0:
            continue
        lost = min(count, int(math.ceil(count * pct)))
        if lost > 0:
            losses[st] = lost
    return losses


def apply_wormhole_damage(fleet, pct: float) -> dict:
    """Destroy `pct` of each ship type in `fleet`; returns the losses dict."""
    losses = compute_losses(fleet.get_all_ship_counts(), pct)
    for st, lost in losses.items():
        fleet.set_ship_count(st, fleet.get_ship_count(st) - lost)
    return losses
