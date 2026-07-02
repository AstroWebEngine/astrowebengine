"""
AstroWebEngine mod hook API — M3 spine (registry + context + dispatch).

Behavioral mods register handlers at named extension points the engine fires at
well-defined moments. This module is the mechanism; the engine call-sites (where
each hook fires) are wired separately. M3 is read-only: handlers OBSERVE and may
return advisory results; sanctioned mutations arrive in M4.

Two dispatch shapes:
  * observers  — every registered handler runs (fail-soft); used for on_tick,
    on_battle_resolved, on_colony_founded, …
  * override   — the first handler to return a non-None value wins; used for
    resolve_battle (a mod replacing the default resolver).

Security: handlers are arbitrary code. Loading them from mods is gated by the
operator (a default-off trust flag); see load_mod_hooks(). First-party hooks may
register directly. A throwing handler is caught and logged — one bad mod can't
take down a tick.
"""
import logging

logger = logging.getLogger("awe")

# Known hook points. Override hooks return a value that replaces engine behavior;
# observer hooks are fire-and-forget.
OBSERVER_HOOKS = {
    "on_tick",
    "on_battle_resolved",
    "on_colony_founded",
    "on_research_completed",
    "on_economy_collect",
}
OVERRIDE_HOOKS = {
    "resolve_battle",
    "compute_victory",
}
ALL_HOOKS = OBSERVER_HOOKS | OVERRIDE_HOOKS

# name -> list of {fn, order, mod_id}
_registry = {}


def _safe_copy(v):
    """Deep-copy plain data so a handler can't mutate the caller's structures;
    pass live handles (db session, ORM objects) through by reference — those are
    intentionally shared with behavioral mods and aren't deep-copyable."""
    import copy
    if isinstance(v, (dict, list, tuple, set, str, bytes, int, float, bool, type(None))):
        try:
            return copy.deepcopy(v)
        except Exception:
            return v
    return v


class HookContext:
    """Context passed to handlers (M3).

    Exposes named data plus a seeded rng and the engine logger. Plain-data values
    (e.g. the battle `report`) are deep-copied so a handler can't corrupt the
    engine's own structures. Live handles passed in `data` (a DB `session`, ORM
    objects) are shared by reference — behavioral mods act through them; that is
    the (gated) mutation surface, formalized further in M4. `stop()` halts an
    observer chain early.
    """

    def __init__(self, data: dict = None, rng=None):
        self._data = {k: _safe_copy(v) for k, v in (data or {}).items()}
        self.rng = rng
        self.log = logger
        self._stopped = False

    def get(self, key, default=None):
        return self._data.get(key, default)

    def __getitem__(self, key):
        return self._data[key]

    def keys(self):
        return self._data.keys()

    def stop(self):
        self._stopped = True

    @property
    def stopped(self):
        return self._stopped


def register(name: str, fn, order: int = 100, mod_id: str = "first_party"):
    """Register a handler for a hook point. Lower `order` runs first."""
    if name not in ALL_HOOKS:
        raise ValueError(f"unknown hook '{name}'. Known: {sorted(ALL_HOOKS)}")
    _registry.setdefault(name, []).append({"fn": fn, "order": order, "mod_id": mod_id})
    _registry[name].sort(key=lambda h: (h["order"], h["mod_id"]))


def clear(mod_id: str = None):
    """Remove all handlers, or just those from one mod (used on reload)."""
    if mod_id is None:
        _registry.clear()
        return
    for name in list(_registry):
        _registry[name] = [h for h in _registry[name] if h["mod_id"] != mod_id]


def handlers(name: str) -> list:
    return list(_registry.get(name, []))


