"""Game-definition and mod operations shared by the admin routes and the MCP server.

Anything that changes the running ruleset goes through here, so the admin UI and
an AI assistant hit the same compile -> validate -> safety gate.
"""
import os

from game_definition import (
    get_game_definition, set_game_definition, compile_definition, validate_definition,
    check_definition_safety, engine_safety_metadata, list_available_definitions,
    load_definition_from_file, persist_active_definition, persist_mod_base, load_mod_base,
)

DEFINITIONS_DIR = os.path.join(os.path.dirname(os.path.abspath(__file__)), "game_definitions")
_ROSTER_SECTIONS = ("ships", "buildings", "research", "defenses")


class DefinitionRejected(Exception):
    def __init__(self, message, errors=None, blocked=None):
        super().__init__(message)
        self.message = message
        self.errors = list(errors or [])
        self.blocked = list(blocked or [])


def has_universe(db) -> bool:
    from models import Galaxy
    return db.query(Galaxy).first() is not None


def _compile(definition):
    try:
        return compile_definition(definition)
    except Exception as exc:
        raise DefinitionRejected(f"Compile error: {exc}", errors=[f"Compile error: {exc}"])


def check_definition(definition: dict, db) -> dict:
    compiled = _compile(definition)
    errors = validate_definition(compiled)
    safety = check_definition_safety(compiled, has_universe(db))
    return {
        "ok": len(errors) == 0,
        "definition": compiled,
        "errors": errors,
        "warnings": [w["message"] for w in safety if not w.get("blocked")],
        "blocked": [w["message"] for w in safety if w.get("blocked")],
    }


def _roster(defn: dict) -> dict:
    return {s: sorted((defn.get(s) or {}).keys()) for s in _ROSTER_SECTIONS}


def apply_definition(definition: dict, db, user, source: str, actor_label=None) -> dict:
    from auth import log_event
    from catalog_sync import invalidate_all_online

    compiled = _compile(definition)
    errors = validate_definition(compiled)
    if errors:
        raise DefinitionRejected(f"Invalid definition: {'; '.join(errors)}", errors=errors)

    safety = check_definition_safety(compiled, has_universe(db))
    blocked = [w["message"] for w in safety if w.get("blocked")]
    warnings = [w["message"] for w in safety if not w.get("blocked")]
    if blocked:
        raise DefinitionRejected(
            "Cannot switch definition — blocked changes: " + "; ".join(blocked), blocked=blocked)

    roster_changed = _roster(get_game_definition()) != _roster(compiled)
    set_game_definition(compiled)
    persist_active_definition(db, compiled)  # survive restart, no env var
    persist_mod_base(compiled)  # mods compose onto this, so disabling one removes it
    invalidate_all_online(["specs"], "game_definition_change")
    name = compiled.get("meta", {}).get("name", "unknown")
    via = f" (via AI token '{actor_label}')" if actor_label else ""
    log_event(db, user.id, f"game_definition_{source}", f"{source.title()} game definition: {name}{via}")

    result = {"ok": True, "name": name, "roster_changed": roster_changed}
    if warnings:
        result["warnings"] = warnings
    return result


def list_building_blocks() -> dict:
    fragments = []
    fragments_dir = os.path.join(DEFINITIONS_DIR, "fragments")
    if os.path.exists(fragments_dir):
        for root, _dirs, files in os.walk(fragments_dir):
            for fname in files:
                if not fname.endswith(".json"):
                    continue
                full = os.path.join(root, fname)
                rel = os.path.relpath(full, DEFINITIONS_DIR)
                try:
                    meta = load_definition_from_file(full, compile_extends=False).get("meta", {})
                except Exception:
                    meta = {}
                fragments.append({
                    "filename": rel,
                    "name": meta.get("name", fname),
                    "description": meta.get("description", ""),
                    "component_type": meta.get("component_type", "fragment"),
                })
    return {
        "definitions": list_available_definitions(),
        "fragments": sorted(fragments, key=lambda x: (x["component_type"], x["filename"])),
        "safety": engine_safety_metadata(),
    }


