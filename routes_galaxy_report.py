"""
Galaxy Report routes — scouted bases, fleets, and moving fleets.
Split from routes_map.py for readability.
"""
from fastapi import Depends, Query, HTTPException
from sqlalchemy.orm import Session
from datetime import datetime

from sqlalchemy import func
from typing import Optional

from models import (
    User, Colony, Fleet, Planet, StarSystem, Region, Galaxy,
    ScoutedBase, ScoutedFleet, GuildMember, Guild, Building
)
from auth import get_token_from_header, get_current_user, get_db
from game_scouting import _get_guild_member_ids
from combat import _fleet_total_ships, _fleet_value
from specs import ALL_SHIP_TYPES, PLANET_TYPE_STATS


def register_galaxy_report_routes(app):

    @app.get("/api/scanners")
    def get_scanners(token: str = Depends(get_token_from_header), db: Session = Depends(get_db)):
        """Scanners — incoming fleet movements to regions where the player has bases."""
        user = get_current_user(token, db)
        now = datetime.utcnow()

        # Find all region IDs where this player has bases
        my_bases = db.query(Colony).filter(Colony.user_id == user.id).all()
        base_region_ids = set()
        for c in my_bases:
            if c.planet and c.planet.system:
                base_region_ids.add(c.planet.system.region_id)

        if not base_region_ids:
            return []

        # All colony IDs in those regions (for destination_base_id matching)
        region_colony_ids = set(
            cid for (cid,) in db.query(Colony.id)
            .join(Planet, Colony.planet_id == Planet.id)
            .join(StarSystem, Planet.system_id == StarSystem.id)
            .filter(StarSystem.region_id.in_(base_region_ids))
            .all()
        )
        # All planet IDs in those regions (for destination_planet_id matching)
        region_planet_ids = set(
            pid for (pid,) in db.query(Planet.id)
            .join(StarSystem, Planet.system_id == StarSystem.id)
            .filter(StarSystem.region_id.in_(base_region_ids))
            .all()
        )

        results = []

        # All moving fleets heading INTO our base regions
        moving = db.query(Fleet).filter(Fleet.is_moving == True).all()
        for f in moving:
            if f.arrival_time and f.arrival_time <= now:
                continue

            # Check if destination is in our base regions
            dest_planet = None
            if f.destination_base_id and f.destination_base_id in region_colony_ids:
                dest_col = db.query(Colony).filter(Colony.id == f.destination_base_id).first()
                if dest_col:
                    dest_planet = dest_col.planet
            elif f.destination_planet_id and f.destination_planet_id in region_planet_ids:
                dest_planet = db.query(Planet).filter(Planet.id == f.destination_planet_id).first()

            if not dest_planet:
                continue

            total = _fleet_total_ships(f)
            if total <= 0:
                continue

            owner = db.query(User).filter(User.id == f.user_id).first()
            if not owner:
                continue

            is_own = (f.user_id == user.id)
            guild_tag = _get_player_guild_tag(owner.id, db) if not is_own else ""

            entry = {
                "fleet_name": f.name if is_own else None,
                "player": owner.username,
                "guild_tag": guild_tag,
                "is_own": is_own,
                "destination": dest_planet.name if dest_planet else "Unknown",
                "arrival": f.arrival_time.isoformat() if f.arrival_time else None,
                "size": total,
            }

            if is_own:
                ships = f.get_all_ship_counts()
                entry["ships"] = ships

            results.append(entry)

        # Sort by arrival time (soonest first)
        results.sort(key=lambda r: r.get("arrival") or "")
        return results

    @app.get("/api/galaxy-report")
    def galaxy_report(
        galaxy_id: int = Query(...),
        show: str = Query("bases"),
        token: str = Depends(get_token_from_header),
        db: Session = Depends(get_db)
    ):
        """Galaxy Report — shows scouted bases, fleets, or moving fleets."""
        user = get_current_user(token, db)
        shared_ids = _get_guild_member_ids(user.id, db)

        galaxy = db.query(Galaxy).filter(Galaxy.id == galaxy_id).first()
        if not galaxy:
            raise HTTPException(404, "Galaxy not found")

        gal_prefix = galaxy.name + ":"
        gal_regions = db.query(Region.id).filter(Region.galaxy_id == galaxy_id).subquery()

        # Find regions with guild/player presence (base or stationary fleet)
        presence_region_ids = set()
        presence_bases = (db.query(Colony)
            .join(Planet, Colony.planet_id == Planet.id)
            .join(StarSystem, Planet.system_id == StarSystem.id)
            .filter(Colony.user_id.in_(shared_ids), StarSystem.region_id.in_(db.query(gal_regions)))
            .all())
        for c in presence_bases:
            presence_region_ids.add(c.planet.system.region_id)
        presence_fleets_q = (db.query(Fleet)
            .filter(Fleet.user_id.in_(shared_ids), Fleet.is_moving == False)
            .all())
        for f in presence_fleets_q:
            if f.base_id:
                pass  # already covered by base presence
            elif f.location_planet_id:
                p = db.query(Planet).filter(Planet.id == f.location_planet_id).first()
                if p and p.system.region_id:
                    rid = p.system.region_id
                    reg = db.query(Region).filter(Region.id == rid, Region.galaxy_id == galaxy_id).first()
                    if reg:
                        presence_region_ids.add(rid)

        if show == "bases":
            return _report_bases(db, shared_ids, gal_prefix, presence_region_ids)
        elif show == "fleets":
            return _report_fleets(db, shared_ids, gal_prefix, presence_region_ids)
        elif show == "moving_fleets":
            return _report_moving_fleets(db, shared_ids, gal_prefix, presence_region_ids)
        return []


    @app.get("/api/player-report")
    def player_report(
        player_id: int = Query(0),
        show: str = Query("bases"),
        token: str = Depends(get_token_from_header),
        db: Session = Depends(get_db)
    ):
        """Player Report — scouted bases/fleets for a specific player by ID."""
        user = get_current_user(token, db)
        shared_ids = _get_guild_member_ids(user.id, db)

        if not player_id:
            return {"bases": [], "fleets": [], "count": 0, "message": "Enter a player ID to search."}

        target_user = db.query(User).filter(User.id == player_id).first()
        if not target_user:
            return {"bases": [], "fleets": [], "count": 0, "message": "Player not found."}

        target_name = target_user.username

        # Get presence region IDs for live data
        presence_region_ids = set()
        for c in db.query(Colony).filter(Colony.user_id.in_(shared_ids)).all():
            if c.planet and c.planet.system:
                presence_region_ids.add(c.planet.system.region_id)

        if show == "bases":
            return _player_report_bases(db, shared_ids, target_name, presence_region_ids)
        elif show == "fleets":
            return _player_report_fleets(db, shared_ids, target_name, presence_region_ids)
        elif show == "moving_fleets":
            return _player_report_moving_fleets(db, shared_ids, target_name, presence_region_ids)
        return []

    @app.get("/api/guild-report")
    def guild_report(
        guild_id: int = Query(...),
        show: str = Query("bases"),
        token: str = Depends(get_token_from_header),
        db: Session = Depends(get_db)
    ):
        """Guild Report — scouted bases/fleets for members of a specific guild."""
        user = get_current_user(token, db)
        shared_ids = _get_guild_member_ids(user.id, db)

        guild = db.query(Guild).filter(Guild.id == guild_id).first()
        if not guild:
            raise HTTPException(404, "Guild not found")

        # Get all member usernames for this guild
        members = db.query(GuildMember).filter(GuildMember.guild_id == guild_id).all()
        member_user_ids = [m.user_id for m in members]
        member_users = db.query(User).filter(User.id.in_(member_user_ids)).all() if member_user_ids else []
        member_names = {u.username for u in member_users}

        # Get presence region IDs for live data
        presence_region_ids = set()
        for c in db.query(Colony).filter(Colony.user_id.in_(shared_ids)).all():
            if c.planet and c.planet.system:
                presence_region_ids.add(c.planet.system.region_id)

        if show == "bases":
            return _guild_report_bases(db, shared_ids, member_names, guild.tag, presence_region_ids)
        elif show == "fleets":
            return _guild_report_fleets(db, shared_ids, member_names, guild.tag, presence_region_ids)
        elif show == "moving_fleets":
            return _guild_report_moving_fleets(db, shared_ids, member_names, guild.tag, presence_region_ids)
        return []

    # ======================== TOP SCOUTERS ========================

    @app.get("/api/top-scouters")
    def top_scouters(token: str = Depends(get_token_from_header), db: Session = Depends(get_db)):
        """Rank players by number of unique bases they've scouted."""
        user = get_current_user(token, db)
        shared_ids = _get_guild_member_ids(user.id, db)

        # Count distinct (owner_name, location) per scouter
        rows = (
            db.query(
                ScoutedBase.user_id,
                func.count(func.distinct(ScoutedBase.owner_name + '|' + ScoutedBase.location)).label("cnt")
            )
            .filter(ScoutedBase.user_id.in_(shared_ids))
            .group_by(ScoutedBase.user_id)
            .order_by(func.count(func.distinct(ScoutedBase.owner_name + '|' + ScoutedBase.location)).desc())
            .all()
        )

        results = []
        for user_id_val, cnt in rows:
            u = db.query(User).filter(User.id == user_id_val).first()
            if u:
                results.append({"player": u.username, "scouted_count": cnt})
        return results

    # ======================== TOP JUMP GATES ========================

    @app.get("/api/top-jump-gates")
    def top_jump_gates(token: str = Depends(get_token_from_header), db: Session = Depends(get_db)):
        """Rank bases by jump gate level (only shows bases with jump gates)."""
        user = get_current_user(token, db)

        # Find all jump_gate buildings with level > 0
        jg_buildings = (
            db.query(Building, Colony, Planet)
            .join(Colony, Building.colony_id == Colony.id)
            .join(Planet, Colony.planet_id == Planet.id)
            .filter(Building.building_type == "jump_gate", Building.level > 0)
            .order_by(Building.level.desc())
            .all()
        )

        results = []
        for bld, col, planet in jg_buildings:
            owner = db.query(User).filter(User.id == col.user_id).first()
            if not owner:
                continue
            guild_tag = _get_player_guild_tag(owner.id, db)
            results.append({
                "player": _format_player(owner.username, guild_tag),
                "base": col.name,
                "location": planet.name,
                "level": bld.level,
            })
        return results

    # ======================== ASTROS REPORT ========================

    @app.get("/api/astros-report")
    def astros_report(
        galaxy_id: int = Query(0),
        terrain: Optional[str] = Query(None),
        body_type: Optional[str] = Query(None),
        orbit: Optional[int] = Query(None),
        token: str = Depends(get_token_from_header),
        db: Session = Depends(get_db)
    ):
        """Search astros by galaxy, terrain, body type, and orbit position."""
        user = get_current_user(token, db)

        if not galaxy_id:
            return {"results": [], "message": "Select a galaxy to search."}

        galaxy = db.query(Galaxy).filter(Galaxy.id == galaxy_id).first()
        if not galaxy:
            raise HTTPException(404, "Galaxy not found")

        # Base query: colonizable planets in this galaxy (exclude gas_giant, asteroid_belt)
        q = (
            db.query(Planet)
            .join(StarSystem, Planet.system_id == StarSystem.id)
            .join(Region, StarSystem.region_id == Region.id)
            .filter(
                Region.galaxy_id == galaxy_id,
                ~Planet.planet_type.in_(["gas_giant", "asteroid_belt"]),
            )
        )

        # Filter by terrain
        if terrain:
            q = q.filter(Planet.planet_type == terrain)

        # Filter by body type (inferred from planet_type and orbit_row)
        if body_type == "Planet":
            q = q.filter(~Planet.planet_type.in_(["gas_giant", "asteroid_belt", "asteroid"]), Planet.orbit_row == 0)
        elif body_type == "Moon":
            q = q.filter(~Planet.planet_type.in_(["gas_giant", "asteroid_belt"]), Planet.orbit_row > 0)
        elif body_type == "Asteroid":
            q = q.filter(Planet.planet_type.in_(["asteroid", "asteroid_belt"]))

        # Filter by orbit position
        if orbit:
            q = q.filter(Planet.orbit_position == orbit)

        planets = q.order_by(Planet.name).limit(500).all()

        results = []
        for p in planets:
            # Infer body type
            if p.planet_type == "asteroid":
                bt = "Asteroid"
            elif (p.orbit_row or 0) == 0:
                bt = "Planet"
            else:
                bt = "Moon"

            # Check if colonized
            owner_name = None
            base_name = None
            if p.colony:
                owner = db.query(User).filter(User.id == p.colony.user_id).first()
                owner_name = owner.username if owner else "?"
                base_name = p.colony.name

            results.append({
                "location": p.name,
                "terrain": PLANET_TYPE_STATS.get(p.planet_type, {}).get("name", p.planet_type),
                "type": bt,
                "orbit": p.orbit_position,
                "area": p.area,
                "solar": p.solar,
                "gas": p.gas,
                "fertility": p.fertility,
                "metal": p.metal,
                "crystal": p.crystal,
                "occupied": p.is_colonized,
                "owner": owner_name,
                "base_name": base_name,
            })

        return {"results": results, "count": len(results)}


