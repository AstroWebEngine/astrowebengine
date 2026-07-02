"""
Game logic and calculation helpers for AstroWebEngine.
Contains all game calculations, combat system, and event processing.
"""

import json
import math
import random
from datetime import datetime, timedelta
from sqlalchemy.orm import Session

import mod_hooks
from database import SessionLocal
from models import (
    User, Colony, Building, Defense, Research, Fleet, ShipQueue,
    Planet, StarSystem, Region, ScoutedRegion, ScoutedBase, ScoutedFleet,
    TradeRoute, BattleReport,
    GuildMember, Guild, ConstructionQueue, ResearchQueue, Galaxy,
    Commander,
)
from specs import SHIP_SPECS, ALL_SHIP_TYPES, BUILDING_SPECS, RESEARCH_SPECS, DEFENSE_SPECS, GOODS_SPEC, COMMANDER_SKILL_SPECS
from resources import (can_afford, deduct_cost, add_resources,
                       get_resource_model, get_resource_types, total_cost_value)
from auth import get_config, get_config_float, get_config_int, get_effective_ship_spec, get_effective_defense_spec, get_effective_building_spec, get_effective_research_spec, get_all_building_specs, get_all_research_specs, is_ship_disabled, is_defense_disabled, log_event, log_credits, log_fleet_change
from config_defaults import *


# ======================== GAME CALCULATION HELPERS ========================

def _building_dict(colony) -> dict:
    """Build a {type: level} dict for O(1) lookups. Cached on the colony object per request."""
    cache = getattr(colony, '_blv_cache', None)
    if cache is not None:
        return cache
    cache = {b.building_type: b.level for b in colony.buildings}
    colony._blv_cache = cache
    return cache

def get_building_level(colony, building_type: str) -> int:
    return _building_dict(colony).get(building_type, 0)

def _tech_dict(user) -> dict:
    """Build a {type: level} dict for O(1) lookups. Cached on the user object per request."""
    cache = getattr(user, '_tech_cache', None)
    if cache is not None:
        return cache
    cache = {r.tech_type: r.level for r in user.research}
    user._tech_cache = cache
    return cache

def get_tech_level(user, tech_type: str) -> int:
    return _tech_dict(user).get(tech_type, 0)


def evaluate_tech_bonuses(user, db=None):
    """Evaluate all research tech bonuses from specs (data-driven).
    Returns a dict with accumulated bonus effects:
      - stat_multipliers: {stat_name: multiplier} (e.g. {"energy": 1.15, "construction": 1.10})
      - weapon_power: {weapon_type: multiplier} (e.g. {"laser": 1.25})
      - combat_stats: {"armour": multiplier, "shield": multiplier}
      - fleet_count_bonus: int (extra fleet slots from computer tech etc.)
      - speed_multipliers: {drive_or_ship: multiplier}
      - stealth_level: float (detection reduction factor)
      - research_links: int
      - orbital_build_time_mult: float (e.g. 0.85 for -15%)
    """
    try:
        all_specs = get_all_research_specs(db)
    except (AttributeError, Exception):
        # Fallback to raw specs when db is unavailable (e.g. unit tests)
        all_specs = RESEARCH_SPECS
    tech_levels = _tech_dict(user)

    stat_multipliers = {}
    weapon_power = {}
    combat_stats = {}
    fleet_count_bonus = 0
    speed_multipliers = {}
    stealth_factor = 0.0
    research_links = 0
    orbital_build_mult = 1.0

    for tech_type, spec in all_specs.items():
        level = tech_levels.get(tech_type, 0)
        if level <= 0:
            continue
        bonuses = spec.get("bonuses", [])
        for b in bonuses:
            btype = b.get("type", "")
            per_level = b.get("per_level", 0)

            if btype == "stat_multiplier":
                stat = b.get("stat", "")
                stat_multipliers[stat] = stat_multipliers.get(stat, 1.0) + per_level * level

            elif btype == "weapon_power":
                weapon = b.get("weapon", "")
                weapon_power[weapon] = weapon_power.get(weapon, 1.0) + per_level * level

            elif btype == "combat_stat":
                stat = b.get("stat", "")
                combat_stats[stat] = combat_stats.get(stat, 1.0) + per_level * level

            elif btype == "fleet_count":
                fleet_count_bonus += int(per_level * level)

            elif btype == "speed_multiplier":
                key = b.get("drive", b.get("ship", ""))
                speed_multipliers[key] = speed_multipliers.get(key, 1.0) + per_level * level

            elif btype == "stealth":
                stealth_factor += per_level * level

            elif btype == "research_link":
                research_links += int(per_level * level)

            elif btype == "orbital_build_time":
                orbital_build_mult += per_level * level

            # "unlock" type has no numeric effect — handled by prereq checks

    return {
        "stat_multipliers": stat_multipliers,
        "weapon_power": weapon_power,
        "combat_stats": combat_stats,
        "fleet_count_bonus": fleet_count_bonus,
        "speed_multipliers": speed_multipliers,
        "stealth_factor": stealth_factor,
        "research_links": research_links,
        "orbital_build_time_mult": orbital_build_mult,
    }


def _user_has_capital(user) -> bool:
    """Check if any of the user's colonies has a Capital built. Cached per request."""
    cache = getattr(user, '_has_capital', None)
    if cache is not None:
        return cache
    result = any(get_building_level(c, "capital") > 0 for c in user.colonies)
    user._has_capital = result
    return result


def get_commander_bonus(db, skill_type):
    """Get the bonus_per_level for a commander skill, with game_config override support."""
    override = get_config(db, f"commander_{skill_type}_bonus")
    if override is not None:
        try:
            return float(override)
        except (ValueError, TypeError):
            pass
    spec = COMMANDER_SKILL_SPECS.get(skill_type)
    if spec:
        return spec.get("bonus_per_level", COMMANDER_BONUS_PER_LEVEL)
    return COMMANDER_BONUS_PER_LEVEL


def get_commander_level_at_base(db, colony_id, skill_type):
    """Get level of the assigned Base Commander with given skill at a base. Returns 0 if none."""
    if not colony_id:
        return 0
    cmdr = db.query(Commander).filter(
        Commander.colony_id == colony_id,
        Commander.is_assigned == True,
        Commander.skill_type == skill_type,
        Commander.is_traveling == False,
    ).first()
    return cmdr.level if cmdr else 0


def get_best_commander_level(db, user_id, skill_type):
    """Get highest level assigned commander of given skill across all bases."""
    cmdr = db.query(Commander).filter(
        Commander.user_id == user_id,
        Commander.skill_type == skill_type,
        Commander.is_assigned == True,
        Commander.is_traveling == False,
        Commander.colony_id != None,
    ).order_by(Commander.level.desc()).first()
    return cmdr.level if cmdr else 0


