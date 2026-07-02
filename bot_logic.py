"""
NPC Bot AI for AstroWebEngine
Creates bot accounts and runs them through build-up cycles.
Bots upgrade buildings, research tech, build ships, colonize planets,
build defenses, and attack nearby enemies.
"""

import random
import math
import logging
from datetime import datetime, timedelta
from sqlalchemy.orm import Session
from sqlalchemy import or_

from models import (User, Colony, Building, Defense, Research, Fleet, Galaxy,
                    ConstructionQueue, ResearchQueue, Planet, StarSystem, Region, ShipQueue,
                    TradeRoute, ScoutedBase, ScoutedFleet, Commander)
from specs import BUILDING_SPECS, RESEARCH_SPECS, DEFENSE_SPECS
from auth import (hash_password, get_config, get_config_float, get_config_int,
                  get_effective_building_spec, get_effective_research_spec,
                  get_effective_defense_spec, get_effective_ship_spec,
                  get_all_building_specs, get_all_research_specs,
                  get_all_defense_specs, get_all_ship_specs,
                  is_building_disabled, is_research_disabled, is_defense_disabled,
                  ships_with_capability, fleet_capability_ship,
                  log_event, log_credits)
from game_logic import (calc_base_stats, calc_building_cost, calc_research_cost,
                        calc_defense_cost,
                        collect_resources, get_building_level, get_tech_level,
                        _ship_build_time, _check_completions, _process_ship_queues,
                        _process_fleet_arrivals, _fleet_is_empty,
                        project_resources_after_queue, _calc_distance)
from resources import (can_afford, deduct_cost, scale_cost, total_cost_value,
                       get_user_resources, seed_starting_resources)
from config_defaults import FLEET_TRAVEL_DIVISOR, JUMP_GATE_SPEED_BONUS_PER_LEVEL, COLONIZE_SCORE_BONUS
from combat import resolve_battle

logger = logging.getLogger("awe")

# Bot name pools
BOT_FIRST = [
    "Admiral", "Captain", "Commander", "Lord", "Baron", "Duke", "General",
    "Marshal", "Colonel", "Warlord", "Emperor", "Khan", "Overlord", "Sentinel",
    "Phantom", "Shadow", "Iron", "Steel", "Dark", "Storm", "Thunder", "Nova",
    "Stellar", "Cosmic", "Void", "Nexus", "Apex", "Prime", "Alpha", "Omega",
]
BOT_LAST = [
    "Hawk", "Wolf", "Viper", "Raven", "Phoenix", "Dragon", "Falcon", "Titan",
    "Reaper", "Hunter", "Striker", "Blaze", "Fury", "Surge", "Bolt", "Fang",
    "Claw", "Edge", "Core", "Star", "Fleet", "Force", "Guard", "Shield",
    "Blade", "Arrow", "Lance", "Axe", "Hammer", "Pike",
]

# Build priority orders for different strategies
BUILD_ORDER_BALANCED = [
    ("urban_structures", 2), ("solar_plants", 2), ("metal_refineries", 2),
    ("research_labs", 1), ("shipyard", 1),
    ("urban_structures", 4), ("solar_plants", 4), ("metal_refineries", 4),
    ("robotic_factories", 2), ("research_labs", 2), ("shipyard", 3),
    ("spaceports", 1), ("crystal_mines", 1),
    ("urban_structures", 6), ("solar_plants", 6), ("metal_refineries", 6),
    ("robotic_factories", 4), ("shipyard", 5), ("research_labs", 3),
    ("spaceports", 3), ("crystal_mines", 3),
    ("urban_structures", 8), ("solar_plants", 8), ("metal_refineries", 8),
    ("robotic_factories", 6), ("shipyard", 8), ("research_labs", 5),
    ("spaceports", 5), ("command_centers", 2),
    ("urban_structures", 10), ("solar_plants", 10), ("metal_refineries", 10),
    ("shipyard", 10), ("research_labs", 8),
]

RESEARCH_ORDER_BALANCED = [
    ("computer", 2), ("energy", 2), ("laser", 1), ("armour", 2),
    ("computer", 4), ("energy", 4), ("laser", 2), ("missiles", 1),
    ("armour", 4), ("stellar_drive", 1),
    ("energy", 6), ("laser", 4), ("plasma", 1), ("armour", 6),
    ("stellar_drive", 3), ("shielding", 1),
    ("energy", 8), ("armour", 8), ("plasma", 3), ("shielding", 2),
    ("warp_drive", 1), ("stellar_drive", 5),
    ("energy", 10), ("armour", 10), ("plasma", 5), ("shielding", 4),
]

BUILD_ORDER_BUILDER = [
    ("urban_structures", 3), ("solar_plants", 3), ("metal_refineries", 3),
    ("robotic_factories", 2), ("spaceports", 2), ("crystal_mines", 2),
    ("urban_structures", 6), ("solar_plants", 6), ("metal_refineries", 6),
    ("robotic_factories", 4), ("spaceports", 4), ("crystal_mines", 4),
    ("research_labs", 2), ("shipyard", 2),
    ("urban_structures", 10), ("solar_plants", 10), ("metal_refineries", 10),
    ("robotic_factories", 8), ("spaceports", 8), ("crystal_mines", 6),
    ("research_labs", 4), ("shipyard", 4),
    ("nanite_factories", 2), ("orbital_base", 1),
]

BUILD_ORDER_MILITARY = [
    ("urban_structures", 2), ("solar_plants", 2), ("metal_refineries", 2),
    ("shipyard", 2), ("research_labs", 1),
    ("urban_structures", 4), ("solar_plants", 4), ("metal_refineries", 4),
    ("shipyard", 5), ("research_labs", 2),
    ("robotic_factories", 2), ("command_centers", 2),
    ("urban_structures", 6), ("solar_plants", 6), ("metal_refineries", 6),
    ("shipyard", 8), ("research_labs", 3), ("command_centers", 4),
    ("urban_structures", 8), ("solar_plants", 8), ("metal_refineries", 8),
    ("shipyard", 12), ("research_labs", 5), ("command_centers", 6),
]

DEFENSE_ORDER_BALANCED = [
    ("barracks", 3), ("laser_turrets", 3),
    ("barracks", 5), ("laser_turrets", 5), ("missile_turrets", 3),
    ("plasma_turrets", 2), ("missile_turrets", 5),
]

DEFENSE_ORDER_BUILDER = [
    ("barracks", 5), ("laser_turrets", 5), ("missile_turrets", 5),
    ("plasma_turrets", 3), ("ion_turrets", 2),
]

DEFENSE_ORDER_MILITARY = [
    ("barracks", 2), ("laser_turrets", 2),
    ("barracks", 4), ("laser_turrets", 4),
]

# Extended research orders (Phase 2 — mid/late game)
RESEARCH_ORDER_PHASE2 = [
    ("computer", 6), ("energy", 12), ("laser", 6), ("plasma", 6),
    ("armour", 12), ("shielding", 6), ("warp_drive", 4),
    ("ion", 1), ("plasma", 8), ("armour", 14),
    ("ion", 4), ("shielding", 8), ("warp_drive", 8),
    ("photon", 1), ("armour", 16), ("shielding", 10),
]