def _get_player_guild_tag(user_id: int, db: Session) -> str:
    """Helper to look up a player's guild tag."""
    gm = db.query(GuildMember).filter(GuildMember.user_id == user_id).first()
    if gm:
        g = db.query(Guild).filter(Guild.id == gm.guild_id).first()
        if g:
            return g.tag
    return ""


def _format_player(username: str, guild_tag: str) -> str:
    return f"[{guild_tag}] {username}" if guild_tag else username


def _report_bases(db, shared_ids, gal_prefix, presence_region_ids):
    results = []
    seen_keys = set()

    # 1. Scouted bases from autoscout data
    scouted = db.query(ScoutedBase).filter(
        ScoutedBase.user_id.in_(shared_ids),
        ScoutedBase.location.like(gal_prefix + "%")
    ).order_by(ScoutedBase.location).all()
    for r in scouted:
        key = (r.owner_name, r.location)
        if key not in seen_keys:
            seen_keys.add(key)
            results.append({
                "player": _format_player(r.owner_name, r.owner_guild_tag),
                "base": r.base_name,
                "location": r.location,
                "last_seen": r.last_seen.isoformat() if r.last_seen else None,
            })

    # 2. Live bases in regions where we have presence
    if presence_region_ids:
        live_bases = (db.query(Colony)
            .join(Planet, Colony.planet_id == Planet.id)
            .join(StarSystem, Planet.system_id == StarSystem.id)
            .filter(StarSystem.region_id.in_(presence_region_ids))
            .all())
        for c in live_bases:
            owner = c.user
            guild_tag = _get_player_guild_tag(owner.id, db)
            loc = c.planet.name if c.planet else ""
            key = (owner.username, loc)
            if key not in seen_keys:
                seen_keys.add(key)
                results.append({
                    "player": _format_player(owner.username, guild_tag),
                    "base": c.name,
                    "location": loc,
                    "last_seen": None,
                })

    results.sort(key=lambda r: r.get("location", ""))
    return results


