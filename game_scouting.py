"""
Scouting, fog of war, autoscout system, and recycler auto-collection.
Split from game_logic.py for readability.
"""

import json
from datetime import datetime, timedelta
from sqlalchemy.orm import Session

import action_points
from database import SessionLocal
from models import (
    User, Colony, Fleet, Planet, StarSystem, Region, Galaxy,
    ScoutedRegion, ScoutedBase, ScoutedFleet, GuildMember, Guild
)
from auth import get_config, get_config_float, get_effective_ship_spec, log_event, log_credits
from specs import ALL_SHIP_TYPES
from resources import add_resources
from config_defaults import *


# ======================== REGION SNAPSHOTS (FOG OF WAR) ========================

def _record_region_snapshot(user_id: int, region_id: int, db: Session):
    """Capture a snapshot of a region for fog of war."""
    region = db.query(Region).filter(Region.id == region_id).first()
    if not region:
        return
    systems = []
    for s in region.systems:
        planets = []
        for p in s.planets:
            _cat = "Asteroid" if p.planet_type in ("asteroid", "asteroid_belt") else ("Moon" if (p.orbit_row or 0) > 0 else "Planet")
            pd = {
                "id": p.id, "name": p.name, "type": p.planet_type,
                "category": _cat,
                "orbit": p.orbit_position, "orbit_row": p.orbit_row if p.orbit_row is not None else 0,
                "is_colonized": p.is_colonized,
                "solar": p.solar, "gas": p.gas, "fertility": p.fertility,
                "area": p.area, "metal": p.metal, "crystal": p.crystal,
                "debris": round(p.debris or 0, 1),
                "owner": None, "base_id": None, "base_name": None,
            }
            if p.is_colonized and p.colony:
                pd["owner"] = p.colony.user.username
                pd["base_id"] = p.colony.id
                pd["base_name"] = p.colony.name
            planets.append(pd)
        systems.append({
            "id": s.id, "name": s.name, "star_type": s.star_type,
            "planets": planets,
        })
    snapshot = json.dumps({"id": region.id, "name": region.name, "systems": systems})
    existing = db.query(ScoutedRegion).filter(
        ScoutedRegion.user_id == user_id, ScoutedRegion.region_id == region_id
    ).first()
    if existing:
        existing.last_scouted = datetime.utcnow()
        existing.snapshot_data = snapshot
    else:
        db.add(ScoutedRegion(user_id=user_id, region_id=region_id, last_scouted=datetime.utcnow(), snapshot_data=snapshot))


# ======================== GUILD SHARING & VISIBILITY ========================

def _get_guild_member_ids(user_id: int, db: Session) -> list:
    """Get list of guild member IDs whose scouted data is shared with this user."""
    membership = db.query(GuildMember).filter(GuildMember.user_id == user_id).first()
    if not membership:
        return [user_id]
    if not membership.has_perm("-") and not membership.has_perm("+"):
        return [user_id]
    members = db.query(GuildMember).filter(GuildMember.guild_id == membership.guild_id).all()
    shared = []
    for m in members:
        if m.has_perm("-") or m.has_perm("+"):
            shared.append(m.user_id)
    if user_id not in shared:
        shared.append(user_id)
    return shared


def _check_user_region_presence(user_ids: list, region_id: int, db: Session) -> bool:
    """Check if any of the given users have a base or stationary fleet in a region."""
    # Direct join query — more reliable than lazy-loading through relationships
    from sqlalchemy import and_
    base_match = (db.query(Colony.id)
                  .join(Planet, Planet.id == Colony.planet_id)
                  .join(StarSystem, StarSystem.id == Planet.system_id)
                  .filter(Colony.user_id.in_(user_ids),
                          StarSystem.region_id == region_id)
                  .first())
    if base_match:
        return True
    for uid in user_ids:
        fleets = db.query(Fleet).filter(Fleet.user_id == uid, Fleet.is_moving == False).all()
        for f in fleets:
            if f.base_id:
                colony = db.query(Colony).filter(Colony.id == f.base_id).first()
                if colony and colony.planet and colony.planet.system and colony.planet.system.region_id == region_id:
                    return True
            elif f.location_planet_id:
                planet = db.query(Planet).filter(Planet.id == f.location_planet_id).first()
                if planet and planet.system and planet.system.region_id == region_id:
                    return True
    return False


