"""
Game Definition System for the AstroWebEngine.

A game definition is a complete description of a game's rules, units, buildings,
research, and mechanics. The engine loads one game definition at startup and uses it
to drive all gameplay calculations.

The default definition ships with the engine and implements classic single-resource gameplay.
Server operators can create custom definitions for different game styles.

Game definitions can be:
- Python dicts (built-in, fast)
- JSON files (portable, shareable)
- Loaded from the database (admin panel editable)
"""

import json
import os
from copy import deepcopy
from pathlib import Path
from typing import Optional

# The active game definition — loaded at startup, read by all game systems
_active_definition = None


def get_game_definition() -> dict:
    """Get the currently active game definition."""
    global _active_definition
    if _active_definition is None:
        _active_definition = build_default_definition()
    return _active_definition


def set_game_definition(definition: dict):
    """Set the active game definition (used during startup or hot-reload).

    Also syncs the definition's content (ships/buildings/research/defenses/
    weapon_types) into the runtime spec structures so the active ruleset's roster
    actually takes effect everywhere (build, combat, catalog, admin)."""
    global _active_definition
    _active_definition = definition
    try:
        import specs
        specs.apply_definition_specs(definition or {})
    except Exception as e:
        import logging
        logging.getLogger("awe").error(f"[game_definition] runtime spec sync failed: {e}")


# ---------------------------------------------------------------------------
# Engine flag safety categories
# ---------------------------------------------------------------------------

# Flags that can be changed at any time without risk
HOTSWAP_SAFE = {
    "combat_max_rounds",       # Just affects future battles
    "defenses_destructible",   # Just affects post-combat repair logic
    "defense_repair_percent",  # Just a number used in combat
    "buildings_destructible",  # FUTURE/not-yet-consumed: mechanism not implemented
    "ships_always_destroyed",  # FUTURE/not-yet-consumed: combat always destroys ships
    "construction_queue_max",  # live: read via get_config_int in routes_bases
    "research_queue_max",      # live: read via get_config_int in routes_research
    "production_queue_max",    # live: read via get_config_int in routes_fleets
}

# Flags that require a universe wipe / fresh game to change safely.
# NOTE on consumption: the engine reads resource_model/resource_types,
# defense_model, map_topology, galaxy_network and galaxy_shape at runtime.
# combat_model is validated and carried in definitions but battle behavior is
# actually governed by combat_max_rounds (1 = simultaneous, >1 = rounds), so the
# flag is effectively descriptive. map_depth/map_levels are declared for a future
# 3-level map but NOT yet consumed (the engine always builds the 4-level map).
SETUP_ONLY = {
    "combat_model",     # descriptive; battle behavior follows combat_max_rounds
    "resource_model",    # Changing single->multi mid-game: costs become dicts, user.credits meaningless
    "defense_model",     # Changing level->count: defense.level means different things in each model
    "map_depth",         # FUTURE/not-yet-consumed: engine always builds the 4-level map
    "map_levels",        # FUTURE/not-yet-consumed: tied to map_depth
    "map_topology",      # hierarchy<->graph rewires travel + needs link generation (fresh universe)
    "galaxy_network",    # galaxy/cluster arrangement: ring/equal_distance/line/pumpkin/wormhole_only
    "galaxy_shape",      # intra-galaxy system placement: procedural_spiral (default) vs templates
    "resource_types",    # Tied to resource_model
}

# Flags safe to change but may cause balance shifts (warn but allow)
BALANCE_SENSITIVE = set()


def engine_flag_safety(flag: str) -> str:
    if flag in SETUP_ONLY:
        return "setup_only"
    if flag in BALANCE_SENSITIVE:
        return "balance_sensitive"
    return "live"


def engine_safety_metadata() -> dict:
    return {
        "setup_only": sorted(SETUP_ONLY),
        "balance_sensitive": sorted(BALANCE_SENSITIVE),
        "live": sorted(HOTSWAP_SAFE),
    }


