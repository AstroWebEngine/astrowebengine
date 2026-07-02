"""
Data-driven combat system.
Extracted from game_logic.py for maintainability.
"""

import json
import math
from decimal import Decimal, ROUND_HALF_UP
from sqlalchemy.orm import Session

from models import Colony, Fleet, BattleReport
from specs import ALL_SHIP_TYPES, SHIP_SPECS, DEFENSE_SPECS, WEAPON_TYPES
from auth import get_effective_ship_spec, get_effective_defense_spec, log_credits, log_fleet_change
from config_defaults import *
from resources import add_resources, total_cost_value
from game_definition import get_game_definition


def _maybe_form_moon(db, planet, debris, owner_user, engine_cfg):
    """Debris-based moon formation: battle debris at a planet has a chance to
    coalesce into a moon owned by the planet's owner ("moonshot").

    Classic formula (verified against an open-source reference implementation):
    1% per 100k debris, capped; chances below the floor never roll; the moon's
    size scales with the formation chance.

    Engine flags (definition `engine` section):
      moon_formation: true to enable (default off)
      moon_chance_per_100k_debris: chance added per 100k debris value (default 0.01)
      moon_max_chance: cap on the formation chance (default 0.20)
      moon_min_chance: below this the moon never forms (default 0.01)
      moon_terrain: terrain key for the new moon (default "craters")

    Returns the new moon Planet, or None."""
    import random as _random
    from models import Planet, Building, Defense
    from auth import get_all_astro_specs, get_all_building_specs, get_all_defense_specs

    if not engine_cfg.get("moon_formation"):
        return None
    if planet is None or owner_user is None or debris <= 0:
        return None
    # One moon per position: any satellite (orbit_row > 0) at this slot blocks formation.
    existing = (db.query(Planet)
                .filter(Planet.system_id == planet.system_id,
                        Planet.orbit_position == planet.orbit_position,
                        Planet.orbit_row > 0)
                .first())
    if existing:
        return None

    per_100k = float(engine_cfg.get("moon_chance_per_100k_debris", 0.01))
    max_chance = float(engine_cfg.get("moon_max_chance", 0.20))
    min_chance = float(engine_cfg.get("moon_min_chance", 0.01))
    chance = min(max_chance, (debris / 100_000.0) * per_100k)
    if chance < min_chance or _random.random() >= chance:
        return None

    terrain = engine_cfg.get("moon_terrain", "craters")
    specs_all = get_all_astro_specs(db)
    stats = specs_all.get(terrain) or next(iter(specs_all.values()))
    # Coordinate-style name: replace the astro part with this slot's next row.
    coord_prefix = planet.name.rsplit(":", 1)[0] if ":" in planet.name else planet.name
    moon = Planet(
        name=f"{coord_prefix}:{planet.orbit_position * 10 + 1:02d}",
        system_id=planet.system_id, planet_type=terrain,
        orbit_position=planet.orbit_position, orbit_row=1,
        solar=stats.get("solar", 0), gas=stats.get("gas", 0),
        fertility=stats.get("fertility", 4),
        # Classic moon size: fields = rand(10..20) + 3 per % of formation chance
        # (bigger battles make bigger moons).
        area=_random.randint(10, 20) + int(300 * chance),
        metal=stats.get("metal", 0), crystal=stats.get("crystal", 0),
        temperature=planet.temperature,
        is_colonized=True,
    )
    db.add(moon)
    db.flush()
    # The moon belongs to the planet's owner and starts empty (no starter levels).
    moon_base = Colony(planet_id=moon.id, user_id=owner_user.id, name="Moon")
    db.add(moon_base)
    db.flush()
    for bt in get_all_building_specs(db).keys():
        db.add(Building(colony_id=moon_base.id, building_type=bt, level=0))
    for dt in get_all_defense_specs(db).keys():
        db.add(Defense(colony_id=moon_base.id, defense_type=dt, level=0))
    return moon


def _rebuild_count(lost, factor, model):
    """Units rebuilt after battle from `lost` units at rebuild `factor`.

    model "fixed": deterministic lost*factor (engine default).
    model "binomial": classic stochastic rebuild (verified against retro-game) —
    binomially distributed, approximated with a gaussian: mean = lost*factor,
    sd = sqrt(lost*factor*(1-factor)), clamped to [0, lost], whole units."""
    if factor <= 0 or lost <= 0:
        return 0.0
    if model == "binomial":
        import random as _random
        mean = lost * factor
        sd = math.sqrt(lost * factor * (1.0 - factor)) if factor < 1.0 else 0.0
        n = int(_random.gauss(mean, sd)) if sd > 0 else int(mean)
        return float(max(0, min(int(lost), n)))
    return lost * factor


def _plunder_resources(available, capacity, resource_types):
    """Classic cargo-fill plunder order (verified against retro-game).

    For metal/crystal/deuterium: 1/3 of capacity with the 1st resource, 1/2 of
    the remainder with the 2nd, the rest with the 3rd, then refill passes at
    1/2 for all but the last. Leftover capacity stays unused — you cannot top
    up entirely with one resource. Returns {resource: taken}."""
    taken = {r: 0.0 for r in resource_types}
    remaining = {r: max(0.0, float(available.get(r, 0))) for r in resource_types}
    cap = max(0.0, float(capacity))

    def _take(res, factor):
        nonlocal cap
        amount = min(cap / factor, remaining[res])
        amount = float(int(amount))
        cap -= amount
        remaining[res] -= amount
        taken[res] += amount

    n = len(resource_types)
    for i, res in enumerate(resource_types):      # first pass: 1/n, 1/(n-1), ... 1/1
        _take(res, n - i)
    for res in resource_types[:-1]:               # refill passes at 1/2
        _take(res, 2)
    return {r: v for r, v in taken.items() if v > 0}


