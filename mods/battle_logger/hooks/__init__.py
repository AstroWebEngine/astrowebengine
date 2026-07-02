"""
Battle Logger — example behavioral mod for AstroWebEngine.

Registers a read-only on_battle_resolved observer that logs a one-line summary
of every battle. This is the reference for how a behavioral mod plugs into the
M3 hook API: expose `register_hooks(register)` and call `register(hook_name, fn)`.

The handler receives a read-only HookContext; it only reads, never mutates.
"""
import logging

logger = logging.getLogger("awe")


def _on_battle_resolved(ctx):
    report = ctx.get("report") or {}
    attacker = ctx.get("attacker_user")
    defender = ctx.get("defender_user")
    atk = getattr(attacker, "username", "?")
    dfn = getattr(defender, "username", "?")
    result = report.get("result", "?")
    debris = report.get("debris", 0)
    loot = report.get("combat_loot", 0)
    logger.info(f"[mod:battle_logger] {atk} vs {dfn} -> {result} (debris {debris}, loot {loot})")


def register_hooks(register):
    """Entry point the engine calls to wire this mod's hooks."""
    register("on_battle_resolved", _on_battle_resolved)
