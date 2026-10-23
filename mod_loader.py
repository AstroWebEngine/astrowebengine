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
import re
import json
from pathlib import Path

from packaging.specifiers import SpecifierSet, InvalidSpecifier
from packaging.version import Version, InvalidVersion

from game_definition import _deep_merge, validate_definition, load_definition_from_file

MODS_DIR = os.path.join(os.path.dirname(os.path.abspath(__file__)), "mods")
MOD_API_VERSION = "1.0"
VALID_KINDS = ("ruleset", "content", "skin", "behavioral")
REQUIRED_MANIFEST_FIELDS = ("id", "name", "version", "kind")


# ---------------------------------------------------------------------------
# Manifest discovery & validation
# ---------------------------------------------------------------------------

_BARE_VERSION = re.compile(r"\d+(\.\d+)*")


def version_range(text) -> SpecifierSet:
    """Parse a version requirement into a packaging SpecifierSet.

    Accepts standard specifiers (">=1.2,<2"), npm-style shorthands ("^1.2" =
    >=1.2,<2; "~1.2" = >=1.2,<1.3) and a bare version ("1.2" = this major
    version, at least 1.2). Empty means any version. Raises ValueError.
    """
    t = str(text or "").strip()
    if not t:
        return SpecifierSet()
    try:
        if t[0] == "^":
            v = Version(t[1:])
            return SpecifierSet(f">={v},<{v.major + 1}")
        if t[0] == "~" and not t.startswith("~="):
            v = Version(t[1:])
            return SpecifierSet(f">={v},<{v.major}.{v.minor + 1}")
        if _BARE_VERSION.fullmatch(t):
            v = Version(t)
            return SpecifierSet(f">={v},<{v.major + 1}")
        return SpecifierSet(t)
    except (InvalidVersion, InvalidSpecifier) as exc:
        raise ValueError(f"invalid version requirement {text!r}") from exc


def _api_compatible(required: str, current: str = MOD_API_VERSION) -> bool:
    """True if engine API `current` satisfies the mod's `engine_api` requirement."""
    try:
        return Version(current) in version_range(required)
    except ValueError:
        return False


def _requirements(manifest: dict) -> list:
    """Normalized `requires`: [(mod_id, SpecifierSet, text)]. Entries are a mod id
    string or {"id": ..., "version": ...}. Raises ValueError on a malformed entry."""
    raw = manifest.get("requires", [])
    if raw in (None, ""):
        return []
    if not isinstance(raw, list):
        raise ValueError("'requires' must be a list")
    out = []
    for entry in raw:
        if isinstance(entry, str) and entry.strip():
            out.append((entry.strip(), SpecifierSet(), ""))
        elif isinstance(entry, dict) and isinstance(entry.get("id"), str) and entry["id"].strip():
            text = str(entry.get("version") or "")
            out.append((entry["id"].strip(), version_range(text), text))
        else:
            raise ValueError(f"'requires' entry must be a mod id or {{\"id\", \"version\"}}: {entry!r}")
    return out


def _conflicts(manifest: dict) -> set:
    raw = manifest.get("conflicts", []) or []
    return {c.strip() for c in raw if isinstance(c, str) and c.strip()} if isinstance(raw, list) else set()


def validate_manifest(manifest: dict) -> list:
    """Return a list of manifest errors (empty = valid)."""
    errors = []
    for field in REQUIRED_MANIFEST_FIELDS:
        if not manifest.get(field):
            errors.append(f"manifest missing required field: {field}")
    kind = manifest.get("kind")
    if kind and kind not in VALID_KINDS:
        errors.append(f"manifest.kind must be one of {VALID_KINDS}")
    if manifest.get("version"):
        try:
            Version(str(manifest["version"]))
        except InvalidVersion:
            errors.append(f"manifest.version {manifest['version']!r} is not a version number (e.g. 1.0.2)")
    try:
        version_range(manifest.get("engine_api", ""))
        if not _api_compatible(manifest.get("engine_api", "")):
            errors.append(
                f"engine_api {manifest.get('engine_api')!r} incompatible with engine {MOD_API_VERSION}")
    except ValueError as exc:
        errors.append(f"engine_api: {exc}")
    try:
        _requirements(manifest)
    except ValueError as exc:
        errors.append(str(exc))
    if not isinstance(manifest.get("conflicts", []) or [], list):
        errors.append("'conflicts' must be a list of mod ids")
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
    counts = {}
    for m in found:
        counts[m["id"]] = counts.get(m["id"], 0) + 1
    for m in found:
        if counts[m["id"]] > 1:
            m["errors"].append(f"duplicate mod id {m['id']!r}: {counts[m['id']]} folders claim it")
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
    mod_dir = Path(mod["dir"]).resolve()
    path = (mod_dir / rel).resolve()   # resolves .. and symlinks before the check
    if mod_dir not in path.parents:
        raise ValueError(f"mod {mod['id']} definition escapes its directory: {rel}")
    return load_definition_from_file(str(path))


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