def _raid_plunder(db, attacker_user, defender_user, attacker_fleet, eff_ship_specs, engine_cfg):
    """Cargo raid: the winner steals from the defender's stockpile, capped
    by the surviving fleet's cargo capacity (ship spec `cargo`).

    The classic rule takes up to plunder_percent (default 50%) of the planet's
    resources; this engine stores resources per ACCOUNT, so the plunderable
    pool is the defender's stockpile split evenly across their bases."""
    from resources import (get_user_resources, get_resource_types,
                           deduct_cost, add_resources)

    percent = float(engine_cfg.get("plunder_percent", 0.5))
    capacity = sum(attacker_fleet.get_ship_count(st) * (eff_ship_specs[st].get("cargo") or 0)
                   for st in ALL_SHIP_TYPES)
    if capacity <= 0 or percent <= 0:
        return None
    bases = max(1, len(getattr(defender_user, "colonies", []) or []))
    stock = get_user_resources(defender_user)
    available = {r: (stock.get(r, 0) or 0) / bases * percent for r in get_resource_types()}
    taken = _plunder_resources(available, capacity, get_resource_types())
    if not taken:
        return None
    deduct_cost(defender_user, taken)
    add_resources(attacker_user, taken)
    total = total_cost_value(taken)
    log_credits(db, attacker_user.id, total, "Raid plunder", "combat")
    log_credits(db, defender_user.id, -total, f"Raided by {attacker_user.username}", "combat")
    return taken


def _destroy_moon(db, colony, planet):
    """Remove a destroyed moon and everything on it. Fleets stationed at the
    moon die with it; visiting/in-transit fleets are rerouted to the parent
    planet (same system + position, orbit_row 0), matching the classic rule."""
    from models import (Planet, Building, Defense, Fleet, ConstructionQueue,
                        ResearchQueue, ShipQueue, TradeRoute, Commander)
    from sqlalchemy import or_

    parent = (db.query(Planet)
              .filter(Planet.system_id == planet.system_id,
                      Planet.orbit_position == planet.orbit_position,
                      Planet.orbit_row == 0)
              .first())
    db.query(Defense).filter(Defense.colony_id == colony.id).delete()
    db.query(Building).filter(Building.colony_id == colony.id).delete()
    db.query(ConstructionQueue).filter(ConstructionQueue.colony_id == colony.id).delete()
    db.query(ResearchQueue).filter(ResearchQueue.colony_id == colony.id).delete()
    db.query(ShipQueue).filter(ShipQueue.colony_id == colony.id).delete()
    for cmdr in db.query(Commander).filter(Commander.colony_id == colony.id).all():
        cmdr.colony_id = None
        cmdr.is_assigned = False
    for f in db.query(Fleet).filter(Fleet.base_id == colony.id).all():
        db.delete(f)
    for f in db.query(Fleet).filter(Fleet.location_planet_id == planet.id).all():
        f.location_planet_id = parent.id if parent else None
    for f in db.query(Fleet).filter(Fleet.destination_planet_id == planet.id).all():
        f.destination_planet_id = parent.id if parent else None
    for f in db.query(Fleet).filter(Fleet.destination_base_id == colony.id).all():
        f.destination_base_id = None
        f.destination_planet_id = parent.id if parent else None
    db.query(TradeRoute).filter(or_(TradeRoute.base_a_id == colony.id,
                                    TradeRoute.base_b_id == colony.id)).delete()
    db.delete(colony)
    db.delete(planet)
    db.flush()


def attempt_moon_destruction(db, attacker_fleet, defender_colony):
    """Moon destruction ("destroy" mission). Classic formulas
    (verified against an open-source reference implementation):
      moon chance      = min(1, (1 - 0.01*sqrt(diameter)) * sqrt(num_destroyers))
      backfire chance  = 5e-5 * diameter  (ALL destroyer ships lost)
    Both rolls are independent — you can crack the moon AND lose the fleet.
    Diameter derives from the moon's fields: d = 1000*sqrt(area).

    Requires engine.moon_destruction and ships flagged `can_destroy_moons`.
    Returns a result dict for the battle report."""
    import math
    import random as _random
    from auth import ships_with_capability

    result = {"chance": 0.0, "destroyed": False,
              "backfire_chance": 0.0, "destroyers_lost": 0}
    engine_cfg = get_game_definition().get("engine", {}) or {}
    if not engine_cfg.get("moon_destruction"):
        return result
    planet = getattr(defender_colony, "planet", None)
    if planet is None or (planet.orbit_row or 0) == 0:
        return result
    destroyer_keys = ships_with_capability(db, "can_destroy_moons")
    num = sum(attacker_fleet.get_ship_count(k) for k in destroyer_keys)
    if num <= 0:
        return result

    diameter = 1000.0 * math.sqrt(max(1, planet.area or 1))
    result["chance"] = round(
        min(1.0, max(0.0, 1.0 - 0.01 * math.sqrt(diameter)) * math.sqrt(num)), 4)
    result["backfire_chance"] = round(min(1.0, 5e-5 * diameter), 4)

    if _random.random() < result["chance"]:
        result["destroyed"] = True
        _destroy_moon(db, defender_colony, planet)
    if _random.random() < result["backfire_chance"]:
        for k in destroyer_keys:
            result["destroyers_lost"] += attacker_fleet.get_ship_count(k)
            attacker_fleet.set_ship_count(k, 0)
    return result


def _fleet_ship_counts(fleet) -> dict:
    """Get all ship counts — uses Fleet abstraction if available, falls back to getattr."""
    if hasattr(fleet, 'get_ship_count'):
        return {st: fleet.get_ship_count(st) for st in ALL_SHIP_TYPES}
    return {st: getattr(fleet, st, 0) or 0 for st in ALL_SHIP_TYPES}

def _fleet_total_ships(fleet) -> int:
    return sum(_fleet_ship_counts(fleet).values())

def _fleet_value(fleet, db) -> float:
    counts = _fleet_ship_counts(fleet)
    return sum(counts[st] * total_cost_value(get_effective_ship_spec(db, st).get("cost", 0)) for st in ALL_SHIP_TYPES)


# Legacy unit ordering fallback (rarely hit — combat prefers each spec's explicit
# `rounding` field or generic key/class inference). Computed live from the active
# SHIP_SPECS so it stays correct after a ruleset mod syncs a different roster.