def _report_fleets(db, shared_ids, gal_prefix, presence_region_ids):
    results = []
    seen_keys = set()

    # 1. Scouted stationary fleets
    scouted = db.query(ScoutedFleet).filter(
        ScoutedFleet.user_id.in_(shared_ids),
        ScoutedFleet.is_moving == False,
        ScoutedFleet.location.like(gal_prefix + "%")
    ).order_by(ScoutedFleet.fleet_size.desc()).all()
    for r in scouted:
        key = (r.owner_name, r.location, "scouted")
        seen_keys.add(key)
        results.append({
            "player": _format_player(r.owner_name, r.owner_guild_tag),
            "location": r.location,
            "size": r.fleet_size,
            "last_seen": r.last_seen.isoformat() if r.last_seen else None,
            "days_ago": (datetime.utcnow() - r.last_seen).days if r.last_seen else None,
        })

    # 2. Live fleets in regions with presence
    if presence_region_ids:
        live_fleets = db.query(Fleet).filter(Fleet.is_moving == False).all()
        for f in live_fleets:
            loc_planet = None
            if f.base_id:
                col = db.query(Colony).filter(Colony.id == f.base_id).first()
                if col:
                    loc_planet = col.planet
            elif f.location_planet_id:
                loc_planet = db.query(Planet).filter(Planet.id == f.location_planet_id).first()
            if not loc_planet:
                continue
            rid = loc_planet.system.region_id
            if rid not in presence_region_ids:
                continue
            owner = db.query(User).filter(User.id == f.user_id).first()
            if not owner:
                continue
            loc = loc_planet.name if loc_planet else ""
            val = _fleet_value(f, db)
            if val <= 0:
                continue
            key = (owner.username, loc, "live")
            if key not in seen_keys:
                seen_keys.add(key)
                guild_tag = _get_player_guild_tag(owner.id, db)
                results.append({
                    "player": _format_player(owner.username, guild_tag),
                    "location": loc,
                    "size": val,
                    "last_seen": None,
                    "days_ago": None,
                })

    results.sort(key=lambda r: r.get("size", 0), reverse=True)
    return results