def _check_selection(mods: dict, selected: list) -> list:
    """Errors for the selected mods: their own manifest problems, unmet or
    disabled requirements, version mismatches, and conflicts (either side)."""
    errors = []
    chosen = set(selected)
    for mid in selected:
        mod = mods[mid]
        if mod["errors"]:
            errors.append(f"{mid}: " + "; ".join(mod["errors"]))
            continue
        for req_id, spec, text in _requirements(mod["manifest"]):
            dep = mods.get(req_id)
            if dep is None:
                errors.append(f"{mid} requires {req_id}, which is not installed")
            elif req_id not in chosen:
                errors.append(f"{mid} requires {req_id}, which is installed but not enabled")
            else:
                try:
                    ok = Version(str(dep["manifest"].get("version", "0"))) in spec
                except InvalidVersion:
                    ok = False
                if not ok:
                    errors.append(f"{mid} requires {req_id} {text}; installed version is "
                                  f"{dep['manifest'].get('version')}")
    seen = set()
    for a in selected:
        for b in selected:
            if a >= b or (a, b) in seen:
                continue
            by = [x for x, y in ((a, b), (b, a)) if y in _conflicts(mods[x]["manifest"])]
            if by:
                seen.add((a, b))
                errors.append(f"{a} and {b} conflict (declared by {', '.join(by)}); enable only one")
    return errors


def _dependency_order(mods: dict, ids: list) -> tuple:
    """Order `ids` so each mod comes after the mods it requires (among `ids`),
    ties broken by (load_order, id). Returns (ordered, error_or_None)."""
    key = lambda m: (mods[m]["manifest"].get("load_order", 100), m)
    deps = {m: [r for r, _, _ in _requirements(mods[m]["manifest"]) if r in ids] for m in ids}
    ordered, state = [], {}   # state: 1 = visiting, 2 = done

    def visit(m, path):
        if state.get(m) == 2:
            return None
        if state.get(m) == 1:
            cycle = path[path.index(m):] + [m]
            return "dependency cycle: " + " -> ".join(cycle)
        state[m] = 1
        for d in sorted(deps[m], key=key):
            err = visit(d, path + [m])
            if err:
                return err
        state[m] = 2
        ordered.append(m)
        return None

    for m in sorted(ids, key=key):
        err = visit(m, [])
        if err:
            return [], err
    return ordered, None


def compose_active_definition(db, fallback_base: dict, enabled=None, ruleset_id=None) -> tuple:
    """Compose base ruleset + enabled content mods. Returns (definition, report).

    `enabled` / `ruleset_id` override the saved selection (mod_planner previews a
    selection before saving it); None means "use what's saved".

    All or nothing: any problem with the selection (an enabled mod that is
    invalid or fails to load, a missing/disabled/wrong-version requirement, a
    conflict, a dependency cycle) is reported in `errors` and no overlay is
    applied, so a failed plan never half-changes the game.
    """
    report = {"ruleset": None, "applied": [], "skipped": [], "conflicts": [], "errors": []}
    enabled = list(get_enabled_mod_ids(db) if enabled is None else enabled)
    mods = {}
    for m in discover_mods():
        mods.setdefault(m["id"], m)   # duplicates already carry an error

    # 1) base ruleset
    ruleset_id = get_active_ruleset_id(db) if ruleset_id is None else ruleset_id
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

    # 2) check the whole selection before touching the definition
    missing = [m for m in enabled if m not in mods]
    for m in missing:
        report["errors"].append(f"{m} is enabled but not installed")
    selected = [m for m in enabled if m in mods]
    if report["ruleset"] and report["ruleset"] not in selected:
        selected.append(report["ruleset"])
    report["errors"].extend(_check_selection(mods, selected))

    content = [m for m in selected if mods[m]["manifest"].get("kind") == "content"]
    order, cycle = _dependency_order(mods, content)
    if cycle:
        report["errors"].append(cycle)

    overlays = []
    if not report["errors"]:
        for mid in order:
            try:
                overlays.append((mid, load_mod_definition(mods[mid])))
            except Exception as exc:
                report["errors"].append(f"{mid} failed to load: {exc}")
    if report["errors"]:
        return definition, report

    # 3) overlay, dependencies first
    for mid, overlay in overlays:
        definition = _deep_merge(definition, overlay)
        report["applied"].append(mid)

    # Restore base display identity + record what's layered on.
    if report["applied"] and isinstance(definition.get("meta"), dict):
        if base_meta_name:
            definition["meta"]["name"] = base_meta_name
        definition["meta"]["active_mods"] = list(report["applied"])

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