def _round_half_up(value, digits: int) -> float:
    """Match Java/BigDecimal half-up rounding used by the reference calculator."""
    quant = "1" if digits == 0 else "1." + ("0" * digits)
    return float(Decimal(str(value)).quantize(Decimal(quant), rounding=ROUND_HALF_UP))


def _rd2(value) -> float:
    return _round_half_up(value, 2)


def _rd3(value) -> float:
    return _round_half_up(value, 3)


def _rd5(value) -> float:
    return _round_half_up(value, 5)


def _rounding_digits(rounding_type: int) -> int:
    """Precision used for persisted survivor counts by configured unit class."""
    if rounding_type == 1:
        return 1
    if rounding_type == 2:
        return 3
    return 0


def _clean_rounding_type(value):
    try:
        parsed = int(value)
    except (TypeError, ValueError):
        return None
    if parsed in (0, 1, 2):
        return parsed
    return None


def _infer_rounding_from_generic_key(unit_key: str):
    """Infer rounding for generic public-slot IDs when no spec field exists."""
    key = str(unit_key or "").lower()
    small_prefixes = ("ship_s", "ship_small", "small_ship", "ship_utility", "utility_ship")
    medium_prefixes = ("ship_m", "ship_medium", "med_ship", "medium_ship")
    capital_prefixes = (
        "ship_l", "ship_large", "large_ship",
        "ship_c", "ship_capital", "capital_ship",
    )
    if key.startswith(small_prefixes):
        return 0
    if key.startswith(medium_prefixes):
        return 1
    if key.startswith(capital_prefixes):
        return 2
    return None


def _rounding_from_spec(unit_key: str, spec: dict):
    """Return a data-driven rounding category from explicit fields or generic class."""
    if not spec:
        return None

    explicit = _clean_rounding_type(spec.get("rounding"))
    if explicit is not None:
        return explicit

    unit_class = str(
        spec.get("class") or spec.get("ship_class") or spec.get("hull_class") or ""
    ).strip().lower()
    if unit_class in ("small", "light", "utility"):
        return 0
    if unit_class in ("medium", "med"):
        return 1
    if unit_class in ("large", "capital", "heavy", "supercapital"):
        return 2

    return _infer_rounding_from_generic_key(unit_key)


def _get_rounding_type(unit_key, is_defense=False, eff_specs=None):
    """Unit rounding category.

    Type 0 = binary/ceil, Type 1 = partial at 0.1, Type 2 = partial at 0.001.
    Defenses always use Type 2. Ships prefer explicit spec fields, then generic
    key/class inference, then the legacy insertion-order fallback.
    """
    if is_defense:
        return 2

    if eff_specs:
        inferred = _rounding_from_spec(unit_key, eff_specs.get(unit_key, {}))
        if inferred is not None:
            return inferred

    inferred = _infer_rounding_from_generic_key(unit_key)
    if inferred is not None:
        return inferred

    # No signal from the caller's eff_specs or the generic key: read the ship's
    # own `rounding` field from the live roster (data-driven; replaces a legacy
    # insertion-order positional band that was roster-specific and meaningless
    # on other rosters).
    return int(SHIP_SPECS.get(unit_key, {}).get("rounding", 0) or 0)


def _round_quantity(rounding_type, qty):
    """Round unit quantity per engine rounding rules."""
    if qty <= 0:
        return 0.0
    if rounding_type == 0:
        return math.ceil(qty)
    return _round_half_up(qty, _rounding_digits(rounding_type))


def _uses_partial_damage(unit_key, eff_specs=None) -> bool:
    return _get_rounding_type(unit_key, False, eff_specs) > 0


def _get_weapon_tech(user, weapon_type):
    """Legacy helper — still used for manual tech lookups outside data-driven path."""
    from game_logic import get_tech_level
    tech_map = {"laser": "laser", "missiles": "missiles", "plasma": "plasma",
                "ion": "ion", "photon": "photon", "disruptor": "disruptor"}
    tech = tech_map.get(weapon_type, "")
    return get_tech_level(user, tech) if tech else 0


def _get_fleet_bonus(ship_counts, eff_ship_specs):
    """Return power+armour multiplier from the highest fleet_bonus in the fleet (data-driven).
    Each ship spec can have a 'fleet_bonus' field (e.g. 0.05 for the capital-tier flagship, 0.10 for the top-tier flagship).
    Only the highest bonus applies (they don't stack)."""
    best_bonus = 0.0
    for st, count in ship_counts.items():
        if count > 0:
            spec = eff_ship_specs.get(st, {})
            bonus = spec.get("fleet_bonus", 0)
            if bonus > best_bonus:
                best_bonus = bonus
    return 1.0 + best_bonus


def _make_ship_stats(spec, wpn_tech, arm_tech, shd_tech, cc_lv, tc_lv, fleet_bonus, tc_bonus=None,
                     weapon_power_mults=None, combat_stat_mults=None):
    """Calculate effective ship combat stats.
    If weapon_power_mults/combat_stat_mults are provided (data-driven), use them.
    Otherwise fall back to raw tech level / divisor (legacy)."""
    tc_factor = tc_lv * tc_bonus if tc_bonus is not None else tc_lv / TACTICAL_COMMANDER_DIVISOR

    if weapon_power_mults is not None:
        wpn_mult = weapon_power_mults.get(spec["weapon"], 1.0)
    else:
        wpn_mult = 1 + wpn_tech / WEAPON_TECH_DIVISOR

    if combat_stat_mults is not None:
        arm_mult = combat_stat_mults.get("armour", 1.0)
        shd_mult = combat_stat_mults.get("shield", 1.0)
    else:
        arm_mult = 1 + arm_tech / ARMOUR_TECH_DIVISOR
        shd_mult = 1 + shd_tech / SHIELDING_TECH_DIVISOR

    power = spec["attack"] * wpn_mult * (1 + cc_lv / COMMAND_CENTER_DIVISOR + tc_factor) * fleet_bonus
    armour = spec["armour"] * arm_mult * fleet_bonus
    shield = spec.get("shield", 0) * shd_mult
    return {"power": power, "armour": armour, "shield": shield,
            "cost": spec["cost"], "weapon": spec["weapon"]}