def _report_moving_fleets(db, shared_ids, gal_prefix, presence_region_ids):
    results = []
    now = datetime.utcnow()

    # 1. Scouted moving fleets
    scouted = db.query(ScoutedFleet).filter(
        ScoutedFleet.user_id.in_(shared_ids),
        ScoutedFleet.is_moving == True,
        ScoutedFleet.location.like(gal_prefix + "%")
    ).order_by(ScoutedFleet.fleet_size.desc()).all()
    for r in scouted:
        if r.arrival_time and r.arrival_time > now:
            results.append({
                "player": _format_player(r.owner_name, r.owner_guild_tag),
                "destination": r.destination,
                "arrival": r.arrival_time.isoformat(),
                "size": r.fleet_size,
                "last_seen": r.last_seen.isoformat() if r.last_seen else None,
                "days_ago": (now - r.last_seen).days if r.last_seen else None,
            })

    # 2. Live moving fleets visible from presence regions
    if presence_region_ids:
        moving = db.query(Fleet).filter(Fleet.is_moving == True).all()
        for f in moving:
            if not f.destination_planet_id and not f.destination_base_id:
                continue
            dest_planet = None
            if f.destination_base_id:
                dest_col = db.query(Colony).filter(Colony.id == f.destination_base_id).first()
                if dest_col:
                    dest_planet = dest_col.planet
            elif f.destination_planet_id:
                dest_planet = db.query(Planet).filter(Planet.id == f.destination_planet_id).first()
            if not dest_planet:
                continue
            rid = dest_planet.system.region_id
            if rid not in presence_region_ids:
                continue
            owner = db.query(User).filter(User.id == f.user_id).first()
            if not owner:
                continue
            val = _fleet_value(f, db)
            if val <= 0:
                continue
            guild_tag = _get_player_guild_tag(owner.id, db)
            dest_loc = dest_planet.name if dest_planet else ""
            arrival = f.arrival_time.isoformat() if f.arrival_time else None
            results.append({
                "player": _format_player(owner.username, guild_tag),
                "destination": dest_loc,
                "arrival": arrival,
                "size": val,
                "last_seen": None,
                "days_ago": None,
            })

    if not results:
        return {"message": "No moving fleets detected in regions where you have presence.", "data": []}
    results.sort(key=lambda r: r.get("size", 0), reverse=True)
    return results