# Extended build orders (Phase 2 — expand economy for late game)
BUILD_ORDER_PHASE2 = [
    ("urban_structures", 12), ("solar_plants", 12), ("metal_refineries", 12),
    ("robotic_factories", 8), ("nanite_factories", 2), ("shipyard", 12),
    ("research_labs", 10), ("spaceports", 8), ("command_centers", 4),
    ("economic_centers", 2), ("orbital_base", 2),
    ("shipyard", 14), ("research_labs", 12),
    ("nanite_factories", 4), ("android_factories", 2),
    ("shipyard", 16),
]

# Max colonies per simulated player-bot strategy. NPC faction accounts use
# strategy keys "settlers"/"raiders", which intentionally fall back to one fixed base.
MAX_COLONIES = {"balanced": 4, "builder": 5, "military": 3}

STRATEGIES = {
    "balanced": (BUILD_ORDER_BALANCED, RESEARCH_ORDER_BALANCED, DEFENSE_ORDER_BALANCED),
    "builder": (BUILD_ORDER_BUILDER, RESEARCH_ORDER_BALANCED, DEFENSE_ORDER_BUILDER),
    "military": (BUILD_ORDER_MILITARY, RESEARCH_ORDER_BALANCED, DEFENSE_ORDER_MILITARY),
}

NPC_FACTIONS = {
    "settlers": {
        "username": "Settlers",
        "email": "settlers@npc.local",
        "base_prefix": "Settler Base",
        "starting_credits": 500.0,
    },
    "raiders": {
        "username": "Raiders",
        "email": "raiders@npc.local",
        "base_prefix": "Raider Base",
        "starting_credits": 500.0,
    },
}
NPC_STRATEGIES = set(NPC_FACTIONS.keys())

NPC_ALIASES = {
    "settlers": "settlers",
    "settler": "settlers",
    "raiders": "raiders",
    "raider": "raiders",
}


def normalize_npc_type(npc_type: str = "settlers") -> str:
    """Normalize admin-facing NPC names into stable faction keys."""
    key = str(npc_type or "settlers").strip().lower()
    key = NPC_ALIASES.get(key, key)
    if key not in NPC_FACTIONS:
        raise ValueError(f"Unknown NPC type '{npc_type}'. Use 'settlers', 'raiders', or 'both'.")
    return key


def get_or_create_npc_account(db: Session, npc_type: str = "settlers") -> User:
    """Return the shared account for an NPC faction, creating it if needed."""
    faction_key = normalize_npc_type(npc_type)
    faction = NPC_FACTIONS[faction_key]
    user = db.query(User).filter(User.username == faction["username"]).first()
    if not user:
        user = db.query(User).filter(User.email == faction["email"]).first()
    if user and not user.is_bot:
        raise ValueError(f"NPC username '{faction['username']}' is already used by a player account")

    if not user:
        user = User(
            username=faction["username"],
            email=faction["email"],
            hashed_password=hash_password(f"npc_{faction_key}_{random.randint(10000, 99999)}"),
            is_bot=True,
            bot_strategy=faction_key,
            credits=faction["starting_credits"],
        )
        db.add(user)
        seed_starting_resources(user)  # multi-resource economies: starting stash
        db.flush()
    else:
        user.is_bot = True
        user.bot_strategy = faction_key
        if not user.email:
            user.email = faction["email"]

    for tech_type in RESEARCH_SPECS.keys():
        existing = db.query(Research).filter(
            Research.user_id == user.id,
            Research.tech_type == tech_type,
        ).first()
        if not existing:
            db.add(Research(user_id=user.id, tech_type=tech_type, level=0))

    db.flush()
    return user


def _server_midnight(dt: datetime) -> datetime:
    return dt.replace(hour=0, minute=0, second=0, microsecond=0)


def _parse_config_datetime(value: str):
    if not value:
        return None
    text = str(value).strip()
    if not text:
        return None
    try:
        return datetime.fromisoformat(text.replace("Z", "+00:00")).replace(tzinfo=None)
    except ValueError:
        return None


def _config_bool(db: Session, key: str, default: bool = True) -> bool:
    raw = get_config(db, key, "true" if default else "false")
    return str(raw).strip().lower() not in ("0", "false", "no", "off", "")


def _clamp_fraction(value: float, default: float) -> float:
    try:
        parsed = float(value)
    except (TypeError, ValueError):
        parsed = default
    return max(0.0, min(1.0, parsed))