def _make_def_stats(spec, wpn_tech, arm_tech, shd_tech, dc_lv, dc_bonus=None,
                    weapon_power_mults=None, combat_stat_mults=None):
    """Calculate effective defense combat stats.
    If weapon_power_mults/combat_stat_mults are provided (data-driven), use them.
    Otherwise fall back to raw tech level / divisor (legacy)."""
    dc_factor = dc_lv * dc_bonus if dc_bonus is not None else dc_lv / DEFENSE_COMMANDER_DIVISOR
    dc_mult = 1 + dc_factor

    if weapon_power_mults is not None:
        wpn_mult = weapon_power_mults.get(spec["weapon"], 1.0)
    else:
        wpn_mult = 1 + wpn_tech / WEAPON_TECH_DIVISOR

    if combat_stat_mults is not None:
        arm_mult = combat_stat_mults.get("armour", 1.0)
        shd_mult = combat_stat_mults.get("shield", 1.0)
    else:
        arm_mult = 1 + arm_tech / ARMOUR_TECH_DIVISOR
        shd_mult = 1 + shd_tech / SHIELDING_TECH_DIVISOR

    power = spec["attack"] * wpn_mult * dc_mult
    armour = spec["armour"] * arm_mult * dc_mult
    shield = spec.get("shield", 0) * shd_mult * dc_mult
    return {"power": power, "armour": armour, "shield": shield,
            "cost": spec["cost"], "weapon": spec["weapon"]}


def _single_attack_damage(attacker_power, attacker_weapon, defender_shield, is_ion_crossshield=False):
    """Calculate damage from one unit type attacking one defender type.
    Shield passthrough is now data-driven from WEAPON_TYPES spec."""
    if defender_shield == 0:
        return attacker_power
    # Data-driven: look up weapon's shield passthrough from specs
    wpn_spec = WEAPON_TYPES.get(attacker_weapon, {})
    passthrough = wpn_spec.get("shield_passthrough", NORMAL_SHIELD_PASSTHROUGH)
    passthrough_mult = 1 - passthrough
    if defender_shield < attacker_power:
        return attacker_power - defender_shield * passthrough_mult
    else:
        return attacker_power * passthrough


def _single_attack_damage_exp(attacker_power, attacker_weapon, defender_shield, exponent):
    """Damage raised to exponent for proportional allocation."""
    dmg = _rd2(_single_attack_damage(attacker_power, attacker_weapon, defender_shield))
    if exponent == 1.0:
        return dmg
    return dmg ** exponent if dmg > 0 else 0.0


def _apply_fleet_attack(attackers, atk_stat_map, defenders, def_stat_map, exponent, eff_ship_specs=None):
    """One side fires at the other.

    Per-target damage is rounded before allocation, and overflow is reprocessed
    as a fresh wave of the same attacker type.
    """
    total_damage_dealt = 0.0
    atk_types = [t for t in attackers if attackers[t] > 0]

    for a_type in atk_types:
        a_stats = atk_stat_map[a_type]
        a_power = a_stats["power"]
        a_weapon = a_stats["weapon"]
        current_qty = attackers[a_type]
        if current_qty <= 0:
            continue

        attacker_rounding = _get_rounding_type(a_type, a_type not in ALL_SHIP_TYPES, eff_ship_specs)
        max_waves = 30
        while current_qty > 1e-6 and max_waves > 0:
            max_waves -= 1

            damage_vs = {}
            total_damage_sum = 0.0
            for d_type in defenders:
                if defenders[d_type] <= 0:
                    continue
                d_stats = def_stat_map[d_type]
                single_dmg = _rd2(_single_attack_damage(a_power, a_weapon, d_stats["shield"]))
                if single_dmg <= 0:
                    continue
                dmg_exp = single_dmg if exponent == 1.0 else single_dmg ** exponent
                damage_vs[d_type] = (single_dmg, dmg_exp)
                total_damage_sum += dmg_exp

            if total_damage_sum <= 0:
                break

            overflow = 0.0
            for d_type, (single_dmg, dmg_exp) in damage_vs.items():
                if defenders[d_type] <= 0:
                    continue
                d_stats = def_stat_map[d_type]
                d_armour = _rd3(d_stats["armour"])
                if d_armour <= 0 or single_dmg <= 0:
                    continue

                proportion = _rd5(dmg_exp / total_damage_sum)
                allocation = proportion * current_qty
                units_killed = _rd2(_rd2(allocation * _rd2(single_dmg)) / d_armour)
                max_killable_alloc = defenders[d_type] * d_armour / single_dmg

                if allocation > max_killable_alloc:
                    defenders[d_type] = 0.0
                    overflow += allocation - max_killable_alloc
                    total_damage_dealt += max_killable_alloc * single_dmg
                else:
                    defenders[d_type] -= units_killed
                    total_damage_dealt += allocation * single_dmg

            if overflow > 1e-6:
                current_qty = _round_quantity(attacker_rounding, overflow)
            else:
                break

    return total_damage_dealt