# ======================== PLAYER REPORT HELPERS ========================

def _player_report_bases(db, shared_ids, target_name, presence_region_ids):
    results = []
    seen_keys = set()

    # 1. Scouted bases matching target player
    scouted = db.query(ScoutedBase).filter(
        ScoutedBase.user_id.in_(shared_ids),
        ScoutedBase.owner_name == target_name
    ).order_by(ScoutedBase.location).all()
    for r in scouted:
        key = (r.owner_name, r.location)
        if key not in seen_keys:
            seen_keys.add(key)
            results.append({
                "player": _format_player(r.owner_name, r.owner_guild_tag),
                "base": r.base_name,
                "location": r.location,
                "last_seen": r.last_seen.isoformat() if r.last_seen else None,
            })

    # 2. Live bases in regions with presence
    if presence_region_ids:
        target_user = db.query(User).filter(User.username == target_name).first()
        if target_user:
            live = (db.query(Colony)
                .join(Planet, Colony.planet_id == Planet.id)
                .join(StarSystem, Planet.system_id == StarSystem.id)
                .filter(Colony.user_id == target_user.id,
                        StarSystem.region_id.in_(presence_region_ids))
                .all())
            for c in live:
                loc = c.planet.name if c.planet else ""
                key = (target_name, loc)
                if key not in seen_keys:
                    seen_keys.add(key)
                    gt = _get_player_guild_tag(target_user.id, db)
                    results.append({
                        "player": _format_player(target_name, gt),
                        "base": c.name,
                        "location": loc,
                        "last_seen": None,
                    })

    results.sort(key=lambda r: r.get("location", ""))
    return results