def list_mods(db) -> dict:
    import mod_loader as ml
    enabled = set(ml.get_enabled_mod_ids(db))
    active_ruleset = ml.get_active_ruleset_id(db)
    mods = []
    for m in ml.discover_mods():
        man = m["manifest"]
        mods.append({
            "id": m["id"], "name": man.get("name", m["id"]),
            "version": man.get("version", ""), "author": man.get("author", ""),
            "kind": man.get("kind", ""), "description": man.get("description", ""),
            "valid": not m["errors"], "errors": m["errors"],
            "enabled": m["id"] in enabled,
            "active_ruleset": m["id"] == active_ruleset,
        })
    return {"mods": mods, "active_ruleset": active_ruleset, "enabled": sorted(enabled)}


def _mod_base() -> dict:
    """What enabled mods are composed onto: the recorded base ruleset, else (no base was
    ever recorded on this server) the live definition."""
    base = load_mod_base()
    return base if base is not None else get_game_definition()


def apply_mods(db) -> dict:
    import mod_loader as ml
    report = ml.apply_active_mods(db, _mod_base())
    if not report["errors"]:
        persist_active_definition(db, get_game_definition())  # survive restart
    return {"success": not report["errors"], "report": report}


_NO_MOD_BASE = ("Can't cleanly remove a mod on this server yet: re-activate the base ruleset "
                "(Game Definitions tab or activate_definition), then apply mods again.")


def _apply_mods_strict(db) -> dict:
    """Like apply_mods, but a setup-only change is blocked (as for activate), not warned."""
    import mod_loader as ml
    composed, report = ml.compose_active_definition(db, _mod_base())
    if report["errors"]:
        raise DefinitionRejected("Mods did not compose: " + "; ".join(report["errors"]),
                                 errors=report["errors"])
    safety = check_definition_safety(composed, has_universe(db))
    blocked = [w["message"] for w in safety if w.get("blocked")]
    if blocked:
        raise DefinitionRejected("Cannot apply mod - blocked changes: " + "; ".join(blocked),
                                 blocked=blocked)
    report["safety"] = safety
    set_game_definition(composed)
    persist_active_definition(db, composed)  # survive restart
    return {"success": True, "report": report}


def set_mod_enabled_and_apply(db, mod_id: str, enabled: bool, strict: bool = False) -> dict:
    """Toggle a mod and recompose. strict=True (the AI assistant) only allows content mods
    and refuses setup-only changes on a running universe instead of warning."""
    import mod_loader as ml
    mod_id = str(mod_id or "").strip()
    mod = ml._get_mod(mod_id) if mod_id else None
    if not mod:
        raise DefinitionRejected("Mod not found")
    if strict and mod["manifest"].get("kind") != "content":
        raise DefinitionRejected("Only content mods can be toggled by the AI assistant")
    enabled = bool(enabled)
    if (not enabled and load_mod_base() is None
            and (get_game_definition().get("meta") or {}).get("active_mods")):
        # Without a recorded base the live definition already contains the mod's overlay,
        # so recomposing onto it would leave the mod's rules in place.
        raise DefinitionRejected(_NO_MOD_BASE)
    was_enabled = mod_id in ml.get_enabled_mod_ids(db)
    ml.set_mod_enabled(db, mod_id, enabled)
    db.commit()

    def restore_flag():  # don't leave a flag that didn't apply
        ml.set_mod_enabled(db, mod_id, was_enabled)
        db.commit()

    if strict:
        try:
            result = _apply_mods_strict(db)
        except DefinitionRejected:
            restore_flag()
            raise
    else:
        result = apply_mods(db)
        if not result["success"]:
            restore_flag()
    result["enabled"] = ml.get_enabled_mod_ids(db)
    return result