def get_settlers_target_per_galaxy(db: Session, now: datetime = None) -> int:
    """Settlers target: starts high, drops yearly, floors at minimum."""
    now = now or datetime.utcnow()
    start = max(0, get_config_int(db, "NPC_SETTLERS_BASES_START", 5))
    minimum = max(0, get_config_int(db, "NPC_SETTLERS_BASES_MIN", 2))
    reduction = max(0, get_config_int(db, "NPC_SETTLERS_BASES_REDUCTION_PER_YEAR", 1))
    started_at = _parse_config_datetime(get_config(db, "game_started_at", ""))
    years = 0
    if started_at:
        years = max(0, (now.date() - started_at.date()).days // 365)
    return max(minimum, start - reduction * years)


def _initialize_npc_base_state(db: Session, user: User, colony: Colony, now: datetime = None):
    now = now or datetime.utcnow()
    if user.bot_strategy == "settlers":
        colony.npc_stability = _clamp_fraction(
            get_config_float(db, "NPC_SETTLERS_STABILITY_INITIAL", 1.0),
            1.0,
        )
        colony.npc_last_stability_tick = _server_midnight(now)
    else:
        colony.npc_stability = None
        colony.npc_last_stability_tick = None


def delete_npc_colony(db: Session, colony: Colony, delete_empty_account: bool = False):
    """Delete one NPC base and local data without wiping shared faction accounts."""
    bot = colony.user or db.query(User).filter(User.id == colony.user_id).first()
    planet_id = colony.planet_id

    db.query(ShipQueue).filter(ShipQueue.colony_id == colony.id).delete(synchronize_session=False)
    db.query(ConstructionQueue).filter(ConstructionQueue.colony_id == colony.id).delete(synchronize_session=False)
    db.query(ResearchQueue).filter(ResearchQueue.colony_id == colony.id).delete(synchronize_session=False)
    db.query(Commander).filter(Commander.user_id == colony.user_id, Commander.colony_id == colony.id).delete(synchronize_session=False)
    db.query(TradeRoute).filter(or_(TradeRoute.base_a_id == colony.id, TradeRoute.base_b_id == colony.id)).delete(synchronize_session=False)
    db.query(ScoutedBase).filter(ScoutedBase.planet_id == planet_id).delete(synchronize_session=False)
    db.query(ScoutedFleet).filter(ScoutedFleet.planet_id == planet_id).delete(synchronize_session=False)

    # Foreign fleets at a disbanded base become orbiting fleets at the same astro.
    for foreign_fleet in db.query(Fleet).filter(Fleet.user_id != colony.user_id, Fleet.base_id == colony.id).all():
        foreign_fleet.base_id = None
        foreign_fleet.location_planet_id = planet_id
    for inbound_fleet in db.query(Fleet).filter(Fleet.destination_base_id == colony.id).all():
        inbound_fleet.destination_base_id = None
        inbound_fleet.destination_planet_id = planet_id

    for fleet in db.query(Fleet).filter(
        Fleet.user_id == colony.user_id,
        or_(
            Fleet.base_id == colony.id,
            Fleet.origin_base_id == colony.id,
            Fleet.destination_base_id == colony.id,
            Fleet.location_planet_id == planet_id,
            Fleet.origin_planet_id == planet_id,
            Fleet.destination_planet_id == planet_id,
        ),
    ).all():
        db.delete(fleet)

    if colony.planet:
        colony.planet.is_colonized = False
    db.delete(colony)
    db.flush()

    if bot and delete_empty_account and bot.bot_strategy not in ("settlers", "raiders"):
        remaining = db.query(Colony).filter(Colony.user_id == bot.id).count()
        if remaining == 0:
            db.query(ResearchQueue).filter(ResearchQueue.user_id == bot.id).delete(synchronize_session=False)
            db.query(Research).filter(Research.user_id == bot.id).delete(synchronize_session=False)
            db.query(Fleet).filter(Fleet.user_id == bot.id).delete(synchronize_session=False)
            db.delete(bot)


def process_settlers_stability(db: Session, now: datetime = None):
    """Apply Settlers daily stability decay and disband bases at 0%."""
    if not _config_bool(db, "NPC_SETTLERS_STABILITY_ENABLED", True):
        return {"processed": 0, "disbanded": 0, "created": 0}

    now = now or datetime.utcnow()
    current_midnight = _server_midnight(now)
    initial = _clamp_fraction(get_config_float(db, "NPC_SETTLERS_STABILITY_INITIAL", 1.0), 1.0)
    decay = max(0.0, get_config_float(db, "NPC_SETTLERS_STABILITY_DECAY_PER_DAY", 0.03))
    settlers = db.query(User).filter(User.is_bot == True, User.bot_strategy == "settlers").first()
    if not settlers:
        return {"processed": 0, "disbanded": 0, "created": 0}

    processed = 0
    disbanded = 0
    for colony in list(settlers.colonies):
        if colony.npc_stability is None:
            colony.npc_stability = initial
        if colony.npc_last_stability_tick is None:
            colony.npc_last_stability_tick = current_midnight
            continue

        last_midnight = _server_midnight(colony.npc_last_stability_tick)
        days = (current_midnight.date() - last_midnight.date()).days
        if days <= 0:
            continue

        processed += 1
        colony.npc_stability = max(0.0, (colony.npc_stability or initial) - decay * days)
        colony.npc_last_stability_tick = current_midnight
        if colony.npc_stability <= 0:
            base_name = colony.name
            delete_npc_colony(db, colony)
            disbanded += 1
            logger.info(f"[npc-stability] Settlers base disbanded: {base_name}")

    db.commit()
    maintenance = maintain_settlers_bases(db, now=now, settlers_user=settlers)
    return {
        "processed": processed,
        "disbanded": disbanded,
        "created": maintenance.get("created", 0),
        "target_per_galaxy": maintenance.get("target_per_galaxy", get_settlers_target_per_galaxy(db, now)),
    }


def maintain_settlers_bases(db: Session, now: datetime = None, settlers_user: User = None):
    """Top up Settlers bases to the configured per-galaxy target."""
    if not _config_bool(db, "NPC_SETTLERS_AUTO_MAINTAIN_ENABLED", True):
        return {"created": 0, "target_per_galaxy": get_settlers_target_per_galaxy(db, now)}

    now = now or datetime.utcnow()
    target = get_settlers_target_per_galaxy(db, now)
    if target <= 0:
        return {"created": 0, "target_per_galaxy": target}

    settlers = settlers_user or db.query(User).filter(User.is_bot == True, User.bot_strategy == "settlers").first()
    if not settlers:
        return {"created": 0, "target_per_galaxy": target}

    created = 0
    for galaxy in db.query(Galaxy).order_by(Galaxy.id).all():
        result = create_bot_accounts(db, count=target, galaxy_id=galaxy.id, npc_type="settlers")
        created += len(result)
    if created:
        logger.info(f"[npc-stability] Created {created} Settlers replacement base(s)")
    return {"created": created, "target_per_galaxy": target}


def _npc_colony_count_in_galaxy(db: Session, user_id: int, galaxy_id: int) -> int:
    return (
        db.query(Colony)
        .join(Planet, Colony.planet_id == Planet.id)
        .join(StarSystem, Planet.system_id == StarSystem.id)
        .join(Region, StarSystem.region_id == Region.id)
        .filter(Colony.user_id == user_id, Region.galaxy_id == galaxy_id)
        .count()
    )


def create_bot_accounts(db: Session, count: int = 4, galaxy_id: int = None, npc_type: str = "settlers"):
    """Create NPC bases under one shared faction account.

    If galaxy_id is provided, count is treated as the target number of bases
    for that NPC faction in that galaxy.
    """
    created = []
    faction_key = normalize_npc_type(npc_type)
    faction = NPC_FACTIONS[faction_key]
    user = get_or_create_npc_account(db, faction_key)
    target_count = max(0, int(count or 0))

    if galaxy_id:
        existing_count = _npc_colony_count_in_galaxy(db, user.id, galaxy_id)
        create_count = max(0, target_count - existing_count)
    else:
        create_count = target_count

    for _ in range(create_count):
        base = _assign_homeworld_in_galaxy(
            user,
            db,
            galaxy_id,
            base_name_prefix=faction["base_prefix"],
        )
        if not base:
            break
        db.flush()
        created.append({
            "account_id": user.id,
            "account": user.username,
            "npc_type": faction_key,
            "base_id": base.id,
            "base_name": base.name,
            "planet_id": base.planet_id,
            "galaxy_id": galaxy_id,
        })
        logger.info(f"[bot] Created NPC base: {base.name} ({user.username}) galaxy={galaxy_id}")

    db.commit()
    return created


def create_simulated_bot_accounts(db: Session, count: int = 10, galaxy_id: int = None):
    """Create classic simulated player bots, one account per bot/base."""
    created = []
    strategies = ["balanced", "builder", "military"]

    for _ in range(max(0, int(count or 0))):
        for _attempt in range(50):
            name = f"{random.choice(BOT_FIRST)}{random.choice(BOT_LAST)}{random.randint(1, 999)}"
            existing = db.query(User).filter(User.username == name).first()
            if not existing:
                break
        else:
            continue

        strategy = random.choice(strategies)
        user = User(
            username=name,
            email=f"{name.lower()}@bot.local",
            hashed_password=hash_password(f"bot_{name}_{random.randint(10000, 99999)}"),
            is_bot=True,
            bot_strategy=strategy,
            credits=500.0,
        )
        db.add(user)
        seed_starting_resources(user)  # multi-resource economies: starting stash
        db.flush()

        base = _assign_homeworld_in_galaxy(user, db, galaxy_id)
        if not base:
            db.delete(user)
            continue
        db.flush()

        created.append({
            "id": user.id,
            "account_id": user.id,
            "account": user.username,
            "name": user.username,
            "strategy": strategy,
            "npc_type": "simulated",
            "base_id": base.id,
            "base_name": base.name,
            "planet_id": base.planet_id,
            "galaxy_id": galaxy_id,
        })
        logger.info(f"[bot] Created simulated bot: {name} ({strategy}) galaxy={galaxy_id}")

    db.commit()
    return created


def _assign_homeworld_in_galaxy(user, db, galaxy_id=None, base_name_prefix=None):
    """Assign an NPC base within a specific galaxy, or anywhere if no galaxy is given."""
    from models import Planet, StarSystem, Region, Colony, Building, Defense, Research, Fleet
    from specs import BUILDING_SPECS, RESEARCH_SPECS, DEFENSE_SPECS

    # Prefer available 3rd-orbit Earthly planets, matching normal homeworld placement.
    query = (
        db.query(Planet)
        .join(StarSystem, Planet.system_id == StarSystem.id)
        .join(Region, StarSystem.region_id == Region.id)
        .filter(
            Planet.is_colonized == False,
            Planet.planet_type == "earthly",
            Planet.orbit_position == 3,
        )
    )
    if galaxy_id:
        query = query.filter(Region.galaxy_id == galaxy_id)
    candidates = query.all()
    if not candidates:
        # Fallback: any uncolonized planet in this galaxy.
        query = (
            db.query(Planet)
            .join(StarSystem, Planet.system_id == StarSystem.id)
            .join(Region, StarSystem.region_id == Region.id)
            .filter(
                Planet.is_colonized == False,
            )
        )
        if galaxy_id:
            query = query.filter(Region.galaxy_id == galaxy_id)
        candidates = query.all()
    if not candidates:
        # No planets available in this galaxy at all — skip
        logger.warning(f"[bot] No available planets in galaxy {galaxy_id} for {user.username}")
        return None

    planet = random.choice(candidates)
    planet.is_colonized = True
    base_name = f"{base_name_prefix} {planet.name}" if base_name_prefix else f"{user.username}'s Homeworld"
    base = Colony(planet_id=planet.id, user_id=user.id, name=base_name[:50])
    db.add(base)
    db.flush()
    _initialize_npc_base_state(db, user, base)
    # Starter buildings — same as players: only Urban Structures Lv1
    # Guard against duplicates: only add if colony has no buildings yet
    existing_buildings = db.query(Building).filter(Building.colony_id == base.id).count()
    if existing_buildings == 0:
        for bt, bspec in BUILDING_SPECS.items():
            db.add(Building(colony_id=base.id, building_type=bt, level=bspec.get("start_level", 0)))
    # Initialize defenses
    existing_defenses = db.query(Defense).filter(Defense.colony_id == base.id).count()
    if existing_defenses == 0:
        for dt in DEFENSE_SPECS.keys():
            db.add(Defense(colony_id=base.id, defense_type=dt, level=0))
    # Initialize research
    for tt in RESEARCH_SPECS.keys():
        existing = db.query(Research).filter(Research.user_id == user.id, Research.tech_type == tt).first()
        if not existing:
            db.add(Research(user_id=user.id, tech_type=tt, level=0))
    # Starter fleet
    db.add(Fleet(name="Home Fleet", user_id=user.id, base_id=base.id))
    user.score += 10
    user.bases_founded_peak = max(getattr(user, "bases_founded_peak", 0) or 0, len(user.colonies))
    return base


def _bot_wealth(bot: User) -> float:
    """A scalar proxy for a bot's spendable wealth that works for both single-
    and multi-resource economies (sum of all resource balances). Bot strategy
    thresholds/spend-percentages are scalar by nature, so they compare against
    this; the actual transactions use can_afford/deduct_cost (which preserve
    per-resource costs)."""
    return total_cost_value(get_user_resources(bot))


def _roster_order(specs, classic_order, tiers, keep):
    """Build a bot priority order for the ACTIVE roster: classic entries that
    still exist (preserving the tuned classic strategy), then every other roster
    key cost-sorted and escalated across `tiers`. On the classic roster the
    extras are empty; on a different ruleset the classic keys don't exist, so the
    order becomes fully roster-derived — which is what lets bots play any
    definition instead of going inert."""
    existing = set(specs.keys())
    in_classic = {k for k, _ in classic_order}
    out = [(k, lvl) for (k, lvl) in classic_order if k in existing]

    def _cost(k):
        s = specs.get(k, {})
        return total_cost_value(s.get("base_cost", s.get("cost", 1)) or 1)

    extras = sorted((k for k in existing if k not in in_classic and keep(k)), key=_cost)
    for t in tiers:
        out.extend((k, t) for k in extras)
    return out


def _effective_build_order(db, classic_order):
    return _roster_order(get_all_building_specs(db), classic_order,
                         (2, 4, 6, 8, 10, 12, 16), lambda k: not is_building_disabled(db, k))


def _effective_research_order(db, classic_order):
    return _roster_order(get_all_research_specs(db), classic_order,
                         (2, 4, 6, 8, 10, 12), lambda k: not is_research_disabled(db, k))


def _effective_defense_order(db, classic_order):
    return _roster_order(get_all_defense_specs(db), classic_order,
                         (3, 6, 10, 20), lambda k: not is_defense_disabled(db, k))


def tick_bots(db: Session, include_stats: bool = False):
    """Run one AI tick for all bot accounts.
    Call this periodically (e.g., every 30-60 seconds) from a background task.
    Each bot: collects resources, checks completions, queues next build/research, builds ships.
    """
    game_speed = get_config_float(db, "game_speed", 1.0)
    now = datetime.utcnow()

    bots = db.query(User).filter(User.is_bot == True).all()
    for bot in bots:
        try:
            _tick_single_bot(bot, db, game_speed, now)
        except Exception as e:
            logger.error(f"[bot] Error ticking {bot.username}: {e}")

    db.commit()
    if include_stats:
        return collect_bot_stats(db)
    return None


def collect_bot_stats(db: Session):
    """Return lightweight aggregate stats for the current bot population."""
    bots = db.query(User).filter(User.is_bot == True).all()
    total_colonies = 0
    total_fleets = 0
    moving_fleets = 0
    orbiting_fleets = 0
    staged_attacks = 0
    total_credits = 0.0
    total_combat_power = 0
    strategies = {"settlers": 0, "raiders": 0, "balanced": 0, "builder": 0, "military": 0, "other": 0}
    top_bot = None

    for bot in bots:
        total_colonies += len(bot.colonies)
        total_credits += _bot_wealth(bot)
        strategy = bot.bot_strategy or "other"
        if strategy not in strategies:
            strategy = "other"
        strategies[strategy] += 1
        if top_bot is None or (bot.score or 0) > (top_bot.score or 0):
            top_bot = bot

        for fleet in bot.fleets:
            total_fleets += 1
            if fleet.is_moving:
                moving_fleets += 1
            if fleet.location_planet_id and not fleet.base_id:
                orbiting_fleets += 1
                planet = db.query(Planet).filter(Planet.id == fleet.location_planet_id).first()
                if planet and getattr(planet, "colony", None) and planet.colony.user_id != bot.id:
                    staged_attacks += 1
            total_combat_power += _fleet_combat_power(fleet, db)

    return {
        "bots": len(bots),
        "colonies": total_colonies,
        "avg_colonies": round(total_colonies / len(bots), 2) if bots else 0,
        "fleets": total_fleets,
        "moving_fleets": moving_fleets,
        "orbiting_fleets": orbiting_fleets,
        "staged_attacks": staged_attacks,
        "total_credits": round(total_credits),
        "total_combat_power": round(total_combat_power),
        "strategies": strategies,
        "top_bot": (
            {
                "username": top_bot.username,
                "score": round(top_bot.score or 0),
                "bases": len(top_bot.colonies),
            }
            if top_bot else None
        ),
    }


def _tick_single_bot(bot: User, db: Session, game_speed: float, now: datetime):
    """AI logic for a single bot account."""
    # 1. Collect resources, check completions, process ship/fleet arrivals
    collect_resources(bot, db, game_speed)
    _process_ship_queues(bot, db, game_speed)
    _process_fleet_arrivals(bot, db)
    if (bot.bot_strategy or "") in NPC_STRATEGIES:
        return

    # 2. For each colony, try to queue construction
    strategy_name = bot.bot_strategy or "balanced"
    build_order, research_order, defense_order = STRATEGIES.get(strategy_name, STRATEGIES["balanced"])

    # Extend build/research orders with Phase 2, then resolve against the ACTIVE
    # roster (classic items that exist + roster-derived extras) so bots play any
    # ruleset, not just the classic one.
    full_build_order = _effective_build_order(db, list(build_order) + BUILD_ORDER_PHASE2)
    full_research_order = _effective_research_order(db, list(research_order) + RESEARCH_ORDER_PHASE2)
    full_defense_order = _effective_defense_order(db, defense_order)

    for colony in bot.colonies:
        _bot_try_construct(bot, colony, db, game_speed, full_build_order, now)

    # 3. Try to queue research
    _bot_try_research(bot, db, game_speed, full_research_order, now)

    # 4. Build defenses on each colony
    for colony in bot.colonies:
        _bot_try_build_defenses(bot, colony, db, game_speed, full_defense_order, now)

    # 5. Build ships if shipyard is high enough and we have credits
    for colony in bot.colonies:
        _bot_try_build_ships(bot, colony, db, game_speed, now)

    # 6. Colonize new planets if a colonizer ship is available and below colony limit.
    _bot_try_colonize(bot, db, game_speed, now, strategy_name)

    # 7. If a combat fleet is already staged over an enemy planet, attack immediately.
    if _bot_try_attack(bot, db, game_speed, now, launch_only=False):
        return

    # 8. Otherwise, sometimes launch a new attack wave.
    if random.random() < 0.1:  # 10% chance per tick
        _bot_try_attack(bot, db, game_speed, now, launch_only=True)


def _noncombat_ship_keys(db: Session) -> set:
    """Ship keys that are support units (colonizer / recycler / scout), resolved
    from the active roster's capabilities rather than hard-coded keys. Used to
    exclude them from combat-power and fleet-size estimates so the bot AI works
    on any roster, not just the classic one."""
    keys = set()
    for cap in ("can_colonize", "can_recycle", "can_autoscout"):
        keys.update(ships_with_capability(db, cap))
    return keys


def _fleet_combat_power(fleet, db: Session):
    """Cheap fleet power estimate for bot targeting decisions."""
    power = 0
    noncombat = _noncombat_ship_keys(db)
    for st, count in fleet.get_all_ship_counts().items():
        if count > 0 and st not in noncombat:
            spec = get_effective_ship_spec(db, st)
            power += count * spec.get("attack", 0)
    return power


def _estimate_colony_defense_power(colony: Colony, db: Session):
    """Rough colony defense+fleet strength estimate for bot caution checks."""
    def_power = 0
    for d in colony.defenses:
        if d.level > 0:
            dspec = get_effective_defense_spec(db, d.defense_type)
            def_power += d.level * dspec.get("attack", 0)
    def_fleets = db.query(Fleet).filter(
        Fleet.base_id == colony.id,
        Fleet.is_moving == False,
        Fleet.user_id == colony.user_id,
    ).all()
    for df in def_fleets:
        def_power += _fleet_combat_power(df, db)
    return def_power


def _bot_try_construct(bot: User, colony: Colony, db: Session, game_speed: float,
                       build_order: list, now: datetime):
    """Try to queue the next building upgrade for a bot's colony."""
    # Check queue size
    queue = (db.query(ConstructionQueue)
             .filter(ConstructionQueue.colony_id == colony.id,
                     ConstructionQueue.user_id == bot.id)
             .order_by(ConstructionQueue.position).all())
    if len(queue) >= 3:  # Bots only use 3 of 5 queue slots
        return

    stats = calc_base_stats(colony, bot, game_speed)

    # Find next building to upgrade from the build order
    for building_type, target_level in build_order:
        if is_building_disabled(db, building_type):
            continue

        building = next((b for b in colony.buildings if b.building_type == building_type), None)
        if not building:
            continue

        # Get effective level including queued items
        effective_level = building.level
        for q in queue:
            if q.item_category == 'building' and q.item_type == building_type:
                effective_level = q.target_level

        if effective_level >= target_level:
            continue  # Already at or past target

        spec = get_effective_building_spec(db, building_type)
        if not spec:
            continue
        max_lv = spec.get("max_level", 0)
        if max_lv > 0 and effective_level >= max_lv:
            continue

        # Skip buildings that depend on planet resources the planet doesn't have
        planet = colony.planet
        if building_type == "crystal_mines" and planet.crystal <= 0:
            continue
        if building_type == "solar_plants" and planet.solar <= 0:
            continue
        if building_type == "gas_plants" and planet.gas <= 0:
            continue
        if building_type == "metal_refineries" and planet.metal <= 0:
            continue

        # Check tech requirements
        tech_ok = True
        for tech, level_needed in spec.get("tech_req", {}).items():
            if get_tech_level(bot, tech) < level_needed:
                tech_ok = False
                break
        if not tech_ok:
            continue

        # Smart resource check: project resources after queued items complete
        projected = project_resources_after_queue(colony, bot, queue, db)
        energy_req = spec.get("energy_req", 0)
        pop_req = spec.get("pop_req", 0)
        area_req = spec.get("area_req", 0)
        if energy_req > 0 and projected["energy"] - projected["energy_used"] < energy_req:
            continue
        if pop_req > 0 and projected["population"] - projected["pop_used"] < pop_req:
            continue
        if area_req > 0 and projected["area"] - projected["area_used"] < area_req:
            continue

        # Calculate cost
        cost, build_time = calc_building_cost(db, building_type, effective_level, stats, game_speed)
        if not can_afford(bot, cost):
            continue  # Not enough resources, try next

        # Queue it — only deduct cost for position 0 (active item)
        # Queued items get charged when they become active in _advance_construction_queue
        position = len(queue)
        if position == 0:
            deduct_cost(bot, cost)

        if position == 0:
            building.is_constructing = True
            building.construction_end = now + timedelta(seconds=build_time)
            finish_at = building.construction_end
            started_at = now
        else:
            finish_at = None
            started_at = None

        qi = ConstructionQueue(
            colony_id=colony.id, user_id=bot.id, position=position,
            item_category='building', item_type=building_type,
            target_level=effective_level + 1, cost=cost, build_time=build_time,
            started_at=started_at, finish_at=finish_at
        )
        db.add(qi)
        queue.append(qi)

        if len(queue) >= 3:
            break  # Queue is full enough


def _bot_try_research(bot: User, db: Session, game_speed: float,
                      research_order: list, now: datetime):
    """Try to queue the next research for a bot. Uses best research base."""
    # Pick the best research base (highest lab level)
    best_base = max(bot.colonies, key=lambda c: get_building_level(c, "research_labs"), default=None)
    if not best_base or get_building_level(best_base, "research_labs") <= 0:
        return

    queue = (db.query(ResearchQueue)
             .filter(ResearchQueue.user_id == bot.id,
                     ResearchQueue.colony_id == best_base.id)
             .order_by(ResearchQueue.position).all())
    if len(queue) >= 3:  # Bots use 3 of 6 slots
        return

    base_lab_level = get_building_level(best_base, "research_labs")
    base_lab_capacity = calc_base_stats(best_base, bot, game_speed).get("research", 0)
    if base_lab_capacity <= 0:
        return

    # Get all actively researching techs across all bases
    active_techs = set()
    active_items = db.query(ResearchQueue.tech_type).filter(
        ResearchQueue.user_id == bot.id,
        ResearchQueue.position == 0,
        ResearchQueue.finish_at != None,
    ).all()
    for row in active_items:
        active_techs.add(row[0])

    # If the bot already has a shipyard, grab the fighter unlock quickly so fleets
    # start existing earlier in a fresh simulation.
    if get_building_level(best_base, "shipyard") >= 1 and get_tech_level(bot, "laser") < 1:
        queued_laser = db.query(ResearchQueue).filter(
            ResearchQueue.user_id == bot.id,
            ResearchQueue.tech_type == "laser",
        ).first()
        if not queued_laser:
            research_order = [("laser", 1)] + list(research_order)

    for tech_type, target_level in research_order:
        if is_research_disabled(db, tech_type):
            continue

        r = next((r for r in bot.research if r.tech_type == tech_type), None)
        if not r:
            continue

        # Get effective level including queued across all bases
        effective_level = r.level
        all_queued = (db.query(ResearchQueue)
                     .filter(ResearchQueue.user_id == bot.id,
                             ResearchQueue.tech_type == tech_type)
                     .order_by(ResearchQueue.target_level.desc()).first())
        if all_queued:
            effective_level = all_queued.target_level

        if effective_level >= target_level:
            continue

        spec = get_effective_research_spec(db, tech_type)
        if not spec:
            continue

        # Check prerequisites
        prereqs_ok = True
        for prereq_tech, prereq_level in spec.get("prereqs", {}).items():
            if get_tech_level(bot, prereq_tech) < prereq_level:
                prereqs_ok = False
                break
        if not prereqs_ok:
            continue

        # Check lab requirement against this base
        if base_lab_level < spec.get("lab_req", 1):
            continue

        cost, research_time = calc_research_cost(db, tech_type, effective_level, game_speed, base_lab_capacity, colony_id=best_base.id)
        if not can_afford(bot, cost):
            continue

        position = len(queue)

        # Check tech conflict for position 0
        can_start = True
        if position == 0 and tech_type in active_techs:
            can_start = False

        if position == 0 and can_start:
            deduct_cost(bot, cost)
            r.is_researching = True
            r.research_end = now + timedelta(seconds=research_time)
            finish_at = r.research_end
            started_at = now
        else:
            finish_at = None
            started_at = None

        qi = ResearchQueue(
            user_id=bot.id, colony_id=best_base.id, position=position,
            tech_type=tech_type, target_level=effective_level + 1,
            cost=cost, research_time=research_time,
            started_at=started_at, finish_at=finish_at
        )
        db.add(qi)
        queue.append(qi)

        if len(queue) >= 3:
            break


def _bot_try_build_ships(bot: User, colony: Colony, db: Session,
                         game_speed: float, now: datetime):
    """Build ships via the production queue (same as players)."""
    sy_level = get_building_level(colony, "shipyard")
    if sy_level < 1:
        return

    # Skip if this base already has an active ship queue
    existing = db.query(ShipQueue).filter(ShipQueue.colony_id == colony.id).first()
    if existing and existing.built < existing.count:
        return

    # Only build ships if the bot has a decent resource surplus
    if _bot_wealth(bot) < 50:
        return

    def _can_build_ship(spec: dict) -> bool:
        if not spec:
            return False
        if spec.get("shipyard", 1) > sy_level:
            return False
        return not any(get_tech_level(bot, t) < lvl for t, lvl in (spec.get("req") or {}).items())

    # Build from the active roster. This keeps bots compatible with the classic
    # roster keys (fighters/outpost_ships/etc.) and future GUI-authored rulesets.
    ship_choices = []
    noncombat = _noncombat_ship_keys(db)
    for key, spec in get_all_ship_specs(db).items():
        if key in noncombat or spec.get("attack", 0) <= 0:
            continue
        if not _can_build_ship(spec):
            continue
        ship_choices.append((key, total_cost_value(spec.get("cost", 10)) or 1))
    ship_choices.sort(key=lambda x: x[1])

    # Decide what to build based on needs
    strategy = bot.bot_strategy or "balanced"
    num_colonies = len(bot.colonies)
    max_colonies = MAX_COLONIES.get(strategy, 1)

    # Priority: build a colony ship if we need to colonize and have none.
    # Resolve the colonizer from the active roster (capability-driven) instead of
    # hard-coding a ship key, so a custom roster's colonizer is used and no
    # ship is queued when the roster has none.
    colonizer_keys = ships_with_capability(db, "can_colonize")
    buildable_colonizer_keys = [
        k for k in colonizer_keys
        if _can_build_ship(get_effective_ship_spec(db, k))
    ]
    needs_outpost = (num_colonies < max_colonies
                     and bool(buildable_colonizer_keys))
    if needs_outpost:
        # Check if we already have a colony ship available
        has_outpost = any(f.get_ship_count(k) > 0
                          for f in bot.fleets for k in colonizer_keys)
        if not has_outpost:
            ckey = buildable_colonizer_keys[0]
            ccost = get_effective_ship_spec(db, ckey).get("cost", 100)
            if can_afford(bot, ccost):
                deduct_cost(bot, ccost)
                per_ship_time = _ship_build_time(ckey, colony, bot, game_speed, db)
                db.add(ShipQueue(
                    colony_id=colony.id, user_id=bot.id, ship_type=ckey,
                    count=1, built=0, started_at=now, cost=ccost,
                    next_complete=now + timedelta(seconds=per_ship_time),
                ))
                return

    if not ship_choices:
        return

    # Pick the best affordable ship, spending more aggressively than before.
    # Exclude colonizers (resolved by capability, not a hard-coded key) — those
    # are queued by the dedicated outpost path above, not as combat ships.
    _colonizers = set(colonizer_keys)
    wealth = _bot_wealth(bot)
    spend_pct = 0.30 if strategy == "military" else 0.20
    affordable = [(st, cost) for st, cost in ship_choices
                  if st not in _colonizers and wealth >= cost * 2]
    if not affordable:
        return

    # Mix combat ships: primarily high-tier, but sometimes build hangar-carried
    # craft when carriers are available.
    ship_type, ship_cost = affordable[-1]

    selected_spec = get_effective_ship_spec(db, ship_type)
    if selected_spec.get("hangar", 0) > 0 and random.random() < 0.5:
        carried_entry = next(
            ((s, c) for s, c in affordable
             if get_effective_ship_spec(db, s).get("hangar", 0) < 0),
            None,
        )
        if carried_entry:
            ship_type, ship_cost = carried_entry

    count = max(1, int(wealth * spend_pct / max(1, ship_cost)))
    # Cap count to keep build times reasonable
    count = min(count, 20 if ship_cost < 50 else (10 if ship_cost < 200 else 5))

    # Charge the real (per-resource) cost; trim the count to what's affordable.
    unit_cost = get_effective_ship_spec(db, ship_type).get("cost", ship_cost)
    real_cost = scale_cost(unit_cost, count)
    while count > 1 and not can_afford(bot, real_cost):
        count -= 1
        real_cost = scale_cost(unit_cost, count)
    if not can_afford(bot, real_cost):
        return
    deduct_cost(bot, real_cost)

    per_ship_time = _ship_build_time(ship_type, colony, bot, game_speed, db)
    total_time = per_ship_time * count

    db.add(ShipQueue(
        colony_id=colony.id, user_id=bot.id, ship_type=ship_type,
        count=count, built=0, started_at=now, cost=real_cost,
        next_complete=now + timedelta(seconds=total_time),
    ))


def _bot_try_build_defenses(bot: User, colony: Colony, db: Session, game_speed: float,
                            defense_order: list, now: datetime):
    """Queue defense upgrades for a bot's colony (uses shared construction queue)."""
    queue = (db.query(ConstructionQueue)
             .filter(ConstructionQueue.colony_id == colony.id,
                     ConstructionQueue.user_id == bot.id)
             .order_by(ConstructionQueue.position).all())
    if len(queue) >= 3:
        return

    stats = calc_base_stats(colony, bot, game_speed)

    for defense_type, target_level in defense_order:
        if is_defense_disabled(db, defense_type):
            continue

        defense = next((d for d in colony.defenses if d.defense_type == defense_type), None)
        if not defense:
            continue

        # Get effective level including queued items
        effective_level = defense.level
        for q in queue:
            if q.item_category == 'defense' and q.item_type == defense_type:
                effective_level = q.target_level

        if effective_level >= target_level:
            continue

        dspec = get_effective_defense_spec(db, defense_type)
        if not dspec:
            continue

        # Check tech requirements
        tech_ok = True
        for tech, level_needed in dspec.get("req", {}).items():
            if get_tech_level(bot, tech) < level_needed:
                tech_ok = False
                break
        if not tech_ok:
            continue

        # Check resource availability
        projected = project_resources_after_queue(colony, bot, queue, db)
        energy_req = dspec.get("energy_req", 0)
        pop_req = dspec.get("pop_req", 1)
        area_req = dspec.get("area_req", 0)
        if energy_req > 0 and projected["energy"] - projected["energy_used"] < energy_req:
            continue
        if pop_req > 0 and projected["population"] - projected["pop_used"] < pop_req:
            continue
        if area_req > 0 and projected["area"] - projected["area_used"] < area_req:
            continue

        # Cost via the shared calculator (handles level vs count model + multi-
        # resource dict costs); cost is a scalar or a per-resource dict.
        cost, build_time, _units = calc_defense_cost(db, defense_type, effective_level, game_speed)

        if not can_afford(bot, cost):
            continue

        position = len(queue)
        if position == 0:
            deduct_cost(bot, cost)
            log_credits(db, bot.id, -total_cost_value(cost), f"Defense: {defense_type} Lv{effective_level + 1}", "construction")
            defense.is_constructing = True
            defense.construction_end = now + timedelta(seconds=build_time)
            finish_at = defense.construction_end
            started_at = now
        else:
            finish_at = None
            started_at = None

        qi = ConstructionQueue(
            colony_id=colony.id, user_id=bot.id, position=position,
            item_category='defense', item_type=defense_type,
            target_level=effective_level + 1, cost=cost, build_time=build_time,
            started_at=started_at, finish_at=finish_at
        )
        db.add(qi)
        queue.append(qi)

        if len(queue) >= 3:
            break


def _bot_try_colonize(bot: User, db: Session, game_speed: float, now: datetime,
                      strategy_name: str):
    """Find and colonize new planets using the roster's colonizer ship."""
    num_colonies = len(bot.colonies)
    max_cols = MAX_COLONIES.get(strategy_name, 1)
    if num_colonies >= max_cols:
        return

    # Find a non-moving fleet carrying a colonizer, resolved from the active
    # roster's can_colonize capability rather than a hard-coded ship key.
    for fleet in bot.fleets:
        if fleet.is_moving:
            continue
        colonizer_key = fleet_capability_ship(fleet, db, "can_colonize")
        if not colonizer_key:
            continue

        # Fleet has a colonizer; check if it is at an uncolonized planet.
        if fleet.location_planet_id:
            planet = db.query(Planet).filter(Planet.id == fleet.location_planet_id).first()
            if planet and not planet.is_colonized:
                _bot_colonize_planet(bot, fleet, planet, db, colonizer_key)
                return

        # Fleet is at a base — find a good nearby planet to send it to
        if fleet.base_id:
            origin_colony = db.query(Colony).filter(Colony.id == fleet.base_id).first()
            if not origin_colony or not origin_colony.planet:
                continue

            target = _find_colonization_target(bot, origin_colony.planet, db)
            if target:
                _bot_send_fleet(bot, fleet, origin_colony.planet, target, db, game_speed)
                return


def _find_colonization_target(bot: User, origin_planet, db: Session):
    """Find a good uncolonized planet near the origin for colonization."""
    region = origin_planet.system.region
    galaxy_id = region.galaxy_id

    # Prefer same region first, then expand to galaxy
    # Preferred terrain IDs are internal generation keys; public display names are neutral.
    preferred_types = ["gaia", "earthly", "crystalline", "rocky", "metallic", "arid"]

    # Search in same galaxy for uncolonized planets
    candidates = (
        db.query(Planet)
        .join(StarSystem, Planet.system_id == StarSystem.id)
        .join(Region, StarSystem.region_id == Region.id)
        .filter(
            Region.galaxy_id == galaxy_id,
            Planet.is_colonized == False,
            ~Planet.planet_type.in_(["gas_giant", "asteroid_belt"]),
        )
        .limit(200)
        .all()
    )

    if not candidates:
        return None

    # Score candidates: prefer good terrain, closer distance
    scored = []
    for p in candidates:
        # Skip non-colonizable body types.
        if p.planet_type in ("gas_giant", "asteroid_belt"):
            continue
        terrain_bonus = 10 if p.planet_type in preferred_types[:2] else (
            5 if p.planet_type in preferred_types[2:4] else 0)
        area = p.area or 80
        fertility = p.fertility or 4
        metal = p.metal or 2
        score = terrain_bonus + area / 10 + fertility + metal
        distance = _calc_distance(origin_planet, p)
        score += max(0, 12 - distance) * 1.5
        if p.system.region_id == origin_planet.system.region_id:
            score += 4
        # Prefer planets (orbit_row 0) over moons
        if (p.orbit_row or 0) == 0:
            score += 5
        scored.append((p, score))

    if not scored:
        return None

    # Sort by score descending, pick from top 5 randomly
    scored.sort(key=lambda x: x[1], reverse=True)
    top = scored[:min(5, len(scored))]
    return random.choice(top)[0]


def _bot_colonize_planet(bot: User, fleet, planet, db: Session, colonizer_key: str):
    """Colonize an uncolonized planet, consuming one colonizer ship (resolved by
    the can_colonize capability) from the fleet."""
    from specs import PLANET_TYPE_STATS
    ptype_stats = PLANET_TYPE_STATS.get(planet.planet_type, {})
    if ptype_stats.get("colonizable", True) is False:
        return  # Can't colonize this type

    # Consume one colonizer ship.
    fleet.set_ship_count(colonizer_key, fleet.get_ship_count(colonizer_key) - 1)

    planet.is_colonized = True
    colony = Colony(planet_id=planet.id, user_id=bot.id, name=f"{bot.username}'s Colony")
    db.add(colony)
    db.flush()

    # Initialize buildings
    for bt, bspec in BUILDING_SPECS.items():
        if not is_building_disabled(db, bt):
            db.add(Building(colony_id=colony.id, building_type=bt, level=bspec.get("start_level", 0)))
    # Initialize defenses
    for dt in DEFENSE_SPECS.keys():
        if not is_defense_disabled(db, dt):
            db.add(Defense(colony_id=colony.id, defense_type=dt, level=0))

    # Move fleet to new colony
    if _fleet_is_empty(fleet):
        db.delete(fleet)
    else:
        fleet.base_id = colony.id
        fleet.location_planet_id = None

    bot.score += COLONIZE_SCORE_BONUS
    log_event(db, bot.id, "colonize", f"Bot colonized {planet.name} ({planet.planet_type})")


def _bot_send_fleet(bot: User, fleet, origin_planet, dest_planet, db: Session, game_speed: float):
    """Send a bot's fleet to a destination planet."""
    # Calculate fleet speed
    stellar_level = get_tech_level(bot, "stellar_drive")
    warp_level = get_tech_level(bot, "warp_drive")

    min_speed = 999
    for st, count in fleet.get_all_ship_counts().items():
        if count > 0:
            spec = get_effective_ship_spec(db, st)
            base_spd = spec.get("speed", 0) if spec else 0
            if base_spd > 0:
                drive = spec.get("drive", "stellar")
                tech_lvl = warp_level if drive == "warp" else stellar_level
                effective = round(base_spd * (1 + tech_lvl * 0.05), 1)
                min_speed = min(min_speed, effective)
    if min_speed == 999:
        min_speed = 1

    travel_divisor = get_config_float(db, "FLEET_TRAVEL_DIVISOR", FLEET_TRAVEL_DIVISOR)

    # Jump gate bonus
    speed_mult = 1.0
    if fleet.base_id:
        origin_colony = db.query(Colony).filter(Colony.id == fleet.base_id).first()
        if origin_colony:
            jg_level = get_building_level(origin_colony, "jump_gate")
            if jg_level > 0:
                jg_bonus = get_config_float(db, "jump_gate_speed_bonus", JUMP_GATE_SPEED_BONUS_PER_LEVEL)
                speed_mult *= (1 + jg_level * jg_bonus)

    distance = _calc_distance(origin_planet, dest_planet)
    travel_time = distance * travel_divisor / (min_speed * speed_mult * game_speed)
    travel_time = max(10, travel_time)

    fleet.is_moving = True
    fleet.origin_base_id = fleet.base_id

    dest_colony = dest_planet.colony if hasattr(dest_planet, 'colony') else None
    # Friendly colonies can be docked to directly. Enemy colonies are approached in orbit
    # so the bot can resolve a real attack on the next tick instead of "docking" at an enemy base.
    if dest_colony and dest_colony.user_id == bot.id:
        fleet.destination_base_id = dest_colony.id
        fleet.destination_planet_id = None
    else:
        fleet.destination_base_id = None
        fleet.destination_planet_id = dest_planet.id

    fleet.arrival_time = datetime.utcnow() + timedelta(seconds=travel_time)
    fleet.base_id = None
    fleet.location_planet_id = None
    log_event(db, bot.id, "fleet", f"Bot fleet '{fleet.name}' sent to {dest_planet.name}")


def _bot_try_attack(bot: User, db: Session, game_speed: float, now: datetime, launch_only: bool = False):
    """Attack from orbit if already staged, otherwise optionally launch a new attack wave."""
    # Resolve staged attacks first: fleets orbiting enemy planets should fight, not sit forever.
    if not launch_only:
        for fleet in bot.fleets:
            if fleet.is_moving or not fleet.location_planet_id:
                continue
            planet = db.query(Planet).filter(Planet.id == fleet.location_planet_id).first()
            colony = getattr(planet, "colony", None) if planet else None
            if not colony or colony.user_id == bot.id:
                continue
            defender = colony.user
            if not defender or defender.is_admin:
                continue
            if defender.newbie_protection_until and defender.newbie_protection_until > now:
                continue

            fleet_power = _fleet_combat_power(fleet, db)
            if fleet_power < 20:
                continue
            def_power = _estimate_colony_defense_power(colony, db)
            if fleet_power <= def_power * 1.5:
                continue

            report = resolve_battle(fleet, bot, colony, defender, game_speed, db)
            result = report.get("result", "draw")
            if _fleet_is_empty(fleet):
                db.delete(fleet)
            else:
                fleet.base_id = None
                fleet.location_planet_id = colony.planet_id
                fleet.destination_base_id = None
                fleet.destination_planet_id = None
            logger.info(
                f"[bot] {bot.username} attacked {defender.username} at {colony.name} "
                f"-> {result} (atk_loss={report.get('attacker_value_lost', 0)}, "
                f"def_loss={report.get('defender_value_lost', 0)})"
            )
            return True

    # Need a fleet with combat ships that is stationed at one of the bot's own bases.
    best_fleet = None
    best_fleet_power = 0
    for fleet in bot.fleets:
        if fleet.is_moving:
            continue
        if not fleet.base_id:
            continue
        power = _fleet_combat_power(fleet, db)
        _noncombat = _noncombat_ship_keys(db)
        total_ships = sum(
            count for st, count in fleet.get_all_ship_counts().items()
            if count > 0 and st not in _noncombat
        )
        if total_ships >= 5 and power > best_fleet_power:
            best_fleet = fleet
            best_fleet_power = power

    if not best_fleet or best_fleet_power < 20:
        return False  # Not enough firepower

    # Find the origin planet
    origin_colony = db.query(Colony).filter(Colony.id == best_fleet.base_id).first()
    if not origin_colony or not origin_colony.planet:
        return False

    galaxy_id = origin_colony.planet.system.region.galaxy_id

    # Find nearby enemy bases in the same galaxy
    enemy_colonies = (
        db.query(Colony)
        .join(Planet, Colony.planet_id == Planet.id)
        .join(StarSystem, Planet.system_id == StarSystem.id)
        .join(Region, StarSystem.region_id == Region.id)
        .filter(
            Region.galaxy_id == galaxy_id,
            Colony.user_id != bot.id,
        )
        .all()
    )

    if not enemy_colonies:
        return False

    # Filter: don't attack players under newbie protection
    valid_targets = []
    for ec in enemy_colonies:
        owner = db.query(User).filter(User.id == ec.user_id).first()
        if not owner:
            continue
        if owner.is_admin:
            continue
        # Check newbie protection
        if owner.newbie_protection_until and owner.newbie_protection_until > now:
            continue
        def_power = _estimate_colony_defense_power(ec, db)

        # Only attack if we have ~2x the defender's power (bots are cautious)
        if best_fleet_power > def_power * 2:
            valid_targets.append(ec)

    if not valid_targets:
        return False

    # Pick a random target from valid ones
    target = random.choice(valid_targets)
    target_planet = target.planet
    if not target_planet:
        return False

    _bot_send_fleet(bot, best_fleet, origin_colony.planet, target_planet, db, game_speed)
    logger.info(
        f"[bot] {bot.username} launched attack fleet '{best_fleet.name}' "
        f"toward {target.user.username}:{target.name}"
    )
    return True