def project_resources_after_queue(colony, user, queue, db=None):
    """Project energy capacity, energy used, population, pop used, area, and area used
    after all items currently in the construction queue complete.

    This lets the queue validation be "smart" — if item #1 uses the last energy slot,
    item #2 correctly sees there's no energy left. Conversely, if item #1 is Solar Plants,
    item #2 sees the extra energy it will provide.

    Returns dict with: energy, energy_used, population, pop_used, area, area_used
    """
    # Start with current building levels
    projected_levels = {}
    for b in colony.buildings:
        projected_levels[b.building_type] = b.level

    # Start with current defense levels
    projected_def_levels = {}
    for d in colony.defenses:
        projected_def_levels[d.defense_type] = d.level

    # Apply queued items to get projected levels
    for q in queue:
        if q.item_category == 'building':
            projected_levels[q.item_type] = q.target_level
        elif q.item_category == 'defense':
            projected_def_levels[q.item_type] = q.target_level

    planet = colony.planet

    # Evaluate contributions from projected building levels (data-driven)
    all_specs = get_all_building_specs(db)
    s = _evaluate_contributions(projected_levels, planet, all_specs)

    tech_bonuses = evaluate_tech_bonuses(user)
    energy_mult = tech_bonuses["stat_multipliers"].get("energy", 1.0)
    energy_cap = s.get("energy", 0) + BASE_ENERGY_BONUS
    energy_cap = int(energy_cap * energy_mult)

    pop_cap = s.get("population", 0)
    area_cap = planet.area + s.get("area", 0)

    # Calculate projected usage from projected levels
    energy_used = 0
    pop_used = 0
    area_used = 0
    for btype, blevel in projected_levels.items():
        bspec = get_effective_building_spec(db, btype) if db else BUILDING_SPECS.get(btype, {})
        energy_used += bspec.get("energy_req", 0) * blevel
        pop_used += bspec.get("pop_req", 0) * blevel
        area_used += bspec.get("area_req", 0) * blevel

    # Defenses also consume energy, area, and population
    for dtype, dlevel in projected_def_levels.items():
        dspec = get_effective_defense_spec(db, dtype) if db else DEFENSE_SPECS.get(dtype, {})
        energy_used += dspec.get("energy_req", 0) * dlevel
        pop_used += dspec.get("pop_req", 0) * dlevel
        area_used += dspec.get("area_req", 0) * dlevel

    return {
        "energy": energy_cap, "energy_used": energy_used,
        "population": pop_cap, "pop_used": pop_used,
        "area": area_cap, "area_used": area_used,
    }

def _evaluate_contributions(building_levels, planet, all_specs):
    """Evaluate building contributions from specs to produce accumulated stats.
    building_levels: dict {building_type: level}
    planet: planet object (or dict-like with solar, gas, metal, crystal, fertility, area)
    all_specs: dict of all building specs (with contributions field)
    Returns dict of accumulated stat values.
    """
    stats = {}

    # First pass: accumulate fertility_modifier (needed before population calc)
    fertility_mod = 0
    for btype, level in building_levels.items():
        if level <= 0:
            continue
        spec = all_specs.get(btype, {})
        contribs = spec.get("contributions", {})
        fm = contribs.get("fertility_modifier")
        if fm:
            fertility_mod += fm.get("per_level", 0) * level

    effective_fertility = max((getattr(planet, 'fertility', 0) if hasattr(planet, 'fertility') else planet.get('fertility', 0)) + fertility_mod, 1)

    # Second pass: accumulate all other contributions
    for btype, level in building_levels.items():
        if level <= 0:
            continue
        spec = all_specs.get(btype, {})
        contribs = spec.get("contributions", {})
        for stat_name, contrib in contribs.items():
            if stat_name == "fertility_modifier":
                continue  # already handled
            ctype = contrib.get("type", "flat")
            per_level = contrib.get("per_level", 0)
            if ctype == "flat":
                stats[stat_name] = stats.get(stat_name, 0) + per_level * level
            elif ctype == "planet_stat":
                planet_stat = contrib.get("stat", "")
                # Use effective_fertility for fertility-based contributions
                if planet_stat == "fertility":
                    stat_val = effective_fertility
                elif hasattr(planet, planet_stat):
                    stat_val = getattr(planet, planet_stat, 0)
                else:
                    stat_val = planet.get(planet_stat, 0) if isinstance(planet, dict) else 0
                stats[stat_name] = stats.get(stat_name, 0) + per_level * level * stat_val

    return stats


def calc_base_stats(colony, user, game_speed=1.0):
    """Calculate base stats using data-driven building contributions.
    All building effects are defined in the 'contributions' field of each building spec.
    When game_speed > 1, construction/production/research rates are multiplied accordingly."""
    planet = colony.planet

    # Build levels dict from colony buildings
    building_levels = _building_dict(colony)

    # Get all building specs (with admin overrides)
    all_specs = get_all_building_specs(None)

    # Evaluate contributions from building specs
    s = _evaluate_contributions(building_levels, planet, all_specs)

    # Tech bonuses (data-driven from research spec bonuses)
    tech_bonuses = evaluate_tech_bonuses(user)
    stat_mults = tech_bonuses["stat_multipliers"]

    # Energy: building contributions + flat base bonus, scaled by energy tech
    energy = s.get("energy", 0) + BASE_ENERGY_BONUS
    energy = int(energy * stat_mults.get("energy", 1.0))

    # Population: directly from contributions (fertility_modifier already applied)
    population = s.get("population", 0)

    # Area: planet base area + building contributions
    area = planet.area + s.get("area", 0)

    # Industrial base feeds into BOTH construction and production
    industrial = s.get("industrial", 0)

    # Construction = industrial + base bonuses
    construction = industrial + CONSTRUCTION_BONUS_BASE
    is_home = getattr(colony, 'is_home_base', False)
    if not is_home:
        user_colony_ids = sorted([c.id for c in user.colonies])
        if user_colony_ids and colony.id == user_colony_ids[0]:
            is_home = True
    if is_home:
        construction += CONSTRUCTION_BONUS_HOMEWORLD

    # Production = industrial + production contributions from buildings (shipyard etc.)
    production = industrial + s.get("production", 0)

    # Apply stat multipliers from tech bonuses (e.g. cybernetics → construction+production)
    construction_mult = stat_mults.get("construction", 1.0)
    if construction_mult != 1.0:
        construction = int(construction * construction_mult)
    production_mult = stat_mults.get("production", 1.0)
    if production_mult != 1.0:
        production = int(production * production_mult)

    # Conquest mode (opt-in): an occupied base produces nothing for its owner.
    if getattr(colony, "occupied_by", None):
        from game_definition import get_game_definition
        _eng = (get_game_definition().get("engine", {}) or {})
        if str(_eng.get("occupation_zero_production", "")).strip().lower() in ("1", "true", "yes", "on"):
            production = 0

    # Economy: from contributions + capital empire bonus + occupation penalty
    economy = s.get("economy", 0)
    capital_lv = building_levels.get("capital", 0)
    if capital_lv == 0 and _user_has_capital(user):
        economy += CAPITAL_EMPIRE_BONUS
    economy_penalty = getattr(colony, 'economy_penalty', 0) or 0
    if economy_penalty > 0:
        economy = max(0, economy - economy_penalty)

    # Research: from contributions, scaled by research tech multiplier (AI tech)
    research = s.get("research", 0)
    research_mult = stat_mults.get("research", 1.0)
    if research_mult != 1.0:
        research = int(research * research_mult)

    # Per-resource production (multi-resource economies, e.g. metal/crystal/
    # deuterium). Buildings contribute to a resource by naming it as the stat
    # (contributions: {"metal": {"type": "flat", "per_level": N}}), which the
    # generic contribution evaluator already accumulates into `s`. In single-
    # resource mode this stays empty and income flows through `economy`.
    resource_income = {}
    if get_resource_model() == "multi":
        for rt in get_resource_types():
            resource_income[rt] = max(0, s.get(rt, 0))

    # Game speed multiplier
    if game_speed != 1.0:
        economy = int(economy * game_speed)
        construction = int(construction * game_speed)
        production = int(production * game_speed)
        research = int(research * game_speed)
        resource_income = {rt: int(v * game_speed) for rt, v in resource_income.items()}

    return {
        "economy": economy,
        "resource_income": resource_income,
        "construction": construction,
        "production": production,
        "research": research,
        "energy": energy,
        "population": population,
        "area": area,
        "shipyard_level": s.get("shipyard_level", 0),
        "ground_shipyard": s.get("ground_shipyard", 0),
        "orbital_shipyard": s.get("orbital_shipyard", 0),
        "research_lab_level": s.get("research_lab_level", 0),
        "command_level": s.get("command_level", 0),
        "jump_gate_level": s.get("jump_gate_level", 0),
    }

