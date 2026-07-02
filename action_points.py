"""
Action-point ("Turns") economy — engine option.

A regenerating per-player pool that actions spend (the BBS / Trade-Wars / Solar
Empire "Turns" mechanic). OPT-IN: inert unless the active game definition sets
`engine.economy_actions == "action_points"`. When off, every function here is a
no-op, so action-site calls (debit_action_points) are safe to land everywhere
without affecting time-economy games.

Config lives in the active game definition so a ruleset mod (e.g. Solar Empire)
turns it on and sets costs:

    "engine": {
      "economy_actions": "action_points",
      "action_points": {
        "start": 40, "regen_per_hour": 10, "max": 250,
        "apply_to_bots": false,
        "costs": { "fleet_attack": 2, "fleet_send": 1, "colonize": 3, ... }
      }
    }

The `costs` map is also the per-action mod-override table.
"""
from datetime import datetime

from fastapi import HTTPException

from game_definition import get_game_definition

_DEFAULTS = {"start": 0.0, "regen_per_hour": 0.0, "max": 0.0, "apply_to_bots": False}


def _engine(db) -> dict:
    return get_game_definition().get("engine", {}) or {}


def ap_enabled(db) -> bool:
    """True when the active definition selects the action-point economy."""
    return _engine(db).get("economy_actions") == "action_points"


def ap_config(db) -> dict:
    cfg = dict(_DEFAULTS)
    cfg.update(_engine(db).get("action_points", {}) or {})
    return cfg


def ap_cost(db, action_key: str) -> float:
    """Cost for an action key; 0 (free) when unlisted. Negative costs are
    clamped to 0 so a bad definition can't make an action grant turns."""
    costs = ap_config(db).get("costs", {}) or {}
    try:
        return max(0.0, float(costs.get(action_key, 0) or 0))
    except (TypeError, ValueError):
        return 0.0


def _applies_to(user, db) -> bool:
    if not ap_enabled(db):
        return False
    if getattr(user, "is_bot", False) and not ap_config(db).get("apply_to_bots", False):
        return False
    return True


def accrue_action_points(user, db, now: datetime = None) -> float:
    """Lazily regenerate a player's action points up to the cap. Returns current.

    No-op (returns current) when the economy is off or the user is exempt. On the
    first ever accrual the player is seeded with the configured `start`.
    """
    if not _applies_to(user, db):
        return getattr(user, "action_points", 0.0) or 0.0
    cfg = ap_config(db)
    cap = float(cfg["max"])
    now = now or datetime.utcnow()
    if user.last_ap_accrual is None:
        # First contact — seed starting turns (never above the cap).
        user.action_points = min(cap, max(user.action_points or 0.0, float(cfg["start"])))
        user.last_ap_accrual = now
        return user.action_points
    hours = (now - user.last_ap_accrual).total_seconds() / 3600.0
    if hours > 0:
        gained = hours * float(cfg["regen_per_hour"])
        user.action_points = (user.action_points or 0.0) + gained
        user.last_ap_accrual = now
    elif hours < 0:
        # Clock skew / imported future timestamp — recover instead of stranding.
        user.last_ap_accrual = now
    # Always enforce the cap (handles a lowered max or over-cap imported data).
    user.action_points = min(cap, user.action_points or 0.0)
    return user.action_points


def can_afford_action(user, db, action_key: str) -> bool:
    if not _applies_to(user, db):
        return True
    cost = ap_cost(db, action_key)
    if cost <= 0:
        return True
    return accrue_action_points(user, db) >= cost


def debit_action_points(user, db, action_key: str) -> None:
    """Accrue, then spend `action_key`'s cost. Raises HTTP 400 if short.

    No-op when the economy is off, the user is exempt (e.g. a bot), or the action
    is free. Call AFTER validation and BEFORE the first irreversible mutation.
    """
    if not _applies_to(user, db):
        return
    cost = ap_cost(db, action_key)
    if cost <= 0:
        return
    current = accrue_action_points(user, db)
    if current < cost:
        raise HTTPException(
            400,
            f"Not enough turns: {action_key} costs {cost:g}, you have {current:.0f}.",
        )
    user.action_points = current - cost


def ap_state(user, db) -> dict:
    """Player-facing AP snapshot for the state endpoint/HUD (empty when off)."""
    if not _applies_to(user, db):
        return {"enabled": False}
    cfg = ap_config(db)
    return {
        "enabled": True,
        "current": round(accrue_action_points(user, db), 1),
        "max": float(cfg["max"]),
        "regen_per_hour": float(cfg["regen_per_hour"]),
    }
