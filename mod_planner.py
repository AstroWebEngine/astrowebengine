"""Preview, then apply, a change to the mod selection — one path for the admin
panel and the AI assistant.

plan() composes a proposed selection (mods to enable/disable, optionally a new
base ruleset) without saving anything, and reports errors, safety warnings,
blocked changes and a readable summary of what would change. apply() recomputes
the plan, refuses it if anything moved since the preview (selection, ruleset,
active definition, installed mods), and otherwise saves the selection and
activates the result together — or changes nothing.

strict=True is the AI assistant's mode: content mods only, no ruleset switch,
and setup-only changes on a running universe are refused instead of warned.
"""
import hashlib
import json

import mod_loader as ml
from game_definition import (check_definition_safety, get_game_definition, load_mod_base,
                             persist_active_definition, set_game_definition)

_UNCHANGED = object()
_ROSTER = ("ships", "buildings", "defenses", "research")
_NO_MOD_BASE = ("Can't cleanly remove a mod on this server yet: re-activate the base ruleset "
                "(Game Definitions tab or activate_definition), then apply mods again.")


class PlanRejected(Exception):
    def __init__(self, message, plan=None):
        super().__init__(message)
        self.message = message
        self.plan = plan


def has_universe(db) -> bool:
    from models import Galaxy
    return db.query(Galaxy).first() is not None


def _mod_base() -> dict:
    base = load_mod_base()
    return base if base is not None else get_game_definition()


def summarize_changes(old: dict, new: dict) -> dict:
    """What a player or operator would notice: roster entries added/removed and
    engine settings that change."""
    out = {}
    for section in _ROSTER:
        a, b = set(old.get(section) or {}), set(new.get(section) or {})
        if a != b:
            out[section] = {"added": sorted(b - a), "removed": sorted(a - b)}
    old_e, new_e = old.get("engine") or {}, new.get("engine") or {}
    flags = {k: {"old": old_e.get(k), "new": new_e.get(k)}
             for k in sorted(set(old_e) | set(new_e)) if old_e.get(k) != new_e.get(k)}
    if flags:
        out["engine"] = flags
    old_name, new_name = (old.get("meta") or {}).get("name"), (new.get("meta") or {}).get("name")
    if old_name != new_name:
        out["name"] = {"old": old_name, "new": new_name}
    return out


def _fingerprint(selection: dict, mods: dict, current: dict, composed: dict) -> str:
    versions = {m: (mods[m]["manifest"].get("version"), mods[m]["errors"] == []) for m in mods}
    blob = json.dumps({"sel": selection, "mods": versions,
                       "current": current, "composed": composed},
                      sort_keys=True, default=str)
    return hashlib.sha256(blob.encode()).hexdigest()[:16]


def _compute(db, enable=(), disable=(), ruleset=_UNCHANGED, strict=False):
    """Returns (public plan dict, composed definition)."""
    current_enabled = ml.get_enabled_mod_ids(db)
    current_ruleset = ml.get_active_ruleset_id(db)
    enable, disable = [str(m).strip() for m in enable], [str(m).strip() for m in disable]
    target_enabled = [m for m in current_enabled if m not in disable]
    target_enabled += [m for m in enable if m not in target_enabled]
    target_ruleset = current_ruleset if ruleset is _UNCHANGED else (ruleset or "")

    mods = {m["id"]: m for m in ml.discover_mods()}
    errors, warnings, blocked = [], [], []
    for m in enable + disable:
        if m not in mods:
            errors.append(f"{m}: no such mod is installed")
    if target_ruleset and mods.get(target_ruleset, {}).get("manifest", {}).get("kind") != "ruleset":
        errors.append(f"{target_ruleset}: not an installed ruleset mod")
    if strict:
        for m in enable + disable:
            if m in mods and mods[m]["manifest"].get("kind") != "content":
                errors.append(f"Only content mods can be toggled by the AI assistant ({m} is not one)")
        if target_ruleset != current_ruleset:
            errors.append("the AI assistant can't switch the base ruleset")
    removing = set(current_enabled) - set(target_enabled)
    if (removing and load_mod_base() is None
            and (get_game_definition().get("meta") or {}).get("active_mods")):
        errors.append(_NO_MOD_BASE)

    current = get_game_definition()
    composed, report = ml.compose_active_definition(
        db, _mod_base(), enabled=target_enabled, ruleset_id=target_ruleset)
    errors += report["errors"]
    safety = [] if report["errors"] else check_definition_safety(composed, has_universe(db))
    for w in safety:
        (blocked if w.get("blocked") else warnings).append(w["message"])
    ok = not errors and not (strict and blocked)
    selection = {"enabled": target_enabled, "ruleset": target_ruleset}
    plan = {
        "plan_id": _fingerprint(selection, mods, current, composed),
        "ok": ok,
        "errors": errors,
        "warnings": warnings,
        "blocked": blocked,          # strict: refused; admin: warned, operator decides
        "selection": selection,
        "applied": report["applied"],
        "safety": safety,            # raw {flag, current, new, blocked, message} entries
        "changes": summarize_changes(current, composed) if not report["errors"] else {},
    }
    return plan, composed


def plan(db, enable=(), disable=(), ruleset=_UNCHANGED, strict=False) -> dict:
    """Preview a selection change. Saves nothing."""
    return _compute(db, enable, disable, ruleset, strict)[0]


def apply(db, plan_id: str, enable=(), disable=(), ruleset=_UNCHANGED, strict=False,
          user=None, actor_label=None) -> dict:
    """Apply a previewed plan: same arguments as plan(), plus its plan_id."""
    fresh, composed = _compute(db, enable, disable, ruleset, strict)
    if fresh["plan_id"] != plan_id:
        raise PlanRejected("The game or the installed mods changed since this preview; "
                           "preview again before applying.", fresh)
    if not fresh["ok"]:
        raise PlanRejected("This change can't be applied: " + "; ".join(
            fresh["errors"] or fresh["blocked"]), fresh)

    from auth import get_config, set_config
    saved = {k: get_config(db, k, "") or "" for k in ("enabled_mods", "active_ruleset_mod")}
    previous = get_game_definition()
    try:
        set_config(db, "enabled_mods", ",".join(fresh["selection"]["enabled"]))
        set_config(db, "active_ruleset_mod", fresh["selection"]["ruleset"])
        set_game_definition(composed)
        persist_active_definition(db, composed)   # survives restart; tells other workers
    except Exception:
        for k, v in saved.items():
            set_config(db, k, v)
        set_game_definition(previous)
        raise
    if user is not None:
        from auth import log_event
        via = f" via AI token '{actor_label}'" if actor_label else ""
        log_event(db, user.id, "mods_applied",
                  f"Mods: {', '.join(fresh['applied']) or 'none'}"
                  f"{' on ' + fresh['selection']['ruleset'] if fresh['selection']['ruleset'] else ''}{via}")
    try:
        from catalog_sync import invalidate_all_online
        invalidate_all_online(["specs"], "mods_applied")
    except Exception:
        pass
    return {**fresh, "ok": True}