def _player_report_fleets(db, shared_ids, target_name, presence_region_ids):
    results = []
    seen_keys = set()

    # 1. Scouted stationary fleets
    scouted = db.query(ScoutedFleet).filter(
        ScoutedFleet.user_id.in_(shared_ids),
        ScoutedFleet.is_moving == False,
        ScoutedFleet.owner_name == target_name
    ).order_by(ScoutedFleet.fleet_size.desc()).all()
    for r in scouted:
        key = (r.owner_name, r.location, "scouted")
        seen_keys.add(key)
        results.append({
            "player": _format_player(r.owner_name, r.owner_guild_tag),
            "location": r.location,
            "size": r.fleet_size,
            "last_seen": r.last_seen.isoformat() if r.last_seen else None,
            "days_ago": (datetime.utcnow() - r.last_seen).days if r.last_seen else None,
        })

    # 2. Live fleets in presence regions
    if presence_region_ids:
        target_user = db.query(User).filter(User.username == target_name).first()
        if target_user:
            live_fleets = db.query(Fleet).filter(
                Fleet.user_id == target_user.id, Fleet.is_moving == False
            ).all()
            for f in live_fleets:
                loc_planet = None
                if f.base_id:
                    col = db.query(Colony).filter(Colony.id == f.base_id).first()
                    if col:
                        loc_planet = col.planet
                elif f.location_planet_id:
                    loc_planet = db.query(Planet).filter(Planet.id == f.location_planet_id).first()
                if not loc_planet:
                    continue
                rid = loc_planet.system.region_id
                if rid not in presence_region_ids:
                    continue
                loc = loc_planet.name if loc_planet else ""
                val = _fleet_value(f, db)
                if val <= 0:
                    continue
                key = (target_name, loc, "live")
                if key not in seen_keys:
                    seen_keys.add(key)
                    gt = _get_player_guild_tag(target_user.id, db)
                    results.append({
                        "player": _format_player(target_name, gt),
                        "location": loc,
                        "size": val,
                        "last_seen": None,
                        "days_ago": None,
                    })

    results.sort(key=lambda r: r.get("size", 0), reverse=True)
    return results


