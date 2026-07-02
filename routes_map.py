from fastapi import Depends, Query, HTTPException
from typing import Optional
from sqlalchemy.orm import Session
from sqlalchemy import func
from datetime import datetime, timedelta
import json

from database import SessionLocal
from models import (
    User, Cluster, Galaxy, Region, StarSystem, Planet, Colony, Building,
    Defense, Fleet, ScoutedRegion, ScoutedBase, ScoutedFleet,
    GalaxyLink, BattleReport, ShipQueue,
    GuildMember, Guild, Wormhole
)
from auth import (
    get_token_from_header, get_optional_token_dep, get_current_user,
    get_config, get_config_float, get_config_int, get_db
)
from game_logic import (
    collect_resources, _process_fleet_arrivals, _process_ship_queues,
    _fleet_total_ships, _fleet_value, calc_economy_rate, calc_max_fleet_size,
    calc_max_fleet_count, calc_player_level, calc_colony_cost, calc_tech_cost,
    apply_colony_reserve,
    calc_base_stats, _get_region_visibility, get_building_level, get_tech_level
)
from resources import get_user_resources
from config_defaults import NEWBIE_PROTECTION_LEVEL
from specs import SHIP_SPECS, ALL_SHIP_TYPES, BUILDING_SPECS, DEFENSE_SPECS, get_astro_category
from auth import get_effective_building_spec, get_effective_defense_spec, get_effective_ship_spec


def _guild_tag(user_id, db):
    """Get a player's guild tag or empty string."""
    gm = db.query(GuildMember).filter(GuildMember.user_id == user_id).first()
    if gm:
        g = db.query(Guild).filter(Guild.id == gm.guild_id).first()
        if g:
            return g.tag
    return ""


def _body_type(planet):
    """Determine actual body type from planet_type and orbit_row."""
    if planet.planet_type in ("asteroid", "asteroid_belt"):
        return "Asteroid"
    if planet.planet_type == "gas_giant":
        return "Gas Giant"
    if (planet.orbit_row or 0) > 0:
        return "Moon"
    return "Planet"


def _fog_visible_type(planet):
    """Return the astro type that remains visible through fog of war.

    The engine still distinguishes a few obvious body classes such as gas giants,
    asteroids, and asteroid belts. Everything else stays masked down to the
    broader body category.
    """
    if planet.planet_type in ("gas_giant", "asteroid", "asteroid_belt"):
        return planet.planet_type
    return get_astro_category(planet.planet_type, _body_type(planet)).lower()


