"""
Fleet utility routes: split, merge, rename, repair, disband, guild hide, autoscout toggle, specs.
Split from routes_fleets.py for readability.
"""
from fastapi import HTTPException, Depends, Query
from sqlalchemy.orm import Session
from datetime import datetime, timedelta
import json

from models import User, Colony, Fleet, Planet, Galaxy, Region
from auth import (get_token_from_header, get_current_user, get_config, get_config_float, get_db,
                  get_effective_ship_spec, get_effective_defense_spec,
                  get_effective_building_spec, get_effective_research_spec,
                  log_event, log_credits, log_fleet_change,
                  fleet_capability_ship)
from game_logic import (calc_max_fleet_count, get_tech_level,
                        _fleet_total_ships, _fleet_value)
from specs import SHIP_SPECS, ALL_SHIP_TYPES, DEFENSE_SPECS, BUILDING_SPECS, RESEARCH_SPECS, GOODS_SPEC
from resources import can_afford, deduct_cost, format_cost, add_resources
from config_defaults import *
from pydantic import BaseModel
import action_points


class FleetMergeRequest(BaseModel):
    source_fleet_id: int
    target_fleet_id: int

class FleetRenameRequest(BaseModel):
    fleet_id: int
    name: str

class FleetDisbandRequest(BaseModel):
    fleet_id: int