def _player_report_moving_fleets(db, shared_ids, target_name, presence_region_ids):
    results = []
    now = datetime.utcnow()

    # 1. Scouted moving fleets
    scouted = db.query(ScoutedFleet).filter(
        ScoutedFleet.user_id.in_(shared_ids),
        ScoutedFleet.is_moving == True,
        ScoutedFleet.owner_name == target_name
    ).order_by(ScoutedFleet.fleet_size.desc()).all()
    for r in scouted:
        if r.arrival_time and r.arrival_time > now:
            results.append({
                "player": _format_player(r.owner_name, r.owner_guild_tag),
                "destination": r.destination,
                "arrival": r.arrival_time.isoformat(),
                "size": r.fleet_size,
                "last_seen": r.last_seen.isoformat() if r.last_seen else None,
                "days_ago": (now - r.last_seen).days if r.last_seen else None,
            })

    # 2. Live moving fleets in presence regions
    if presence_region_ids:
        target_user = db.query(User).filter(User.username == target_name).first()
        if target_user:
            moving = db.query(Fleet).filter(
                Fleet.user_id == target_user.id, Fleet.is_moving == True
            ).all()
            for f in moving:
                if not f.destination_planet_id and not f.destination_base_id:
                    continue
                dest_planet = None
                if f.destination_base_id:
                    dest_col = db.query(Colony).filter(Colony.id == f.destination_base_id).first()
                    if dest_col:
                        dest_planet = dest_col.planet
                elif f.destination_planet_id:
                    dest_planet = db.query(Planet).filter(Planet.id == f.destination_planet_id).first()
                if not dest_planet:
                    continue
                rid = dest_planet.system.region_id
                if rid not in presence_region_ids:
                    continue
                val = _fleet_value(f, db)
                if val <= 0:
                    continue
                gt = _get_player_guild_tag(target_user.id, db)
                dest_loc = dest_planet.name if dest_planet else ""
                arrival = f.arrival_time.isoformat() if f.arrival_time else None
                results.append({
                    "player": _format_player(target_name, gt),
                    "destination": dest_loc,
                    "arrival": arrival,
                    "size": val,
                    "last_seen": None,
                    "days_ago": None,
                })

    if not results:
        return {"message": "No moving fleets detected for this player.", "data": []}
    results.sort(key=lambda r: r.get("size", 0), reverse=True)
    return results


# ======================== GUILD REPORT HELPERS ========================

def _guild_report_bases(db, shared_ids, member_names, guild_tag, presence_region_ids):
    results = []
    seen_keys = set()

    # 1. Scouted bases belonging to guild members
    scouted = db.query(ScoutedBase).filter(
        ScoutedBase.user_id.in_(shared_ids),
        ScoutedBase.owner_name.in_(member_names)
    ).order_by(ScoutedBase.location).all()
    for r in scouted:
        key = (r.owner_name, r.location)
        if key not in seen_keys:
            seen_keys.add(key)
            results.append({
                "player": _format_player(r.owner_name, r.owner_guild_tag or guild_tag),
                "base": r.base_name,
                "location": r.location,
                "last_seen": r.last_seen.isoformat() if r.last_seen else None,
            })

    # 2. Live bases in presence regions
    if presence_region_ids:
        member_users = db.query(User).filter(User.username.in_(member_names)).all()
        member_user_ids = [u.id for u in member_users]
        if member_user_ids:
            live = (db.query(Colony)
                .join(Planet, Colony.planet_id == Planet.id)
                .join(StarSystem, Planet.system_id == StarSystem.id)
                .filter(Colony.user_id.in_(member_user_ids),
                        StarSystem.region_id.in_(presence_region_ids))
                .all())
            for c in live:
                loc = c.planet.name if c.planet else ""
                key = (c.user.username, loc)
                if key not in seen_keys:
                    seen_keys.add(key)
                    results.append({
                        "player": _format_player(c.user.username, guild_tag),
                        "base": c.name,
                        "location": loc,
                        "last_seen": None,
                    })

    results.sort(key=lambda r: r.get("location", ""))
    return results