def _get_region_visibility(user_id: int, region_id: int, db: Session) -> str:
    """Returns visibility level for a region: 'live', 'snapshot', or 'fog'."""
    admin_user = db.query(User).filter(User.id == user_id).first()
    if admin_user and admin_user.is_admin:
        return "live"
    shared_user_ids = _get_guild_member_ids(user_id, db)
    if _check_user_region_presence(shared_user_ids, region_id, db):
        return "live"
    scouted = db.query(ScoutedRegion).filter(
        ScoutedRegion.user_id.in_(shared_user_ids),
        ScoutedRegion.region_id == region_id
    ).first()
    if scouted:
        return "snapshot"
    return "fog"


# ======================== DEBRIS AUTO-COLLECTION ========================

def process_recycler_tick(db: Session):
    """Auto-collect debris for stationary fleets carrying a recycler ship (any
    ship flagged can_recycle in the active roster). Called every 30 minutes.
    Each recycler collects RECYCLER_RATE_PER_UNIT debris times game speed."""
    from auth import ships_with_capability
    game_speed = get_config_float(db, "game_speed", 1.0)
    recycler_keys = ships_with_capability(db, "can_recycle")
    if not recycler_keys:
        return
    # Can't SQL-filter ships stored in ships_extra, so scan stationary auto-recycle
    # fleets and sum recycler ships via the count abstraction.
    fleets = db.query(Fleet).filter(
        Fleet.is_moving == False,
        Fleet.auto_recycle == True
    ).all()
    for fleet in fleets:
        collector_count = sum(fleet.get_ship_count(k) for k in recycler_keys)
        if collector_count <= 0:
            continue
        planet = None
        if fleet.base_id:
            colony = db.query(Colony).filter(Colony.id == fleet.base_id).first()
            if colony:
                planet = colony.planet
        elif fleet.location_planet_id:
            planet = db.query(Planet).filter(Planet.id == fleet.location_planet_id).first()
        if not planet or (planet.debris or 0) <= 0:
            continue
        collected = min(planet.debris, collector_count * RECYCLER_RATE_PER_UNIT * game_speed)
        planet.debris -= collected
        user = db.query(User).filter(User.id == fleet.user_id).first()
        if user:
            add_resources(user, collected)
            log_credits(db, user.id, collected, f"Debris collection at {planet.name}", "income")
            log_event(db, user.id, "recycling",
                      f"Recyclers collected {int(collected)} cr debris at {planet.name}")
    db.commit()


# ======================== AUTOSCOUT SYSTEM ========================

def _boustrophedon_order(grid_w: int, grid_h: int) -> list:
    """Build the boustrophedon traversal order for a galaxy grid."""
    order = []
    for y in range(grid_h):
        if y % 2 == 0:
            for x in range(grid_w):
                order.append((x, y))
        else:
            for x in range(grid_w - 1, -1, -1):
                order.append((x, y))
    return order


def _find_guild_base_system_in_region(region: Region, guild_member_ids: list, db: Session):
    """If any guild member has a base in this region, return that system. Otherwise None."""
    for system in region.systems:
        for planet in system.planets:
            if planet.is_colonized and planet.colony and planet.colony.user_id in guild_member_ids:
                return system
    return None