def calc_building_cost(db, building_type: str, current_level: int, base_stats: dict, game_speed: float, is_occupied: bool = False, colony_id: int = None, user=None):
    """Returns (cost, build_time_seconds).
    Cost is scalar (single-resource) or dict (multi-resource).
    Build time formula: time_hours = total_cost_value / construction. Occupied bases +30%.
    Construction commander: -1% cost per level (time reduces because cost is lower).
    Anti-Gravity tech: -5% build time per level for orbital buildings (area_req == 0)."""
    from resources import scale_cost, total_cost_value
    spec = get_effective_building_spec(db, building_type)
    base_cost = spec["base_cost"]  # scalar or dict
    cost = scale_cost(base_cost, spec["cost_mult"] ** current_level)
    # Construction commander reduces cost; time follows since time = cost / rate
    if colony_id:
        cc_lv = get_commander_level_at_base(db, colony_id, "construction")
        if cc_lv > 0:
            cost = scale_cost(cost, 1 - cc_lv * get_commander_bonus(db, "construction"))
    construction_rate = max(base_stats.get("construction", 1), 1)
    cost_value = total_cost_value(cost)
    build_time = (cost_value / construction_rate) * 3600
    if is_occupied:
        build_time *= OCCUPATION_TIME_PENALTY  # 30% penalty
    # Anti-Gravity: reduce build time for orbital buildings (area_req == 0)
    if user and spec.get("area_req", 1) == 0:
        tech_bonuses = evaluate_tech_bonuses(user, db)
        orbital_mult = tech_bonuses.get("orbital_build_time_mult", 1.0)
        if orbital_mult < 1.0:
            build_time *= orbital_mult
    import math
    if isinstance(cost, dict):
        cost = {k: int(math.ceil(v)) for k, v in cost.items()}
    else:
        cost = int(math.ceil(cost))
    return cost, max(MIN_BUILD_TIME_SECONDS, int(math.ceil(build_time)))

def calc_research_cost(db, tech_type: str, current_level: int, game_speed: float, base_lab_capacity: int, is_occupied: bool = False, colony_id: int = None):
    """Returns (cost, research_time_seconds).
    Cost is scalar (single-resource) or dict (multi-resource).
    Research time formula: time_hours = total_cost_value / research_capacity. Occupied bases +30%.
    Research commander: -1% cost per level (at this base only; time reduces because cost is lower)."""
    from resources import scale_cost, total_cost_value
    spec = get_effective_research_spec(db, tech_type)
    base_cost = spec["base_cost"]  # scalar or dict
    cost = scale_cost(base_cost, spec["cost_mult"] ** current_level)
    # Research commander at this base reduces cost; time follows since time = cost / rate
    if colony_id:
        rc_lv = get_commander_level_at_base(db, colony_id, "research")
        if rc_lv > 0:
            cost = scale_cost(cost, 1 - rc_lv * get_commander_bonus(db, "research"))
    lab_factor = max(base_lab_capacity, 1)
    cost_value = total_cost_value(cost)
    research_time = (cost_value / lab_factor) * 3600
    if is_occupied:
        research_time *= OCCUPATION_TIME_PENALTY
    import math
    if isinstance(cost, dict):
        cost = {k: int(math.ceil(v)) for k, v in cost.items()}
    else:
        cost = int(math.ceil(cost))
    return cost, max(MIN_RESEARCH_TIME_SECONDS, int(math.ceil(research_time)))

def calc_defense_cost(db, defense_type: str, current_level: int, game_speed: float, count: int = 1):
    """Calculate defense build cost.

    Level model: cost = base_cost * cost_mult^current_level, builds 1 level
    Count model: cost = base_cost * count, builds N units at flat cost

    Returns (cost, build_time_seconds, units_built).
    """
    from resources import scale_cost, total_cost_value
    from game_definition import get_game_definition
    dspec = get_effective_defense_spec(db, defense_type)
    game_def = get_game_definition()
    defense_model = game_def.get("engine", {}).get("defense_model", "level")

    if defense_model == "count":
        unit_cost = dspec["cost"]  # scalar or dict
        cost = scale_cost(unit_cost, count)
        cost_value = total_cost_value(cost)
        build_time = (cost_value * 5 / game_speed)  # time scales with total cost
        units_built = count
    else:
        cost_mult = dspec.get("cost_mult", 1.5)
        cost = scale_cost(dspec["cost"], cost_mult ** current_level)
        cost_value = total_cost_value(cost)
        build_time = (cost_value * 5 / game_speed)
        units_built = 1

    if isinstance(cost, dict):
        cost = {k: int(math.ceil(v)) for k, v in cost.items()}
    else:
        cost = int(math.ceil(cost))
    return cost, max(5, int(math.ceil(build_time))), units_built


def get_defense_model() -> str:
    """Get the active defense model from game definition."""
    from game_definition import get_game_definition
    return get_game_definition().get("engine", {}).get("defense_model", "level")