def _guild_report_fleets(db, shared_ids, member_names, guild_tag, presence_region_ids):
    results = []
    seen_keys = set()

    # 1. Scouted stationary fleets
    scouted = db.query(ScoutedFleet).filter(
        ScoutedFleet.user_id.in_(shared_ids),
        ScoutedFleet.is_moving == False,
        ScoutedFleet.owner_name.in_(member_names)
    ).order_by(ScoutedFleet.fleet_size.desc()).all()
    for r in scouted:
        key = (r.owner_name, r.location, "scouted")
        seen_keys.add(key)
        results.append({
            "player": _format_player(r.owner_name, r.owner_guild_tag or guild_tag),
            "location": r.location,
            "size": r.fleet_size,
            "last_seen": r.last_seen.isoformat() if r.last_seen else None,
            "days_ago": (datetime.utcnow() - r.last_seen).days if r.last_seen else None,
        })

    # 2. Live fleets in presence regions
    if presence_region_ids:
        member_users = db.query(User).filter(User.username.in_(member_names)).all()
        member_user_ids = [u.id for u in member_users]
        if member_user_ids:
            live_fleets = db.query(Fleet).filter(
                Fleet.user_id.in_(member_user_ids), Fleet.is_moving == False
            ).all()
            for f in live_fleets:
                loc_planet = None
                if f.base_id:
                    col = db.query(Colony).filter(Colony.id == f.base_id).first()
                    if col:
                        loc_planet = col.planet
                elif f.location_planet_id:
                    loc_planet = db.query(Planet).filter(Planet.id == f.location_planet_id).first()
                if not loc_planet:
                    continue
                rid = loc_planet.system.region_id
                if rid not in presence_region_ids:
                    continue
                owner = db.query(User).filter(User.id == f.user_id).first()
                if not owner:
                    continue
                loc = loc_planet.name if loc_planet else ""
                val = _fleet_value(f, db)
                if val <= 0:
                    continue
                key = (owner.username, loc, "live")
                if key not in seen_keys:
                    seen_keys.add(key)
                    results.append({
                        "player": _format_player(owner.username, guild_tag),
                        "location": loc,
                        "size": val,
                        "last_seen": None,
                        "days_ago": None,
                    })

    results.sort(key=lambda r: r.get("size", 0), reverse=True)
    return results


def _guild_report_moving_fleets(db, shared_ids, member_names, guild_tag, presence_region_ids):
    results = []
    now = datetime.utcnow()

    # 1. Scouted moving fleets
    scouted = db.query(ScoutedFleet).filter(
        ScoutedFleet.user_id.in_(shared_ids),
        ScoutedFleet.is_moving == True,
        ScoutedFleet.owner_name.in_(member_names)
    ).order_by(ScoutedFleet.fleet_size.desc()).all()
    for r in scouted:
        if r.arrival_time and r.arrival_time > now:
            results.append({
                "player": _format_player(r.owner_name, r.owner_guild_tag or guild_tag),
                "destination": r.destination,
                "arrival": r.arrival_time.isoformat(),
                "size": r.fleet_size,
                "last_seen": r.last_seen.isoformat() if r.last_seen else None,
                "days_ago": (now - r.last_seen).days if r.last_seen else None,
            })

    # 2. Live moving fleets in presence regions
    if presence_region_ids:
        member_users = db.query(User).filter(User.username.in_(member_names)).all()
        member_user_ids = [u.id for u in member_users]
        if member_user_ids:
            moving = db.query(Fleet).filter(
                Fleet.user_id.in_(member_user_ids), Fleet.is_moving == True
            ).all()
            for f in moving:
                if not f.destination_planet_id and not f.destination_base_id:
                    continue
                dest_planet = None
                if f.destination_base_id:
                    dest_col = db.query(Colony).filter(Colony.id == f.destination_base_id).first()
                    if dest_col:
                        dest_planet = dest_col.planet
                elif f.destination_planet_id:
                    dest_planet = db.query(Planet).filter(Planet.id == f.destination_planet_id).first()
                if not dest_planet:
                    continue
                rid = dest_planet.system.region_id
                if rid not in presence_region_ids:
                    continue
                owner = db.query(User).filter(User.id == f.user_id).first()
                if not owner:
                    continue
                val = _fleet_value(f, db)
                if val <= 0:
                    continue
                dest_loc = dest_planet.name if dest_planet else ""
                arrival = f.arrival_time.isoformat() if f.arrival_time else None
                results.append({
                    "player": _format_player(owner.username, guild_tag),
                    "destination": dest_loc,
                    "arrival": arrival,
                    "size": val,
                    "last_seen": None,
                    "days_ago": None,
                })

    if not results:
        return {"message": "No moving fleets detected for this guild.", "data": []}
    results.sort(key=lambda r: r.get("size", 0), reverse=True)
    return results