def check_definition_safety(new_definition: dict, has_universe: bool = False) -> list:
    """Check if switching to a new game definition is safe.

    Returns a list of warnings/errors. Empty list = safe to switch.
    Items with 'blocked': True cannot be overridden.
    """
    warnings = []
    if not has_universe:
        return warnings  # No universe = fresh game, anything goes

    current = get_game_definition()
    cur_engine = current.get("engine", {})
    new_engine = new_definition.get("engine", {})

    for key in SETUP_ONLY:
        cur_val = cur_engine.get(key)
        new_val = new_engine.get(key)
        if cur_val is not None and new_val is not None and cur_val != new_val:
            warnings.append({
                "flag": key,
                "current": cur_val,
                "new": new_val,
                "blocked": True,
                "message": f"Cannot change '{key}' after universe generation "
                           f"({cur_val} -> {new_val}). Reset the game first.",
            })

    for key in BALANCE_SENSITIVE:
        cur_val = cur_engine.get(key)
        new_val = new_engine.get(key)
        if cur_val is not None and new_val is not None and cur_val != new_val:
            warnings.append({
                "flag": key,
                "current": cur_val,
                "new": new_val,
                "blocked": False,
                "message": f"Changing '{key}' ({cur_val} -> {new_val}) will significantly "
                           f"affect game balance for existing players.",
            })

    return warnings