def calc_economy_rate(colony, user, game_speed: float) -> float:
    """Income value per hour for a colony, as a single aggregate number (game
    speed baked in). Single-resource: the credits economy. Multi-resource: the
    summed per-resource production, so rankings/trade keep a scalar to work with."""
    stats = calc_base_stats(colony, user, game_speed)
    if get_resource_model() == "multi":
        return sum(stats.get("resource_income", {}).values())
    return stats["economy"]

def calc_trade_income(base_a, base_b, distance: float, num_players: int,
                      speed_mult: float = 1.0) -> float:
    """Trade income formula.
    Trade Income = Sqrt(Lowest base's economy × speed_mult) × [1 + Sqrt(2×Distance)/75 + Sqrt(Players)/10]
    Self-trades (same owner) give 2× income.
    num_players: number of players in the owner's trade network.
    speed_mult: matches game speed (1.0 normal, 3.0 for ×3 speed servers, etc).
    """
    econ_a = calc_base_stats(base_a, base_a.user, speed_mult)["economy"]
    econ_b = calc_base_stats(base_b, base_b.user, speed_mult)["economy"]
    lowest = min(econ_a, econ_b)
    income = math.sqrt(max(lowest, 1)) * (
        1 + math.sqrt(2 * distance) / TRADE_DISTANCE_DIVISOR + math.sqrt(max(num_players, 0)) / TRADE_PLAYERS_DIVISOR
    )
    # Self-trade bonus: both bases owned by same player → 2× income
    if base_a.user_id == base_b.user_id:
        income *= SELF_TRADE_BONUS_MULT
    return math.ceil(income)

def calc_tech_cost(user, db: Session) -> float:
    """Total technology cost invested (geometric series: base_cost * (cost_mult^level - 1) / (cost_mult - 1))."""
    total = 0
    for r in user.research:
        if r.level <= 0:
            continue
        spec = get_effective_research_spec(db, r.tech_type)
        base = spec.get("base_cost", 0)
        mult = spec.get("cost_mult", 1.5)
        if mult == 1:
            total += base * r.level
        else:
            total += base * (mult ** r.level - 1) / (mult - 1)
    return total

def calc_player_level(user, db: Session, game_speed: float) -> float:
    """Player level = (Economy×100 + Fleet + Technology) ^ 0.25"""
    total_econ = sum(calc_economy_rate(c, user, game_speed) for c in user.colonies)
    total_fleet = sum(_fleet_value(f, db) for f in user.fleets)
    total_tech = calc_tech_cost(user, db)
    raw = total_econ * PLAYER_LEVEL_ECONOMY_MULT + total_fleet + total_tech
    return round(max(1, raw ** PLAYER_LEVEL_EXPONENT), 2)

def calc_colony_cost(user) -> float:
    """Escalating base cost: each new base costs more.

    Rebuild discount: while the player holds fewer bases than their peak
    (e.g. after disbanding), the next base costs only COLONY_REBUILD_DISCOUNT
    of normal until they climb back to their previous base count.
    This is the gross price; any base_reserve is applied on top at purchase."""
    base_count = len(user.colonies)
    # Colony cost table (Base 2 through Base 25)
    cost_table = [100, 200, 500, 1_000, 2_000, 5_000, 10_000, 20_000, 50_000,
                  100_000, 200_000, 400_000, 650_000, 1_000_000, 1_500_000,
                  2_500_000, 4_000_000, 6_500_000, 10_000_000, 15_000_000,
                  25_000_000, 40_000_000, 65_000_000, 100_000_000]
    idx = max(0, base_count - 1)  # first colony is free (homeworld)
    full = float(cost_table[idx]) if idx < len(cost_table) else float(cost_table[-1])
    peak = getattr(user, "bases_founded_peak", 0) or 0
    if base_count < peak:
        return full * COLONY_REBUILD_DISCOUNT
    return full


def apply_colony_reserve(user, gross: float):
    """Apply the player's base_reserve to a gross colony cost.
    Returns (net_credits_due, reserve_used). Does NOT mutate the user."""
    reserve = getattr(user, "base_reserve", 0.0) or 0.0
    used = min(reserve, max(gross, 0.0))
    return max(gross - used, 0.0), used


def structure_refund_value(db, kind: str, type_key: str, from_level: int, to_level: int = None) -> float:
    """Reserve credits gained by downgrading a structure from `from_level` down to
    `to_level` (default: one level). Refunds STRUCTURE_DOWNGRADE_REFUND_PERCENT of the
    raw build cost of each level removed. `kind` is 'building' or 'defense'."""
    from resources import scale_cost, total_cost_value
    if to_level is None:
        to_level = from_level - 1
    if from_level <= to_level:
        return 0.0
    if kind == "defense":
        spec = get_effective_defense_spec(db, type_key)
        base_cost = spec["cost"]
        cost_mult = spec.get("cost_mult", 1.5)
    else:
        spec = get_effective_building_spec(db, type_key)
        base_cost = spec["base_cost"]
        cost_mult = spec.get("cost_mult", 1.5)
    total = 0.0
    for lvl in range(to_level + 1, from_level + 1):  # cost of each level removed (level lvl built at exponent lvl-1)
        total += total_cost_value(scale_cost(base_cost, cost_mult ** (lvl - 1)))
    return total * STRUCTURE_DOWNGRADE_REFUND_PERCENT

def calc_total_production(user, game_speed: float) -> int:
    """Total production across all bases."""
    total = 0
    for colony in user.colonies:
        stats = calc_base_stats(colony, user, game_speed)
        total += stats["production"]
    return total

def calc_max_fleet_size(user, game_speed: float) -> int:
    """Fleet size limit: Total Production × 2500"""
    return calc_total_production(user, game_speed) * FLEET_SIZE_LIMIT_MULTIPLIER


def calc_max_fleet_count(user, db=None) -> int:
    """Maximum number of separate fleets. Uses data-driven fleet_count_bonus from tech bonuses."""
    tech_bonuses = evaluate_tech_bonuses(user, db)
    fleet_bonus = tech_bonuses["fleet_count_bonus"]
    num_bases = len(user.colonies) if user.colonies else 0
    # +1 slot per base you are occupying
    occupied_count = 0
    if db:
        occupied_count = db.query(Colony).filter(Colony.occupied_by == user.id).count()
    return num_bases + occupied_count + fleet_bonus

def check_hangar_capacity(fleet, db) -> dict:
    """Check if fleet has enough hangar space for carried ships.
    Negative hangar values mean the ship consumes carrier space."""
    hangar_needed = 0
    hangar_available = 0
    for st in ALL_SHIP_TYPES:
        count = fleet.get_ship_count(st)
        if count <= 0:
            continue
        spec = get_effective_ship_spec(db, st)
        if spec["hangar"] < 0:
            hangar_needed += count * abs(spec["hangar"])
        elif spec["hangar"] > 0:
            hangar_available += count * spec["hangar"]
    return {"needed": hangar_needed, "available": hangar_available, "ok": hangar_available >= hangar_needed}

