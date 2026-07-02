"""Client catalog routes.

The catalog is the frontend's normalized lookup table for reference-coded game
objects. Gameplay payloads can carry compact keys such as ship/building/research
IDs, while the frontend resolves display names and current admin overrides here.
"""
from fastapi import Depends
from sqlalchemy.orm import Session

from auth import (
    get_all_ship_specs, get_all_defense_specs, get_all_building_specs,
    get_all_research_specs, get_all_astro_specs, is_ship_disabled,
    is_defense_disabled, is_building_disabled, is_research_disabled,
    is_astro_disabled, get_config, get_db,
)
from game_definition import get_game_definition
from specs import GOODS_SPEC, WEAPON_TYPES, COMMANDER_SKILL_SPECS


def _catalog_section(db: Session, specs: dict, disabled_fn, include_disabled: bool):
    result = {}
    for key, spec in specs.items():
        disabled = bool(disabled_fn(db, key))
        if disabled and not include_disabled:
            continue
        item = dict(spec or {})
        item["key"] = key
        item["disabled"] = disabled
        result[key] = item
    return result


def _static_section(specs: dict):
    result = {}
    for key, spec in specs.items():
        item = dict(spec or {})
        item["key"] = key
        item.setdefault("disabled", False)
        result[key] = item
    return result


def _commander_section(db: Session):
    result = {}
    for key, spec in COMMANDER_SKILL_SPECS.items():
        item = dict(spec or {})
        item["key"] = key
        override = get_config(db, f"commander_{key}_bonus")
        if override:
            try:
                item["bonus_per_level"] = float(override)
                item["overridden"] = True
            except (TypeError, ValueError):
                item["overridden"] = False
        else:
            item["overridden"] = False
        item.setdefault("disabled", False)
        result[key] = item
    return result


def _build_spec_catalog(db: Session, include_disabled: bool = False):
    definition = get_game_definition()
    return {
        "schema_version": 1,
        "meta": definition.get("meta", {}),
        "engine": definition.get("engine", {}),
        "specs": {
            "ships": _catalog_section(db, get_all_ship_specs(db), is_ship_disabled, include_disabled),
            "defenses": _catalog_section(db, get_all_defense_specs(db), is_defense_disabled, include_disabled),
            "buildings": _catalog_section(db, get_all_building_specs(db), is_building_disabled, include_disabled),
            "research": _catalog_section(db, get_all_research_specs(db), is_research_disabled, include_disabled),
            "astros": _catalog_section(db, get_all_astro_specs(db), is_astro_disabled, include_disabled),
            "weapons": _static_section(definition.get("weapon_types") or WEAPON_TYPES),
            "commanders": _commander_section(db),
            "goods": _static_section({"goods": GOODS_SPEC}),
        },
    }


def register_catalog_routes(app):
    @app.get("/api/catalog/specs")
    def get_catalog_specs(include_disabled: bool = False, db: Session = Depends(get_db)):
        """Return all display/spec lookup tables keyed by stable internal IDs."""
        return _build_spec_catalog(db, include_disabled=include_disabled)

    @app.get("/api/catalog/visible")
    def get_visible_catalog(include_disabled: bool = False, db: Session = Depends(get_db)):
        """Return normalized catalog data visible to the current client.

        Today this is the game-definition/spec catalog. Player/world catalogs will
        be added behind this same endpoint after visibility rules are centralized.
        """
        catalog = _build_spec_catalog(db, include_disabled=include_disabled)
        catalog["players"] = {}
        catalog["world"] = {"galaxies": {}, "regions": {}, "systems": {}, "planets": {}, "colonies": {}}
        return catalog