def register_map_routes(app):
    """Register all map and galaxy API endpoints."""

    @app.get("/api/game/status")
    def game_status(db: Session = Depends(get_db)):
        status_val = get_config(db, "game_status", "setup")
        # During generation, return minimal data to avoid locking
        if status_val == "generating":
            return {
                "status": "generating",
                "gen_progress": get_config(db, "gen_progress", ""),
                "game_name": get_config(db, "game_name", "AstroWebEngine"),
                "total_planets": 0, "colonized_planets": 0, "total_players": 0,
                "colonize_cost": 0, "winner": "", "domination_pct": 0,
                "economic_target": 0, "win_condition": "", "game_speed": 1.0,
            }
        total_planets = db.query(Planet).count()
        colonized = db.query(Planet).filter(Planet.is_colonized == True).count()
        total_players = db.query(User).filter(User.is_admin == False, User.is_bot == False).count()
        total_bases = db.query(Colony).count()
        # Online = seen in last 5 minutes
        online_cutoff = datetime.utcnow() - timedelta(minutes=5)
        online_count = db.query(User).filter(User.last_seen >= online_cutoff, User.is_admin == False, User.is_bot == False).count()
        # Server age in days
        first_user = db.query(User).order_by(User.created_at).first()
        started_days = (datetime.utcnow() - first_user.created_at).days if first_user else 0
        return {
            "status": status_val,
            "gen_progress": "",
            "game_name": get_config(db, "game_name", "AstroWebEngine"),
            "colonize_cost": get_config_int(db, "colonize_cost", 200),
            "total_planets": total_planets,
            "colonized_planets": colonized,
            "total_players": total_players,
            "online_players": online_count,
            "total_bases": total_bases,
            "started_days": started_days,
            "winner": get_config(db, "winner", ""),
            "domination_pct": round(colonized / max(total_planets, 1) * 100, 1),
            "economic_target": get_config_int(db, "economic_target", 100000),
            "win_condition": get_config(db, "win_condition", "domination"),
            "game_speed": get_config_float(db, "game_speed", 1.0),
        }

    @app.get("/api/player/stats")
    def player_stats(token: str = Depends(get_token_from_header), db: Session = Depends(get_db)):
        user = get_current_user(token, db)
        game_speed = get_config_float(db, "game_speed", 1.0)
        collect_resources(user, db, game_speed)
        _process_fleet_arrivals(user, db)
        _process_ship_queues(user, db, game_speed)
        base_count = len(user.colonies)
        occupied_count = db.query(Colony).filter(Colony.occupied_by == user.id).count()
        total_ships = sum(_fleet_total_ships(f) for f in user.fleets)
        total_econ = sum(calc_economy_rate(c, user, game_speed) for c in user.colonies)
        total_fleet_size = sum(_fleet_value(f, db) for f in user.fleets)
        max_fleet = calc_max_fleet_size(user, game_speed)
        level = calc_player_level(user, db, game_speed)
        next_colony_cost = calc_colony_cost(user)
        next_colony_net, next_colony_reserve_used = apply_colony_reserve(user, next_colony_cost)
        total_tech = round(calc_tech_cost(user, db))
        import action_points
        return {
            "credits": round(user.credits, 1),
            "resources": {k: round(v, 1) for k, v in get_user_resources(user).items()},
            "action_points": action_points.ap_state(user, db),
            "bases": base_count,
            "ships": total_ships,
            "total_ships": total_ships,
            "score": user.score,
            "economy": round(total_econ, 1),
            "level": level,
            "experience": round(user.experience, 1),
            "fleet_size": round(total_fleet_size),
            "max_fleet_size": max_fleet,
            "fleet_count": len(user.fleets),
            "max_fleet_count": calc_max_fleet_count(user, db),
            "occupied_bases": occupied_count,
            "next_colony_cost": next_colony_cost,
            "next_colony_net": round(next_colony_net),
            "base_reserve": round(getattr(user, "base_reserve", 0.0) or 0.0),
            "bases_founded_peak": getattr(user, "bases_founded_peak", 0) or 0,
            "technology": total_tech,
            "is_admin": user.is_admin,
            "level_protected": level < NEWBIE_PROTECTION_LEVEL,
            "date_format": user.date_format or "MDY",
            "show_bbcode_images": bool(user.show_bbcode_images),
        }

    @app.get("/api/player/notifications")
    def player_notifications(token: str = Depends(get_token_from_header), db: Session = Depends(get_db)):
        user = get_current_user(token, db)
        reports = db.query(BattleReport).filter(
            (BattleReport.attacker_id == user.id) | (BattleReport.defender_id == user.id)
        ).order_by(BattleReport.created_at.desc()).limit(20).all()
        return [{"id": r.id, "created_at": r.created_at.isoformat()} for r in reports]

    @app.get("/api/clusters")
    def get_clusters(db: Session = Depends(get_db)):
        """List all clusters with their galaxies."""
        clusters = db.query(Cluster).all()
        result = []
        for c in clusters:
            gals = db.query(Galaxy).filter(Galaxy.cluster_id == c.id).order_by(Galaxy.galaxy_index).all()
            result.append({
                "id": c.id,
                "name": c.name,
                "cluster_index": c.cluster_index,
                "galaxies": [{"id": g.id, "name": g.name, "galaxy_index": g.galaxy_index} for g in gals],
            })
        return result

    @app.get("/api/galaxies")
    def get_galaxies(db: Session = Depends(get_db)):
        galaxies = db.query(Galaxy).order_by(Galaxy.name).all()
        result = []
        for g in galaxies:
            cluster_name = ""
            if g.cluster:
                cluster_name = g.cluster.name
            result.append({
                "id": g.id, "name": g.name,
                "cluster_id": g.cluster_id, "cluster_name": cluster_name,
                "galaxy_index": g.galaxy_index,
                "grid_w": g.regions_grid_w, "grid_h": g.regions_grid_h,
            })
        return result

    @app.get("/api/galaxy-links")
    def get_galaxy_links(db: Session = Depends(get_db)):
        """Get all galaxy connections for map visualization."""
        links = db.query(GalaxyLink).all()
        return [{"galaxy_a_id": l.galaxy_a_id, "galaxy_b_id": l.galaxy_b_id, "distance": l.distance} for l in links]

    @app.get("/api/galaxies/{galaxy_id}/graph")
    def get_galaxy_graph(galaxy_id: int, db: Session = Depends(get_db)):
        """Graph-topology view of one galaxy: systems (as nodes with grid
        positions) + their SystemLink edges. Empty when not in graph mode — the
        data layer for a node-link map rendering."""
        import graph_map
        from models import SystemLink, StarSystem, Region
        if not graph_map.is_graph_map(db):
            return {"graph_mode": False, "nodes": [], "links": []}
        systems = (db.query(StarSystem)
                   .join(Region, StarSystem.region_id == Region.id)
                   .filter(Region.galaxy_id == galaxy_id).all())
        sys_ids = {s.id for s in systems}
        nodes = []
        for s in systems:
            _, x, y = graph_map._system_xy(s)
            nodes.append({"id": s.id, "name": s.name, "x": x, "y": y,
                          "region_id": s.region_id, "star_type": s.star_type})
        # links with at least one endpoint in this galaxy
        links = []
        for l in db.query(SystemLink).all():
            if l.system_a_id in sys_ids or l.system_b_id in sys_ids:
                links.append({"system_a_id": l.system_a_id, "system_b_id": l.system_b_id,
                              "weight": l.weight, "kind": l.kind, "one_way": l.one_way})
        return {"graph_mode": True, "galaxy_id": galaxy_id, "nodes": nodes, "links": links}

    @app.get("/api/wormhole-report")
    def wormhole_report(token: str = Depends(get_token_from_header), db: Session = Depends(get_db)):
        """Return wormholes only in regions the player has scouted."""
        user = get_current_user(token, db)
        # Get all region IDs this player has scouted
        scouted_region_ids = {r[0] for r in db.query(ScoutedRegion.region_id).filter(
            ScoutedRegion.user_id == user.id).all()}
        # Also include regions where the player has a colony (always visible)
        for colony in user.colonies:
            if colony.planet and colony.planet.system:
                scouted_region_ids.add(colony.planet.system.region_id)
        wormholes = db.query(Wormhole).all()
        result = []
        for wh in wormholes:
            planet = wh.planet
            if not planet or not planet.system:
                continue
            system = planet.system
            region = system.region
            if region.id not in scouted_region_ids:
                continue  # Player hasn't scouted this region
            galaxy = region.galaxy
            result.append({
                "id": wh.id,
                "location": planet.name,
                "planet_id": planet.id,
                "galaxy": galaxy.name,
                "wormhole_type": wh.wormhole_type,
            })
        return result

    @app.get("/api/galaxies/{galaxy_id}/regions")
    def get_galaxy_regions(galaxy_id: int, token: Optional[str] = Depends(get_optional_token_dep), db: Session = Depends(get_db)):
        # Use efficient SQL aggregates instead of lazy-loading all systems/planets
        regions = db.query(Region).filter(Region.galaxy_id == galaxy_id).all()

        # Batch: system counts per region
        sys_counts = dict(
            db.query(StarSystem.region_id, func.count(StarSystem.id))
            .filter(StarSystem.region_id.in_([r.id for r in regions]))
            .group_by(StarSystem.region_id).all()
        )
        # Batch: planet counts per region (join through systems)
        planet_counts = dict(
            db.query(StarSystem.region_id, func.count(Planet.id))
            .join(Planet, Planet.system_id == StarSystem.id)
            .filter(StarSystem.region_id.in_([r.id for r in regions]))
            .group_by(StarSystem.region_id).all()
        )
        # Batch: colonized counts per region
        colonized_counts = dict(
            db.query(StarSystem.region_id, func.count(Planet.id))
            .join(Planet, Planet.system_id == StarSystem.id)
            .filter(StarSystem.region_id.in_([r.id for r in regions]),
                    Planet.is_colonized == True)
            .group_by(StarSystem.region_id).all()
        )
        # Batch: star info per region (name=grid position + star_type for mini starfield)
        region_ids = [r.id for r in regions]
        star_info_rows = (
            db.query(StarSystem.region_id, StarSystem.name, StarSystem.star_type)
            .filter(StarSystem.region_id.in_(region_ids))
            .order_by(StarSystem.region_id, StarSystem.id)
            .all()
        )
        star_info_by_region = {}
        for rid, sname, stype in star_info_rows:
            star_info_by_region.setdefault(rid, []).append([sname, stype])

        current_user = None
        if token:
            try:
                current_user = get_current_user(token, db)
            except Exception:
                pass

        result = []
        for r in regions:
            sys_count = sys_counts.get(r.id, 0)
            planet_count = planet_counts.get(r.id, 0)
            colonized = colonized_counts.get(r.id, 0)
            # Fog of war visibility
            visibility = "fog"
            last_scouted = None
            if current_user:
                visibility = _get_region_visibility(current_user.id, r.id, db)
                if visibility == "snapshot":
                    scouted = db.query(ScoutedRegion).filter(
                        ScoutedRegion.user_id == current_user.id, ScoutedRegion.region_id == r.id
                    ).first()
                    if scouted:
                        last_scouted = scouted.last_scouted.isoformat()
            result.append({
                "id": r.id, "name": r.name, "grid_x": r.grid_x, "grid_y": r.grid_y,
                "systems": sys_count,
                "planets": planet_count,
                "colonized": colonized if visibility != "fog" else 0,
                "visibility": visibility,
                "last_scouted": last_scouted,
                "star_info": star_info_by_region.get(r.id, []),
            })
        return result

    @app.get("/api/regions/{region_id}")
    def get_region(region_id: int, token: Optional[str] = Depends(get_optional_token_dep), db: Session = Depends(get_db)):
        region = db.query(Region).filter(Region.id == region_id).first()
        if not region:
            raise HTTPException(404, "Region not found")
        current_user = None
        if token:
            try:
                current_user = get_current_user(token, db)
            except Exception:
                pass

        # Fog of war check
        visibility = "live"  # default if no auth
        last_scouted = None
        if current_user:
            visibility = _get_region_visibility(current_user.id, region.id, db)

        # FOG: return structure (systems/astro positions) but mask types and stats
        # FOW reveals that bodies exist and whether they're Planet/Moon/Asteroid, but not the specific type
        if visibility == "fog" and current_user:
            fog_systems = []
            for s in region.systems:
                fog_planets = []
                for p in s.planets:
                    fog_planets.append({
                        "id": p.id, "name": p.name,
                        "type": _fog_visible_type(p),
                        "category": get_astro_category(p.planet_type, _body_type(p)),
                        "orbit": p.orbit_position,
                        "orbit_row": p.orbit_row if p.orbit_row is not None else 0,
                        "is_colonized": False,  # hidden in fog
                        "solar": 0, "gas": 0, "fertility": 0, "area": 0, "metal": 0, "crystal": 0,
                        "debris": 0, "owner": None, "base_id": None, "base_name": None,
                        "is_mine": False, "occupied_by": None, "fog": True,
                        "has_wormhole": False,
                    })
                fog_systems.append({
                    "id": s.id, "name": s.name, "star_type": s.star_type,
                    "planets": fog_planets,
                })
            return {
                "id": region.id, "name": region.name, "systems": fog_systems,
                "visibility": "fog", "last_scouted": None,
                "message": "Unexplored region. Send a fleet to scout for detailed intel.",
            }

        # SNAPSHOT: return frozen data from last scout
        if visibility == "snapshot" and current_user:
            scouted = db.query(ScoutedRegion).filter(
                ScoutedRegion.user_id == current_user.id, ScoutedRegion.region_id == region.id
            ).first()
            if scouted and scouted.snapshot_data:
                snapshot = json.loads(scouted.snapshot_data)
                # Mark is_mine and backfill category on snapshot planets
                # Old snapshots have orbit_row=1 for all (bug), so look up real data
                snap_planet_ids = [p["id"] for s in snapshot.get("systems", []) for p in s.get("planets", [])]
                real_planets = {rp.id: rp for rp in db.query(Planet).filter(Planet.id.in_(snap_planet_ids)).all()} if snap_planet_ids else {}
                for s in snapshot.get("systems", []):
                    for p in s.get("planets", []):
                        p["is_mine"] = (current_user and p.get("owner") == current_user.username)
                        rp = real_planets.get(p["id"])
                        if rp:
                            p["category"] = _body_type(rp)
                            p["orbit_row"] = rp.orbit_row if rp.orbit_row is not None else 0
                        elif p.get("type", "") in ("asteroid", "asteroid_belt"):
                            p["category"] = "Asteroid"
                        else:
                            p["category"] = "Planet"
                snapshot["visibility"] = "snapshot"
                snapshot["last_scouted"] = scouted.last_scouted.isoformat()
                snapshot["message"] = f"Snapshot from {scouted.last_scouted.strftime('%Y-%m-%d %H:%M')} — intel may be outdated."
                return snapshot

        # LIVE: return real-time data
        # Batch-query wormholes in this region
        region_planet_ids = [p.id for s in region.systems for p in s.planets]
        wormhole_planet_ids = set()
        if region_planet_ids:
            wh_rows = db.query(Wormhole.planet_id).filter(Wormhole.planet_id.in_(region_planet_ids)).all()
            wormhole_planet_ids = {r[0] for r in wh_rows}

        # Batch-query fleet presence per planet (stationary + incoming)
        # Returns: {planet_id: [{"user_id": int, "size": int}, ...]}
        fleet_presence = {}
        if region_planet_ids:
            # Stationary fleets at these planets
            stat_rows = (db.query(Fleet.location_planet_id, Fleet.user_id,
                         func.count(Fleet.id).label("cnt"))
                         .filter(Fleet.location_planet_id.in_(region_planet_ids),
                                 Fleet.is_moving == False)
                         .group_by(Fleet.location_planet_id, Fleet.user_id).all())
            for planet_id, uid, cnt in stat_rows:
                fleet_presence.setdefault(planet_id, []).append({"user_id": uid, "size": cnt})
            # Incoming fleets (moving toward these planets)
            move_rows = (db.query(Fleet.destination_planet_id, Fleet.user_id,
                          func.count(Fleet.id).label("cnt"))
                          .filter(Fleet.destination_planet_id.in_(region_planet_ids),
                                  Fleet.is_moving == True)
                          .group_by(Fleet.destination_planet_id, Fleet.user_id).all())
            for planet_id, uid, cnt in move_rows:
                fleet_presence.setdefault(planet_id, []).append({"user_id": uid, "size": cnt})

        # Build guild member set for current user
        my_guild_member_ids = set()
        if current_user:
            gm = db.query(GuildMember).filter(GuildMember.user_id == current_user.id).first()
            if gm:
                guild_members = db.query(GuildMember.user_id).filter(
                    GuildMember.guild_id == gm.guild_id).all()
                my_guild_member_ids = {m[0] for m in guild_members}

        systems = []
        for s in region.systems:
            planets = []
            for p in s.planets:
                pd = {
                    "id": p.id, "name": p.name, "type": p.planet_type,
                    "category": get_astro_category(p.planet_type, _body_type(p)),
                    "orbit": p.orbit_position, "orbit_row": p.orbit_row if p.orbit_row is not None else 0,
                    "is_colonized": p.is_colonized,
                    "solar": p.solar, "gas": p.gas, "fertility": p.fertility,
                    "area": p.area, "metal": p.metal, "crystal": p.crystal,
                    "debris": round(p.debris or 0, 1),
                    "owner": None, "base_id": None, "base_name": None, "is_mine": False,
                    "occupied_by": None,
                    "has_wormhole": p.id in wormhole_planet_ids,
                }
                if p.is_colonized and p.colony:
                    pd["owner"] = p.colony.user.username
                    pd["base_id"] = p.colony.id
                    pd["base_name"] = p.colony.name
                    if current_user and p.colony.user_id == current_user.id:
                        pd["is_mine"] = True
                    if p.colony.occupied_by:
                        pd["occupied_by"] = p.colony.occupier.username if p.colony.occupier else "Unknown"
                # Fleet presence dots: categorize as mine/guild/other
                fp = fleet_presence.get(p.id, [])
                if fp and current_user:
                    dots = []
                    for entry in fp:
                        if entry["user_id"] == current_user.id:
                            cat = "mine"
                        elif entry["user_id"] in my_guild_member_ids:
                            cat = "guild"
                        else:
                            cat = "other"
                        dots.append({"cat": cat, "size": entry["size"]})
                    pd["fleet_dots"] = dots
                elif fp:
                    pd["fleet_dots"] = [{"cat": "other", "size": e["size"]} for e in fp]
                planets.append(pd)
            systems.append({
                "id": s.id, "name": s.name, "star_type": s.star_type,
                "planets": planets,
            })
        return {"id": region.id, "name": region.name, "systems": systems, "visibility": "live", "last_scouted": None}

    # ── Base / Planet Detail ─────────────────────────
    @app.get("/api/base-detail/{base_id}")
    def get_base_detail(base_id: int, token: str = Depends(get_token_from_header), db: Session = Depends(get_db)):
        """Return detailed base info: planet stats, structures, defenses, fleets.
        Viewable by any player (base scouting view)."""
        user = get_current_user(token, db)
        colony = db.query(Colony).filter(Colony.id == base_id).first()
        if not colony:
            raise HTTPException(404, "Base not found")

        planet = colony.planet
        system = planet.system
        region = system.region
        galaxy = region.galaxy
        owner = colony.user
        is_mine = (owner.id == user.id)

        game_speed = get_config_float(db, "game_speed", 1.0)
        stats = calc_base_stats(colony, owner, game_speed)

        # Structures list (only show built ones to other players, show all to owner)
        structures = []
        for b in colony.buildings:
            if b.level == 0 and not b.is_constructing and not is_mine:
                continue  # hide unbuilt from other players
            spec = get_effective_building_spec(db, b.building_type)
            structures.append({
                "type": b.building_type,
                "name": spec.get("name", b.building_type),
                "level": b.level,
                "is_constructing": b.is_constructing if is_mine else False,
            })

        # Defenses
        defenses = []
        for d in colony.defenses:
            if d.level == 0 and not d.is_constructing:
                continue
            dspec = get_effective_defense_spec(db, d.defense_type)
            current_qty = d.quantity  # level * 5 (always full unless mid-repair)
            defenses.append({
                "type": d.defense_type,
                "name": dspec.get("name", d.defense_type),
                "level": d.level,
                "quantity": current_qty,
                "max_quantity": current_qty,  # at current level; same as quantity when fully repaired
            })

        # Fleets stationed at this base (visible to all players)
        fleets_at_base = db.query(Fleet).filter(
            Fleet.base_id == base_id,
            Fleet.is_moving == False
        ).all()
        # Check if viewer has F (Fleets) permission for guild fleet details
        my_gm = db.query(GuildMember).filter(GuildMember.user_id == user.id).first()
        can_see_guild_fleets = my_gm and my_gm.has_perm("F") if my_gm else False
        fleet_list = []
        for f in fleets_at_base:
            total = _fleet_total_ships(f)
            if total == 0:
                continue
            entry = {
                "id": f.id,
                "name": f.name,
                "player": f.user.username,
                "guild_tag": _guild_tag(f.user_id, db),
                "player_id": f.user_id,
                "is_mine": f.user_id == user.id,
                "size": _fleet_value(f, db),
            }
            # Show fleet composition to owner always
            is_guildmate = False
            if f.user_id != user.id and my_gm:
                f_gm = db.query(GuildMember).filter(GuildMember.user_id == f.user_id, GuildMember.guild_id == my_gm.guild_id).first()
                is_guildmate = f_gm is not None
            if f.user_id == user.id:
                entry["ships"] = f.get_all_ship_counts()
                # Show hide status to owner
                if f.guild_hidden_until and f.guild_hidden_until > datetime.utcnow():
                    entry["guild_hidden_until"] = f.guild_hidden_until.isoformat()
            elif is_guildmate:
                # Check if fleet is hidden from guild
                is_hidden = f.guild_hidden_until and f.guild_hidden_until > datetime.utcnow()
                if is_hidden and not can_see_guild_fleets:
                    # F permission overrides hide; without F, skip hidden fleets
                    entry["guild_hidden"] = True
                else:
                    entry["ships"] = f.get_all_ship_counts()
            fleet_list.append(entry)

        # Incoming fleets (only show your own incoming fleets)
        incoming = db.query(Fleet).filter(
            Fleet.destination_base_id == base_id,
            Fleet.is_moving == True
        ).all()
        incoming_list = []
        for f in incoming:
            if f.user_id == user.id or is_mine:
                incoming_list.append({
                    "id": f.id,
                    "name": f.name,
                    "player": f.user.username,
                    "guild_tag": _guild_tag(f.user_id, db),
                    "player_id": f.user_id,
                    "is_mine": f.user_id == user.id,
                    "size": _fleet_value(f, db),
                    "arrival": f.arrival_time.isoformat() if f.arrival_time else None,
                })

        # Guild info
        guild_tag = ""

        gm = db.query(GuildMember).filter(GuildMember.user_id == owner.id).first()
        if gm:
            guild = db.query(Guild).filter(Guild.id == gm.guild_id).first()
            if guild:
                guild_tag = guild.tag

        # Energy usage
        energy_used = sum(get_effective_building_spec(db, b.building_type).get("energy_req", 0) * b.level for b in colony.buildings)
        energy_used += sum(get_effective_defense_spec(db, d.defense_type).get("energy_req", 0) * d.level for d in colony.defenses)

        owner_level = calc_player_level(owner, db, game_speed)
        owner_prot_broken = bool(owner.protection_broken_until and owner.protection_broken_until > datetime.utcnow())

        # Wormhole info for base-detail
        wormhole = db.query(Wormhole).filter(Wormhole.planet_id == planet.id).first()
        wormhole_info = None
        if wormhole:
            from routes_fleets import _calc_wormhole_speed_factor
            wh_speed = _calc_wormhole_speed_factor(db)
            wh_pct = int((wh_speed - 1) * 100) if wh_speed > 1 else 0
            wormhole_info = {"type": wormhole.wormhole_type, "speed_pct": wh_pct, "speed_factor": wh_speed}

        return {
            "base_id": colony.id,
            "base_name": colony.name,
            "is_mine": is_mine,
            "owner": owner.username,
            "owner_id": owner.id,
            "owner_level": owner_level,
            "owner_protection_broken": owner_prot_broken,
            "guild_tag": guild_tag,
            "occupied_by": colony.occupier.username if colony.occupied_by else None,
            "economy": stats["economy"],
            "economy_max": stats["economy"],  # current/max economy
            "wormhole": wormhole_info,
            "planet": {
                "id": planet.id,
                "name": planet.name,
                "type": planet.planet_type,
                "category": get_astro_category(planet.planet_type, _body_type(planet)),
                "orbit": planet.orbit_position,
                "coords": planet.name,
                "solar": planet.solar,
                "gas": planet.gas,
                "fertility": planet.fertility,
                "area": planet.area,
                "metal": planet.metal,
                "crystal": planet.crystal,
            },
            "location": {
                "galaxy": galaxy.name,
                "region": region.name,
                "system": system.name,
            },
            "structures": structures,
            "defenses": defenses,
            "fleets": fleet_list,
            "incoming_fleets": incoming_list,
            "energy": stats["energy"],
            "energy_used": energy_used,
        }

    @app.get("/api/planet-detail/{planet_id}")
    def get_planet_detail(planet_id: int, token: str = Depends(get_token_from_header), db: Session = Depends(get_db)):
        """Return planet detail — if colonized, redirect to base detail; otherwise show raw planet stats."""
        user = get_current_user(token, db)
        planet = db.query(Planet).filter(Planet.id == planet_id).first()
        if not planet:
            raise HTTPException(404, "Planet not found")

        system = planet.system
        region = system.region
        galaxy = region.galaxy

        visibility = _get_region_visibility(user.id, region.id, db) if user else "live"

        if visibility == "fog":
            return {
                "planet_id": planet.id,
                "name": planet.name,
                "type": _fog_visible_type(planet),
                "category": get_astro_category(planet.planet_type, _body_type(planet)),
                "orbit": planet.orbit_position,
                "coords": planet.name,
                "solar": "",
                "gas": "",
                "fertility": "",
                "area": "",
                "metal": "",
                "crystal": "",
                "is_colonized": False,
                "base_id": None,
                "base_name": None,
                "owner": None,
                "guild_tag": "",
                "fleets": [],
                "fog": True,
                "location": {
                    "galaxy": galaxy.name,
                    "region": region.name,
                    "system": system.name,
                },
            }

        result = {
            "planet_id": planet.id,
            "name": planet.name,
            "type": planet.planet_type,
            "category": get_astro_category(planet.planet_type, _body_type(planet)),
            "orbit": planet.orbit_position,
            "coords": planet.name,
            "solar": planet.solar,
            "gas": planet.gas,
            "fertility": planet.fertility,
            "area": planet.area,
            "metal": planet.metal,
            "crystal": planet.crystal,
            "temperature": planet.temperature,
            "is_colonized": planet.is_colonized,
            "base_id": None,
            "base_name": None,
            "owner": None,
            "guild_tag": "",
            "location": {
                "galaxy": galaxy.name,
                "region": region.name,
                "system": system.name,
            },
        }

        if planet.is_colonized and planet.colony:
            result["base_id"] = planet.colony.id
            result["base_name"] = planet.colony.name
            result["owner"] = planet.colony.user.username

    
            gm = db.query(GuildMember).filter(GuildMember.user_id == planet.colony.user_id).first()
            if gm:
                guild = db.query(Guild).filter(Guild.id == gm.guild_id).first()
                if guild:
                    result["guild_tag"] = guild.tag

        # Wormhole info
        wormhole = db.query(Wormhole).filter(Wormhole.planet_id == planet.id).first()
        if wormhole:
            from routes_fleets import _calc_wormhole_speed_factor
            wh_speed = _calc_wormhole_speed_factor(db)
            wh_pct = int((wh_speed - 1) * 100) if wh_speed > 1 else 0
            result["wormhole"] = {
                "type": wormhole.wormhole_type,
                "speed_pct": wh_pct,
                "speed_factor": wh_speed,
            }

        # Fleets at this planet (including uncolonized)
        fleets_here = db.query(Fleet).filter(
            ((Fleet.base_id == planet.colony.id) if planet.colony else (Fleet.location_planet_id == planet.id)),
            Fleet.is_moving == False
        ).all() if planet.colony or True else []

        # Simpler query
        fleet_list = []
        if planet.is_colonized and planet.colony:
            stationed = db.query(Fleet).filter(Fleet.base_id == planet.colony.id, Fleet.is_moving == False).all()
        else:
            stationed = db.query(Fleet).filter(Fleet.location_planet_id == planet.id, Fleet.is_moving == False).all()

        for f in stationed:
            total = _fleet_total_ships(f)
            if total == 0:
                continue
            fleet_list.append({
                "id": f.id,
                "name": f.name,
                "player": f.user.username,
                "guild_tag": _guild_tag(f.user_id, db),
                "player_id": f.user_id,
                "is_mine": f.user_id == user.id,
                "size": _fleet_value(f, db),
            })
        result["fleets"] = fleet_list

        return result

    @app.get("/api/resolve-coords")
    def resolve_coords(coords: str, token: str = Depends(get_token_from_header), db: Session = Depends(get_db)):
        """Resolve a coordinate string (e.g. 'A12:43:96:20') to galaxy/region/system/planet IDs for map navigation."""
        get_current_user(token, db)
        planet = db.query(Planet).filter(Planet.name == coords).first()
        if not planet:
            raise HTTPException(404, "Coordinates not found")
        system = planet.system
        region = system.region
        galaxy = region.galaxy
        return {
            "planet_id": planet.id,
            "system_id": system.id,
            "system_name": system.name,
            "region_id": region.id,
            "region_name": region.name,
            "galaxy_id": galaxy.id,
            "galaxy_name": galaxy.name,
            "cluster_id": galaxy.cluster_id,
            "is_colonized": planet.is_colonized,
            "base_id": planet.colony.id if planet.colony else None,
        }
