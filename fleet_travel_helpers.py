from models import Building, Colony, Wormhole
from auth import get_effective_ship_spec, get_config_float
from game_logic import _calc_distance, get_building_level, get_tech_level
from specs import ALL_SHIP_TYPES
from config_defaults import WORMHOLE_TOP_JG_COUNT, WORMHOLE_SPEED_PER_JG_LEVEL, JUMP_GATE_SPEED_BONUS_PER_LEVEL, FLEET_TRAVEL_DIVISOR

def _calc_wormhole_speed_factor(db):
    """Calculate wormhole speed factor from top N Jump Gate levels on the server."""
    top_n = int(WORMHOLE_TOP_JG_COUNT)
    # Get all jump_gate building levels across all bases
    jg_buildings = (db.query(Building.level)
        .filter(Building.building_type == "jump_gate", Building.level > 0)
        .order_by(Building.level.desc())
        .limit(top_n)
        .all())
    if not jg_buildings:
        return 1.0  # base factor, no bonus
    levels = [b.level for b in jg_buildings]
    avg_level = sum(levels) / len(levels)
    return 1 + WORMHOLE_SPEED_PER_JG_LEVEL * int(avg_level)  # floor of avg


def _calc_fleet_travel(fleet, user, db, origin_planet, dest_planet, game_speed, drive_override=None, use_jump_gate=False, use_wormhole=False):
    """Calculate travel time for a fleet moving to a destination.
    use_jump_gate: player must opt-in to use a Jump Gate at the origin astro.
    use_wormhole: player must opt-in to use a Wormhole at the origin astro.
    Returns dict with travel info + jg_available, jg_level, wh_available, wh_dest_planet_id.
    """
    stellar_level = get_tech_level(user, "stellar_drive")
    warp_level = get_tech_level(user, "warp_drive")

    # Get tech-based speed bonuses (e.g., Anti-Gravity +5% flagship speed per level)
    from game_logic import evaluate_tech_bonuses
    tech_bonuses = evaluate_tech_bonuses(user, db)
    speed_mults = tech_bonuses.get("speed_multipliers", {})

    ship_speeds = {}
    min_speed = 999
    drive_types = set()
    for st in ALL_SHIP_TYPES:
        count = fleet.get_ship_count(st)
        if count > 0:
            spec = get_effective_ship_spec(db, st)
            base_spd = spec["speed"]
            drive = spec.get("drive", "stellar")
            if base_spd > 0:
                drive_types.add(drive)
                if drive_override is not None:
                    tech_lvl = drive_override
                else:
                    tech_lvl = warp_level if drive == "warp" else stellar_level
                effective = round(base_spd * (1 + tech_lvl * 0.05), 1)
                # Apply per-ship-type speed bonuses (e.g., Anti-Gravity â†’ capital units)
                ship_bonus = speed_mults.get(st, 1.0)
                if ship_bonus != 1.0:
                    effective = round(effective * ship_bonus, 1)
                ship_speeds[st] = effective
                min_speed = min(min_speed, effective)
    if min_speed == 999:
        min_speed = 1

    # Jump gate bonus and cross-galaxy checks
    speed_mult = 1.0
    jg_level = 0
    origin_planet_id = origin_planet.id
    if fleet.base_id:
        origin_colony = db.query(Colony).filter(Colony.id == fleet.base_id).first()
        if origin_colony:
            jg_level = get_building_level(origin_colony, "jump_gate")

    # Check guild members' Jump Gates on the same planet (guild sharing)
    if jg_level <= 0:
        from models import GuildMember
        player_membership = db.query(GuildMember).filter(GuildMember.user_id == user.id).first()
        if player_membership:
            guild_member_ids = [gm.user_id for gm in
                db.query(GuildMember.user_id).filter(
                    GuildMember.guild_id == player_membership.guild_id,
                    GuildMember.user_id != user.id
                ).all()]
            if guild_member_ids:
                guild_colonies = db.query(Colony).filter(
                    Colony.planet_id == origin_planet_id,
                    Colony.user_id.in_(guild_member_ids)
                ).all()
                for gc in guild_colonies:
                    gc_jg = get_building_level(gc, "jump_gate")
                    if gc_jg > jg_level:
                        jg_level = gc_jg

    # Apply JG speed bonus only if player opted in
    if use_jump_gate and jg_level > 0:
        jg_bonus = get_config_float(db, "jump_gate_speed_bonus", JUMP_GATE_SPEED_BONUS_PER_LEVEL)
        speed_mult *= (1 + jg_level * jg_bonus)

    # Check for wormhole at origin (works like a jump gate â€” choose any destination)
    origin_wormhole = db.query(Wormhole).filter(Wormhole.planet_id == origin_planet.id).first()
    wh_available = bool(origin_wormhole)

    # Apply wormhole speed bonus if player opted in
    if use_wormhole:
        if not origin_wormhole:
            return {"error": "No wormhole at this location."}
        wh_speed = _calc_wormhole_speed_factor(db)
        speed_mult *= wh_speed

    # Check if cross-galaxy travel
    is_cross_galaxy = False
    if origin_planet.system and dest_planet.system:
        origin_gal_id = origin_planet.system.region.galaxy_id
        dest_gal_id = dest_planet.system.region.galaxy_id
        if origin_gal_id != dest_gal_id:
            is_cross_galaxy = True

    # Stellar-only fleets need a Jump Gate or Wormhole for cross-galaxy travel
    if is_cross_galaxy and "stellar" in drive_types and "warp" not in drive_types:
        if not (use_jump_gate and jg_level > 0) and not use_wormhole:
            hint = ""
            if jg_level > 0 or wh_available:
                hint = " Enable 'Use Jump Gate' or 'Use Wormhole' to proceed."
            return {"error": f"Stellar-drive fleets require a Jump Gate or Wormhole to travel between galaxies.{hint}"}

    travel_divisor = get_config_float(db, "FLEET_TRAVEL_DIVISOR", FLEET_TRAVEL_DIVISOR)
    distance = _calc_distance(origin_planet, dest_planet)
    travel_time = distance * travel_divisor / (min_speed * speed_mult * game_speed)
    travel_time = max(10, travel_time)

    # Logistics commander bonus: -X% travel time per level at departure base
    # Applies to owner's fleets AND guild members departing from this base
    from game_logic import get_commander_level_at_base, get_commander_bonus
    departure_colony = db.query(Colony).filter(Colony.planet_id == fleet.location_planet_id).first() if fleet.location_planet_id else None
    if departure_colony:
        logistics_lv = get_commander_level_at_base(db, departure_colony.id, "logistics")
        if logistics_lv > 0:
            # Check if fleet owner is the base owner or a guild member
            apply_bonus = False
            if departure_colony.user_id == fleet.user_id:
                apply_bonus = True
            else:
                # Check guild membership
                from models import GuildMember
                fleet_guild = db.query(GuildMember.guild_id).filter(GuildMember.user_id == fleet.user_id).scalar()
                base_guild = db.query(GuildMember.guild_id).filter(GuildMember.user_id == departure_colony.user_id).scalar()
                if fleet_guild and base_guild and fleet_guild == base_guild:
                    apply_bonus = True
            if apply_bonus:
                travel_time *= (1 - logistics_lv * get_commander_bonus(db, "logistics"))
                travel_time = max(10, travel_time)

    # Natural wormhole: a flat hop regardless of distance (overrides the speed
    # math above), plus an optional traverse-damage tax (applied on send).
    wormhole_damage_pct = 0.0
    if use_wormhole:
        import wormhole as _wh
        if _wh.is_natural(db):
            travel_time = _wh.flat_travel_seconds(db, game_speed)
            wormhole_damage_pct = _wh.damage_percent(db)

    return {
        "travel_time": travel_time,
        "wormhole_damage_pct": wormhole_damage_pct,
        "min_speed": min_speed,
        "distance": distance,
        "speed_mult": speed_mult,
        "ship_speeds": ship_speeds,
        "drive_types": drive_types,
        "stellar_level": stellar_level,
        "warp_level": warp_level,
        "jg_available": jg_level > 0,
        "jg_level": jg_level,
        "wh_available": wh_available,
    }