def build_default_definition() -> dict:
    """Build the default game definition.
    This pulls from the existing specs and config_defaults modules."""
    import specs as _specs
    from specs import SHIP_SPECS, BUILDING_SPECS, RESEARCH_SPECS, DEFENSE_SPECS, WEAPON_TYPES

    def _pristine(cat, fallback):
        try:
            return _specs.pristine_specs(cat)
        except Exception:
            return dict(fallback)
    from config_defaults import (
        CONSTRUCTION_BONUS_BASE, CONSTRUCTION_BONUS_HOMEWORLD,
        BASE_ENERGY_BONUS, CAPITAL_EMPIRE_BONUS,
        DAMAGE_ALLOCATION_EXPONENT, COMBAT_LOOT_PERCENT, DEBRIS_PERCENT,
        ION_SHIELD_PASSTHROUGH, NORMAL_SHIELD_PASSTHROUGH,
        OCCUPATION_TIME_PENALTY, MIN_BUILD_TIME_SECONDS, MIN_RESEARCH_TIME_SECONDS,
        FLEET_TRAVEL_DIVISOR, BASE_FLEET_COUNT,
        FLEET_SIZE_LIMIT_MULTIPLIER,
        CONSTRUCTION_QUEUE_MAX, RESEARCH_QUEUE_MAX, PRODUCTION_QUEUE_MAX,
    )

    return {
        "meta": {
            "name": "Classic Space",
            "version": "1.0",
            "description": "Classic single-resource space strategy gameplay with "
                           "simultaneous combat and level-based defenses.",
            "author": "Engine Team",
        },

        "engine": {
            # Resource model: "single" (credits only) or "multi" (metal/crystal/deut etc.)
            "resource_model": "single",
            "resource_types": ["credits"],

            # Defense model: "level" (upgrade levels, engine default) or "count" (build multiples)
            "defense_model": "level",

            # Destructibility: what can be permanently destroyed in combat?
            "defenses_destructible": True,        # Can defenses be permanently destroyed?
            "defense_repair_percent": 0.0,        # % of destroyed defenses that auto-repair
            "buildings_destructible": False,      # Can buildings be destroyed (e.g., by missiles)?
            "ships_always_destroyed": True,       # Ships destroyed = gone forever

            # Combat model: "simultaneous" (both sides fire at once, engine default) or "rounds" (round-based)
            "combat_model": "simultaneous",
            "combat_max_rounds": 1,               # simultaneous=1, rounds-based commonly 6

            # Map depth: number of navigation levels. NOT yet consumed — the
            # engine always builds the 4-level map; 3-level is a future option.
            # 4 = galaxy > region > system > orbit (default)
            # 3 = galaxy > system > slot
            "map_depth": 4,
            "map_levels": ["galaxy", "region", "system", "orbit"],

            # Queue limits
            "construction_queue_max": CONSTRUCTION_QUEUE_MAX,
            "research_queue_max": RESEARCH_QUEUE_MAX,
            "production_queue_max": PRODUCTION_QUEUE_MAX,

            # Report categories visible in Empire > Reports sidebar
            # Each entry is an internal key matching the frontend tab ID
            "report_categories": [
                "scanners", "player", "guild", "galaxy",
                "top_scouters", "top_jump_gates", "trade",
                "wormholes", "astros",
            ],
        },

        "economy": {
            "construction_bonus_base": CONSTRUCTION_BONUS_BASE,
            "construction_bonus_homeworld": CONSTRUCTION_BONUS_HOMEWORLD,
            "base_energy_bonus": BASE_ENERGY_BONUS,
            "capital_empire_bonus": CAPITAL_EMPIRE_BONUS,
            "occupation_time_penalty": OCCUPATION_TIME_PENALTY,
            "min_build_time_seconds": MIN_BUILD_TIME_SECONDS,
            "min_research_time_seconds": MIN_RESEARCH_TIME_SECONDS,
        },

        "combat": {
            "damage_allocation_exponent": DAMAGE_ALLOCATION_EXPONENT,
            "loot_percent": COMBAT_LOOT_PERCENT,
            "debris_percent": DEBRIS_PERCENT,
        },

        "fleet": {
            "travel_divisor": FLEET_TRAVEL_DIVISOR,
            "base_fleet_count": BASE_FLEET_COUNT,
            "size_limit_multiplier": FLEET_SIZE_LIMIT_MULTIPLIER,
        },

        # Game entity specs — the full data-driven defaults. Pull from the
        # PRISTINE snapshot, not the live dicts (which a ruleset mod may have
        # synced to other content via apply_definition_specs).
        "ships": _pristine("ships", SHIP_SPECS),
        "buildings": _pristine("buildings", BUILDING_SPECS),
        "research": _pristine("research", RESEARCH_SPECS),
        "defenses": _pristine("defenses", DEFENSE_SPECS),
        "weapon_types": _pristine("weapon_types", WEAPON_TYPES),
        # Terrain/astro display names + balance. Optional in authored
        # definitions — absent means engine defaults.
        "terrains": _pristine("terrains", {}),
    }


def _deep_merge(base: dict, override: dict) -> dict:
    """Recursively merge definition fragments; child values win."""
    result = deepcopy(base or {})
    for key, value in (override or {}).items():
        if key == "extends":
            continue
        if isinstance(value, dict) and isinstance(result.get(key), dict):
            result[key] = _deep_merge(result[key], value)
        else:
            result[key] = deepcopy(value)
    return result


def _definition_root_for(path: Path) -> Path:
    default_root = (Path(__file__).resolve().parent / "game_definitions").resolve()
    try:
        resolved = path.resolve()
        if resolved == default_root or default_root in resolved.parents:
            return default_root
    except OSError:
        pass
    return path.resolve().parent


def _resolve_definition_ref(ref: str, current_dir: Path, root: Path) -> Path:
    text = str(ref or "").strip()
    if not text:
        raise ValueError("Empty game definition fragment reference")
    if os.path.isabs(text):
        candidate = Path(text).resolve()
    else:
        candidate = (current_dir / text).resolve()
        if not candidate.exists():
            candidate = (root / text).resolve()
    root = root.resolve()
    if candidate != root and root not in candidate.parents:
        raise ValueError(f"Game definition fragment escapes definition root: {ref}")
    if not candidate.exists():
        raise ValueError(f"Game definition fragment not found: {ref}")
    if candidate.suffix.lower() != ".json":
        raise ValueError(f"Game definition fragment must be JSON: {ref}")
    return candidate


