from fastapi import HTTPException, Depends
from typing import Optional
from sqlalchemy.orm import Session
from models import (User, Colony, Building, Defense, Research, Fleet, Planet, Cluster, Galaxy, Region, StarSystem, GameConfig, Message, Guild, GuildMember, ShipQueue, ConstructionQueue, ResearchQueue, TradeRoute, BattleReport, ScoutedRegion, ScoutedBase, ScoutedFleet, EventLog, CreditLog, FleetAuditLog, GalaxyLink, GuildBoardPost, Commander, Bookmark, TutorialProgress, BugReport, Wormhole, SystemLink, Changelog, CreateGuildRequest)
from auth import (get_token_from_header, get_optional_token_dep, get_current_user, check_admin,
    create_access_token, get_config, get_config_float, get_config_int, set_config, get_db, log_event, log_credits, hash_password,
    get_effective_ship_spec, get_effective_defense_spec,
    get_effective_building_spec, get_effective_research_spec, get_effective_astro_spec,
    is_ship_disabled, is_defense_disabled, is_building_disabled, is_research_disabled, is_astro_disabled,
    get_all_ship_specs, get_all_defense_specs, get_all_building_specs, get_all_research_specs, get_all_astro_specs,
    _add_custom_spec, _remove_custom_spec, _config_cache)
from specs import SHIP_SPECS, DEFENSE_SPECS, BUILDING_SPECS, RESEARCH_SPECS, PLANET_TYPE_STATS, ALL_SHIP_TYPES, COMMANDER_SKILL_SPECS
from universe import generate_universe, _assign_homeworld, _add_cluster
from game_logic import calc_base_stats, calc_economy_rate, _fleet_value, get_building_level, _fleet_total_ships, calc_player_level
from game_definition import (get_game_definition, set_game_definition, build_default_definition,
    validate_definition, load_definition_from_file, save_definition_to_file,
    export_current_definition, list_available_definitions, check_definition_safety,
    compile_definition, engine_safety_metadata,
    persist_active_definition, clear_persisted_definition)
from resources import set_user_resources, add_resources
from bot_logic import (
    create_bot_accounts, create_simulated_bot_accounts, tick_bots, collect_bot_stats,
    delete_npc_colony, get_settlers_target_per_galaxy,
)
from catalog_sync import invalidate_all_online
from datetime import datetime, timedelta
import json
import logging

logger = logging.getLogger("awe")


def _bounded_int(value, default: int, minimum: int = 0, maximum: int = 50) -> int:
    try:
        parsed = int(value)
    except (TypeError, ValueError):
        parsed = default
    return max(minimum, min(maximum, parsed))


def _colony_galaxy_name(colony: Colony) -> str:
    try:
        return colony.planet.system.region.galaxy.name
    except AttributeError:
        return ""