def is_capital_occupied(user) -> bool:
    """Check if the player's Capital base is occupied by an enemy."""
    for colony in user.colonies:
        if get_building_level(colony, "capital") > 0 and colony.occupied_by:
            return True
    return False

def collect_resources(user, db: Session, game_speed: float, include_completions: bool = True):
    """Collect hourly income for a user.

    By default this also advances construction/research completions, which is
    useful for request-driven gameplay. Background income sweeps can disable
    queue advancement because the dedicated queue tick already handles that.
    """
    now = datetime.utcnow()
    # Action-point ("Turns") economy accrues lazily alongside income (no-op when
    # the option is off). Actions that don't pass through here accrue on debit.
    import action_points
    action_points.accrue_action_points(user, db, now)
    total_earned = 0.0
    max_ticks = 0
    multi = get_resource_model() == "multi"
    resource_earned = {}  # per-resource income (multi-resource economies)

    # Credits are awarded once per hour at :00 — count how many :00 boundaries passed
    # Use atomic UPDATE with WHERE to prevent double-collection from concurrent requests
    for colony in user.colonies:
        last = colony.last_collected
        next_tick = last.replace(minute=0, second=0, microsecond=0) + timedelta(hours=1)
        ticks = 0
        while next_tick <= now:
            ticks += 1
            next_tick += timedelta(hours=1)
        if ticks > 0:
            # Atomic: only update if last_collected hasn't changed (prevents race condition)
            rows_updated = db.query(Colony).filter(
                Colony.id == colony.id,
                Colony.last_collected == last,
            ).update({"last_collected": now}, synchronize_session=False)
            if rows_updated == 0:
                continue  # Another worker already collected for this colony
            db.flush()
            db.refresh(colony)
            rate = calc_economy_rate(colony, user, game_speed)
            total_earned += rate * ticks
            if multi:
                inc = calc_base_stats(colony, user, game_speed).get("resource_income", {})
                for rt, amt in inc.items():
                    resource_earned[rt] = resource_earned.get(rt, 0) + amt * ticks
            max_ticks = max(max_ticks, ticks)
        _update_unrest(colony, db)

    # Trade route income: use per-colony ticks via max_ticks
    if max_ticks > 0:
        trade_routes = db.query(TradeRoute).filter(
            TradeRoute.owner_id == user.id, TradeRoute.is_closing == False
        ).all()
        for tr in trade_routes:
            total_earned += tr.income * max_ticks
        _process_occupation_income(user, db, game_speed)
        # Capital occupied penalty: -15% empire income when Capital base is occupied
        capital_occupied = is_capital_occupied(user)
        if capital_occupied:
            total_earned *= (1 - CAPITAL_OCCUPIED_PENALTY)
        if multi:
            # Multi-resource economies pay differentiated per-resource production
            # directly (total_earned remains the aggregate used for reporting).
            if capital_occupied:
                resource_earned = {rt: int(v * (1 - CAPITAL_OCCUPIED_PENALTY))
                                   for rt, v in resource_earned.items()}
            if any(v > 0 for v in resource_earned.values()):
                add_resources(user, resource_earned)
                log_credits(db, user.id, sum(resource_earned.values()), "Empire Income", "income")
        else:
            add_resources(user, total_earned)
            if total_earned > 0:
                log_credits(db, user.id, total_earned, "Empire Income", "income")

    # Commander XP: earned from combat, spent on upgrades (no passive gain)
    # (XP awarded in combat.py when battles occur)

    # Check and complete constructions / research when requested by the caller.
    if include_completions:
        _check_completions(user, db, now)
    db.commit()
    mod_hooks.fire("on_economy_collect", {
        "user": user, "db": db, "game_speed": game_speed,
        "total_earned": total_earned, "now": now,
    })
    return total_earned

def _check_completions(user, db, now):
    """Advance all queues — construction, defense, and research.
    All completions go through the queue system."""
    for colony in user.colonies:
        _advance_construction_queue(colony, user, db, now)
    _advance_research_queue(user, db, now)
    _process_commander_arrivals(user, db, now)


def _process_commander_arrivals(user, db, now):
    """Complete commander travel — set is_traveling=False when arrival_time has passed."""
    traveling = db.query(Commander).filter(
        Commander.user_id == user.id,
        Commander.is_traveling == True,
        Commander.arrival_time != None,
        Commander.arrival_time <= now,
    ).all()
    for cmdr in traveling:
        cmdr.is_traveling = False
        cmdr.arrival_time = None

    # Complete commander training
    training = db.query(Commander).filter(
        Commander.user_id == user.id,
        Commander.is_training == True,
        Commander.training_complete_time != None,
        Commander.training_complete_time <= now,
    ).all()
    for cmdr in training:
        cmdr.level += 1
        cmdr.is_training = False
        cmdr.training_complete_time = None


def _advance_construction_queue(colony, user, db, now):
    """Check if the active construction queue item is done, complete it,
    and start the next queued item."""
    queue = (db.query(ConstructionQueue)
             .filter(ConstructionQueue.colony_id == colony.id,
                     ConstructionQueue.user_id == user.id)
             .order_by(ConstructionQueue.position)
             .all())
    if not queue:
        # Clear stale is_constructing flags on buildings/defenses with no queue
        for b in colony.buildings:
            if b.is_constructing:
                b.is_constructing = False
                b.construction_end = None
        for d in colony.defenses:
            if d.is_constructing:
                d.is_constructing = False
                d.construction_end = None
        return

    # Complete all finished items and start next
    changed = True
    while changed:
        changed = False
        active = next((q for q in queue if q.position == 0), None)
        if not active:
            if queue:
                queue.sort(key=lambda q: q.position)
                for i, q in enumerate(queue):
                    q.position = i
                changed = True
                continue
            break
        # Safety: if position 0 has no finish_at, it's stalled — start it now
        if not active.finish_at:
            if not can_afford(user, active.cost):
                break  # Can't afford — wait until player has resources
            deduct_cost(user, active.cost)
            log_credits(db, user.id, -total_cost_value(active.cost), f"Construction: {active.item_type} Lv{active.target_level}", "construction")
            active.started_at = now
            active.finish_at = now + timedelta(seconds=active.build_time)
            if active.item_category == 'building':
                building = next((b for b in colony.buildings if b.building_type == active.item_type), None)
                if building:
                    building.is_constructing = True
                    building.construction_end = active.finish_at
            elif active.item_category == 'defense':
                defense = next((d for d in colony.defenses if d.defense_type == active.item_type), None)
                if defense:
                    defense.is_constructing = True
                    defense.construction_end = active.finish_at
            changed = True
            continue
        if active.finish_at <= now:
            # Complete this item
            if active.item_category == 'building':
                building = next((b for b in colony.buildings if b.building_type == active.item_type), None)
                if building:
                    building.level = active.target_level
                    building.is_constructing = False
                    building.construction_end = None
                    colony._blv_cache = None  # invalidate building level cache
                    if active.item_type == 'capital':
                        user._has_capital = None
            elif active.item_category == 'defense':
                defense = next((d for d in colony.defenses if d.defense_type == active.item_type), None)
                if defense:
                    defense.level = active.target_level
                    defense.is_constructing = False
                    defense.construction_end = None
            db.delete(active)
            queue.remove(active)
            # Promote remaining items
            for q in queue:
                q.position -= 1
            # Start the new position-0 item
            new_active = next((q for q in queue if q.position == 0), None)
            if new_active:
                if not can_afford(user, new_active.cost):
                    break  # Can't afford next item — wait
                deduct_cost(user, new_active.cost)
                log_credits(db, user.id, -total_cost_value(new_active.cost), f"Construction: {new_active.item_type} Lv{new_active.target_level}", "construction")
                new_active.started_at = now
                new_active.finish_at = now + timedelta(seconds=new_active.build_time)
                # Mark the actual building/defense as constructing
                if new_active.item_category == 'building':
                    building = next((b for b in colony.buildings if b.building_type == new_active.item_type), None)
                    if building:
                        building.is_constructing = True
                        building.construction_end = new_active.finish_at
                elif new_active.item_category == 'defense':
                    defense = next((d for d in colony.defenses if d.defense_type == new_active.item_type), None)
                    if defense:
                        defense.is_constructing = True
                        defense.construction_end = new_active.finish_at
            changed = True