def _extends_list(value) -> list:
    if not value:
        return []
    if isinstance(value, str):
        return [value]
    if isinstance(value, list):
        return value
    raise ValueError("Game definition 'extends' must be a string or list of strings")


def compile_definition(definition: dict, base_dir: str = None, root_dir: str = None, _seen=None) -> dict:
    """Resolve `extends` fragments into one complete game definition.

    Fragments are merged left-to-right, then the current definition is applied
    last. Dicts merge recursively; lists/scalars replace the inherited value.
    """
    if not isinstance(definition, dict):
        raise ValueError("Game definition must be a JSON object")

    current_dir = Path(base_dir).resolve() if base_dir else (Path(__file__).resolve().parent / "game_definitions").resolve()
    root = Path(root_dir).resolve() if root_dir else current_dir
    seen = set(_seen or set())
    merged = {}

    for ref in _extends_list(definition.get("extends")):
        child_path = _resolve_definition_ref(ref, current_dir, root)
        if child_path in seen:
            raise ValueError(f"Circular game definition extends reference: {child_path}")
        with open(child_path, "r", encoding="utf-8") as f:
            child = json.load(f)
        compiled_child = compile_definition(
            child,
            base_dir=str(child_path.parent),
            root_dir=str(root),
            _seen=seen | {child_path},
        )
        merged = _deep_merge(merged, compiled_child)

    return _deep_merge(merged, definition)


def load_definition_from_file(filepath: str, compile_extends: bool = True) -> dict:
    """Load a game definition from a JSON file, resolving fragments by default."""
    path = Path(filepath).resolve()
    with open(path, 'r', encoding='utf-8') as f:
        definition = json.load(f)
    if not compile_extends:
        return definition
    root = _definition_root_for(path)
    return compile_definition(definition, base_dir=str(path.parent), root_dir=str(root))


def save_definition_to_file(definition: dict, filepath: str):
    """Save a game definition to a JSON file."""
    with open(filepath, 'w', encoding='utf-8') as f:
        json.dump(definition, f, indent=2, ensure_ascii=False)


def export_current_definition(filepath: str):
    """Export the currently active game definition to a JSON file."""
    save_definition_to_file(get_game_definition(), filepath)


# ── Persisted active definition ───────────────────────────────────────────────
# An admin's Build-Game / import / mod activation should survive a restart
# without touching env vars. The compiled definition is written to a per-instance
# runtime file (outside game_definitions/ so it isn't listed as a selectable
# preset or committed — see .gitignore) and flagged in game_config. Startup
# resolves: AWE_GAME_DEFINITION env (multi-universe/ops override) → this persisted
# selection → built-in default.
_ACTIVE_DEFINITION_FILE = str(Path(__file__).resolve().parent / "_active_definition.json")
_ACTIVE_DEFINITION_FLAG = "active_definition"  # game_config: "persisted" | ""


def persist_active_definition(db, definition: dict):
    """Save `definition` as this instance's active ruleset so restart restores it."""
    save_definition_to_file(definition, _ACTIVE_DEFINITION_FILE)
    from auth import set_config
    set_config(db, _ACTIVE_DEFINITION_FLAG, "persisted")


def clear_persisted_definition(db):
    """Forget any persisted selection (startup falls back to env / default)."""
    from auth import set_config
    set_config(db, _ACTIVE_DEFINITION_FLAG, "")
    try:
        os.remove(_ACTIVE_DEFINITION_FILE)
    except OSError:
        pass