def resolve_battle(attacker_fleet, attacker_user, defender_colony, defender_user, game_speed, db,
                   target_fleet_id=None, defender_planet_id=None):
    """Battle facade — the single entry point every caller routes through.

    A behavioral mod may register an overriding `resolve_battle` hook to replace
    the engine's resolver entirely (e.g. a positional / module-based combat
    system). If a mod handler returns a report, it is used as-is; otherwise the
    built-in resolver runs. Either way, `on_battle_resolved` observers fire once
    afterward, so reports/notifications cover modded and default combat alike.

    An overriding resolver owns its own persistence and must return a report with
    the keys downstream code reads (see _resolve_battle_default / combat docs).
    """
    import mod_hooks
    report = mod_hooks.fire_override("resolve_battle", {
        "attacker_fleet": attacker_fleet,
        "attacker_user": attacker_user,
        "defender_colony": defender_colony,
        "defender_user": defender_user,
        "game_speed": game_speed,
        "db": db,
        "target_fleet_id": target_fleet_id,
        "defender_planet_id": defender_planet_id,
    })
    # Guard the override contract: a mod resolver must return a report dict with
    # at least a "result". Anything else is rejected (logged) and the built-in
    # resolver runs — a malformed override can't corrupt downstream readers.
    if report is not None and not (isinstance(report, dict) and "result" in report):
        import logging
        logging.getLogger("awe").warning(
            f"[resolve_battle] override returned invalid report "
            f"({type(report).__name__}); falling back to default resolver"
        )
        report = None
    if report is None:
        report = _resolve_battle_default(
            attacker_fleet, attacker_user, defender_colony, defender_user, game_speed, db,
            target_fleet_id=target_fleet_id, defender_planet_id=defender_planet_id,
        )
    # Observers run once, for both modded and default resolution.
    mod_hooks.fire("on_battle_resolved", {
        "report": report,
        "attacker_user": attacker_user,
        "defender_user": defender_user,
        "defender_colony": defender_colony,
        "attacker_fleet": attacker_fleet,
        "game_speed": game_speed,
        "db": db,
    })
    return report