def _get_actively_researching_techs(user, db):
    """Return set of tech_types that have an active (position=0, started) research anywhere."""
    active_items = db.query(ResearchQueue.tech_type).filter(
        ResearchQueue.user_id == user.id,
        ResearchQueue.position == 0,
        ResearchQueue.finish_at != None,
    ).all()
    return {row[0] for row in active_items}

def _advance_research_queue(user, db, now):
    """Advance per-base research queues. Each base has its own queue.
    Constraint: only one base can actively research a given tech at a time."""
    for colony in user.colonies:
        _advance_colony_research_queue(colony, user, db, now)

def _advance_colony_research_queue(colony, user, db, now):
    """Advance a single colony's research queue."""
    queue = (db.query(ResearchQueue)
             .filter(ResearchQueue.user_id == user.id,
                     ResearchQueue.colony_id == colony.id)
             .order_by(ResearchQueue.position)
             .all())
    if not queue:
        return

    changed = True
    while changed:
        changed = False
        active = next((q for q in queue if q.position == 0), None)
        if not active:
            if queue:
                queue.sort(key=lambda q: q.position)
                for i, q in enumerate(queue):
                    q.position = i
                changed = True
                continue
            break
        # Safety: if position 0 has no finish_at, it's stalled — try to start it
        if not active.finish_at:
            # Check: is another base already actively researching this tech?
            active_techs = _get_actively_researching_techs(user, db)
            if active.tech_type in active_techs:
                break  # Another base is researching this tech — wait
            if not can_afford(user, active.cost):
                break  # Can't afford — wait until player has resources
            deduct_cost(user, active.cost)
            log_credits(db, user.id, -total_cost_value(active.cost), f"Research: {active.tech_type} Lv{active.target_level}", "research")
            active.started_at = now
            active.finish_at = now + timedelta(seconds=active.research_time)
            r = next((r for r in user.research if r.tech_type == active.tech_type), None)
            if r:
                r.is_researching = True
                r.research_end = active.finish_at
            changed = True
            continue
        if active.finish_at <= now:
            # Complete this research
            completed_tech = active.tech_type
            completed_level = active.target_level
            r = next((r for r in user.research if r.tech_type == active.tech_type), None)
            if r:
                r.level = active.target_level
                r.is_researching = False
                r.research_end = None
                user._tech_cache = None  # invalidate tech level cache
            db.delete(active)
            queue.remove(active)
            db.flush()
            mod_hooks.fire("on_research_completed", {
                "user": user, "colony": colony, "db": db,
                "tech_type": completed_tech, "level": completed_level, "now": now,
            })
            # Promote remaining items in this colony's queue
            for q in queue:
                q.position -= 1
            # Try to start the new position-0 item
            new_active = next((q for q in queue if q.position == 0), None)
            if new_active:
                # Check tech conflict before starting
                active_techs = _get_actively_researching_techs(user, db)
                if new_active.tech_type in active_techs:
                    changed = True
                    continue  # Can't start — another base is researching this tech
                if not can_afford(user, new_active.cost):
                    break  # Can't afford next item — wait
                deduct_cost(user, new_active.cost)
                log_credits(db, user.id, -total_cost_value(new_active.cost), f"Research: {new_active.tech_type} Lv{new_active.target_level}", "research")
                new_active.started_at = now
                new_active.finish_at = now + timedelta(seconds=new_active.research_time)
                r = next((r for r in user.research if r.tech_type == new_active.tech_type), None)
                if r:
                    r.is_researching = True
                    r.research_end = new_active.finish_at
            changed = True

def _merge_fleet_into(source, target):
    """Merge all ships from source fleet into target fleet, including damage state."""
    import json as _json
    for st in ALL_SHIP_TYPES:
        src_count = source.get_ship_count(st)
        if src_count > 0:
            tgt_count = target.get_ship_count(st)
            target.set_ship_count(st, tgt_count + src_count)
    # Merge damage states — if both have a damaged unit of the same type,
    # keep the worst-damaged one (lowest health fraction)
    src_dmg = _json.loads(source.ship_damage or "{}")
    tgt_dmg = _json.loads(target.ship_damage or "{}")
    for st, frac in src_dmg.items():
        if st in tgt_dmg:
            tgt_dmg[st] = min(tgt_dmg[st], frac)
        else:
            tgt_dmg[st] = frac
    target.ship_damage = _json.dumps(tgt_dmg) if tgt_dmg else "{}"

def _fleet_is_empty(fleet):
    """Check if a fleet has zero total ships."""
    return fleet.get_total_ships() == 0

def _cleanup_empty_fleets(user, db):
    """Delete any fleets with 0 ships that are not moving."""
    for fleet in list(user.fleets):
        if not fleet.is_moving and _fleet_is_empty(fleet):
            db.delete(fleet)