def _record_scouted_intel(user_id: int, region: Region, db: Session):
    """When a scout visits a region, record all visible bases and fleets for the galaxy report."""
    from combat import _fleet_value
    now = datetime.utcnow()
    for system in region.systems:
        for planet in system.planets:
            # Record bases
            if planet.is_colonized and planet.colony:
                owner = db.query(User).filter(User.id == planet.colony.user_id).first()
                if not owner or owner.id == user_id:
                    continue
                guild_tag = ""
                gm = db.query(GuildMember).filter(GuildMember.user_id == owner.id).first()
                if gm:
                    guild = db.query(Guild).filter(Guild.id == gm.guild_id).first()
                    if guild:
                        guild_tag = guild.tag
                existing = db.query(ScoutedBase).filter(
                    ScoutedBase.user_id == user_id,
                    ScoutedBase.planet_id == planet.id
                ).first()
                if existing:
                    existing.owner_name = owner.username
                    existing.owner_guild_tag = guild_tag
                    existing.base_name = planet.colony.name
                    existing.location = planet.name
                    existing.last_seen = now
                else:
                    db.add(ScoutedBase(
                        user_id=user_id, planet_id=planet.id,
                        owner_name=owner.username, owner_guild_tag=guild_tag,
                        base_name=planet.colony.name, location=planet.name,
                        last_seen=now
                    ))
            # Record fleets at this planet
            stationed_fleets = db.query(Fleet).filter(
                Fleet.is_moving == False,
                Fleet.location_planet_id == planet.id
            ).all()
            if planet.colony:
                based_fleets = db.query(Fleet).filter(
                    Fleet.is_moving == False,
                    Fleet.base_id == planet.colony.id
                ).all()
                stationed_fleets = list(set(stationed_fleets + based_fleets))
            for fleet in stationed_fleets:
                if fleet.user_id == user_id:
                    continue
                fleet_val = _fleet_value(fleet, db)
                if fleet_val <= 0:
                    continue
                owner = db.query(User).filter(User.id == fleet.user_id).first()
                if not owner:
                    continue
                guild_tag = ""
                gm = db.query(GuildMember).filter(GuildMember.user_id == owner.id).first()
                if gm:
                    guild = db.query(Guild).filter(Guild.id == gm.guild_id).first()
                    if guild:
                        guild_tag = guild.tag
                existing = db.query(ScoutedFleet).filter(
                    ScoutedFleet.user_id == user_id,
                    ScoutedFleet.planet_id == planet.id,
                    ScoutedFleet.owner_name == owner.username
                ).first()
                if existing:
                    existing.fleet_size = fleet_val
                    existing.owner_guild_tag = guild_tag
                    existing.location = planet.name
                    existing.is_moving = False
                    existing.last_seen = now
                else:
                    db.add(ScoutedFleet(
                        user_id=user_id, planet_id=planet.id,
                        owner_name=owner.username, owner_guild_tag=guild_tag,
                        location=planet.name, fleet_size=fleet_val,
                        is_moving=False, last_seen=now
                    ))


def _autoscout_get_next_target(fleet, db, current_region_id=None):
    """Determine the next planet an autoscout should travel to.
    Skips the region the scout is currently in (already scouted by being there)."""
    galaxy = db.query(Galaxy).filter(Galaxy.id == fleet.autoscout_galaxy_id).first()
    if not galaxy:
        return None

    grid_w = galaxy.regions_grid_w or 10
    grid_h = galaxy.regions_grid_h or 10
    traversal = _boustrophedon_order(grid_w, grid_h)
    region_index = fleet.autoscout_region_index or 0

    guild_member_ids = []
    gm = db.query(GuildMember).filter(GuildMember.user_id == fleet.user_id).first()
    if gm:
        members = db.query(GuildMember).filter(GuildMember.guild_id == gm.guild_id).all()
        guild_member_ids = [m.user_id for m in members]

    attempts = 0
    max_attempts = len(traversal) + 1
    while attempts < max_attempts:
        attempts += 1
        if region_index >= len(traversal):
            region_index = 0

        gx, gy = traversal[region_index]
        region = db.query(Region).filter(
            Region.galaxy_id == galaxy.id,
            Region.grid_x == gx, Region.grid_y == gy
        ).first()

        if not region or not region.systems:
            region_index += 1
            continue

        # Skip the region the scout is currently in — already scouted
        if current_region_id and region.id == current_region_id:
            region_index += 1
            continue

        guild_sys = _find_guild_base_system_in_region(region, guild_member_ids, db)
        if guild_sys:
            target_system = guild_sys
        else:
            target_system = sorted(region.systems, key=lambda s: s.id)[0]

        planets = sorted(target_system.planets, key=lambda p: (p.orbit_position, p.orbit_row or 1))
        target = planets[0] if planets else None

        fleet.autoscout_region_index = region_index + 1
        fleet.autoscout_system_index = 0
        fleet.autoscout_planet_index = 0

        if target:
            return target
        region_index += 1
        continue

    fleet.autoscout_region_index = 0
    fleet.autoscout_system_index = 0
    fleet.autoscout_planet_index = 0
    return None