def dispatch_observers(name: str, ctx: HookContext) -> HookContext:
    """Run every registered observer for `name`, fail-soft, in order.

    Always returns the (possibly mutated-by-design) ctx. Exceptions are caught
    and logged so one handler can't break the engine path that fired the hook.
    """
    if name not in OBSERVER_HOOKS:
        raise ValueError(f"'{name}' is not an observer hook")
    for h in _registry.get(name, []):
        if ctx.stopped:
            break
        try:
            h["fn"](ctx)
        except Exception as exc:
            logger.warning(f"[hook:{name}] mod '{h['mod_id']}' raised: {exc}")
    return ctx


def dispatch_override(name: str, ctx: HookContext):
    """Return the first non-None result from a registered override handler.

    Used where a mod may replace engine behavior (e.g. resolve_battle). If no
    handler returns a value, returns None and the caller uses its default.
    """
    if name not in OVERRIDE_HOOKS:
        raise ValueError(f"'{name}' is not an override hook")
    for h in _registry.get(name, []):
        try:
            result = h["fn"](ctx)
        except Exception as exc:
            logger.warning(f"[hook:{name}] override mod '{h['mod_id']}' raised: {exc}")
            continue
        if result is not None:
            return result
    return None


# ---------------------------------------------------------------------------
# Convenience: one-line firing from engine call-sites
# ---------------------------------------------------------------------------

def fire(name: str, data: dict = None, rng=None):
    """Build a read-only ctx and run observers, fail-soft. No-op if no handlers.

    Safe to drop into any engine path: returns None and does nothing when no mod
    has registered for `name`, and never raises into the caller.
    """
    if not _registry.get(name):
        return None
    try:
        return dispatch_observers(name, HookContext(data, rng=rng))
    except Exception as exc:
        logger.warning(f"[hook:{name}] fire error: {exc}")
        return None


def fire_override(name: str, data: dict = None, rng=None):
    """Return the first override handler's result, or None if none/empty/error."""
    if not _registry.get(name):
        return None
    try:
        return dispatch_override(name, HookContext(data, rng=rng))
    except Exception as exc:
        logger.warning(f"[hook:{name}] override fire error: {exc}")
        return None


# ---------------------------------------------------------------------------
# Loading hooks from mods (gated)
# ---------------------------------------------------------------------------

def behavioral_mods_allowed(db) -> bool:
    """Behavioral mods run arbitrary code; loading them is opt-in & off by default."""
    from auth import get_config
    raw = (get_config(db, "AWE_ALLOW_BEHAVIORAL_MODS", "false") or "").strip().lower()
    return raw in ("1", "true", "yes", "on")


def load_mod_hooks(db) -> dict:
    """Import & register hooks from enabled mods that declare a `hooks` module.

    Returns a report. Does nothing unless the operator has explicitly allowed
    behavioral mods. First-party hooks register themselves directly and are not
    affected by this gate.
    """
    report = {"loaded": [], "skipped": [], "blocked": False}
    if not behavioral_mods_allowed(db):
        report["blocked"] = True
        return report
    import importlib.util
    import os
    import mod_loader as ml
    enabled = set(ml.get_enabled_mod_ids(db))
    for mod in ml.discover_mods():
        if mod["id"] not in enabled or mod["errors"]:
            continue
        hooks_py = os.path.join(mod["dir"], "hooks", "__init__.py")
        if not os.path.isfile(hooks_py):
            continue
        try:
            spec = importlib.util.spec_from_file_location(f"awe_mod_{mod['id']}_hooks", hooks_py)
            module = importlib.util.module_from_spec(spec)
            spec.loader.exec_module(module)
            if hasattr(module, "register_hooks"):
                module.register_hooks(lambda name, fn, order=100: register(name, fn, order, mod_id=mod["id"]))
                report["loaded"].append(mod["id"])
            else:
                report["skipped"].append({"id": mod["id"], "reason": "no register_hooks()"})
        except Exception as exc:
            logger.warning(f"[hooks] mod '{mod['id']}' failed to load: {exc}")
            report["skipped"].append({"id": mod["id"], "reason": str(exc)})
    return report