def _process_fleet_arrivals(user, db):
    """Move arrived fleets to their destination, merge with existing fleets, and clean up empties."""
    now = datetime.utcnow()
    for fleet in list(user.fleets):
        if fleet.is_moving and fleet.arrival_time and fleet.arrival_time <= now:
            arrival_moment = fleet.arrival_time or now
            fleet.is_moving = False
            fleet.arrival_time = None
            fleet.origin_base_id = None
            fleet.origin_planet_id = None
            if fleet.is_autoscout:
                # Start dwell from the scheduled arrival time, not the later processing tick.
                fleet.autoscout_last_move = arrival_moment

            if fleet.destination_base_id:
                # Arriving at a colony — verify it still exists
                colony = db.query(Colony).filter(Colony.id == fleet.destination_base_id).first()
                if colony:
                    fleet.base_id = fleet.destination_base_id
                    fleet.destination_base_id = None
                    fleet.location_planet_id = None
                else:
                    # Colony was abandoned mid-flight — land on the planet instead
                    fleet.base_id = None
                    fleet.location_planet_id = fleet.destination_planet_id
                    fleet.destination_base_id = None
                    fleet.destination_planet_id = None
                    colony = None
                if colony and colony.planet:
                    _record_region_snapshot(user.id, colony.planet.system.region_id, db)

                # Merge with existing stationed fleet at this base (skip autoscouts)
                if not fleet.is_autoscout:
                    existing = db.query(Fleet).filter(
                        Fleet.user_id == user.id,
                        Fleet.base_id == fleet.base_id,
                        Fleet.is_moving == False,
                        Fleet.is_autoscout == False,
                        Fleet.id != fleet.id
                    ).first()
                    if existing:
                        _merge_fleet_into(fleet, existing)
                        db.delete(fleet)
                        continue

            elif fleet.destination_planet_id:
                # Arriving at an uncolonized planet
                fleet.location_planet_id = fleet.destination_planet_id
                fleet.destination_planet_id = None
                fleet.base_id = None
                planet = db.query(Planet).filter(Planet.id == fleet.location_planet_id).first()
                if planet:
                    _record_region_snapshot(user.id, planet.system.region_id, db)

                # Merge with existing stationed fleet at this planet (skip autoscouts)
                if not fleet.is_autoscout:
                    existing = db.query(Fleet).filter(
                        Fleet.user_id == user.id,
                        Fleet.location_planet_id == fleet.location_planet_id,
                        Fleet.is_moving == False,
                        Fleet.is_autoscout == False,
                        Fleet.id != fleet.id
                    ).first()
                    if existing:
                        _merge_fleet_into(fleet, existing)
                        db.delete(fleet)
                        continue

            # Delete if empty after arrival
            if _fleet_is_empty(fleet):
                db.delete(fleet)

    # Also clean up any other empty fleets
    _cleanup_empty_fleets(user, db)
    db.commit()

def _process_ship_queues(user, db, game_speed):
    """Process ship build queues: all ships in a batch are delivered at once
    when the total timer expires (not one at a time). Then advance the queue."""
    now = datetime.utcnow()
    queues = db.query(ShipQueue).filter(ShipQueue.user_id == user.id).order_by(ShipQueue.colony_id, ShipQueue.position).all()
    completed_bases = set()
    for q in queues:
        pos = getattr(q, 'position', 0) or 0
        if pos != 0 or q.built >= q.count:
            continue
        # Fix stuck items: position 0 with started_at but no next_complete
        if not q.next_complete and q.started_at:
            colony = db.query(Colony).filter(Colony.id == q.colony_id).first()
            if colony:
                remaining = q.count - q.built
                per_ship = _ship_build_time(q.ship_type, colony, user, game_speed, db)
                q.next_complete = q.started_at + timedelta(seconds=per_ship * remaining)
                db.flush()
        if not q.next_complete:
            continue
        # Check if the batch timer has elapsed
        if q.next_complete <= now:
            # Deliver all ships at once
            remaining = q.count - q.built
            is_goods = q.ship_type == "goods"
            ship_name = GOODS_SPEC["name"] if is_goods else get_effective_ship_spec(db, q.ship_type).get('name', q.ship_type)

            # Goods auto-sell on completion
            if is_goods:
                sell_price = GOODS_SPEC["sell_price"]
                add_resources(user, sell_price * remaining)
                log_credits(db, user.id, sell_price * remaining, f"Sale of {q.count}x {ship_name}", "production")
                log_event(db, user.id, "construction",
                          f"Completed {q.count}x {ship_name} — sold for {sell_price * remaining} cr")
            else:
                fleet = db.query(Fleet).filter(
                    Fleet.user_id == user.id,
                    Fleet.base_id == q.colony_id,
                    Fleet.is_moving == False
                ).first()
                if not fleet:
                    fleet = Fleet(name="Production Fleet", user_id=user.id, base_id=q.colony_id)
                    db.add(fleet)
                    db.flush()
                ships_before = fleet.get_all_ship_counts()
                current = fleet.get_ship_count(q.ship_type)
                fleet.set_ship_count(q.ship_type, current + remaining)
                user.score += remaining
                log_fleet_change(db, user.id, fleet, "build", ships_before, f"Built {remaining}x {ship_name}")
                log_event(db, user.id, "construction",
                          f"Completed {q.count}x {ship_name}")
            completed_bases.add(q.colony_id)
            db.delete(q)

    # Advance queues for bases that had completions
    if completed_bases:
        db.flush()
        for base_id in completed_bases:
            remaining_q = (db.query(ShipQueue)
                           .filter(ShipQueue.colony_id == base_id, ShipQueue.user_id == user.id)
                           .order_by(ShipQueue.position).all())
            for i, qi in enumerate(remaining_q):
                qi.position = i
            # Start the new position 0 item (credits already paid upfront)
            if remaining_q:
                nxt = remaining_q[0]
                if nxt.started_at is None:
                    ship_name = GOODS_SPEC["name"] if nxt.ship_type == "goods" else get_effective_ship_spec(db, nxt.ship_type).get('name', nxt.ship_type)
                    colony = db.query(Colony).filter(Colony.id == base_id).first()
                    per_ship_time = _ship_build_time(nxt.ship_type, colony, user, game_speed, db)
                    total_time = per_ship_time * nxt.count
                    nxt.started_at = now
                    nxt.next_complete = now + timedelta(seconds=total_time)
                    log_event(db, user.id, "construction",
                              f"Started building {nxt.count}x {ship_name} at {colony.name if colony else '?'}")
    db.commit()


def _ship_build_time(ship_type, colony, user, game_speed, db):
    """Calculate build time for a single ship/goods in seconds.
    Build time formula: time_hours = ship_cost / production. Minimum 10 seconds.
    """
    if ship_type == "goods":
        cost = GOODS_SPEC["cost"]
    else:
        spec = get_effective_ship_spec(db, ship_type)
        cost = spec.get("cost", 10)
    stats = calc_base_stats(colony, user, game_speed)
    production = max(1, stats.get("production", 1))
    occupation_mult = OCCUPATION_TIME_PENALTY if colony.occupied_by else 1.0
    time_s = (total_cost_value(cost) / production) * 3600 * occupation_mult
    # Production commander bonus: -X% build time per level
    prod_lv = get_commander_level_at_base(db, colony.id, "production")
    if prod_lv > 0:
        time_s *= (1 - prod_lv * get_commander_bonus(db, "production"))
    return max(10, time_s)


