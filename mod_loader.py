"""
AstroWebEngine mod loader — M1: content/ruleset packaging.

A *mod* is a self-contained directory under mods/<id>/ with a manifest.json and
(for ruleset/content mods) a definition.json. The active game definition is
composed as:

    base ruleset  +  enabled content mods   (child-wins _deep_merge, by load_order)

This reuses the engine's existing composition primitive (`_deep_merge`) and
validator (`validate_definition`) — mods are dynamically-discovered overlays, not
a parallel system. Behavioral mods (hooks) arrive in a later milestone; M1 is
pure data, so it executes no mod code.

Enable state lives in game_config:
  * enabled_mods       — CSV of enabled mod ids (content + ruleset)
  * active_ruleset_mod — id of the ruleset mod to use as the base (optional)
"""
import os
import json

from game_definition import _deep_merge, validate_definition, load_definition_from_file

MODS_DIR = os.path.join(os.path.dirname(os.path.abspath(__file__)), "mods")
MOD_API_VERSION = "1.0"
VALID_KINDS = ("ruleset", "content", "skin", "behavioral")
REQUIRED_MANIFEST_FIELDS = ("id", "name", "version", "kind")


# ---------------------------------------------------------------------------
# Manifest discovery & validation
# ---------------------------------------------------------------------------

def _api_compatible(required: str, current: str = MOD_API_VERSION) -> bool:
    """Major-version compatibility: a mod targeting 1.x runs on engine 1.y."""
    if not required:
        return True
    try:
        req_major = int(str(required).lstrip("^~").split(".")[0])
        cur_major = int(str(current).split(".")[0])
        return req_major == cur_major
    except (ValueError, IndexError):
        return False


def validate_manifest(manifest: dict) -> list:
    """Return a list of manifest errors (empty = valid)."""
    errors = []
    for field in REQUIRED_MANIFEST_FIELDS:
        if not manifest.get(field):
            errors.append(f"manifest missing required field: {field}")
    kind = manifest.get("kind")
    if kind and kind not in VALID_KINDS:
        errors.append(f"manifest.kind must be one of {VALID_KINDS}")
    if not _api_compatible(manifest.get("engine_api", "")):
        errors.append(
            f"engine_api {manifest.get('engine_api')!r} incompatible with engine {MOD_API_VERSION}"
        )
    if kind in ("ruleset", "content") and not manifest.get("definition"):
        errors.append(f"{kind} mod must declare a 'definition' file")
    return errors


def discover_mods() -> list:
    """Scan mods/ and return [{id, dir, manifest, errors}] sorted by load_order, id."""
    found = []
    if not os.path.isdir(MODS_DIR):
        return found
    for entry in sorted(os.listdir(MODS_DIR)):
        mod_dir = os.path.join(MODS_DIR, entry)
        manifest_path = os.path.join(mod_dir, "manifest.json")
        if not os.path.isfile(manifest_path):
            continue
        try:
            with open(manifest_path, "r", encoding="utf-8") as fh:
                manifest = json.load(fh)
        except (json.JSONDecodeError, OSError) as exc:
            found.append({"id": entry, "dir": mod_dir, "manifest": {}, "errors": [f"unreadable manifest: {exc}"]})
            continue
        manifest.setdefault("id", entry)
        found.append({
            "id": manifest["id"],
            "dir": mod_dir,
            "manifest": manifest,
            "errors": validate_manifest(manifest),
        })
    found.sort(key=lambda m: (m["manifest"].get("load_order", 100), m["id"]))
    return found


def _get_mod(mod_id: str):
    for mod in discover_mods():
        if mod["id"] == mod_id:
            return mod
    return None


def load_mod_definition(mod: dict) -> dict:
    """Load (and compile fragments of) a ruleset/content mod's definition.json."""
    rel = mod["manifest"].get("definition")
    if not rel:
        return {}
    path = os.path.join(mod["dir"], rel)
    if not os.path.abspath(path).startswith(os.path.abspath(mod["dir"])):
        raise ValueError(f"mod {mod['id']} definition escapes its directory")
    return load_definition_from_file(path)