def _resolve_battle_default(attacker_fleet, attacker_user, defender_colony, defender_user, game_speed, db,
                            target_fleet_id=None, defender_planet_id=None):
    """
    Data-driven combat engine.

    Key mechanics:
    - Proportional damage allocation (each attacker fires at ALL defenders proportionally)
    - Shield absorption is data-driven per weapon type:
      non-ion: shield < power -> damage = power - shield*0.99, shield >= power -> power*0.01
      ion:     shield < power -> damage = power - shield*0.5,  shield >= power -> power*0.5
    - Shield passthrough: data-driven per weapon type (WEAPON_TYPES spec)
    - Fleet bonus: data-driven per ship type (fleet_bonus spec field)
    - Commander bonuses: CC/20 + TC/100 for ship power; DC/100 for defense power+armour
    - Rounding: Type 0 (units 0-10) = ceil; Type 1 (11-13) = round 0.1; Type 2 (14-19) = round 0.001
    - Defense rebalancing: after damage, redistribute defense quantities proportionally by cost
    - Debris/loot: based on fully destroyed ships only (not surviving partials or defense losses)
    """
    from game_logic import (
        get_building_level,
        get_commander_level_at_base,
        get_commander_bonus,
        evaluate_tech_bonuses,
    )

    # --- Pre-fetch effective specs (with admin overrides applied) ---
    eff_ship_specs = {st: get_effective_ship_spec(db, st) for st in ALL_SHIP_TYPES}
    eff_def_specs = {dt: get_effective_defense_spec(db, dt) for dt in DEFENSE_SPECS}

    # --- Gather forces ---

    # Attacker ships — account for existing partial damage
    atk_damage_state = json.loads(attacker_fleet.ship_damage or "{}")
    atk_counts = {}
    atk_initial_whole = {}
    for st in ALL_SHIP_TYPES:
        whole = float(attacker_fleet.get_ship_count(st))
        atk_initial_whole[st] = whole
        if st in atk_damage_state and whole > 0:
            # e.g. 6 cruisers with damage 0.75 = 5.75 effective
            whole = (whole - 1) + atk_damage_state[st]
        atk_counts[st] = whole
    atk_initial = {st: atk_counts[st] for st in ALL_SHIP_TYPES}
    if sum(atk_counts.values()) == 0:
        return {"result": "no_ships", "report": "No attacking ships."}

    # Defender ships from the targeted location. Full base battles include all owner fleets;
    # targeted fleet fights can constrain this to a single fleet.
    def_query = db.query(Fleet).filter(
        Fleet.is_moving == False,
        Fleet.user_id == defender_user.id,
    )
    defender_base_id = getattr(defender_colony, "id", None)
    if defender_base_id:
        def_query = def_query.filter(Fleet.base_id == defender_base_id)
    else:
        if defender_planet_id is None:
            defender_planet = getattr(defender_colony, "planet", None)
            defender_planet_id = getattr(defender_planet, "id", None)
        if defender_planet_id is None:
            defender_planet_id = attacker_fleet.location_planet_id
        def_query = def_query.filter(
            Fleet.base_id == None,
            Fleet.location_planet_id == defender_planet_id,
        )
    if target_fleet_id is not None:
        def_query = def_query.filter(Fleet.id == target_fleet_id)
    def_fleets = def_query.all()
    def_counts = {st: 0.0 for st in ALL_SHIP_TYPES}
    def_initial_whole = {st: 0.0 for st in ALL_SHIP_TYPES}
    def_initial_per_fleet = {}  # {fleet_id: {ship_type: count}} for audit logging
    for f in def_fleets:
        f_damage = json.loads(f.ship_damage or "{}")
        def_initial_per_fleet[f.id] = {}
        for st in ALL_SHIP_TYPES:
            whole = float(f.get_ship_count(st))
            def_initial_whole[st] += whole
            def_initial_per_fleet[f.id][st] = whole
            if st in f_damage and whole > 0:
                whole = (whole - 1) + f_damage[st]
            def_counts[st] += whole
    def_initial = {st: def_counts[st] for st in ALL_SHIP_TYPES}

    # Defender defenses
    def_eff = getattr(defender_colony, 'defense_effectiveness', 1.0) or 1.0
    def_defenses = {}
    def_defense_levels_initial = {}
    for d in defender_colony.defenses:
        qty = float(d.level)  # stats already represent 5 turrets per unit
        def_defense_levels_initial[d.defense_type] = qty
        def_defenses[d.defense_type] = qty * def_eff
    def_defenses_initial = dict(def_defenses)

    # --- Tech bonuses (data-driven) ---
    atk_tech = evaluate_tech_bonuses(attacker_user, db)
    def_tech = evaluate_tech_bonuses(defender_user, db)
    atk_weapon_mults = atk_tech["weapon_power"]
    atk_combat_mults = atk_tech["combat_stats"]
    def_weapon_mults = def_tech["weapon_power"]
    def_combat_mults = def_tech["combat_stats"]
    # Legacy variables kept for backward compat with _make_ship_stats signature
    atk_armour_tech = 0
    atk_shielding_tech = 0
    def_armour_tech = 0
    def_shielding_tech = 0

    # Commander bonuses
    atk_cc_lv = 0
    if attacker_fleet.base_id:
        atk_home = db.query(Colony).filter(Colony.id == attacker_fleet.base_id).first()
        if atk_home:
            atk_cc_lv = get_building_level(atk_home, "command_centers")
    atk_tc_lv = get_commander_level_at_base(db, attacker_fleet.base_id, "tactical") if attacker_fleet.base_id else 0
    atk_dc_lv = 0  # attackers don't get defense commander

    def_cc_lv = get_building_level(defender_colony, "command_centers")
    def_tc_lv = get_commander_level_at_base(db, defender_colony.id, "tactical")
    def_dc_lv = get_commander_level_at_base(db, defender_colony.id, "defense")

    # Data-driven commander bonus amounts
    tc_bonus = get_commander_bonus(db, "tactical")
    dc_bonus = get_commander_bonus(db, "defense")

    # --- Fleet bonus detection (data-driven from ship specs) ---
    atk_fleet_bonus = _get_fleet_bonus(atk_counts, eff_ship_specs)
    def_fleet_bonus = _get_fleet_bonus(def_counts, eff_ship_specs)

    # --- Pre-calculate per-unit effective stats ---
    atk_stats = {}
    for st in ALL_SHIP_TYPES:
        spec = eff_ship_specs[st]
        atk_stats[st] = _make_ship_stats(spec, 0, 0, 0,
                                          atk_cc_lv, atk_tc_lv, atk_fleet_bonus, tc_bonus,
                                          weapon_power_mults=atk_weapon_mults, combat_stat_mults=atk_combat_mults)

    def_stats = {}
    for st in ALL_SHIP_TYPES:
        spec = eff_ship_specs[st]
        def_stats[st] = _make_ship_stats(spec, 0, 0, 0,
                                          def_cc_lv, def_tc_lv, def_fleet_bonus, tc_bonus,
                                          weapon_power_mults=def_weapon_mults, combat_stat_mults=def_combat_mults)

    turret_stats = {}
    for dt, dspec in eff_def_specs.items():
        turret_stats[dt] = _make_def_stats(dspec, 0, 0, 0, def_dc_lv, dc_bonus,
                                            weapon_power_mults=def_weapon_mults, combat_stat_mults=def_combat_mults)

    # --- Build combined defender force (ships + defenses as one fleet) ---
    all_def_types = list(ALL_SHIP_TYPES) + list(DEFENSE_SPECS.keys())
    combined_def_counts = {}
    combined_def_stats = {}
    for st in ALL_SHIP_TYPES:
        combined_def_counts[st] = def_counts[st]
        combined_def_stats[st] = def_stats[st]
    for dt in DEFENSE_SPECS:
        combined_def_counts[dt] = def_defenses.get(dt, 0.0)
        combined_def_stats[dt] = turret_stats[dt]

    combined_atk_counts = {st: atk_counts[st] for st in ALL_SHIP_TYPES}
    combined_atk_stats = {st: atk_stats[st] for st in ALL_SHIP_TYPES}

    combined_def_atk_counts = {}
    combined_def_atk_stats = {}
    for st in ALL_SHIP_TYPES:
        if def_counts[st] > 0:
            combined_def_atk_counts[st] = def_counts[st]
            combined_def_atk_stats[st] = def_stats[st]
    for dt in DEFENSE_SPECS:
        if def_defenses.get(dt, 0) > 0:
            combined_def_atk_counts[dt] = def_defenses[dt]
            combined_def_atk_stats[dt] = turret_stats[dt]

    # --- Combat rounds (engine-configurable) ---
    game_def = get_game_definition()
    engine_cfg = game_def.get("engine", {})
    combat_cfg = game_def.get("combat", {})
    max_rounds = engine_cfg.get("combat_max_rounds", 1)
    defenses_destructible = engine_cfg.get("defenses_destructible", False)
    defense_repair_pct = engine_cfg.get("defense_repair_percent", 1.0)
    rebuild_model = engine_cfg.get("rebuild_model", "fixed")
    fleet_rebuild_factor = float(engine_cfg.get("fleet_rebuild_factor", 0.0))
    damage_allocation_exponent = combat_cfg.get("damage_allocation_exponent", DAMAGE_ALLOCATION_EXPONENT)
    loot_percent = combat_cfg.get("loot_percent", COMBAT_LOOT_PERCENT)
    debris_percent = combat_cfg.get("debris_percent", DEBRIS_PERCENT)

    atk_damage_dealt = 0.0
    def_damage_dealt = 0.0
    rounds_fought = 0

    for combat_round in range(max_rounds):
        # Check if either side is wiped out
        atk_alive = sum(combined_atk_counts.get(st, 0) for st in ALL_SHIP_TYPES)
        def_alive = sum(combined_def_counts.get(k, 0) for k in combined_def_counts)
        if atk_alive <= 0 or def_alive <= 0:
            break

        rounds_fought += 1

        atk_before = {st: combined_atk_counts[st] for st in ALL_SHIP_TYPES}
        def_before = {k: combined_def_counts[k] for k in combined_def_counts}

        # Snapshot defender attackers for this round
        round_def_atk_counts = {}
        round_def_atk_stats = {}
        for st in ALL_SHIP_TYPES:
            if combined_def_counts.get(st, 0) > 0:
                round_def_atk_counts[st] = combined_def_counts[st]
                round_def_atk_stats[st] = combined_def_stats[st]
        for dt in DEFENSE_SPECS:
            if combined_def_counts.get(dt, 0) > 0:
                round_def_atk_counts[dt] = combined_def_counts[dt]
                round_def_atk_stats[dt] = turret_stats[dt]

        atk_damage_dealt += _apply_fleet_attack(
            atk_before, combined_atk_stats,
            combined_def_counts, combined_def_stats,
            damage_allocation_exponent, eff_ship_specs)

        def_damage_dealt += _apply_fleet_attack(
            round_def_atk_counts, round_def_atk_stats,
            combined_atk_counts, combined_atk_stats,
            damage_allocation_exponent, eff_ship_specs)

        # Apply rounding per unit type
        for st in ALL_SHIP_TYPES:
            rt = _get_rounding_type(st, False, eff_ship_specs)
            combined_atk_counts[st] = _round_quantity(rt, combined_atk_counts[st])
            combined_def_counts[st] = _round_quantity(rt, combined_def_counts[st])

        for dt in DEFENSE_SPECS:
            combined_def_counts[dt] = _round_quantity(2, combined_def_counts[dt])

    raw_def_defenses_final = {dt: combined_def_counts.get(dt, 0.0) for dt in DEFENSE_SPECS}

    # --- Defense rebalancing / persistence ---
    # Keep the raw end-of-fight turret results for the battle report, but
    # persist damage as one shared defense effectiveness percentage.
    original_def_cost = 0.0
    surviving_def_cost = 0.0
    for dt in DEFENSE_SPECS:
        base_level = def_defense_levels_initial.get(dt, 0.0)
        surv = raw_def_defenses_final.get(dt, 0.0)
        cost = total_cost_value(eff_def_specs[dt]["cost"])
        original_def_cost += base_level * cost
        surviving_def_cost += surv * cost

    new_def_eff = def_eff
    if original_def_cost > 0 and not defenses_destructible:
        new_def_eff = max(0.0, min(1.0, surviving_def_cost / original_def_cost))
        defender_colony.defense_effectiveness = new_def_eff
    elif not defenses_destructible:
        defender_colony.defense_effectiveness = 1.0

    # --- Defense destructibility (engine concept) ---
    # defenses_destructible=False: turret levels stay fixed and
    #   battle damage is stored in colony.defense_effectiveness (regenerates).
    # defenses_destructible=True: individual defense units destroyed, then
    #   defense_repair_percent of destroyed units auto-repair after battle.
    if defenses_destructible and defense_repair_pct > 0:
        for dt in DEFENSE_SPECS:
            initial = def_defenses_initial.get(dt, 0.0)
            surviving = combined_def_counts.get(dt, 0.0)
            destroyed = max(0.0, initial - surviving)
            repaired = _rebuild_count(destroyed, defense_repair_pct, rebuild_model)
            combined_def_counts[dt] = _round_quantity(2, surviving + repaired)

    # --- Extract final counts ---
    atk_counts = {st: combined_atk_counts[st] for st in ALL_SHIP_TYPES}
    def_counts_final = {st: combined_def_counts[st] for st in ALL_SHIP_TYPES}
    def_defenses_final = {dt: combined_def_counts.get(dt, 0.0) for dt in DEFENSE_SPECS}

    # Fleet rebuild (classic engines run this at 0.0; configurable like the
    # defense factor). Rebuilt ships never produce debris — losses below are
    # computed after this.
    if fleet_rebuild_factor > 0:
        for st in ALL_SHIP_TYPES:
            lost = max(0.0, atk_initial[st] - atk_counts[st])
            atk_counts[st] = min(atk_initial[st], atk_counts[st] + _rebuild_count(lost, fleet_rebuild_factor, rebuild_model))
            lost_d = max(0.0, def_initial[st] - def_counts_final[st])
            def_counts_final[st] = min(def_initial[st], def_counts_final[st] + _rebuild_count(lost_d, fleet_rebuild_factor, rebuild_model))

    # --- Calculate losses and apply partial damage ---
    atk_losses = {}
    new_atk_damage = {}
    for st in ALL_SHIP_TYPES:
        remaining = atk_counts[st]
        lost = max(0.0, atk_initial[st] - remaining)
        atk_losses[st] = lost
        if _uses_partial_damage(st, eff_ship_specs) and remaining > 0:
            rt = _get_rounding_type(st, False, eff_ship_specs)
            whole = math.ceil(remaining)
            frac = _round_half_up(remaining - math.floor(remaining), _rounding_digits(rt))
            if frac > 1e-6:
                attacker_fleet.set_ship_count(st, whole)
                new_atk_damage[st] = frac
            else:
                attacker_fleet.set_ship_count(st, int(remaining))
        else:
            attacker_fleet.set_ship_count(st, math.floor(max(0, remaining)))
    attacker_fleet.ship_damage = json.dumps(new_atk_damage) if new_atk_damage else "{}"

    def_losses = {}
    for st in ALL_SHIP_TYPES:
        lost = max(0.0, def_initial[st] - def_counts_final[st])
        def_losses[st] = lost
    for f in def_fleets:
        new_def_damage = {}
        f_old_damage = json.loads(f.ship_damage or "{}")
        for st in ALL_SHIP_TYPES:
            old_whole = float(f.get_ship_count(st))
            old_eff = old_whole
            if st in f_old_damage and old_whole > 0:
                old_eff = (old_whole - 1) + f_old_damage[st]
            total_of_type = def_initial[st]
            if total_of_type > 0 and old_eff > 0:
                surviving_ratio = def_counts_final[st] / total_of_type if total_of_type > 0 else 0
                new_eff = old_eff * surviving_ratio
                if _uses_partial_damage(st, eff_ship_specs) and new_eff > 0:
                    rt = _get_rounding_type(st, False, eff_ship_specs)
                    whole = math.ceil(new_eff)
                    frac = _round_half_up(new_eff - math.floor(new_eff), _rounding_digits(rt))
                    if frac > 1e-6:
                        f.set_ship_count(st, whole)
                        new_def_damage[st] = frac
                    else:
                        f.set_ship_count(st, int(new_eff))
                else:
                    f.set_ship_count(st, max(0, math.floor(new_eff)))
        f.ship_damage = json.dumps(new_def_damage) if new_def_damage else "{}"

    # Apply defense losses
    def_defense_losses = {}
    for dt in DEFENSE_SPECS:
        initial = def_defenses_initial.get(dt, 0.0)
        remaining = def_defenses_final.get(dt, 0.0)
        lost = max(0.0, initial - remaining)
        def_defense_losses[dt] = lost
        defense_obj = next((d for d in defender_colony.defenses if d.defense_type == dt), None)
        if defense_obj:
            base_level = def_defense_levels_initial.get(dt, float(defense_obj.level))
            if defenses_destructible:
                if initial > 0:
                    survival_ratio = max(0.0, min(1.0, remaining / initial))
                else:
                    # If defenses were temporarily at 0% effectiveness, preserve the stored level.
                    survival_ratio = 1.0
                defense_obj.level = max(0, int(base_level * survival_ratio))
            else:
                defense_obj.level = max(0, int(base_level))

    # --- Debris & combat loot ---
    atk_destroyed_full = {
        st: max(0, int(atk_initial_whole[st] - attacker_fleet.get_ship_count(st)))
        for st in ALL_SHIP_TYPES
    }
    def_destroyed_full = {
        st: max(0, int(def_initial_whole[st] - sum(f.get_ship_count(st) for f in def_fleets)))
        for st in ALL_SHIP_TYPES
    }
    atk_destroyed_value = sum(atk_destroyed_full[st] * total_cost_value(eff_ship_specs[st]["cost"]) for st in ALL_SHIP_TYPES)
    def_destroyed_value = sum(def_destroyed_full[st] * total_cost_value(eff_ship_specs[st]["cost"]) for st in ALL_SHIP_TYPES)
    def_turret_destroyed_value = sum(def_defense_losses.get(dt, 0) * total_cost_value(eff_def_specs[dt]["cost"]) for dt in DEFENSE_SPECS)
    total_destroyed = atk_destroyed_value + def_destroyed_value
    combat_loot_each = total_destroyed * loot_percent
    debris = total_destroyed * debris_percent

    moon_formed = None
    if debris > 0:
        planet = getattr(defender_colony, 'planet', None)
        if planet:
            planet.debris = (planet.debris or 0) + debris
            moon_formed = _maybe_form_moon(db, planet, debris, defender_user, engine_cfg)

    add_resources(attacker_user, combat_loot_each)
    add_resources(defender_user, combat_loot_each)
    if combat_loot_each > 0:
        log_credits(db, attacker_user.id, combat_loot_each, f"Combat loot at {defender_colony.name}", "combat")
        log_credits(db, defender_user.id, combat_loot_each, f"Combat loot at {defender_colony.name}", "combat")

    # Determine winner
    atk_remaining = sum(atk_counts.values())
    def_remaining = sum(def_counts_final.values()) + sum(def_defenses_final.values())
    result = "attacker_wins" if atk_remaining > def_remaining else ("defender_wins" if def_remaining > atk_remaining else "draw")

    # Cargo raid (engine plunder_model "cargo"): the winner steals from the
    # defender's stockpile, capped by surviving cargo capacity.
    raid = None
    if result == "attacker_wins" and engine_cfg.get("plunder_model") == "cargo":
        raid = _raid_plunder(db, attacker_user, defender_user, attacker_fleet, eff_ship_specs, engine_cfg)

    # Score changes
    if result == "attacker_wins":
        attacker_user.score += max(1, int(def_destroyed_value / COMBAT_SCORE_DIVISOR))
    elif result == "defender_wins":
        defender_user.score += max(1, int(atk_destroyed_value / COMBAT_SCORE_DIVISOR))

    # Build detailed report
    atk_total_losses = sum(atk_losses.values())
    def_total_losses = sum(def_losses.values())
    report = {
        "result": result,
        "attacker": attacker_user.username,
        "defender": defender_user.username,
        "base_name": defender_colony.name,
        "attacker_forces": {st: atk_initial[st] for st in ALL_SHIP_TYPES if atk_initial.get(st, 0) > 0},
        "defender_forces": {st: def_initial[st] for st in ALL_SHIP_TYPES if def_initial.get(st, 0) > 0},
        "defender_turrets": {dt: def_defenses_initial[dt] for dt in eff_def_specs if def_defenses_initial.get(dt, 0) > 0},
        "attacker_losses": {st: atk_losses[st] for st in ALL_SHIP_TYPES if atk_losses.get(st, 0) > 0},
        "defender_losses": {st: def_losses[st] for st in ALL_SHIP_TYPES if def_losses.get(st, 0) > 0},
        "defense_losses": {dt: v for dt, v in def_defense_losses.items() if v > 0},
        "debris": round(debris),
        "raid": {k: round(v) for k, v in raid.items()} if raid else None,
        "raid_total": round(total_cost_value(raid)) if raid else 0,
        "moon_formed": moon_formed.name if moon_formed else None,
        "attacker_total_losses": atk_total_losses,
        "defender_total_losses": def_total_losses,
        "attacker_value_lost": round(atk_destroyed_value),
        "defender_value_lost": round(def_destroyed_value),
        "defense_value_lost": round(def_turret_destroyed_value),
        "attacker_damage_dealt": round(atk_damage_dealt),
        "defender_damage_dealt": round(def_damage_dealt),
        "combat_loot": round(combat_loot_each),
    }

    # Save battle report
    br = BattleReport(
        attacker_id=attacker_user.id,
        defender_id=defender_user.id,
        base_id=defender_colony.id,
        report=json.dumps(report),
    )
    db.add(br)

    # Fleet audit logs for battle
    atk_before = {st: int(v) for st, v in atk_initial.items() if v > 0}
    log_fleet_change(db, attacker_user.id, attacker_fleet, "battle_loss",
                     atk_before, f"Attack on {defender_colony.name} ({defender_user.username})")
    for f in def_fleets:
        def_before_f = {st: int(def_initial_per_fleet[f.id][st]) for st in ALL_SHIP_TYPES if def_initial_per_fleet.get(f.id, {}).get(st, 0) > 0}
        if def_before_f:
            log_fleet_change(db, defender_user.id, f, "battle_loss",
                             def_before_f, f"Defended {defender_colony.name} vs {attacker_user.username}")

    db.commit()
    return report