def register_fleet_util_routes(app):

    # ======================== FLEET SPLIT / MERGE ========================

    @app.post("/api/fleets/split")
    def split_fleet(fleet_id: int = Query(...), split_into: int = Query(...), token: str = Depends(get_token_from_header), db: Session = Depends(get_db)):
        """Split fleet into N identical sub-fleets."""
        user = get_current_user(token, db)
        fleet = db.query(Fleet).filter(Fleet.id == fleet_id, Fleet.user_id == user.id).first()
        if not fleet:
            raise HTTPException(404, "Fleet not found")
        if fleet.is_moving:
            raise HTTPException(400, "Cannot split a moving fleet")
        current_fleet_count = db.query(Fleet).filter(Fleet.user_id == user.id).count()
        max_fleets = calc_max_fleet_count(user, db)
        available_slots = max_fleets - current_fleet_count
        max_split = min(available_slots + 1, split_into)  # +1 because original fleet counts as one

        if split_into < FLEET_SPLIT_MIN:
            raise HTTPException(400, "Must split into at least 2 fleets")
        new_fleets_needed = split_into - 1
        if new_fleets_needed > available_slots:
            raise HTTPException(400, f"Not enough fleet slots. You have {available_slots} free ({current_fleet_count}/{max_fleets}).")

        ship_counts = fleet.get_all_ship_counts()

        if not ship_counts:
            raise HTTPException(400, "Fleet has no ships to split")

        ships_before = dict(ship_counts)

        new_fleet_ids = []
        for i in range(1, split_into):
            nf = Fleet(
                user_id=user.id,
                base_id=fleet.base_id,
                location_planet_id=fleet.location_planet_id,
                name=f"{fleet.name} ({i+1})",
            )
            db.add(nf)
            db.flush()
            new_fleet_ids.append(nf.id)

            for st, total in ship_counts.items():
                share = total // split_into
                if share > 0:
                    nf.set_ship_count(st, share)

            log_fleet_change(db, user.id, nf, "split", {}, f"Split from fleet {fleet.id} ({fleet.name})")

        for st, total in ship_counts.items():
            share = total // split_into
            remainder = total - share * (split_into - 1)
            fleet.set_ship_count(st, remainder)

        log_fleet_change(db, user.id, fleet, "split", ships_before, f"Split into {split_into} fleets")
        db.commit()
        return {"success": True, "new_fleet_ids": new_fleet_ids, "split_into": split_into}

    @app.post("/api/fleets/merge")
    def merge_fleets(req: FleetMergeRequest, token: str = Depends(get_token_from_header), db: Session = Depends(get_db)):
        """Merge source fleet into target fleet."""
        user = get_current_user(token, db)
        source = db.query(Fleet).filter(Fleet.id == req.source_fleet_id, Fleet.user_id == user.id).first()
        target = db.query(Fleet).filter(Fleet.id == req.target_fleet_id, Fleet.user_id == user.id).first()
        if not source or not target:
            raise HTTPException(404, "Fleet not found")
        if source.id == target.id:
            raise HTTPException(400, "Cannot merge a fleet with itself")
        if source.is_moving or target.is_moving:
            raise HTTPException(400, "Cannot merge moving fleets")
        if source.base_id != target.base_id or source.location_planet_id != target.location_planet_id:
            raise HTTPException(400, "Fleets must be at the same location to merge")
        source_before = source.get_all_ship_counts()
        target_before = target.get_all_ship_counts()
        for st in ALL_SHIP_TYPES:
            src_count = source.get_ship_count(st)
            tgt_count = target.get_ship_count(st)
            target.set_ship_count(st, tgt_count + src_count)
        log_fleet_change(db, user.id, target, "merge", target_before, f"Merged fleet {source.id} ({source.name}) into this fleet")
        db.delete(source)
        db.commit()
        return {"success": True, "fleet_id": target.id}

    @app.post("/api/fleets/rename")
    def rename_fleet(req: FleetRenameRequest, token: str = Depends(get_token_from_header), db: Session = Depends(get_db)):
        user = get_current_user(token, db)
        fleet = db.query(Fleet).filter(Fleet.id == req.fleet_id, Fleet.user_id == user.id).first()
        if not fleet:
            raise HTTPException(404, "Fleet not found")
        if len(req.name) < 1 or len(req.name) > 50:
            raise HTTPException(400, "Fleet name must be 1-50 characters")
        fleet.name = req.name.strip()
        db.commit()
        return {"success": True}

    # ======================== FLEET REORDER ========================

    @app.post("/api/fleets/reorder")
    def reorder_fleets(req: dict, token: str = Depends(get_token_from_header), db: Session = Depends(get_db)):
        user = get_current_user(token, db)
        fleet_ids = req.get("fleet_ids", [])
        if not fleet_ids:
            raise HTTPException(400, "No fleet IDs provided")
        user_fleet_ids = {f.id for f in user.fleets}
        for i, fid in enumerate(fleet_ids):
            if fid not in user_fleet_ids:
                continue
            fleet = db.query(Fleet).filter(Fleet.id == fid).first()
            if fleet:
                fleet.sort_order = i
        db.commit()
        return {"success": True}

    # ======================== FLEET GUILD HIDE ========================

    @app.post("/api/fleets/{fleet_id}/guild-hide")
    def guild_hide_fleet(fleet_id: int, token: str = Depends(get_token_from_header), db: Session = Depends(get_db)):
        """Hide a fleet from guild shared data for 24 hours."""
        user = get_current_user(token, db)
        fleet = db.query(Fleet).filter(Fleet.id == fleet_id, Fleet.user_id == user.id).first()
        if not fleet:
            raise HTTPException(404, "Fleet not found")
        fleet.guild_hidden_until = datetime.utcnow() + timedelta(hours=GUILD_HIDE_DURATION_HOURS)
        db.commit()
        return {"success": True, "hidden_until": fleet.guild_hidden_until.isoformat()}

    @app.post("/api/fleets/{fleet_id}/guild-hide-reset")
    def guild_hide_reset(fleet_id: int, token: str = Depends(get_token_from_header), db: Session = Depends(get_db)):
        """Reset the 24h hide timer back to 24 hours."""
        user = get_current_user(token, db)
        fleet = db.query(Fleet).filter(Fleet.id == fleet_id, Fleet.user_id == user.id).first()
        if not fleet:
            raise HTTPException(404, "Fleet not found")
        if not fleet.guild_hidden_until or fleet.guild_hidden_until < datetime.utcnow():
            raise HTTPException(400, "Fleet is not hidden")
        fleet.guild_hidden_until = datetime.utcnow() + timedelta(hours=GUILD_HIDE_DURATION_HOURS)
        db.commit()
        return {"success": True, "hidden_until": fleet.guild_hidden_until.isoformat()}

    @app.post("/api/fleets/{fleet_id}/guild-hide-cancel")
    def guild_hide_cancel(fleet_id: int, token: str = Depends(get_token_from_header), db: Session = Depends(get_db)):
        """Cancel hiding — make fleet visible to guild again."""
        user = get_current_user(token, db)
        fleet = db.query(Fleet).filter(Fleet.id == fleet_id, Fleet.user_id == user.id).first()
        if not fleet:
            raise HTTPException(404, "Fleet not found")
        fleet.guild_hidden_until = None
        db.commit()
        return {"success": True}

    # ======================== AUTOSCOUT ========================

    @app.post("/api/fleets/{fleet_id}/autoscout")
    def toggle_autoscout(fleet_id: int, token: str = Depends(get_token_from_header), db: Session = Depends(get_db)):
        """Toggle autoscout on/off for a fleet containing a scout ship."""
        user = get_current_user(token, db)
        fleet = db.query(Fleet).filter(Fleet.id == fleet_id, Fleet.user_id == user.id).first()
        if not fleet:
            raise HTTPException(404, "Fleet not found")

        if fleet.is_autoscout:
            fleet.is_autoscout = False
            fleet.autoscout_galaxy_id = None
            db.commit()
            return {"success": True, "is_autoscout": False}

        scout_key = fleet_capability_ship(fleet, db, "can_autoscout")
        if not scout_key:
            raise HTTPException(400, "Fleet must contain a scout ship to autoscout")

        # Autoscout is gated by a research tech in the classic roster. A ruleset
        # mod that doesn't include that tech gets a sensible default cap instead
        # of being permanently blocked.
        from auth import get_all_research_specs
        autoscout_tech = get_config(db, "AUTOSCOUT_TECH", "computer") or "computer"
        if autoscout_tech in get_all_research_specs(db):
            tech_level = get_tech_level(user, autoscout_tech)
            max_autoscouts = tech_level // AUTOSCOUT_PER_COMPUTER_LEVELS
            if max_autoscouts < 1:
                raise HTTPException(400, f"Requires {autoscout_tech} tech level {AUTOSCOUT_PER_COMPUTER_LEVELS} to use autoscout (you have {tech_level})")
        else:
            max_autoscouts = 3  # roster has no gating tech — allow a default few
        current_autoscouts = db.query(Fleet).filter(
            Fleet.user_id == user.id, Fleet.is_autoscout == True
        ).count()
        if current_autoscouts >= max_autoscouts:
            raise HTTPException(400, f"Autoscout limit reached ({current_autoscouts}/{max_autoscouts}). Need Computer tech {(current_autoscouts + 1) * 5} for another.")

        planet = None
        if fleet.is_moving:
            if fleet.destination_base_id:
                dest_col = db.query(Colony).filter(Colony.id == fleet.destination_base_id).first()
                if dest_col:
                    planet = dest_col.planet
            elif fleet.destination_planet_id:
                planet = db.query(Planet).filter(Planet.id == fleet.destination_planet_id).first()
        else:
            if fleet.base_id:
                colony = db.query(Colony).filter(Colony.id == fleet.base_id).first()
                if colony:
                    planet = colony.planet
            elif fleet.location_planet_id:
                planet = db.query(Planet).filter(Planet.id == fleet.location_planet_id).first()
        if not planet or not planet.system:
            raise HTTPException(400, "Cannot determine fleet galaxy")

        region = planet.system.region
        galaxy_id = region.galaxy_id
        galaxy = db.query(Galaxy).filter(Galaxy.id == galaxy_id).first()

        action_points.debit_action_points(user, db, "autoscout_enable")

        # If stationary, split off one scout ship into a dedicated autoscout fleet.
        scout_fleet = fleet
        if not fleet.is_moving:
            has_other_ships = any(
                fleet.get_ship_count(st) > 0
                for st in ALL_SHIP_TYPES if st != scout_key
            )
            if has_other_ships or fleet.get_ship_count(scout_key) > 1:
                scout_fleet = Fleet(
                    user_id=user.id,
                    name=f"Autoscout ({galaxy.name})",
                    base_id=fleet.base_id,
                    location_planet_id=fleet.location_planet_id,
                )
                scout_fleet.set_ship_count(scout_key, 1)
                db.add(scout_fleet)
                fleet.set_ship_count(scout_key, fleet.get_ship_count(scout_key) - 1)
                ships_before = fleet.get_all_ship_counts()
                ships_before[scout_key] = (ships_before.get(scout_key, 0)) + 1
                db.flush()
                log_fleet_change(db, user.id, fleet, "split", ships_before, f"Autoscout split — 1 scout to fleet {scout_fleet.id}")
                log_fleet_change(db, user.id, scout_fleet, "split", {}, f"Autoscout created from fleet {fleet.id}")

        scout_fleet.is_autoscout = True
        scout_fleet.autoscout_galaxy_id = galaxy_id
        grid_w = galaxy.regions_grid_w or 10
        grid_h = galaxy.regions_grid_h or 10
        from game_scouting import _boustrophedon_order
        traversal = _boustrophedon_order(grid_w, grid_h)
        start_idx = 0
        for i, (gx, gy) in enumerate(traversal):
            if gx == region.grid_x and gy == region.grid_y:
                start_idx = i
                break
        scout_fleet.autoscout_region_index = start_idx
        scout_fleet.autoscout_system_index = 0
        scout_fleet.autoscout_planet_index = 0
        scout_fleet.autoscout_last_move = None
        db.commit()
        log_event(db, user.id, "fleet", f"Autoscout enabled for fleet '{scout_fleet.name}' in galaxy {galaxy.name}")
        return {"success": True, "is_autoscout": True, "galaxy": galaxy.name, "scout_fleet_id": scout_fleet.id}

    # ======================== FLEET DISBAND ========================

    @app.post("/api/fleets/disband")
    def disband_fleet(req: FleetDisbandRequest, token: str = Depends(get_token_from_header), db: Session = Depends(get_db)):
        user = get_current_user(token, db)
        fleet = db.query(Fleet).filter(Fleet.id == req.fleet_id, Fleet.user_id == user.id).first()
        if not fleet:
            raise HTTPException(404, "Fleet not found")
        fleet_name = fleet.name
        ships_before = fleet.get_all_ship_counts()

        # Refund rules: in transit = 0%, stationed away from your base = 25%,
        # stationed at your own base = 50% of the fleet's total ship value.
        refund = 0.0
        if not fleet.is_moving:
            value = _fleet_value(fleet, db)
            at_own_base = False
            if fleet.base_id:
                home = db.query(Colony).filter(
                    Colony.id == fleet.base_id, Colony.user_id == user.id
                ).first()
                at_own_base = home is not None
            pct = FLEET_DISBAND_REFUND_HOME if at_own_base else FLEET_DISBAND_REFUND_AWAY
            refund = round(value * pct)

        log_fleet_change(db, user.id, fleet, "disband", ships_before, f"Disbanded fleet '{fleet_name}'")
        if refund > 0:
            add_resources(user, refund)
            log_credits(db, user.id, refund, f"Disbanded fleet '{fleet_name}' — refund", "fleet")
        log_event(db, user.id, "fleet",
                  f"Disbanded fleet '{fleet_name}'" + (f" (refunded {int(refund)} cr)" if refund > 0 else ""))
        db.delete(fleet)
        db.commit()
        return {"success": True, "refund": refund}

    # ======================== FLEET REPAIR ========================

    @app.post("/api/fleets/repair")
    def repair_fleet(req: dict, token: str = Depends(get_token_from_header), db: Session = Depends(get_db)):
        """Repair damaged ships in a fleet."""
        user = get_current_user(token, db)
        fleet_id = req.get("fleet_id")
        fleet = db.query(Fleet).filter(Fleet.id == fleet_id, Fleet.user_id == user.id).first()
        if not fleet:
            raise HTTPException(404, "Fleet not found")
        if fleet.is_moving:
            raise HTTPException(400, "Cannot repair while moving")

        damage_state = json.loads(fleet.ship_damage or "{}")
        if not damage_state:
            raise HTTPException(400, "No damaged ships to repair")

        total_cost = 0.0
        for st, state_frac in damage_state.items():
            spec = get_effective_ship_spec(db, st)
            repair = spec["cost"] * (1 - state_frac) * REPAIR_COST_FRACTION
            total_cost += repair

        if not can_afford(user, total_cost):
            raise HTTPException(400, f"Not enough credits. Repair cost: {format_cost(total_cost)}")

        deduct_cost(user, total_cost)
        log_credits(db, user.id, -total_cost, f"Repair of fleet '{fleet.name}'", "production")
        fleet.ship_damage = "{}"
        db.commit()

        return {
            "success": True,
            "repair_cost": round(total_cost),
            "message": f"Fleet repaired for {int(total_cost)} credits"
        }

    # ======================== SHIP SPECS API (for frontend) ========================

    @app.get("/api/ship-specs")
    def get_ship_specs(db: Session = Depends(get_db)):
        disabled_raw = get_config(db, "disabled_ships") or ""
        disabled_set = set(s.strip() for s in disabled_raw.split(",") if s.strip())
        result = {"goods": GOODS_SPEC}
        for key, spec in SHIP_SPECS.items():
            if key in disabled_set:
                continue
            result[key] = get_effective_ship_spec(db, key)
        return result

    @app.get("/api/defense-specs")
    def get_defense_specs(db: Session = Depends(get_db)):
        disabled_raw = get_config(db, "disabled_defenses") or ""
        disabled_set = set(s.strip() for s in disabled_raw.split(",") if s.strip())
        result = {}
        for key, spec in DEFENSE_SPECS.items():
            if key in disabled_set:
                continue
            result[key] = get_effective_defense_spec(db, key)
        return result

    @app.get("/api/building-specs")
    def get_building_specs_endpoint(db: Session = Depends(get_db)):
        disabled_raw = get_config(db, "disabled_buildings") or ""
        disabled_set = set(s.strip() for s in disabled_raw.split(",") if s.strip())
        result = {}
        for key, spec in BUILDING_SPECS.items():
            if key in disabled_set:
                continue
            result[key] = get_effective_building_spec(db, key)
        return result

    @app.get("/api/research-specs")
    def get_research_specs_endpoint(db: Session = Depends(get_db)):
        disabled_raw = get_config(db, "disabled_research") or ""
        disabled_set = set(s.strip() for s in disabled_raw.split(",") if s.strip())
        result = {}
        for key, spec in RESEARCH_SPECS.items():
            if key in disabled_set:
                continue
            result[key] = get_effective_research_spec(db, key)
        return result

    @app.get("/api/game-mechanics")
    def get_game_mechanics(db: Session = Depends(get_db)):
        """Return key game mechanics constants for the Tables reference page."""
        return {
            "combat": {
                "Command Centers": "+5% fleet attack per level (1 + lv/20)",
                "Weapon Tech": "+5% weapon power per level (1 + lv/20)",
                "Armour Tech": "+5% armour per level (1 + lv/20)",
                "Shielding Tech": "+5% shield per level (1 + lv/20)",
                "Capital Flagship Bonus": "+5% power & armour to all fleet ships",
                "Top Flagship Bonus": "+10% power & armour (overrides capital flagship)",
                "Ion vs Shields": "50% passthrough (vs 1% for normal weapons)",
                "Debris": "40% of destroyed value becomes debris",
                "Combat Loot": "20% of destroyed value to each side",
                "Damage Allocation": "Proportional with exponent 0.85",
            },
            "economy": {
                "Cybernetics Tech": "+5% construction & production per level",
                "AI Tech": "+5% research output per level",
                "Energy Tech": "+5% energy output per level",
                "Research Labs": "8 research per level",
                "Metal Refineries": "+metal industry, +1 economy",
                "Robotic Factories": "+2 industry, +1 economy",
                "Nanite Factories": "+4 industry, +2 economy",
                "Android Factories": "+6 industry, +2 economy",
                "Shipyard": "+2 production, +1 economy",
                "Orbital Shipyard": "+8 production, +2 economy (no area)",
                "Spaceports": "+2 economy, enables trade routes",
                "Economic Centers": "+3 economy",
                "Capital": "+10 economy, +1 to all other bases, -15% empire income if occupied",
                "Crystal Mines": "+economy based on crystal stat",
            },
            "base": {
                "Base Construction Bonus": "+20 flat (all bases)",
                "Homeworld Bonus": "+20 additional construction",
                "Occupation Penalty": "+30% build/research time",
                "Terraform": "+5 area per level",
                "Multi-Level Platforms": "+10 area per level",
                "Orbital Base": "+10 population per level (no area)",
                "Biosphere Mod": "+1 fertility per level",
                "Fusion Plants": "+4 energy per level",
                "Antimatter Plants": "+10 energy per level",
                "Orbital Plants": "+12 energy per level (no area)",
                "Base Energy Bonus": "+2 flat per colony",
            },
            "fleet": {
                "Fleet Slots": "Bases + occupied bases + Computer tech level",
                "Jump Gate": "+70% fleet speed per level",
                "Stealth Tech": "Reduces detection time",
                "Fleet Size Limit": "Total production x 2500",
                "Autoscout": "1 per 5 Computer tech levels",
            },
            "other": {
                "Occupier Income": "30% of base income",
                "Unrest Growth": "+10% per day while occupied",
                "Unrest Decay": "-10% per day after freed",
                "Pillage Cooldown": "24 hours per base",
                "Newbie Protection": "Configurable (default 7 days)",
                "Commander Bonus": "+1% per commander level",
                "Collection Rate": "10 credits per recycler per tick",
                "Trade Route Cost": "2x distance",
            },
        }