def restore_persisted_definition(db):
    """Activate the persisted definition if one is flagged. Returns its name or None."""
    from auth import get_config
    if (get_config(db, _ACTIVE_DEFINITION_FLAG, "") or "").strip() != "persisted":
        return None
    if not os.path.exists(_ACTIVE_DEFINITION_FILE):
        return None
    try:
        # The file is already compiled; don't re-resolve fragments.
        defn = load_definition_from_file(_ACTIVE_DEFINITION_FILE, compile_extends=False)
    except Exception:
        return None
    set_game_definition(defn)
    return defn.get("meta", {}).get("name")


def validate_definition(definition: dict) -> list:
    """Validate a game definition and return a list of errors (empty = valid)."""
    errors = []
    try:
        definition = compile_definition(definition)
    except Exception as exc:
        return [f"Compile error: {exc}"]

    # Check required top-level keys
    required_keys = ["meta", "engine", "ships", "buildings", "research", "defenses", "weapon_types"]
    for key in required_keys:
        if key not in definition:
            errors.append(f"Missing required key: {key}")

    # Check meta
    meta = definition.get("meta", {})
    if not meta.get("name"):
        errors.append("meta.name is required")

    # Check engine config
    engine = definition.get("engine", {})
    valid_resource_models = ["single", "multi"]
    if engine.get("resource_model") not in valid_resource_models:
        errors.append(f"engine.resource_model must be one of {valid_resource_models}")

    valid_defense_models = ["level", "count"]
    if engine.get("defense_model") not in valid_defense_models:
        errors.append(f"engine.defense_model must be one of {valid_defense_models}")

    valid_combat_models = ["simultaneous", "rounds"]
    if engine.get("combat_model") not in valid_combat_models:
        errors.append(f"engine.combat_model must be one of {valid_combat_models}")

    # Validate combat rounds consistency
    combat_model = engine.get("combat_model", "simultaneous")
    max_rounds = engine.get("combat_max_rounds", 1)
    if combat_model == "rounds" and (not isinstance(max_rounds, int) or max_rounds < 1):
        errors.append("engine.combat_max_rounds must be a positive integer for rounds-based combat")

    # Check ships have required fields
    ships = definition.get("ships", {})
    required_ship_fields = ["name", "cost", "attack", "armour", "shield", "weapon"]
    for key, spec in ships.items():
        for field in required_ship_fields:
            if field not in spec:
                errors.append(f"ships.{key} missing required field: {field}")

    # Check buildings have required fields
    buildings = definition.get("buildings", {})
    required_building_fields = ["name", "base_cost", "cost_mult"]
    for key, spec in buildings.items():
        for field in required_building_fields:
            if field not in spec:
                errors.append(f"buildings.{key} missing required field: {field}")

    # Check weapon types
    weapon_types = definition.get("weapon_types", {})
    for key, spec in weapon_types.items():
        if "shield_passthrough" not in spec:
            errors.append(f"weapon_types.{key} missing shield_passthrough")

    # Cross-reference: all ship weapons must exist in weapon_types
    for key, spec in ships.items():
        weapon = spec.get("weapon", "")
        if weapon and weapon not in weapon_types:
            errors.append(f"ships.{key} uses weapon '{weapon}' not defined in weapon_types")

    return errors


def list_available_definitions(definitions_dir: str = None) -> list:
    """List all available game definition JSON files."""
    if definitions_dir is None:
        definitions_dir = os.path.join(os.path.dirname(__file__), "game_definitions")
    if not os.path.exists(definitions_dir):
        return []
    result = []
    for fname in os.listdir(definitions_dir):
        if fname.endswith(".json"):
            filepath = os.path.join(definitions_dir, fname)
            try:
                defn = load_definition_from_file(filepath)
                meta = defn.get("meta", {})
                result.append({
                    "filename": fname,
                    "name": meta.get("name", fname),
                    "version": meta.get("version", "unknown"),
                    "description": meta.get("description", ""),
                })
            except (json.JSONDecodeError, IOError):
                result.append({"filename": fname, "name": fname, "error": "Invalid JSON"})
    return result