# ---------------------------------------------------------------------------
# Enable state (game_config)
# ---------------------------------------------------------------------------

def get_enabled_mod_ids(db) -> list:
    from auth import get_config
    raw = get_config(db, "enabled_mods", "") or ""
    return [m.strip() for m in raw.split(",") if m.strip()]


def set_mod_enabled(db, mod_id: str, enabled: bool):
    from auth import set_config
    ids = get_enabled_mod_ids(db)
    if enabled and mod_id not in ids:
        ids.append(mod_id)
    elif not enabled and mod_id in ids:
        ids = [m for m in ids if m != mod_id]
    set_config(db, "enabled_mods", ",".join(ids))


def get_active_ruleset_id(db) -> str:
    from auth import get_config
    return (get_config(db, "active_ruleset_mod", "") or "").strip()


def set_active_ruleset(db, mod_id: str):
    from auth import set_config
    set_config(db, "active_ruleset_mod", mod_id or "")


# ---------------------------------------------------------------------------
# Composition
# ---------------------------------------------------------------------------

def compose_active_definition(db, fallback_base: dict) -> tuple:
    """Compose base ruleset + enabled content mods. Returns (definition, report)."""
    report = {"ruleset": None, "applied": [], "skipped": [], "conflicts": [], "errors": []}
    enabled = set(get_enabled_mod_ids(db))
    mods = {m["id"]: m for m in discover_mods()}

    # 1) base ruleset
    ruleset_id = get_active_ruleset_id(db)
    definition = fallback_base
    if ruleset_id and ruleset_id in mods and mods[ruleset_id]["manifest"].get("kind") == "ruleset":
        rmod = mods[ruleset_id]
        if rmod["errors"]:
            report["errors"].append(f"ruleset {ruleset_id}: {rmod['errors']}")
        else:
            try:
                definition = load_mod_definition(rmod)
                report["ruleset"] = ruleset_id
            except Exception as exc:
                report["errors"].append(f"ruleset {ruleset_id} failed to load: {exc}")

    # Preserve the base game's display identity — content overlays tweak rules,
    # they don't rename the game.
    base_meta_name = (definition.get("meta") or {}).get("name")

    # 2) overlay enabled content mods in (load_order, id) order
    declared_conflicts = set()
    applied_ids = []
    for mod in discover_mods():
        if mod["manifest"].get("kind") != "content":
            continue
        if mod["id"] not in enabled:
            continue
        if mod["errors"]:
            report["skipped"].append({"id": mod["id"], "reason": mod["errors"]})
            continue
        if mod["id"] in declared_conflicts:
            report["conflicts"].append(mod["id"])
            continue
        try:
            overlay = load_mod_definition(mod)
        except Exception as exc:
            report["skipped"].append({"id": mod["id"], "reason": str(exc)})
            continue
        definition = _deep_merge(definition, overlay)
        applied_ids.append(mod["id"])
        report["applied"].append(mod["id"])
        for c in mod["manifest"].get("conflicts", []):
            declared_conflicts.add(c)

    # Restore base display identity + record what's layered on.
    if applied_ids and isinstance(definition.get("meta"), dict):
        if base_meta_name:
            definition["meta"]["name"] = base_meta_name
        definition["meta"]["active_mods"] = applied_ids

    errors = validate_definition(definition)
    if errors:
        report["errors"].extend(errors)
    return definition, report


def apply_active_mods(db, fallback_base: dict):
    """Compose and install the active definition. Returns the report."""
    definition, report = compose_active_definition(db, fallback_base)
    if not report["errors"]:
        from game_definition import set_game_definition, check_definition_safety
        # Honour the setup-only guard: surface (rather than silently bypass) rule
        # changes that only take full effect on a fresh universe — consistent with the
        # Build Game import path. We warn instead of hard-blocking so an operator can
        # switch rulesets and then regenerate the universe.
        try:
            from models import Galaxy
            has_universe = db.query(Galaxy).first() is not None
        except Exception:
            has_universe = False
        report["safety"] = check_definition_safety(definition, has_universe)
        set_game_definition(definition)
    return report