def _calc_distance(planet_a, planet_b):
    """Calculate Pythagorean distance between two planets.

    Coordinate format: {galaxy}:{region}:{system}:{astro}
    The 2D grid position within a galaxy is:
        x = region_grid_x * 10 + system_x   (system_x = first digit of system name)
        y = region_grid_y * 10 + system_y   (system_y = second digit of system name)

    Same system: orbit difference (min 1)
    Same galaxy, different system: ceil(sqrt(dx² + dy²)), minimum 2
    Same cluster, different galaxy: 200
    Cross-cluster: 1000

    Graph map topology (engine.map_topology == "graph"): distance is the
    shortest-path cost over SystemLink edges, scaled by the configured
    per-hop distance. Same-system stays an orbit difference.
    """
    import math

    # Graph map: shortest-path over links. The session is pulled off the planet
    # object so this stays a drop-in for all callers (no signature change).
    try:
        import graph_map
        from sqlalchemy.orm import object_session
        _db = object_session(planet_a)
        if _db is not None and graph_map.is_graph_map(_db):
            sa, sb = planet_a.system_id, planet_b.system_id
            if sa == sb:
                return max(1, abs((planet_a.orbit_position or 1) - (planet_b.orbit_position or 1)))
            hops = graph_map.graph_distance(sa, sb, _db)
            if hops == math.inf:
                return 999999  # unreachable (shouldn't happen with the connectivity guarantee)
            hop_distance = float(graph_map.graph_config(_db).get("hop_distance", 15))
            return max(2, hops * hop_distance)
    except Exception:
        pass  # fall back to hierarchy distance on any graph-mode error

    reg_a = planet_a.system.region
    reg_b = planet_b.system.region
    gal_a = reg_a.galaxy
    gal_b = reg_b.galaxy

    if gal_a.id == gal_b.id:
        # Same galaxy — Pythagorean distance on the 2D grid
        # System name is 2-digit grid position: first digit = x, second = y
        sys_a_name = planet_a.system.name  # e.g. "23" → x=2, y=3
        sys_b_name = planet_b.system.name

        sys_a_x = int(sys_a_name[0]) if len(sys_a_name) >= 2 else 0
        sys_a_y = int(sys_a_name[1]) if len(sys_a_name) >= 2 else 0
        sys_b_x = int(sys_b_name[0]) if len(sys_b_name) >= 2 else 0
        sys_b_y = int(sys_b_name[1]) if len(sys_b_name) >= 2 else 0

        # Orbit as fractional offset within the system (orbit 1-5 → 0.1-0.5)
        orbit_a = (planet_a.orbit_position or 1) * 0.1
        orbit_b = (planet_b.orbit_position or 1) * 0.1

        # Global 2D position within the galaxy (orbits add a fractional component)
        x1 = reg_a.grid_x * 10 + sys_a_x + orbit_a
        y1 = reg_a.grid_y * 10 + sys_a_y
        x2 = reg_b.grid_x * 10 + sys_b_x + orbit_b
        y2 = reg_b.grid_y * 10 + sys_b_y

        dist = math.sqrt((x2 - x1) ** 2 + (y2 - y1) ** 2)

        # Same system: fractional distance (e.g. 0.1-0.4 between orbits)
        # Cross-system: minimum 1
        if planet_a.system_id == planet_b.system_id:
            return round(max(0.1, dist), 1)
        return round(max(1, dist), 1)

    # Different galaxies — distance per the galaxy-network topology
    # (ring / equal_distance / line / pumpkin / wormhole_only).
    import galaxy_network
    return galaxy_network.galaxy_distance(gal_a, gal_b)

def _process_occupation_income(user, db, game_speed):
    """Collect 30% income from bases this user occupies (hourly tick-based)."""
    occupied = db.query(Colony).filter(Colony.occupied_by == user.id).all()
    now = datetime.utcnow()
    total = 0.0
    for colony in occupied:
        owner = colony.user
        if not owner:
            continue  # owner deleted or abandoned — skip
        # Use same hourly tick boundary as main income
        last = colony.last_collected
        next_tick = last.replace(minute=0, second=0, microsecond=0) + timedelta(hours=1)
        ticks = 0
        while next_tick <= now:
            ticks += 1
            next_tick += timedelta(hours=1)
        if ticks <= 0:
            continue
        rate = calc_economy_rate(colony, owner, game_speed)
        occupation_income = rate * OCCUPIER_INCOME_SHARE * ticks
        total += occupation_income
    add_resources(user, total)
    if total > 0:
        log_credits(db, user.id, total, "Occupation income", "income")
    return total

def _update_unrest(colony, db):
    """Update unrest level for a colony based on time."""
    now = datetime.utcnow()
    if colony.occupied_by:
        # Unrest increases 10%/day while occupied
        if colony.occupation_start:
            days_occupied = (now - colony.occupation_start).total_seconds() / 86400.0
            colony.unrest = min(1.0, days_occupied * UNREST_INCREASE_PER_DAY)
    else:
        # Unrest decreases 10%/day when not occupied (and not recently pillaged)
        if colony.last_pillaged:
            hours_since = (now - colony.last_pillaged).total_seconds() / 3600.0
            if hours_since > 24:
                colony.unrest = max(0.0, colony.unrest - UNREST_DECAY_PER_DAY * ((hours_since - 24) / 24.0))
        else:
            colony.unrest = max(0.0, colony.unrest - UNREST_SLOW_DECAY)  # slow decay
    # Defense regeneration: +1%/hr when not occupied
    if not colony.occupied_by and colony.defense_effectiveness < 1.0:
        colony.defense_effectiveness = min(1.0, colony.defense_effectiveness + DEFENSE_REGEN_PER_HOUR)

    # Economy recovery: 1 economy per 8 hours when not occupied
    # Economy recovery: 1 economy per (8 / game_speed) hours when not occupied
    economy_penalty = getattr(colony, 'economy_penalty', 0) or 0
    if not colony.occupied_by and economy_penalty > 0:
        last_recovery = getattr(colony, 'last_economy_recovery', None)
        if last_recovery:
            game_speed = get_config_float(db, "game_speed", 1.0)
            recovery_interval = ECONOMY_RECOVERY_HOURS / game_speed
            hours_since_recovery = (now - last_recovery).total_seconds() / 3600.0
            ticks = int(hours_since_recovery / recovery_interval)
            if ticks > 0:
                recovered = min(ticks * ECONOMY_RECOVERY_RATE, economy_penalty)
                colony.economy_penalty = economy_penalty - recovered
                colony.last_economy_recovery = now

# ======================== RE-EXPORTS ========================
# These were split into game_scouting.py and combat.py but are re-exported here
# so existing imports like `from game_logic import resolve_battle` keep working.
from combat import _fleet_ship_counts, _fleet_total_ships, _fleet_value, resolve_battle  # noqa: F401
from game_scouting import (  # noqa: F401
    _record_region_snapshot, _get_guild_member_ids, _check_user_region_presence,
    _get_region_visibility, process_recycler_tick, _boustrophedon_order,
    _find_guild_base_system_in_region, _record_scouted_intel,
    _autoscout_get_next_target, process_autoscout_tick,
)