def register_admin_routes(app):

    # ======================== ADMIN ENDPOINTS ========================

    @app.get("/api/admin/config")
    def get_admin_config(token: str = Depends(get_token_from_header), db: Session = Depends(get_db)):
        user = get_current_user(token, db)
        check_admin(user)
        configs = db.query(GameConfig).all()
        return {c.key: c.value for c in configs}

    @app.post("/api/admin/config")
    def set_admin_config(updates: dict, token: str = Depends(get_token_from_header), db: Session = Depends(get_db)):
        user = get_current_user(token, db)
        check_admin(user)
        for k, v in updates.items():
            # Normalize booleans: Python str(True) gives "True" but we store "true"/"false"
            if isinstance(v, bool):
                set_config(db, k, "true" if v else "false")
            else:
                set_config(db, k, str(v))
        return {"success": True}

    @app.post("/api/admin/launch")
    def launch_game(token: str = Depends(get_token_from_header), db: Session = Depends(get_db)):
        user = get_current_user(token, db)
        check_admin(user)
        status = get_config(db, "game_status")
        if status == "active":
            raise HTTPException(400, "Game already active")
        if status == "generating":
            raise HTTPException(400, "Universe generation already in progress")
        # Set status to "generating" so frontend pauses polling
        set_config(db, "game_status", "generating")
        set_config(db, "gen_progress", "0/?")
        db.commit()
        try:
            # Clear any existing universe data before generating fresh
            for tbl in [Wormhole, GalaxyLink, SystemLink, Fleet, Defense, Building, Research, Colony, Planet, StarSystem, Region, Galaxy, Cluster]:
                db.query(tbl).delete()
            db.commit()
            db.expire_all()  # clear SQLAlchemy identity cache
            generate_universe(db)
            set_config(db, "game_status", "active")
            set_config(db, "game_started_at", datetime.utcnow().isoformat())
            set_config(db, "gen_progress", "")
            db.commit()
        except Exception as e:
            # If generation fails, revert status so admin can try again
            set_config(db, "game_status", "setup")
            set_config(db, "gen_progress", "")
            db.commit()
            logger.error(f"[regen] Universe generation failed: {e}")
            raise HTTPException(500, "Universe generation failed. Check server logs for details.")
        # Assign homeworlds to all registered players (not admin/NPC)
        players = db.query(User).filter(User.is_admin == False, User.is_bot == False).all()
        for u in players:
            if not u.colonies:
                _assign_homeworld(u, db)
        return {"success": True, "message": "Universe generated, game is live!"}

    @app.get("/api/admin/players")
    def get_admin_players(token: Optional[str] = Depends(get_optional_token_dep), db: Session = Depends(get_db)):
        if token:
            current_user = get_current_user(token, db)
            check_admin(current_user)
        users = db.query(User).all()
        result = []
        for u in users:
            base_count = len(u.colonies)
            total_ships = sum(_fleet_total_ships(f) for f in u.fleets)
            online_cutoff = datetime.utcnow() - timedelta(minutes=5)
            is_online = u.last_seen and u.last_seen >= online_cutoff
            result.append({
                "id": u.id, "username": u.username, "credits": round(u.credits, 0),
                "score": u.score, "bases": base_count, "ships": total_ships, "is_admin": u.is_admin,
                "is_online": is_online,
                "last_seen": u.last_seen.isoformat() if u.last_seen else None,
            })
        return result

    @app.get("/api/admin/players/{user_id}/detail")
    def get_player_detail(user_id: int, token: str = Depends(get_token_from_header), db: Session = Depends(get_db)):
        """Return detailed player info: bases with buildings + stats, fleets with ship counts."""
        user = get_current_user(token, db)
        check_admin(user)
        target = db.query(User).filter(User.id == user_id).first()
        if not target:
            raise HTTPException(404, "Player not found")
        # Build bases list with stats
        game_speed = get_config_float(db, "game_speed", 1.0)
        bases_list = []
        for colony in target.colonies:
            stats = calc_base_stats(colony, target, game_speed)
            # Only include buildings with level > 0 or constructing
            buildings = [
                {"type": b.building_type, "level": b.level, "constructing": b.is_constructing}
                for b in colony.buildings if b.level > 0 or b.is_constructing
            ]
            defenses = [
                {"type": d.defense_type, "level": d.level, "constructing": d.is_constructing}
                for d in colony.defenses if d.level > 0 or d.is_constructing
            ]
            bases_list.append({
                "id": colony.id, "name": colony.name,
                "coords": colony.planet.name,
                "planet_type": colony.planet.planet_type,
                "economy": stats.get("economy", 0),
                "construction": stats.get("construction", 0),
                "production": stats.get("production", 0),
                "energy": stats.get("energy", 0),
                "population": stats.get("population", 0),
                "area": stats.get("area", 0),
                "buildings": buildings,
                "defenses": defenses,
            })
        # Build fleets list with ship counts
        fleets_list = []
        for fleet in target.fleets:
            # Determine location
            location = "Unknown"
            if fleet.base_id:
                base = db.query(Colony).filter(Colony.id == fleet.base_id).first()
                if base:
                    location = base.planet.name
            elif fleet.location_planet_id:
                planet = db.query(Planet).filter(Planet.id == fleet.location_planet_id).first()
                if planet:
                    location = planet.name
            ships = fleet.get_all_ship_counts()
            total = fleet.get_total_ships()
            fleets_list.append({
                "id": fleet.id, "name": fleet.name,
                "location": location, "ships": ships,
                "total_ships": total, "is_moving": fleet.is_moving,
            })
        return {
            "id": target.id, "username": target.username,
            "credits": round(target.credits, 0), "score": target.score,
            "is_bot": target.is_bot, "bot_strategy": target.bot_strategy,
            "is_admin": target.is_admin,
            "bases": bases_list, "fleets": fleets_list,
        }

    @app.delete("/api/admin/players/{user_id}")
    def delete_player(user_id: int, token: Optional[str] = Depends(get_optional_token_dep), db: Session = Depends(get_db)):
        if token:
            current_user = get_current_user(token, db)
            check_admin(current_user)
        target = db.query(User).filter(User.id == user_id).first()
        if not target:
            raise HTTPException(404, "Player not found")
        if target.is_admin:
            raise HTTPException(400, "Cannot delete admin")
        # Free their planets
        for colony in target.colonies:
            colony.planet.is_colonized = False
        db.query(Colony).filter(Colony.user_id == user_id).delete()
        db.query(Fleet).filter(Fleet.user_id == user_id).delete()
        db.query(Research).filter(Research.user_id == user_id).delete()
        db.query(BattleReport).filter((BattleReport.attacker_id == user_id) | (BattleReport.defender_id == user_id)).delete()
        db.delete(target)
        db.commit()
        return {"success": True}

    @app.post("/api/admin/impersonate/{user_id}")
    def impersonate_player(user_id: int, token: str = Depends(get_token_from_header), db: Session = Depends(get_db)):
        """Admin gets a login token for any player account."""
        user = get_current_user(token, db)
        check_admin(user)
        target = db.query(User).filter(User.id == user_id).first()
        if not target:
            raise HTTPException(404, "Player not found")
        token = create_access_token({"sub": str(target.id)})
        return {"success": True, "token": token, "username": target.username}

    @app.post("/api/admin/create-player")
    def admin_create_player(req: dict, token: str = Depends(get_token_from_header), db: Session = Depends(get_db)):
        """Admin creates a player account directly (no need for player to visit registration page)."""
        user = get_current_user(token, db)
        check_admin(user)
        username = req.get("username", "").strip()
        password = req.get("password", "").strip()
        email = req.get("email", "").strip()
        if not username or not password:
            raise HTTPException(400, "Username and password are required")
        if len(username) < 2 or len(username) > 50:
            raise HTTPException(400, "Username must be 2-50 characters")
        if len(password) < 4:
            raise HTTPException(400, "Password must be at least 4 characters")
        if db.query(User).filter(User.username == username).first():
            raise HTTPException(400, f"Username '{username}' already taken")
        max_players = get_config_int(db, "max_players", 100)
        player_count = db.query(User).filter(User.is_admin == False, User.is_bot == False).count()
        if player_count >= max_players:
            raise HTTPException(400, "Server is full (max_players reached)")
        starting_credits = get_config_float(db, "starting_credits", 500)
        newbie_days = get_config_int(db, "newbie_protection_days", 7)
        from datetime import timedelta
        new_user = User(
            username=username,
            email=email or f"{username}@local",
            hashed_password=hash_password(password),
            is_admin=False,
            credits=starting_credits,
            newbie_protection_until=datetime.utcnow() + timedelta(days=newbie_days) if newbie_days > 0 else None,
        )
        db.add(new_user)
        db.commit()
        db.refresh(new_user)
        # Auto-assign homeworld if game is active
        if get_config(db, "game_status") == "active":
            _assign_homeworld(new_user, db)
        log_event(db, user.id, "admin", f"Created player account: {username}")
        return {"success": True, "message": f"Player '{username}' created", "player_id": new_user.id}

    @app.post("/api/admin/reset")
    def reset_game(token: str = Depends(get_token_from_header), db: Session = Depends(get_db)):
        user = get_current_user(token, db)
        check_admin(user)
        for tbl in [TutorialProgress, Bookmark, BugReport, Changelog, FleetAuditLog, CreditLog, EventLog, GuildBoardPost, GuildMember, Guild, Message, TradeRoute, BattleReport, ScoutedFleet, ScoutedBase, ScoutedRegion, Commander, ShipQueue, ConstructionQueue, ResearchQueue, Wormhole, GalaxyLink, SystemLink, Fleet, Defense, Building, Research, Colony, Planet, StarSystem, Region, Galaxy, Cluster]:
            db.query(tbl).delete()
        db.query(User).filter(User.id != user.id).delete()
        # Reset admin user
        set_user_resources(user, {"credits": 500})
        user.score = 0
        set_config(db, "game_status", "setup")
        set_config(db, "game_started_at", "")
        set_config(db, "winner", "")
        db.commit()
        db.expire_all()  # clear SQLAlchemy identity cache
        return {"success": True}

    # ======================== ADMIN: REGENERATE GALAXY ========================

    @app.post("/api/admin/regenerate-galaxy")
    def regenerate_galaxy(token: str = Depends(get_token_from_header), db: Session = Depends(get_db)):
        """Regenerate the universe while preserving all colonized planets and player data.
        Uncolonized planets get new terrain/stats based on current distribution weights.
        Colonized planets keep their exact stats but get re-linked to new systems."""
        user = get_current_user(token, db)
        check_admin(user)

        from sqlalchemy import and_

        # 1. Snapshot all colonized planets (planet data + coordinate name)
        colonized_planets = db.query(Planet).filter(
            Planet.id.in_(db.query(Colony.planet_id))
        ).all()
        preserved = {}  # coord_name -> planet dict
        for p in colonized_planets:
            preserved[p.name] = {
                "id": p.id,
                "planet_type": p.planet_type,
                "orbit_position": p.orbit_position,
                "orbit_row": p.orbit_row,
                "solar": p.solar, "gas": p.gas, "fertility": p.fertility,
                "area": p.area, "metal": p.metal, "crystal": p.crystal,
            }
        logger.info(f"[regen] Preserving {len(preserved)} colonized planets")

        # 2. Collect fleet references to save
        fleet_locations = {}  # fleet_id -> planet_name
        fleet_destinations = {}  # fleet_id -> planet_name
        for f in db.query(Fleet).all():
            if f.location_planet_id:
                p = db.query(Planet).filter(Planet.id == f.location_planet_id).first()
                if p:
                    fleet_locations[f.id] = p.name
            if f.destination_planet_id:
                p = db.query(Planet).filter(Planet.id == f.destination_planet_id).first()
                if p:
                    fleet_destinations[f.id] = p.name

        # 3. Clear scouting data, bookmarks, wormholes (will be regenerated)
        db.query(ScoutedFleet).delete()
        db.query(ScoutedBase).delete()
        db.query(ScoutedRegion).delete()
        db.query(Bookmark).delete()
        db.query(Wormhole).delete()
        db.query(GalaxyLink).delete()
        db.query(SystemLink).delete()  # graph-map edges; rebuilt by generate_universe

        # 4. Detach colonized planets from their systems (nullify FK temporarily)
        # Clear fleet planet references temporarily
        db.query(Fleet).update({Fleet.location_planet_id: None, Fleet.destination_planet_id: None})

        # 5. Delete all uncolonized planets, then systems, regions, galaxies, clusters
        colonized_ids = [p["id"] for p in preserved.values()]
        if colonized_ids:
            db.query(Planet).filter(~Planet.id.in_(colonized_ids)).delete(synchronize_session='fetch')
        else:
            db.query(Planet).delete()

        # Temporarily nullify system_id on preserved planets
        for pid in colonized_ids:
            db.query(Planet).filter(Planet.id == pid).update({Planet.system_id: None})

        db.query(StarSystem).delete()
        db.query(Region).delete()
        db.query(Galaxy).delete()
        db.query(Cluster).delete()
        db.flush()
        logger.info("[regen] Cleared old universe data")

        # 6. Regenerate the universe (creates new clusters, galaxies, regions, systems, planets)
        generate_universe(db)
        logger.info("[regen] Universe regenerated")

        # 7. Re-link colonized planets to new systems
        relinked = 0
        for coord_name, pdata in preserved.items():
            # Parse coordinate: A11:03:59:10 -> galaxy A11, region 03, system 59
            parts = coord_name.split(":")
            if len(parts) != 4:
                continue
            gal_name = parts[0]
            region_num = int(parts[1])
            sys_num = int(parts[2])

            # Find the new system at this coordinate
            galaxy = db.query(Galaxy).filter(Galaxy.name == gal_name).first()
            if not galaxy:
                logger.warning(f"[regen] Galaxy {gal_name} not found for {coord_name}")
                continue

            region = db.query(Region).filter(
                and_(Region.galaxy_id == galaxy.id, Region.region_number == region_num)
            ).first()
            if not region:
                logger.warning(f"[regen] Region {region_num} not found for {coord_name}")
                continue

            system = db.query(StarSystem).filter(
                and_(StarSystem.region_id == region.id, StarSystem.system_number == sys_num)
            ).first()
            if not system:
                # System doesn't exist at this coordinate in the new generation
                # Create a minimal system for the colonized planet
                system = StarSystem(
                    region_id=region.id,
                    system_number=sys_num,
                    star_type="yellow",
                    wormhole=False,
                )
                db.add(system)
                db.flush()
                logger.info(f"[regen] Created system for colonized planet at {coord_name}")

            # Delete any new planet that was generated at the same coordinate
            db.query(Planet).filter(
                and_(Planet.name == coord_name, Planet.id != pdata["id"])
            ).delete()

            # Re-link the preserved planet to the new system
            db.query(Planet).filter(Planet.id == pdata["id"]).update({
                Planet.system_id: system.id
            })
            relinked += 1

        logger.info(f"[regen] Re-linked {relinked}/{len(preserved)} colonized planets")

        # 8. Restore fleet planet references
        # Build name->id map for all planets
        all_planets = {p.name: p.id for p in db.query(Planet.name, Planet.id).all()}
        for fleet_id, pname in fleet_locations.items():
            if pname in all_planets:
                db.query(Fleet).filter(Fleet.id == fleet_id).update(
                    {Fleet.location_planet_id: all_planets[pname]})
        for fleet_id, pname in fleet_destinations.items():
            if pname in all_planets:
                db.query(Fleet).filter(Fleet.id == fleet_id).update(
                    {Fleet.destination_planet_id: all_planets[pname]})

        # 9. Fix autoscout galaxy references (galaxy IDs changed after regen)
        galaxy_name_to_id = {g.name: g.id for g in db.query(Galaxy).all()}
        autoscout_fleets = db.query(Fleet).filter(Fleet.is_autoscout == True).all()
        for f in autoscout_fleets:
            if f.autoscout_galaxy_id:
                # Find which galaxy the fleet's location is in
                loc_planet = None
                if f.location_planet_id:
                    loc_planet = db.query(Planet).filter(Planet.id == f.location_planet_id).first()
                if loc_planet and loc_planet.system and loc_planet.system.region:
                    new_gal_id = loc_planet.system.region.galaxy_id
                    f.autoscout_galaxy_id = new_gal_id
                else:
                    # Can't determine galaxy — disable autoscout
                    f.is_autoscout = False
                    f.autoscout_galaxy_id = None

        db.commit()
        log_event(db, user.id, "admin", f"Regenerated galaxy, preserved {len(preserved)} colonized planets")
        return {"success": True, "preserved": len(preserved), "relinked": relinked}

    # ======================== ADMIN: GIVE CREDITS ========================

    @app.post("/api/admin/give-credits")
    def admin_give_credits(data: dict, token: str = Depends(get_token_from_header), db: Session = Depends(get_db)):
        user = get_current_user(token, db)
        check_admin(user)
        target = db.query(User).filter(User.id == data.get("user_id")).first()
        if not target:
            raise HTTPException(404, "Player not found")
        amount = float(data.get("amount", 0))
        add_resources(target, amount)
        log_credits(db, target.id, amount, f"Admin grant by {user.username}", "admin")
        db.commit()
        return {"success": True, "new_credits": round(target.credits, 0)}

    @app.post("/api/admin/broadcast")
    def admin_broadcast(data: dict, token: str = Depends(get_token_from_header), db: Session = Depends(get_db)):
        user = get_current_user(token, db)
        check_admin(user)
        subject = data.get("subject", "Admin Broadcast")
        body = data.get("body", "")
        if not body:
            raise HTTPException(400, "Message body required")
        users = db.query(User).all()
        count = 0
        for u in users:
            if u.id != user.id:
                msg = Message(sender_id=user.id, recipient_id=u.id, subject=subject, body=body)
                db.add(msg)
                count += 1
        db.commit()
        return {"success": True, "sent_to": count}


    # ======================== GENERIC SPEC MANAGEMENT ========================
    # Unified pattern: GET list, POST toggle, POST stats (override), POST reset, POST add, DELETE remove
    # Categories: ships, defenses, buildings, research, astros

    def _spec_list(db, category, base_specs, get_all_fn, is_disabled_fn):
        """Build the spec list response for any category."""
        all_specs = get_all_fn(db)
        result = []
        for key, spec in all_specs.items():
            result.append({"key": key, "enabled": not is_disabled_fn(db, key),
                           "is_custom": key not in base_specs, **spec})
        return result

    def _spec_toggle(db, category, key):
        """Toggle enabled/disabled for any spec category."""
        config_key = f"disabled_{category}s"
        disabled_raw = get_config(db, config_key) or ""
        disabled_set = set(s.strip() for s in disabled_raw.split(",") if s.strip())
        if key in disabled_set:
            disabled_set.discard(key)
            enabled = True
        else:
            disabled_set.add(key)
            enabled = False
        set_config(db, config_key, ",".join(sorted(disabled_set)))
        return enabled

    def _spec_override(db, category, key, data):
        """Apply stat overrides for any spec category."""
        override_key = f"{category}_override_{key}"
        overrides = {}
        existing_raw = get_config(db, override_key)
        if existing_raw:
            try:
                overrides = json.loads(existing_raw)
            except:
                pass
        for k, v in data.items():
            if k in ("key", "enabled", "is_custom"):
                continue
            try:
                overrides[k] = float(v) if '.' in str(v) else int(v)
            except (ValueError, TypeError):
                overrides[k] = v
        set_config(db, override_key, json.dumps(overrides))
        return overrides

    # ── Ships ──

    @app.get("/api/admin/ships")
    def get_admin_ships(token: str = Depends(get_token_from_header), db: Session = Depends(get_db)):
        user = get_current_user(token, db); check_admin(user)
        return _spec_list(db, "ship", SHIP_SPECS, get_all_ship_specs, is_ship_disabled)

    @app.post("/api/admin/ships/{key}/toggle")
    def toggle_ship(key: str, token: str = Depends(get_token_from_header), db: Session = Depends(get_db)):
        user = get_current_user(token, db); check_admin(user)
        enabled = _spec_toggle(db, "ship", key)
        return {"success": True, "key": key, "enabled": enabled}

    @app.post("/api/admin/ships/{key}/stats")
    def update_ship_stats(key: str, data: dict, token: str = Depends(get_token_from_header), db: Session = Depends(get_db)):
        user = get_current_user(token, db); check_admin(user)
        _spec_override(db, "ship", key, data)
        return {"success": True, "key": key, "stats": get_effective_ship_spec(db, key)}

    @app.post("/api/admin/ships/{key}/reset")
    def reset_ship(key: str, token: str = Depends(get_token_from_header), db: Session = Depends(get_db)):
        user = get_current_user(token, db); check_admin(user)
        set_config(db, f"ship_override_{key}", "")
        return {"success": True, "key": key, "stats": get_effective_ship_spec(db, key)}

    @app.post("/api/admin/ships/add")
    def add_custom_ship(data: dict, token: str = Depends(get_token_from_header), db: Session = Depends(get_db)):
        user = get_current_user(token, db); check_admin(user)
        key = data.pop("key", "").strip().lower().replace(" ", "_")
        if not key: raise HTTPException(400, "key is required")
        if key in SHIP_SPECS: raise HTTPException(400, f"\'{key}\' is built-in, use /stats to override")
        if "name" not in data: data["name"] = key.replace("_", " ").title()
        _add_custom_spec(db, "ship", key, data)
        return {"success": True, "key": key, "spec": data}

    @app.delete("/api/admin/ships/{key}")
    def remove_custom_ship(key: str, token: str = Depends(get_token_from_header), db: Session = Depends(get_db)):
        user = get_current_user(token, db); check_admin(user)
        if key in SHIP_SPECS: raise HTTPException(400, "Cannot delete built-in types")
        if not _remove_custom_spec(db, "ship", key): raise HTTPException(404, f"Custom ship \'{key}\' not found")
        return {"success": True, "key": key}

    # ── Defenses ──

    @app.get("/api/admin/defenses")
    def get_admin_defenses(token: str = Depends(get_token_from_header), db: Session = Depends(get_db)):
        user = get_current_user(token, db); check_admin(user)
        return _spec_list(db, "def", DEFENSE_SPECS, get_all_defense_specs, is_defense_disabled)

    @app.post("/api/admin/defenses/{key}/toggle")
    def toggle_defense(key: str, token: str = Depends(get_token_from_header), db: Session = Depends(get_db)):
        user = get_current_user(token, db); check_admin(user)
        enabled = _spec_toggle(db, "def", key)
        return {"success": True, "key": key, "enabled": enabled}

    @app.post("/api/admin/defenses/{key}/stats")
    def update_defense_stats(key: str, data: dict, token: str = Depends(get_token_from_header), db: Session = Depends(get_db)):
        user = get_current_user(token, db); check_admin(user)
        _spec_override(db, "def", key, data)
        return {"success": True, "key": key, "stats": get_effective_defense_spec(db, key)}

    @app.post("/api/admin/defenses/{key}/reset")
    def reset_defense(key: str, token: str = Depends(get_token_from_header), db: Session = Depends(get_db)):
        user = get_current_user(token, db); check_admin(user)
        set_config(db, f"def_override_{key}", "")
        return {"success": True, "key": key, "stats": get_effective_defense_spec(db, key)}

    @app.post("/api/admin/defenses/add")
    def add_custom_defense(data: dict, token: str = Depends(get_token_from_header), db: Session = Depends(get_db)):
        user = get_current_user(token, db); check_admin(user)
        key = data.pop("key", "").strip().lower().replace(" ", "_")
        if not key: raise HTTPException(400, "key is required")
        if key in DEFENSE_SPECS: raise HTTPException(400, f"\'{key}\' is built-in, use /stats to override")
        if "name" not in data: data["name"] = key.replace("_", " ").title()
        _add_custom_spec(db, "def", key, data)
        return {"success": True, "key": key, "spec": data}

    @app.delete("/api/admin/defenses/{key}")
    def remove_custom_defense(key: str, token: str = Depends(get_token_from_header), db: Session = Depends(get_db)):
        user = get_current_user(token, db); check_admin(user)
        if key in DEFENSE_SPECS: raise HTTPException(400, "Cannot delete built-in types")
        if not _remove_custom_spec(db, "def", key): raise HTTPException(404, f"Custom defense \'{key}\' not found")
        return {"success": True, "key": key}

    # ── Buildings ──

    @app.get("/api/admin/buildings")
    def get_admin_buildings(token: str = Depends(get_token_from_header), db: Session = Depends(get_db)):
        user = get_current_user(token, db); check_admin(user)
        return _spec_list(db, "building", BUILDING_SPECS, get_all_building_specs, is_building_disabled)

    @app.post("/api/admin/buildings/{key}/toggle")
    def toggle_building(key: str, token: str = Depends(get_token_from_header), db: Session = Depends(get_db)):
        user = get_current_user(token, db); check_admin(user)
        enabled = _spec_toggle(db, "building", key)
        return {"success": True, "key": key, "enabled": enabled}

    @app.post("/api/admin/buildings/{key}/stats")
    def update_building_stats(key: str, data: dict, token: str = Depends(get_token_from_header), db: Session = Depends(get_db)):
        user = get_current_user(token, db); check_admin(user)
        _spec_override(db, "building", key, data)
        return {"success": True, "key": key, "stats": get_effective_building_spec(db, key)}

    @app.post("/api/admin/buildings/{key}/reset")
    def reset_building(key: str, token: str = Depends(get_token_from_header), db: Session = Depends(get_db)):
        user = get_current_user(token, db); check_admin(user)
        set_config(db, f"building_override_{key}", "")
        return {"success": True, "key": key, "stats": get_effective_building_spec(db, key)}

    @app.post("/api/admin/buildings/add")
    def add_custom_building(data: dict, token: str = Depends(get_token_from_header), db: Session = Depends(get_db)):
        user = get_current_user(token, db); check_admin(user)
        key = data.pop("key", "").strip().lower().replace(" ", "_")
        if not key: raise HTTPException(400, "key is required")
        if key in BUILDING_SPECS: raise HTTPException(400, f"\'{key}\' is built-in, use /stats to override")
        if "name" not in data: data["name"] = key.replace("_", " ").title()
        data.setdefault("base_cost", 10)
        data.setdefault("cost_mult", 1.5)
        data.setdefault("time", 30)
        data.setdefault("energy_req", 1)
        data.setdefault("pop_req", 1)
        data.setdefault("area_req", 1)
        data.setdefault("max_level", 20)
        data.setdefault("tech_req", {})
        data.setdefault("advanced", True)
        data.setdefault("desc", "Custom structure")
        _add_custom_spec(db, "building", key, data)
        return {"success": True, "key": key, "spec": data}

    @app.delete("/api/admin/buildings/{key}")
    def remove_custom_building(key: str, token: str = Depends(get_token_from_header), db: Session = Depends(get_db)):
        user = get_current_user(token, db); check_admin(user)
        if key in BUILDING_SPECS: raise HTTPException(400, "Cannot delete built-in types")
        if not _remove_custom_spec(db, "building", key): raise HTTPException(404, f"Custom building \'{key}\' not found")
        return {"success": True, "key": key}

    # ── Research ──

    @app.get("/api/admin/research")
    def get_admin_research(token: str = Depends(get_token_from_header), db: Session = Depends(get_db)):
        user = get_current_user(token, db); check_admin(user)
        return _spec_list(db, "research", RESEARCH_SPECS, get_all_research_specs, is_research_disabled)

    @app.post("/api/admin/research/{key}/toggle")
    def toggle_research(key: str, token: str = Depends(get_token_from_header), db: Session = Depends(get_db)):
        user = get_current_user(token, db); check_admin(user)
        enabled = _spec_toggle(db, "research", key)
        return {"success": True, "key": key, "enabled": enabled}

    @app.post("/api/admin/research/{key}/stats")
    def update_research_stats(key: str, data: dict, token: str = Depends(get_token_from_header), db: Session = Depends(get_db)):
        user = get_current_user(token, db); check_admin(user)
        _spec_override(db, "research", key, data)
        return {"success": True, "key": key, "stats": get_effective_research_spec(db, key)}

    @app.post("/api/admin/research/{key}/reset")
    def reset_research(key: str, token: str = Depends(get_token_from_header), db: Session = Depends(get_db)):
        user = get_current_user(token, db); check_admin(user)
        set_config(db, f"research_override_{key}", "")
        return {"success": True, "key": key, "stats": get_effective_research_spec(db, key)}

    @app.post("/api/admin/research/add")
    def add_custom_research(data: dict, token: str = Depends(get_token_from_header), db: Session = Depends(get_db)):
        user = get_current_user(token, db); check_admin(user)
        key = data.pop("key", "").strip().lower().replace(" ", "_")
        if not key: raise HTTPException(400, "key is required")
        if key in RESEARCH_SPECS: raise HTTPException(400, f"\'{key}\' is built-in, use /stats to override")
        if "name" not in data: data["name"] = key.replace("_", " ").title()
        data.setdefault("base_cost", 100)
        data.setdefault("cost_mult", 2.0)
        data.setdefault("base_time", 60)
        data.setdefault("lab_req", 1)
        data.setdefault("prereqs", {})
        data.setdefault("bonus", "Custom technology")
        _add_custom_spec(db, "research", key, data)
        return {"success": True, "key": key, "spec": data}

    @app.delete("/api/admin/research/{key}")
    def remove_custom_research(key: str, token: str = Depends(get_token_from_header), db: Session = Depends(get_db)):
        user = get_current_user(token, db); check_admin(user)
        if key in RESEARCH_SPECS: raise HTTPException(400, "Cannot delete built-in types")
        if not _remove_custom_spec(db, "research", key): raise HTTPException(404, f"Custom research \'{key}\' not found")
        return {"success": True, "key": key}

    # ── Astro Types ──

    @app.get("/api/admin/astros")
    def get_admin_astros(token: str = Depends(get_token_from_header), db: Session = Depends(get_db)):
        user = get_current_user(token, db); check_admin(user)
        return _spec_list(db, "astro", PLANET_TYPE_STATS, get_all_astro_specs, is_astro_disabled)

    @app.post("/api/admin/astros/{key}/toggle")
    def toggle_astro(key: str, token: str = Depends(get_token_from_header), db: Session = Depends(get_db)):
        user = get_current_user(token, db); check_admin(user)
        enabled = _spec_toggle(db, "astro", key)
        return {"success": True, "key": key, "enabled": enabled}

    @app.post("/api/admin/astros/{key}/stats")
    def update_astro_stats(key: str, data: dict, token: str = Depends(get_token_from_header), db: Session = Depends(get_db)):
        user = get_current_user(token, db); check_admin(user)
        _spec_override(db, "astro", key, data)
        return {"success": True, "key": key, "stats": get_effective_astro_spec(db, key)}

    @app.post("/api/admin/astros/{key}/reset")
    def reset_astro(key: str, token: str = Depends(get_token_from_header), db: Session = Depends(get_db)):
        user = get_current_user(token, db); check_admin(user)
        set_config(db, f"astro_override_{key}", "")
        return {"success": True, "key": key, "stats": get_effective_astro_spec(db, key)}

    @app.post("/api/admin/astros/add")
    def add_custom_astro(data: dict, token: str = Depends(get_token_from_header), db: Session = Depends(get_db)):
        user = get_current_user(token, db); check_admin(user)
        key = data.pop("key", "").strip().lower().replace(" ", "_")
        if not key: raise HTTPException(400, "key is required")
        if key in PLANET_TYPE_STATS: raise HTTPException(400, f"\'{key}\' is built-in, use /stats to override")
        data.setdefault("solar", 0)
        data.setdefault("gas", 2)
        data.setdefault("fertility", 4)
        data.setdefault("area_planet", 85)
        data.setdefault("area_moon", 75)
        data.setdefault("metal", 2)
        data.setdefault("crystal", 0)
        _add_custom_spec(db, "astro", key, data)
        return {"success": True, "key": key, "spec": data}

    @app.delete("/api/admin/astros/{key}")
    def remove_custom_astro(key: str, token: str = Depends(get_token_from_header), db: Session = Depends(get_db)):
        user = get_current_user(token, db); check_admin(user)
        if key in PLANET_TYPE_STATS: raise HTTPException(400, "Cannot delete built-in types")
        if not _remove_custom_spec(db, "astro", key): raise HTTPException(404, f"Custom astro \'{key}\' not found")
        return {"success": True, "key": key}

    @app.post("/api/admin/add-cluster")
    def admin_add_cluster(token: str = Depends(get_token_from_header), db: Session = Depends(get_db)):
        """Manually add a new cluster to the universe."""
        user = get_current_user(token, db)
        check_admin(user)
        if get_config(db, "game_status") != "active":
            raise HTTPException(400, "Game must be active to add clusters")
        cluster = _add_cluster(db)
        # Count available home slots in new cluster
        new_gals = db.query(Galaxy).filter(Galaxy.cluster_id == cluster.id).all()
        gal_ids = [g.id for g in new_gals]
        from sqlalchemy import and_
        home_slots = 0
        if gal_ids:
            home_slots = (
                db.query(Planet)
                .join(StarSystem, Planet.system_id == StarSystem.id)
                .join(Region, StarSystem.region_id == Region.id)
                .filter(
                    Region.galaxy_id.in_(gal_ids),
                    Planet.is_colonized == False,
                    Planet.planet_type == "earthly",
                    Planet.orbit_position == 3,
                )
                .count()
            )
        server_letter = get_config(db, "server_letter", "A")
        base_idx = cluster.cluster_index * 10
        return {
            "success": True,
            "cluster_name": cluster.name,
            "galaxies": f"{server_letter}{base_idx:02d}-{server_letter}{base_idx+9:02d}",
            "home_slots": home_slots,
            "message": f"Added cluster with {home_slots} available home base slots",
        }


    @app.get("/api/admin/cluster-stats")
    def admin_cluster_stats(token: str = Depends(get_token_from_header), db: Session = Depends(get_db)):
        """Get cluster stats including available home base slots per cluster."""
        user = get_current_user(token, db)
        check_admin(user)
        clusters = db.query(Cluster).order_by(Cluster.cluster_index).all()
        result = []
        for c in clusters:
            gals = db.query(Galaxy).filter(Galaxy.cluster_id == c.id).all()
            gal_ids = [g.id for g in gals]
            total_planets = 0
            colonized = 0
            home_slots = 0
            if gal_ids:
                total_planets = (
                    db.query(Planet)
                    .join(StarSystem, Planet.system_id == StarSystem.id)
                    .join(Region, StarSystem.region_id == Region.id)
                    .filter(Region.galaxy_id.in_(gal_ids))
                    .count()
                )
                colonized = (
                    db.query(Planet)
                    .join(StarSystem, Planet.system_id == StarSystem.id)
                    .join(Region, StarSystem.region_id == Region.id)
                    .filter(Region.galaxy_id.in_(gal_ids), Planet.is_colonized == True)
                    .count()
                )
                home_slots = (
                    db.query(Planet)
                    .join(StarSystem, Planet.system_id == StarSystem.id)
                    .join(Region, StarSystem.region_id == Region.id)
                    .filter(
                        Region.galaxy_id.in_(gal_ids),
                        Planet.is_colonized == False,
                        Planet.planet_type == "earthly",
                        Planet.orbit_position == 3,
                    )
                    .count()
                )
            server_letter = get_config(db, "server_letter", "A")
            base_idx = c.cluster_index * 10
            result.append({
                "id": c.id,
                "name": c.name,
                "index": c.cluster_index,
                "galaxies": f"{server_letter}{base_idx:02d}-{server_letter}{base_idx+9:02d}",
                "total_planets": total_planets,
                "colonized": colonized,
                "home_slots_available": home_slots,
            })
        return {"clusters": result, "total_home_slots": sum(r["home_slots_available"] for r in result)}


    # ======================== NPC BOTS ========================

    @app.post("/api/admin/bots/create")
    def admin_create_bots(data: dict, token: str = Depends(get_token_from_header), db: Session = Depends(get_db)):
        """Create NPC bases under shared faction accounts.

        Body examples:
          {"npc_type": "settlers"}  # auto Settlers target by server age
          {"npc_type": "raiders", "count": 1}
          {"npc_type": "both", "raiders_count": 1}
          {"npc_type": "simulated", "count": 10}
        NPC counts are targets per galaxy; simulated bots are additive.
        """
        user = get_current_user(token, db)
        check_admin(user)
        npc_type = str(data.get("npc_type", "settlers")).strip().lower()
        galaxies = db.query(Galaxy).order_by(Galaxy.id).all()
        if not galaxies:
            raise HTTPException(400, "No galaxies exist — launch the game first")

        all_created = []
        targets = []
        settlers_target = get_settlers_target_per_galaxy(db)
        if npc_type == "both":
            targets.append(("settlers", _bounded_int(data.get("settlers_count", data.get("count", settlers_target)), settlers_target, 0, 50)))
            targets.append(("raiders", _bounded_int(data.get("raiders_count", 1), 1, 0, 50)))
        elif npc_type in ("simulated", "simulation", "random", "bot", "bots"):
            targets.append(("simulated", _bounded_int(data.get("count", data.get("sim_count", 10)), 10, 0, 50)))
        elif npc_type in ("raiders", "raider"):
            targets.append(("raiders", _bounded_int(data.get("count", 1), 1, 0, 50)))
        else:
            targets.append(("settlers", _bounded_int(data.get("count", settlers_target), settlers_target, 0, 50)))

        for target_type, per_galaxy in targets:
            if per_galaxy <= 0:
                continue
            for gal in galaxies:
                if target_type == "simulated":
                    result = create_simulated_bot_accounts(db, per_galaxy, galaxy_id=gal.id)
                else:
                    try:
                        result = create_bot_accounts(db, per_galaxy, galaxy_id=gal.id, npc_type=target_type)
                    except ValueError as exc:
                        raise HTTPException(400, str(exc))
                all_created.extend(result)

        return {
            "success": True,
            "created": len(all_created),
            "galaxies": len(galaxies),
            "settlers_target_per_galaxy": settlers_target,
            "targets": [{"npc_type": t, "per_galaxy": c} for t, c in targets],
            "bots": all_created,
        }

    @app.get("/api/admin/bots")
    def admin_list_bots(token: str = Depends(get_token_from_header), db: Session = Depends(get_db)):
        """List NPC faction accounts and individual NPC bases."""
        user = get_current_user(token, db)
        check_admin(user)
        bots = db.query(User).filter(User.is_bot == True).order_by(User.username).all()
        accounts = []
        bases = []
        for bot in bots:
            base_count = len(bot.colonies)
            score = bot.score
            accounts.append({
                "id": bot.id, "username": bot.username,
                "strategy": bot.bot_strategy, "npc_type": bot.bot_strategy,
                "credits": round(bot.credits, 1),
                "score": score, "bases": base_count,
            })
            for colony in sorted(bot.colonies, key=lambda c: (c.id or 0)):
                bases.append({
                    "id": colony.id,
                    "base_id": colony.id,
                    "account_id": bot.id,
                    "username": bot.username,
                    "base_name": colony.name,
                    "strategy": bot.bot_strategy,
                    "npc_type": bot.bot_strategy,
                    "galaxy": _colony_galaxy_name(colony),
                    "stability": (
                        round((colony.npc_stability or 0.0) * 100, 1)
                        if colony.npc_stability is not None else None
                    ),
                    "credits": round(bot.credits, 1),
                    "score": score,
                    "bases": base_count,
                })
        return {
            "bots": accounts,
            "accounts": accounts,
            "bases": bases,
            "stats": collect_bot_stats(db),
            "settlers_target_per_galaxy": get_settlers_target_per_galaxy(db),
        }

    @app.post("/api/admin/bots/tick")
    def admin_tick_bots(token: str = Depends(get_token_from_header), db: Session = Depends(get_db)):
        """Manually run one bot AI tick for all bots."""
        user = get_current_user(token, db)
        check_admin(user)
        stats = tick_bots(db, include_stats=True)
        return {"success": True, "stats": stats}

    @app.delete("/api/admin/bots/{bot_id}")
    def admin_delete_bot(bot_id: int, token: str = Depends(get_token_from_header), db: Session = Depends(get_db)):
        """Remove one NPC base. Shared Settlers/Raiders accounts are preserved."""
        user = get_current_user(token, db)
        check_admin(user)
        colony = (
            db.query(Colony)
            .join(User, Colony.user_id == User.id)
            .filter(Colony.id == bot_id, User.is_bot == True)
            .first()
        )
        if not colony:
            legacy_bot = db.query(User).filter(User.id == bot_id, User.is_bot == True).first()
            if legacy_bot and len(legacy_bot.colonies) == 1:
                colony = legacy_bot.colonies[0]
            else:
                raise HTTPException(404, "NPC base not found")
        delete_npc_colony(db, colony, delete_empty_account=True)
        db.commit()
        return {"success": True}

    # ======================== AWE REGISTRY (OPT-IN) ========================

    @app.get("/api/admin/registry")
    def admin_registry_status(token: str = Depends(get_token_from_header), db: Session = Depends(get_db)):
        """Current AstroWebEngine registry settings + the payload that would be sent."""
        user = get_current_user(token, db)
        check_admin(user)
        from awe_registry import is_registry_enabled, build_registration, DEFAULT_REGISTRY_URL
        from app import __version__
        return {
            "enabled": is_registry_enabled(db),
            "registry_url": get_config(db, "AWE_REGISTRY_URL", DEFAULT_REGISTRY_URL),
            "public_url": get_config(db, "AWE_REGISTRY_PUBLIC_URL", ""),
            "description": get_config(db, "AWE_REGISTRY_DESCRIPTION", ""),
            "payload": build_registration(db, __version__),
        }

    @app.post("/api/admin/registry/register")
    def admin_registry_register(token: str = Depends(get_token_from_header), db: Session = Depends(get_db)):
        """Manually register/refresh this game in the registry now (must be enabled)."""
        user = get_current_user(token, db)
        check_admin(user)
        from awe_registry import register_sync
        from app import __version__
        return register_sync(db, __version__)

    # ======================== MODS ========================

    @app.get("/api/admin/mods")
    def admin_list_mods(token: str = Depends(get_token_from_header), db: Session = Depends(get_db)):
        """List discovered mods with kind, validity, enabled state, active ruleset."""
        user = get_current_user(token, db)
        check_admin(user)
        import mod_loader as ml
        enabled = set(ml.get_enabled_mod_ids(db))
        active_ruleset = ml.get_active_ruleset_id(db)
        mods = []
        for m in ml.discover_mods():
            man = m["manifest"]
            mods.append({
                "id": m["id"], "name": man.get("name", m["id"]),
                "version": man.get("version", ""), "author": man.get("author", ""),
                "kind": man.get("kind", ""), "description": man.get("description", ""),
                "valid": not m["errors"], "errors": m["errors"],
                "enabled": m["id"] in enabled,
                "active_ruleset": m["id"] == active_ruleset,
            })
        return {"mods": mods, "active_ruleset": active_ruleset, "enabled": sorted(enabled)}

    @app.post("/api/admin/mods/enable")
    def admin_enable_mod(data: dict, token: str = Depends(get_token_from_header), db: Session = Depends(get_db)):
        """Enable/disable a content mod. Body: {mod_id, enabled}."""
        user = get_current_user(token, db)
        check_admin(user)
        import mod_loader as ml
        mod_id = str(data.get("mod_id", "")).strip()
        if not mod_id or not ml._get_mod(mod_id):
            raise HTTPException(404, "Mod not found")
        ml.set_mod_enabled(db, mod_id, bool(data.get("enabled", True)))
        db.commit()
        return {"success": True, "enabled": ml.get_enabled_mod_ids(db)}

    @app.post("/api/admin/mods/ruleset")
    def admin_set_ruleset(data: dict, token: str = Depends(get_token_from_header), db: Session = Depends(get_db)):
        """Select the active ruleset mod (the base). Body: {mod_id} ('' clears)."""
        user = get_current_user(token, db)
        check_admin(user)
        import mod_loader as ml
        mod_id = str(data.get("mod_id", "")).strip()
        if mod_id:
            mod = ml._get_mod(mod_id)
            if not mod or mod["manifest"].get("kind") != "ruleset":
                raise HTTPException(400, "Not a valid ruleset mod")
        ml.set_active_ruleset(db, mod_id)
        db.commit()
        return {"success": True, "active_ruleset": ml.get_active_ruleset_id(db)}

    @app.post("/api/admin/mods/apply")
    def admin_apply_mods(token: str = Depends(get_token_from_header), db: Session = Depends(get_db)):
        """Compose enabled mods into the active game definition (hot-swap). Returns the report."""
        user = get_current_user(token, db)
        check_admin(user)
        import mod_loader as ml
        from game_definition import get_game_definition
        report = ml.apply_active_mods(db, get_game_definition())
        if not report["errors"]:
            persist_active_definition(db, get_game_definition())  # survive restart
        return {"success": not report["errors"], "report": report}

    # ======================== GRANT ITEMS (TESTING TOOLS) ========================

    @app.post("/api/admin/grant-buildings")
    def grant_buildings(payload: dict, token: str = Depends(get_token_from_header), db: Session = Depends(get_db)):
        """Set building levels on a base. Payload: {base_id, buildings: {building_type: level, ...}}"""
        user = get_current_user(token, db)
        check_admin(user)
        base_id = payload.get("base_id")
        buildings_data = payload.get("buildings", {})
        if not base_id or not buildings_data:
            raise HTTPException(400, "base_id and buildings dict required")
        colony = db.query(Colony).filter(Colony.id == base_id).first()
        if not colony:
            raise HTTPException(404, "Base not found")
        changed = []
        for btype, level in buildings_data.items():
            spec = get_effective_building_spec(db, btype)
            if not spec:
                continue
            level = max(0, int(level))
            existing = db.query(Building).filter(Building.colony_id == base_id, Building.building_type == btype).first()
            if existing:
                existing.level = level
                existing.is_constructing = False
                existing.construction_end = None
            else:
                if level > 0:
                    db.add(Building(colony_id=base_id, building_type=btype, level=level))
            changed.append(f"{spec.get('name', btype)} → Lv{level}")
        db.commit()
        owner = db.query(User).filter(User.id == colony.user_id).first()
        log_event(db, user.id, "admin", f"Granted buildings to base {colony.name} (owner: {owner.username if owner else '?'}): {', '.join(changed)}")
        return {"success": True, "changed": changed}

    @app.post("/api/admin/grant-defenses")
    def grant_defenses(payload: dict, token: str = Depends(get_token_from_header), db: Session = Depends(get_db)):
        """Set defense levels on a base. Payload: {base_id, defenses: {defense_type: level, ...}}
        Each level represents one defense group."""
        user = get_current_user(token, db)
        check_admin(user)
        base_id = payload.get("base_id")
        defenses_data = payload.get("defenses", {})
        if not base_id or not defenses_data:
            raise HTTPException(400, "base_id and defenses dict required")
        colony = db.query(Colony).filter(Colony.id == base_id).first()
        if not colony:
            raise HTTPException(404, "Base not found")
        changed = []
        for dtype, level in defenses_data.items():
            spec = get_effective_defense_spec(db, dtype)
            if not spec:
                continue
            level = max(0, int(level))
            existing = db.query(Defense).filter(Defense.colony_id == base_id, Defense.defense_type == dtype).first()
            if existing:
                existing.level = level
                existing.is_constructing = False
                existing.construction_end = None
            else:
                if level > 0:
                    db.add(Defense(colony_id=base_id, defense_type=dtype, level=level))
            changed.append(f"{spec.get('name', dtype)} → Lv{level} ({level*5} units)")
        db.commit()
        owner = db.query(User).filter(User.id == colony.user_id).first()
        log_event(db, user.id, "admin", f"Granted defenses to base {colony.name} (owner: {owner.username if owner else '?'}): {', '.join(changed)}")
        return {"success": True, "changed": changed}

    @app.post("/api/admin/grant-ships")
    def grant_ships(payload: dict, token: str = Depends(get_token_from_header), db: Session = Depends(get_db)):
        """Add ships to a fleet at a base. Payload: {base_id, user_id, ships: {ship_type: count, ...}}
        Creates fleet if needed. Counts are ADDED to existing."""
        user = get_current_user(token, db)
        check_admin(user)
        base_id = payload.get("base_id")
        target_user_id = payload.get("user_id")
        ships_data = payload.get("ships", {})
        if not base_id or not target_user_id or not ships_data:
            raise HTTPException(400, "base_id, user_id, and ships dict required")
        colony = db.query(Colony).filter(Colony.id == base_id).first()
        if not colony:
            raise HTTPException(404, "Base not found")
        target_user = db.query(User).filter(User.id == target_user_id).first()
        if not target_user:
            raise HTTPException(404, "User not found")
        # Find or create a stationed fleet for this user at this base
        fleet = db.query(Fleet).filter(
            Fleet.user_id == target_user_id,
            Fleet.base_id == base_id,
            Fleet.is_moving == False
        ).first()
        if not fleet:
            fleet = Fleet(name="Admin Fleet", user_id=target_user_id, base_id=base_id)
            db.add(fleet)
            db.flush()
        changed = []
        total_added = 0
        for stype, count in ships_data.items():
            if stype not in ALL_SHIP_TYPES:
                continue
            count = max(0, int(count))
            if count == 0:
                continue
            current = fleet.get_ship_count(stype)
            fleet.set_ship_count(stype, current + count)
            total_added += count
            spec = get_effective_ship_spec(db, stype)
            changed.append(f"+{count} {spec.get('name', stype)}")
        target_user.score += total_added
        db.commit()
        log_event(db, user.id, "admin", f"Granted ships to {target_user.username} at base {colony.name}: {', '.join(changed)}")
        return {"success": True, "changed": changed, "fleet_id": fleet.id}

    @app.post("/api/admin/grant-research")
    def grant_research(payload: dict, token: str = Depends(get_token_from_header), db: Session = Depends(get_db)):
        """Set research levels for a player. Payload: {user_id, research: {tech_type: level, ...}}"""
        user = get_current_user(token, db)
        check_admin(user)
        target_user_id = payload.get("user_id")
        research_data = payload.get("research", {})
        if not target_user_id or not research_data:
            raise HTTPException(400, "user_id and research dict required")
        target_user = db.query(User).filter(User.id == target_user_id).first()
        if not target_user:
            raise HTTPException(404, "User not found")
        changed = []
        for rtype, level in research_data.items():
            spec = get_effective_research_spec(db, rtype)
            if not spec:
                continue
            level = max(0, int(level))
            existing = db.query(Research).filter(Research.user_id == target_user_id, Research.tech_type == rtype).first()
            if existing:
                existing.level = level
                existing.is_researching = False
                existing.research_end = None
            else:
                if level > 0:
                    db.add(Research(user_id=target_user_id, tech_type=rtype, level=level))
            changed.append(f"{spec.get('name', rtype)} → Lv{level}")
        db.commit()
        log_event(db, user.id, "admin", f"Granted research to {target_user.username}: {', '.join(changed)}")
        return {"success": True, "changed": changed}

    @app.get("/api/admin/player-bases/{user_id}")
    def get_player_bases(user_id: int, token: str = Depends(get_token_from_header), db: Session = Depends(get_db)):
        """Get all bases for a player (for admin grant UI)."""
        user = get_current_user(token, db)
        check_admin(user)
        target_user = db.query(User).filter(User.id == user_id).first()
        if not target_user:
            raise HTTPException(404, "User not found")
        bases = []
        for c in target_user.colonies:
            bases.append({
                "id": c.id,
                "name": c.name,
                "planet_id": c.planet_id,
                "planet_type": c.planet.planet_type if c.planet else "?",
            })
        return bases

    # ══════════ CHANGELOG MANAGEMENT ══════════

    @app.get("/api/admin/changelogs")
    def admin_list_changelogs(token: str = Depends(get_token_from_header), db: Session = Depends(get_db)):
        user = get_current_user(token, db)
        check_admin(user)
        entries = db.query(Changelog).order_by(Changelog.id.desc()).limit(100).all()
        return [{"id": e.id, "version": e.version, "title": e.title, "body": e.body,
                 "created_at": e.created_at.isoformat()} for e in entries]

    @app.post("/api/admin/changelogs")
    def admin_create_changelog(data: dict, token: str = Depends(get_token_from_header), db: Session = Depends(get_db)):
        user = get_current_user(token, db)
        check_admin(user)
        title = (data.get("title") or "").strip()
        if not title:
            raise HTTPException(400, "Title is required")
        entry = Changelog(
            version=(data.get("version") or "").strip()[:20],
            title=title[:200],
            body=(data.get("body") or "").strip()[:5000],
        )
        db.add(entry)
        db.commit()
        db.refresh(entry)
        return {"id": entry.id, "version": entry.version, "title": entry.title}

    @app.delete("/api/admin/changelogs/{entry_id}")
    def admin_delete_changelog(entry_id: int, token: str = Depends(get_token_from_header), db: Session = Depends(get_db)):
        user = get_current_user(token, db)
        check_admin(user)
        entry = db.query(Changelog).filter(Changelog.id == entry_id).first()
        if not entry:
            raise HTTPException(404, "Changelog entry not found")
        db.delete(entry)
        db.commit()
        return {"ok": True}

    # ══════════ PLAYER-FACING CHANGELOG ══════════

    @app.get("/api/changelogs")
    def get_changelogs(token: str = Depends(get_token_from_header), db: Session = Depends(get_db)):
        """Return all changelog entries and mark them as seen."""
        user = get_current_user(token, db)
        entries = db.query(Changelog).order_by(Changelog.id.desc()).limit(50).all()
        result = [{"id": e.id, "version": e.version, "title": e.title, "body": e.body,
                   "created_at": e.created_at.isoformat()} for e in entries]
        # Mark as seen
        if entries:
            max_id = max(e.id for e in entries)
            if (user.last_changelog_seen or 0) < max_id:
                user.last_changelog_seen = max_id
                db.commit()
        return result

    @app.get("/api/changelogs/unseen")
    def get_unseen_changelogs(token: str = Depends(get_token_from_header), db: Session = Depends(get_db)):
        """Return only changelog entries the user hasn't seen yet."""
        user = get_current_user(token, db)
        last_seen = user.last_changelog_seen or 0
        entries = db.query(Changelog).filter(Changelog.id > last_seen).order_by(Changelog.id.desc()).all()
        return [{"id": e.id, "version": e.version, "title": e.title, "body": e.body,
                 "created_at": e.created_at.isoformat()} for e in entries]

    @app.post("/api/changelogs/mark-seen")
    def mark_changelogs_seen(token: str = Depends(get_token_from_header), db: Session = Depends(get_db)):
        """Mark all changelogs as seen."""
        user = get_current_user(token, db)
        max_entry = db.query(Changelog).order_by(Changelog.id.desc()).first()
        if max_entry:
            user.last_changelog_seen = max_entry.id
            db.commit()
        return {"ok": True}

    # ======================== GAME CONSTANTS ADMIN ========================

    def _normalize_game_constant_key(key: str) -> str:
        return key

    def _load_game_constant_current(db, key: str, default_val):
        """Load a constant override.

        Returns tuple(current_override_string_or_none, source_key_or_none, has_override).
        """
        override = get_config(db, key, None)
        if override is not None and override != "":
            return override, key, True

        return None, None, False

    @app.get("/api/admin/game-constants")
    def get_game_constants(token: str = Depends(get_token_from_header), db: Session = Depends(get_db)):
        """Return all game constants grouped by category, with current overrides."""
        user = get_current_user(token, db); check_admin(user)
        import config_defaults
        categories = {
            "Combat": [
                "DAMAGE_ALLOCATION_EXPONENT", "COMBAT_LOOT_PERCENT", "DEBRIS_PERCENT",
                "ION_SHIELD_PASSTHROUGH", "NORMAL_SHIELD_PASSTHROUGH",
                "WEAPON_TECH_DIVISOR", "ARMOUR_TECH_DIVISOR", "SHIELDING_TECH_DIVISOR",
                "COMMAND_CENTER_DIVISOR", "TACTICAL_COMMANDER_DIVISOR", "DEFENSE_COMMANDER_DIVISOR",
                "CAPITAL_SHIP_1_BONUS_MULT", "CAPITAL_SHIP_2_BONUS_MULT",
                "COMBAT_SCORE_DIVISOR", "EXPERIENCE_PERCENT",
            ],
            "Economy & Production": [
                "CONSTRUCTION_BONUS_BASE", "CONSTRUCTION_BONUS_HOMEWORLD",
                "CYBERNETICS_BONUS_PER_LEVEL", "AI_TECH_BONUS_PER_LEVEL",
                "RESEARCH_LAB_RATE", "LAB_CAPACITY_PER_LEVEL",
                "SHIPYARD_PRODUCTION_MULT", "ORBITAL_SHIPYARD_PRODUCTION_MULT",
                "ORBITAL_SHIPYARD_EFFECTIVE_MULT", "BASE_ENERGY_BONUS",
                "ROBOTIC_FACTORY_INDUSTRIAL_MULT", "NANITE_FACTORY_INDUSTRIAL_MULT",
                "ANDROID_FACTORY_INDUSTRIAL_MULT",
                "FUSION_PLANT_ENERGY", "ANTIMATTER_PLANT_ENERGY", "ORBITAL_PLANT_ENERGY",
                "TERRAFORM_AREA_PER_LEVEL", "MLP_AREA_PER_LEVEL",
                "BIOSPHERE_FERTILITY_PER_LEVEL", "ORBITAL_BASE_POP_PER_LEVEL",
            ],
            "Economy Multipliers": [
                "ECON_METAL_REFINERIES", "ECON_ROBOTIC_FACTORIES",
                "ECON_NANITE_FACTORIES", "ECON_ANDROID_FACTORIES",
                "ECON_SHIPYARD", "ECON_ORBITAL_SHIPYARD",
                "ECON_SPACEPORTS", "ECON_ECONOMIC_CENTERS", "ECON_CAPITAL",
            ],
            "Fleet & Movement": [
                "FLEET_TRAVEL_DIVISOR", "BASE_FLEET_COUNT", "FLEET_SIZE_LIMIT_MULTIPLIER",
                "DEFAULT_MIN_SPEED", "JUMP_GATE_SPEED_BONUS_PER_LEVEL",
                "DETECTION_HOURS_CAP", "DETECTION_SENSOR_BASE",
                "DETECTION_FLEET_SIZE_MULT", "DETECTION_STEALTH_BASE",
                "DETECTION_MIN_HOURS", "DETECTION_MAX_HOURS",
            ],
            "Queues & Limits": [
                "CONSTRUCTION_QUEUE_MAX", "RESEARCH_QUEUE_MAX", "PRODUCTION_QUEUE_MAX",
                "FLEET_SPLIT_MIN", "FLEET_SPLIT_MAX",
                "MIN_BUILD_TIME_SECONDS", "MIN_RESEARCH_TIME_SECONDS",
                "OCCUPATION_TIME_PENALTY",
            ],
            "Occupation & Unrest": [
                "OCCUPIER_INCOME_SHARE", "UNREST_INCREASE_PER_DAY", "UNREST_DECAY_PER_DAY",
                "UNREST_SLOW_DECAY", "DEFENSE_REGEN_PER_HOUR", "POST_REVOLT_UNREST",
            ],
            "Server NPCs": [
                "NPC_SETTLERS_BASES_START", "NPC_SETTLERS_BASES_MIN", "NPC_SETTLERS_BASES_REDUCTION_PER_YEAR",
                "NPC_SETTLERS_AUTO_MAINTAIN_ENABLED", "NPC_SETTLERS_STABILITY_ENABLED", "NPC_SETTLERS_STABILITY_INITIAL",
                "NPC_SETTLERS_STABILITY_DECAY_PER_DAY",
            ],
            "AstroWebEngine Registry": [
                "AWE_REGISTRY_ENABLED", "AWE_REGISTRY_URL",
                "AWE_REGISTRY_PUBLIC_URL", "AWE_REGISTRY_DESCRIPTION",
            ],
            "Pillage": [
                "PILLAGE_COOLDOWN_HOURS", "PILLAGE_MAX_HOURS",
                "PILLAGE_ECONOMY_MULT", "PILLAGE_NPC_MULT",
                "PILLAGE_ADDITIONAL_BONUS_MULT",
            ],
            "Trade": [
                "TRADE_ROUTE_COST_MULTIPLIER", "TRADE_DISTANCE_DIVISOR",
                "TRADE_PLAYERS_DIVISOR", "SELF_TRADE_BONUS_MULT",
                "TRADE_ROUTES_PER_SPACEPORT_LEVELS",
                "TRADE_CLOSING_HOURS_SHORT", "TRADE_CLOSING_HOURS_LONG",
                "TRADE_CLOSING_DISTANCE_THRESHOLD", "TRADE_CLOSING_REFUND_PERCENT",
                "PUBLIC_TRADE_LISTING_HOURS",
            ],
            "Commanders": [
                "COMMANDER_RECRUIT_XP_COST", "COMMANDER_RECRUIT_CREDIT_COST",
                "COMMANDER_TRAVEL_INITIAL_SECONDS", "COMMANDER_BONUS_PER_LEVEL",
                "COMMANDER_TRAIN_TIME_PER_LEVEL", "COMMANDER_TRAIN_TIME_CAP",
                "COMMANDER_TRAIN_XP_BASE", "COMMANDER_TRAIN_XP_MULT",
                "COMMANDER_TRAIN_CREDIT_MULT", "COMMANDER_MAX_LEVEL",
                "COMMANDER_XP_ONLY_ABOVE", "COMMANDER_PILLAGE_KILL_CHANCE",
            ],
            "Autoscout": [
                "AUTOSCOUT_DWELL_SECONDS", "AUTOSCOUT_PER_COMPUTER_LEVELS",
            ],
            "Recycling": [
                "RECYCLER_RATE_PER_UNIT",
            ],
            "Wormholes": [
                "WORMHOLE_SPEED_PER_JG_LEVEL", "WORMHOLE_TOP_JG_COUNT",
            ],
            "Protection & Colonization": [
                "PROTECTION_BROKEN_HOURS", "NEWBIE_PROTECTION_LEVEL",
                "COLONIZE_SCORE_BONUS",
            ],
            "Player Level": [
                "PLAYER_LEVEL_ECONOMY_MULT", "PLAYER_LEVEL_EXPONENT",
            ],
            "Repair": [
                "REPAIR_COST_FRACTION",
            ],
            "Background Ticks": [
                "QUEUE_TICK_INTERVAL", "FLEET_ARRIVAL_TICK_INTERVAL", "AUTOSCOUT_TICK_INTERVAL",
            ],
        }
        result = []
        for cat_name, keys in categories.items():
            items = []
            for key in keys:
                default_val = getattr(config_defaults, key, None)
                if default_val is None:
                    continue
                override_val, override_key, has_override = _load_game_constant_current(db, key, default_val)
                try:
                    current = float(override_val) if has_override else default_val
                except (ValueError, TypeError):
                    current = default_val
                    has_override = False
                items.append({
                    "key": key,
                    "default": default_val,
                    "current": current,
                    "overridden": has_override,
                    "override_key": override_key,
                    "safety": "live",
                })
            result.append({"category": cat_name, "items": items})
        return result

    @app.post("/api/admin/game-constants")
    def set_game_constant(body: dict, token: str = Depends(get_token_from_header), db: Session = Depends(get_db)):
        """Set a game constant override."""
        user = get_current_user(token, db); check_admin(user)
        key = body.get("key", "")
        key = _normalize_game_constant_key(key)
        value = body.get("value")
        import config_defaults
        if not hasattr(config_defaults, key):
            raise HTTPException(400, f"Unknown constant: {key}")
        if value is None or value == "":
            existing = db.query(GameConfig).filter(GameConfig.key == key).first()
            if existing:
                db.delete(existing)
                db.commit()
            _config_cache.pop(key, None)
            return {"ok": True, "reset": True}
        set_config(db, key, str(value))
        return {"ok": True}

    # ======================== COMMANDER SKILL SPECS ADMIN ========================

    @app.get("/api/admin/commander-specs")
    def get_commander_specs(token: str = Depends(get_token_from_header), db: Session = Depends(get_db)):
        """Return all commander skill specs with overrides."""
        user = get_current_user(token, db); check_admin(user)
        result = []
        for key, spec in COMMANDER_SKILL_SPECS.items():
            override = get_config(db, f"commander_{key}_bonus")
            result.append({
                "key": key,
                "name": spec["name"],
                "desc": spec["desc"],
                "bonus_per_level": float(override) if override else spec["bonus_per_level"],
                "bonus_category": spec["bonus_category"],
                "scope": spec["scope"],
                "targets": spec["targets"],
                "overridden": override is not None,
            })
        return result

    @app.post("/api/admin/commander-specs")
    def update_commander_spec(body: dict, token: str = Depends(get_token_from_header), db: Session = Depends(get_db)):
        """Update a commander skill's bonus_per_level."""
        user = get_current_user(token, db); check_admin(user)
        key = body.get("key", "")
        bonus = body.get("bonus_per_level")
        if key not in COMMANDER_SKILL_SPECS:
            raise HTTPException(400, f"Unknown commander skill: {key}")
        if bonus is None or bonus == "":
            config_key = f"commander_{key}_bonus"
            existing = db.query(GameConfig).filter(GameConfig.key == config_key).first()
            if existing:
                db.delete(existing)
                db.commit()
                _config_cache.pop(config_key, None)
                invalidate_all_online(["specs"], f"config:{config_key}")
            return {"ok": True, "reset": True}
        try:
            bonus_val = float(bonus)
        except (ValueError, TypeError):
            raise HTTPException(400, "Invalid bonus value")
        set_config(db, f"commander_{key}_bonus", str(bonus_val))
        return {"ok": True}

    # ======================== GAME DEFINITION ENDPOINTS ========================

    @app.get("/api/admin/game-definitions")
    def list_game_definitions(token: str = Depends(get_token_from_header), db: Session = Depends(get_db)):
        """List all available game definition files."""
        user = get_current_user(token, db); check_admin(user)
        definitions = list_available_definitions()
        return {"definitions": definitions}

    @app.get("/api/admin/game-definition/current")
    def get_current_definition(token: str = Depends(get_token_from_header), db: Session = Depends(get_db)):
        """Get the currently active game definition."""
        user = get_current_user(token, db); check_admin(user)
        defn = get_game_definition()
        result = dict(defn)
        result["safety"] = engine_safety_metadata()
        return result

    @app.post("/api/admin/game-definition/export")
    def export_game_definition(token: str = Depends(get_token_from_header), db: Session = Depends(get_db)):
        """Export the current game definition to a JSON file."""
        user = get_current_user(token, db); check_admin(user)
        import os
        defn = get_game_definition()
        defs_dir = os.path.join(os.path.dirname(__file__), "game_definitions")
        os.makedirs(defs_dir, exist_ok=True)
        name_slug = defn.get("meta", {}).get("name", "export").lower().replace(" ", "_")
        filepath = os.path.join(defs_dir, f"{name_slug}.json")
        save_definition_to_file(defn, filepath)
        return {"ok": True, "filename": f"{name_slug}.json"}

    @app.post("/api/admin/game-definition/validate")
    def validate_game_definition(body: dict, token: str = Depends(get_token_from_header), db: Session = Depends(get_db)):
        """Validate a game definition dict and return any errors."""
        user = get_current_user(token, db); check_admin(user)
        errors = validate_definition(body)
        return {"valid": len(errors) == 0, "errors": errors}

    @app.post("/api/admin/game-definition/compile")
    def compile_game_definition(body: dict, token: str = Depends(get_token_from_header), db: Session = Depends(get_db)):
        """Resolve a fragment-based game definition without applying it."""
        user = get_current_user(token, db); check_admin(user)
        try:
            definition = compile_definition(body.get("definition", body))
        except Exception as exc:
            raise HTTPException(400, f"Compile error: {exc}")
        errors = validate_definition(definition)
        safety = check_definition_safety(definition, _has_universe(db))
        return {
            "ok": len(errors) == 0,
            "definition": definition,
            "errors": errors,
            "warnings": [w["message"] for w in safety if not w.get("blocked")],
            "blocked": [w["message"] for w in safety if w.get("blocked")],
        }

    @app.get("/api/admin/game-definition/build-options")
    def get_game_build_options(token: str = Depends(get_token_from_header), db: Session = Depends(get_db)):
        """Return available setup-time components for the Build Game screen."""
        user = get_current_user(token, db); check_admin(user)
        import os
        defs_dir = os.path.join(os.path.dirname(__file__), "game_definitions")
        fragments = []
        fragments_dir = os.path.join(defs_dir, "fragments")
        if os.path.exists(fragments_dir):
            for root, _dirs, files in os.walk(fragments_dir):
                for fname in files:
                    if not fname.endswith(".json"):
                        continue
                    full = os.path.join(root, fname)
                    rel = os.path.relpath(full, defs_dir)
                    try:
                        raw = load_definition_from_file(full, compile_extends=False)
                        meta = raw.get("meta", {})
                    except Exception:
                        meta = {}
                    fragments.append({
                        "filename": rel,
                        "name": meta.get("name", fname),
                        "description": meta.get("description", ""),
                        "component_type": meta.get("component_type", "fragment"),
                    })
        return {
            "definitions": list_available_definitions(),
            "fragments": sorted(fragments, key=lambda x: (x["component_type"], x["filename"])),
            "safety": engine_safety_metadata(),
        }

    def _has_universe(db: Session) -> bool:
        """Check if a universe has been generated (any galaxies exist)."""
        return db.query(Galaxy).first() is not None

    def _check_and_apply_definition(definition: dict, db: Session, user, source: str):
        """Validate, safety-check, and apply a game definition. Returns response dict."""
        try:
            definition = compile_definition(definition)
        except Exception as exc:
            raise HTTPException(400, f"Compile error: {exc}")
        errors = validate_definition(definition)
        if errors:
            raise HTTPException(400, f"Invalid definition: {'; '.join(errors)}")

        # Safety check: block dangerous changes if universe exists
        has_uni = _has_universe(db)
        force = False  # Could add ?force=true param later
        safety = check_definition_safety(definition, has_uni)
        blocked = [w for w in safety if w.get("blocked")]
        warnings = [w for w in safety if not w.get("blocked")]

        if blocked and not force:
            raise HTTPException(400,
                "Cannot switch definition — blocked changes: " +
                "; ".join(w["message"] for w in blocked))

        set_game_definition(definition)
        persist_active_definition(db, definition)  # survive restart, no env var
        invalidate_all_online(["specs"], "game_definition_change")
        log_event(db, user.id, f"game_definition_{source}",
                  f"{source.title()} game definition: {definition.get('meta', {}).get('name', 'unknown')}")

        result = {"ok": True, "name": definition.get("meta", {}).get("name")}
        if warnings:
            result["warnings"] = [w["message"] for w in warnings]
        return result

    @app.post("/api/admin/game-definition/import")
    def import_game_definition(body: dict, token: str = Depends(get_token_from_header), db: Session = Depends(get_db)):
        """Import and activate a game definition. Body should be the full definition dict."""
        user = get_current_user(token, db); check_admin(user)
        definition = body.get("definition", body)
        return _check_and_apply_definition(definition, db, user, "import")

    @app.post("/api/admin/game-definition/load-file")
    def load_game_definition_file(body: dict, token: str = Depends(get_token_from_header), db: Session = Depends(get_db)):
        """Load a game definition from a file in the game_definitions directory."""
        user = get_current_user(token, db); check_admin(user)
        filename = body.get("filename", "")
        if not filename or ".." in filename or "/" in filename or "\\" in filename:
            raise HTTPException(400, "Invalid filename")
        import os
        filepath = os.path.join(os.path.dirname(__file__), "game_definitions", filename)
        if not os.path.exists(filepath):
            raise HTTPException(404, f"Definition file not found: {filename}")
        definition = load_definition_from_file(filepath)
        return _check_and_apply_definition(definition, db, user, "load")

    @app.post("/api/admin/game-definition/reset")
    def reset_game_definition(token: str = Depends(get_token_from_header), db: Session = Depends(get_db)):
        """Reset to the built-in default game definition."""
        user = get_current_user(token, db); check_admin(user)
        defn = build_default_definition()
        set_game_definition(defn)
        clear_persisted_definition(db)  # restart falls back to env / default
        invalidate_all_online(["specs"], "game_definition_reset")
        log_event(db, user.id, "game_definition_reset", "Reset to default game definition")
        return {"ok": True, "name": defn["meta"]["name"]}