def process_autoscout_tick(db: Session):
    """Move autoscout fleets through the galaxy using real fleet movement."""
    from game_logic import get_tech_level, _calc_distance, _process_fleet_arrivals
    now = datetime.utcnow()
    game_speed = get_config_float(db, "game_speed", 1.0)
    tick_interval = max(1.0, get_config_float(db, "AUTOSCOUT_TICK_INTERVAL", AUTOSCOUT_TICK_INTERVAL))
    raw_dwell_seconds = max(0.0, get_config_float(db, "AUTOSCOUT_DWELL_SECONDS", AUTOSCOUT_DWELL_SECONDS))
    dwell_seconds = max(tick_interval, raw_dwell_seconds / max(game_speed, 0.01))

    scout_ids = [fleet.id for fleet in db.query(Fleet.id).filter(Fleet.is_autoscout == True).all()]
    processed_users = set()
    for scout_id in scout_ids:
        fleet = db.query(Fleet).filter(Fleet.id == scout_id, Fleet.is_autoscout == True).first()
        if not fleet:
            continue
        user = db.query(User).filter(User.id == fleet.user_id).first()
        if not user:
            continue
        if user.id not in processed_users:
            _process_fleet_arrivals(user, db)
            processed_users.add(user.id)
            fleet = db.query(Fleet).filter(Fleet.id == scout_id, Fleet.is_autoscout == True).first()
            if not fleet:
                continue

        if not fleet.autoscout_galaxy_id:
            continue
        if fleet.is_moving:
            continue

        if fleet.autoscout_last_move and (now - fleet.autoscout_last_move).total_seconds() < dwell_seconds:
            continue

        # Autoscout scan+hop costs an action point (Turns economy). This is a
        # server-driven action, so pause the scout this tick when the owner can't
        # afford it rather than raising or moving for free; it resumes once turns
        # regenerate. No-op when the economy is off.
        if not action_points.can_afford_action(user, db, "autoscout_hop"):
            continue
        action_points.debit_action_points(user, db, "autoscout_hop")

        # Dwell complete — record intel for current location's region
        if fleet.location_planet_id:
            cur_planet = db.query(Planet).filter(Planet.id == fleet.location_planet_id).first()
            if cur_planet and cur_planet.system:
                _record_region_snapshot(fleet.user_id, cur_planet.system.region_id, db)
                _record_scouted_intel(fleet.user_id, cur_planet.system.region, db)

        # Find the fleet's current planet (for distance calc)
        origin_planet = None
        if fleet.base_id:
            colony = db.query(Colony).filter(Colony.id == fleet.base_id).first()
            if colony:
                origin_planet = colony.planet
        elif fleet.location_planet_id:
            origin_planet = db.query(Planet).filter(Planet.id == fleet.location_planet_id).first()

        if not origin_planet:
            continue

        # Pass current region so autoscout skips it (already scouted)
        current_region_id = None
        if origin_planet.system and origin_planet.system.region_id:
            current_region_id = origin_planet.system.region_id

        target_planet = _autoscout_get_next_target(fleet, db, current_region_id=current_region_id)
        if not target_planet:
            continue
        if target_planet.id == origin_planet.id:
            continue

        # Calculate travel using the scout ship's speed (capability-resolved)
        from auth import fleet_capability_ship
        scout_key = fleet_capability_ship(fleet, db, "can_autoscout")
        if not scout_key:
            # Flagged for autoscout but no capable ship remains (lost in combat or
            # a roster change). Stop autoscouting rather than crawling at the
            # default speed forever.
            fleet.is_autoscout = False
            continue
        scout_spec = get_effective_ship_spec(db, scout_key)
        scout_speed = scout_spec.get("speed", 12)
        drive_tech = get_tech_level(user, "warp_drive")
        speed_mult = 1 + drive_tech * 0.05

        travel_divisor = get_config_float(db, "FLEET_TRAVEL_DIVISOR", FLEET_TRAVEL_DIVISOR)
        distance = _calc_distance(origin_planet, target_planet)
        travel_time = distance * travel_divisor / (scout_speed * speed_mult * game_speed)
        travel_time = max(10, travel_time)

        # Send fleet using normal movement
        fleet.is_moving = True
        fleet.origin_base_id = fleet.base_id
        fleet.origin_planet_id = origin_planet.id if origin_planet else None
        dest_colony = target_planet.colony
        if dest_colony:
            fleet.destination_base_id = dest_colony.id
            fleet.destination_planet_id = None
        else:
            fleet.destination_base_id = None
            fleet.destination_planet_id = target_planet.id
        fleet.arrival_time = now + timedelta(seconds=travel_time)
        fleet.base_id = None
        fleet.location_planet_id = None

    db.commit()
