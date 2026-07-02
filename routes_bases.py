from fastapi import HTTPException, Depends, Query
from sqlalchemy.orm import Session
from datetime import datetime, timedelta
from models import (User, Colony, Building, Defense, Fleet, ShipQueue, Planet,
                    ConstructionQueue, ResearchQueue, TradeRoute, GuildMember, Guild)
from auth import (get_token_from_header, get_current_user, get_config_float, get_config_int, get_db,
                  get_effective_ship_spec, get_effective_defense_spec, get_effective_building_spec,
                  get_effective_research_spec, is_building_disabled, is_defense_disabled,
                  get_all_building_specs, get_all_defense_specs, get_all_research_specs, log_event, log_credits)
from game_logic import (calc_base_stats, calc_building_cost, calc_economy_rate, calc_defense_cost, get_defense_model,
                        get_building_level, get_tech_level,
                        collect_resources, _process_ship_queues, _ship_build_time, _update_unrest,
                        project_resources_after_queue, _record_region_snapshot, is_capital_occupied,
                        structure_refund_value)
from resources import can_afford, deduct_cost, add_resources, format_cost, round_cost, scale_cost, total_cost_value
from config_defaults import *
from pydantic import BaseModel
import action_points


def _dynamic_building_desc(building_type: str, spec: dict, planet=None, game_speed: float = 1.0, db=None) -> str:
    """Generate dynamic building description from config constants, planet stats, and game speed."""
    bt = building_type
    sp = game_speed  # multiplier for construction/prod/econ/research rates

    def _v(val):
        """Format a speed-scaled value: show as int if whole, else 1 decimal."""
        v = val * sp
        return str(int(v)) if v == int(v) else f"{v:.1f}"

    if bt == "urban_structures":
        f = planet.fertility if planet else 0
        return f"+Pop per level (×{f} fertility)" if planet else "+Pop based on Fertility"
    elif bt == "solar_plants":
        s = planet.solar if planet else 0
        return f"+{s} Energy per level" if planet else "+Energy based on Solar"
    elif bt == "gas_plants":
        g = planet.gas if planet else 0
        return f"+{g} Energy per level" if planet else "+Energy based on Gas"
    elif bt == "fusion_plants":
        return f"+{FUSION_PLANT_ENERGY} Energy (flat)"
    elif bt == "antimatter_plants":
        return f"+{ANTIMATTER_PLANT_ENERGY} Energy (flat)"
    elif bt == "orbital_plants":
        return f"+{ORBITAL_PLANT_ENERGY} Energy (no area)"
    elif bt == "research_labs":
        return f"+{_v(RESEARCH_LAB_RATE)} Research per level"
    elif bt == "metal_refineries":
        m = planet.metal if planet else 0
        return f"+{_v(m)} Construction/Prod, +{_v(ECON_METAL_REFINERIES)} econ"
    elif bt == "crystal_mines":
        c = planet.crystal if planet else 0
        return f"+{_v(c)} Economy per level"
    elif bt == "robotic_factories":
        return f"+{_v(ROBOTIC_FACTORY_INDUSTRIAL_MULT)} Construction/Prod, +{_v(ECON_ROBOTIC_FACTORIES)} econ"
    elif bt == "shipyard":
        return f"+{_v(SHIPYARD_PRODUCTION_MULT)} Production, +{_v(ECON_SHIPYARD)} econ, unlocks ships"
    elif bt == "orbital_shipyard":
        return f"+{_v(ORBITAL_SHIPYARD_PRODUCTION_MULT)} Production (no area), +{_v(ECON_ORBITAL_SHIPYARD)} econ"
    elif bt == "spaceports":
        return f"+{_v(ECON_SPACEPORTS)} econ, trade routes"
    elif bt == "command_centers":
        pct = round(100 / COMMAND_CENTER_DIVISOR, 1)
        pct_str = f"{int(pct)}" if pct == int(pct) else f"{pct}"
        return f"+{pct_str}% fleet attack per level"
    elif bt == "nanite_factories":
        return f"+{_v(NANITE_FACTORY_INDUSTRIAL_MULT)} Construction/Prod, +{_v(ECON_NANITE_FACTORIES)} econ"
    elif bt == "android_factories":
        return f"+{_v(ANDROID_FACTORY_INDUSTRIAL_MULT)} Construction/Prod, +{_v(ECON_ANDROID_FACTORIES)} econ"
    elif bt == "economic_centers":
        return f"+{_v(ECON_ECONOMIC_CENTERS)} econ (advanced)"
    elif bt == "terraform":
        return f"+{TERRAFORM_AREA_PER_LEVEL} Area per level"
    elif bt == "multi_level_platforms":
        return f"+{MLP_AREA_PER_LEVEL} Area per level"
    elif bt == "orbital_base":
        return f"+{ORBITAL_BASE_POP_PER_LEVEL} Population (no area)"
    elif bt == "biosphere_mod":
        return f"+{BIOSPHERE_FERTILITY_PER_LEVEL} Fertility per level"
    elif bt == "capital":
        return f"+{_v(ECON_CAPITAL)} econ, designates capital base"
    elif bt == "jump_gate":
        jg_bonus = JUMP_GATE_SPEED_BONUS_PER_LEVEL
        if db:
            jg_bonus = get_config_float(db, "jump_gate_speed_bonus", JUMP_GATE_SPEED_BONUS_PER_LEVEL)
        pct = int(jg_bonus * 100)
        return f"+{pct}% fleet speed per level, stellar cross-galaxy"
    return spec.get("desc", "")


class BaseRename(BaseModel):
    name: str

class BaseSetHome(BaseModel):
    base_id: int

class BaseReorder(BaseModel):
    base_ids: list

class UpgradeBuildingRequest(BaseModel):
    base_id: int
    building_type: str

class BuildDefenseRequest(BaseModel):
    base_id: int
    defense_type: str
    count: int = 1  # For count model: how many units to build

class RevoltRequest(BaseModel):
    base_id: int

class DowngradeStructureRequest(BaseModel):
    base_id: int
    kind: str          # "building" or "defense"
    type_key: str      # building_type or defense_type
    levels: int = 1    # how many levels to remove (default 1)


def register_bases_routes(app):

    @app.get("/api/bases")
    def get_bases(token: str = Depends(get_token_from_header), db: Session = Depends(get_db)):
        user = get_current_user(token, db)
        game_speed = get_config_float(db, "game_speed", 1.0)
        collect_resources(user, db, game_speed)
        # Gather user tech levels for can_build checks
        user_techs = {}
        for r in user.research:
            user_techs[r.tech_type] = r.level

        # Pre-fetch all construction queues for this user's colonies
        all_constr_queues = (db.query(ConstructionQueue)
            .filter(ConstructionQueue.user_id == user.id)
            .order_by(ConstructionQueue.colony_id, ConstructionQueue.position).all())
        constr_queues_by_colony = {}
        for cq in all_constr_queues:
            constr_queues_by_colony.setdefault(cq.colony_id, []).append(cq)

        result = []
        # Sort colonies by user-defined order, then by ID as fallback
        sorted_colonies = sorted(user.colonies, key=lambda c: (
            getattr(c, 'sort_order', 0) or 0,
            c.id
        ))
        for colony in sorted_colonies:
            planet = colony.planet
            system = planet.system
            region = system.region
            galaxy = region.galaxy
            stats = calc_base_stats(colony, user, game_speed)

            # Get construction queue for this colony
            colony_queue = constr_queues_by_colony.get(colony.id, [])

            # Build effective levels map (current level + queued upgrades)
            effective_levels = {}
            for cq in colony_queue:
                if cq.item_category == 'building':
                    effective_levels[cq.item_type] = cq.target_level

            # Resource buildings need planet to have that resource
            resource_buildings = {
                "crystal_mines": planet.crystal,
                "solar_plants": planet.solar,
                "gas_plants": planet.gas,
                "metal_refineries": planet.metal,
            }

            buildings = []
            for b in colony.buildings:
                spec = get_effective_building_spec(db, b.building_type)

                # Use effective level (accounting for queued upgrades) for next cost
                eff_level = effective_levels.get(b.building_type, b.level)
                next_cost, next_time = calc_building_cost(db, b.building_type, eff_level, stats, game_speed, colony_id=colony.id, user=user)

                # Determine if player can build this
                can_build = True
                cannot_reason = ""
                if is_building_disabled(db, b.building_type):
                    can_build = False
                    cannot_reason = "Disabled"
                elif b.building_type in resource_buildings and resource_buildings[b.building_type] <= 0:
                    can_build = False
                    cannot_reason = "Planet lacks resource"
                else:
                    for tech, lvl_needed in spec.get("tech_req", {}).items():
                        if user_techs.get(tech, 0) < lvl_needed:
                            tspec = get_effective_research_spec(db, tech)
                            can_build = False
                            cannot_reason = f"Requires {tspec.get('name', tech)} Lv{lvl_needed}"
                            break

                max_lv = spec.get("max_level", 0)
                is_maxed = max_lv > 0 and eff_level >= max_lv

                buildings.append({
                    "type": b.building_type,
                    "name": spec.get("name", b.building_type),
                    "desc": _dynamic_building_desc(b.building_type, spec, planet, game_speed, db),
                    "level": b.level,
                    "effective_level": eff_level,
                    "max_level": max_lv,
                    "next_cost": round_cost(next_cost, 1),
                    "next_time": round(next_time),
                    "is_constructing": b.is_constructing,
                    "construction_end": b.construction_end.isoformat() if b.construction_end else None,
                    "energy_req": spec.get("energy_req", 0),
                    "pop_req": spec.get("pop_req", 0),
                    "area_req": spec.get("area_req", 0),
                    "tech_req": spec.get("tech_req", {}),
                    "can_build": can_build,
                    "cannot_reason": cannot_reason,
                    "is_maxed": is_maxed,
                })

            # Build effective defense levels from queue
            effective_def_levels = {}
            for cq in colony_queue:
                if cq.item_category == 'defense':
                    effective_def_levels[cq.item_type] = cq.target_level

            defenses = []
            for d in colony.defenses:
                dspec = get_effective_defense_spec(db, d.defense_type)
                cost_mult = dspec.get("cost_mult", 1.5)

                # Use effective level for next cost calc
                d_eff_level = effective_def_levels.get(d.defense_type, d.level)
                next_cost = round_cost(scale_cost(dspec.get("cost", 0), cost_mult ** d_eff_level))
                next_time = round(total_cost_value(next_cost) * 5 / game_speed)  # defense build time in seconds

                # Check if player can build this defense
                d_can_build = True
                d_cannot_reason = ""
                if is_defense_disabled(db, d.defense_type):
                    d_can_build = False
                    d_cannot_reason = "Disabled"
                else:
                    for tech, lvl_needed in dspec.get("req", {}).items():
                        if user_techs.get(tech, 0) < lvl_needed:
                            tspec = get_effective_research_spec(db, tech)
                            d_can_build = False
                            d_cannot_reason = f"Requires {tspec.get('name', tech)} Lv{lvl_needed}"
                            break

                d_is_maxed = d_eff_level >= dspec.get("max_level", 50)

                defenses.append({
                    "type": d.defense_type,
                    "name": dspec.get("name", d.defense_type),
                    "desc": dspec.get("desc", ""),
                    "level": d.level,
                    "effective_level": d_eff_level,
                    "quantity": d.quantity,  # level * 5
                    "cost": dspec.get("cost", 0),
                    "next_cost": next_cost,
                    "next_time": next_time,
                    "max_level": dspec.get("max_level", 50),
                    "energy_req": dspec.get("energy_req", 0),
                    "attack": dspec.get("attack", 0),
                    "armour": dspec.get("armour", 0),
                    "shield": dspec.get("shield", 0),
                    "req": dspec.get("req", {}),
                    "is_constructing": d.is_constructing or False,
                    "construction_end": d.construction_end.isoformat() if d.construction_end else None,
                    "can_build": d_can_build,
                    "cannot_reason": d_cannot_reason,
                    "is_maxed": d_is_maxed,
                })

            # Calculate resource usage (buildings + defenses consume energy)
            energy_used = sum(get_effective_building_spec(db, b.building_type).get("energy_req", 0) * b.level for b in colony.buildings)
            energy_used += sum(get_effective_defense_spec(db, d.defense_type).get("energy_req", 0) * d.level for d in colony.defenses)
            pop_used = sum(get_effective_building_spec(db, b.building_type).get("pop_req", 0) * b.level for b in colony.buildings)
            area_used = sum(get_effective_building_spec(db, b.building_type).get("area_req", 0) * b.level for b in colony.buildings)
            area_used += sum(get_effective_defense_spec(db, d.defense_type).get("area_req", 0) * d.level for d in colony.defenses)

            # Build full construction queue for this colony
            queue_items = []
            for cq in colony_queue:
                cq_spec = (get_effective_building_spec(db, cq.item_type) if cq.item_category == 'building'
                           else get_effective_defense_spec(db, cq.item_type))
                queue_items.append({
                    "id": cq.id,
                    "category": cq.item_category,
                    "type": cq.item_type,
                    "name": cq_spec.get("name", cq.item_type),
                    "target_level": cq.target_level,
                    "position": cq.position,
                    "cost": round_cost(cq.cost, 1) if cq.cost else 0,
                    "build_time": round(cq.build_time) if cq.build_time else 0,
                    "finish_at": cq.finish_at.isoformat() if cq.finish_at else None,
                    "started_at": cq.started_at.isoformat() if cq.started_at else None,
                })

            result.append({
                "id": colony.id,
                "name": colony.name,
                "planet_id": planet.id,
                "planet_name": planet.name,
                "planet_type": planet.planet_type,
                "planet_stats": {
                    "solar": planet.solar, "gas": planet.gas, "fertility": planet.fertility,
                    "area": planet.area, "metal": planet.metal, "crystal": planet.crystal,
                },
                "coords": planet.name,  # coord format: A01:01:01
                "galaxy_id": galaxy.id, "region_id": region.id, "system_id": system.id,
                "economy": stats["economy"],
                "construction": stats["construction"],
                "production": stats["production"],
                "energy": stats["energy"],
                "energy_used": energy_used,
                "population": stats["population"],
                "pop_used": pop_used,
                "area": stats["area"],
                "area_used": area_used,
                "shipyard_level": stats["shipyard_level"],
                "research_capacity": stats.get("research", 0),
                "research_lab_level": stats.get("research_lab_level", 0),
                "buildings": buildings,
                "defenses": defenses,
                "construction_queue": queue_items,
                "occupied_by": colony.occupied_by,
                "occupied_by_name": colony.occupier.username if colony.occupied_by else None,
                "unrest": round(colony.unrest, 3) if colony.unrest else 0,
                "defense_effectiveness": round((colony.defense_effectiveness or 1.0), 3),
                "is_home_base": bool(getattr(colony, 'is_home_base', False)),
                "sort_order": getattr(colony, 'sort_order', 0) or 0,
            })
        # Add ship queue info per base (multiple items per base now)
        _process_ship_queues(user, db, game_speed)
        queues = (db.query(ShipQueue)
                  .filter(ShipQueue.user_id == user.id)
                  .order_by(ShipQueue.colony_id, ShipQueue.position).all())
        queue_by_base = {}
        # Cache colonies for build time calc
        colony_cache = {c.id: c for c in user.colonies}
        for q in queues:
            if q.colony_id not in queue_by_base:
                queue_by_base[q.colony_id] = []
            # Compute total build time for queued items
            colony_obj = colony_cache.get(q.colony_id)
            total_time = None
            if colony_obj:
                per_ship = _ship_build_time(q.ship_type, colony_obj, user, game_speed, db)
                total_time = round(per_ship * q.count)
            queue_by_base[q.colony_id].append({
                "id": q.id,
                "ship_type": q.ship_type,
                "ship_name": get_effective_ship_spec(db, q.ship_type).get("name", q.ship_type),
                "count": q.count,
                "built": q.built,
                "position": getattr(q, 'position', 0) or 0,
                "cost": round(getattr(q, 'cost', 0) or 0, 1),
                "next_complete": q.next_complete.isoformat() if q.next_complete else None,
                "total_time": total_time,
            })
        # Attach per-base research queues
        all_research_queues = db.query(ResearchQueue).filter(
            ResearchQueue.user_id == user.id
        ).order_by(ResearchQueue.colony_id, ResearchQueue.position).all()
        rq_by_base = {}
        for rq in all_research_queues:
            rq_by_base.setdefault(rq.colony_id, []).append(rq)
        for r in result:
            r["ship_queue"] = queue_by_base.get(r["id"], [])
            r["construction_queue_count"] = len(r.get("construction_queue", []))
            # Economy max = economy without penalty; current may be reduced
            col = db.query(Colony).filter(Colony.id == r["id"]).first()
            penalty = getattr(col, 'economy_penalty', 0) or 0
            r["economy_max"] = r["economy"] + penalty
            # Per-base research queue
            base_rqs = rq_by_base.get(r["id"], [])
            if base_rqs:
                rq = base_rqs[0]
                rspec = get_effective_research_spec(db, rq.tech_type)
                r["research_queue"] = {
                    "tech_type": rq.tech_type,
                    "name": rspec.get("name", rq.tech_type),
                    "target_level": rq.target_level,
                    "end_time": rq.finish_at.isoformat() if rq.finish_at else None,
                    "queue_count": len(base_rqs),
                }
        # Attach fleet lists per base
        from game_logic import _fleet_total_ships, _fleet_value
        colony_ids = [r["id"] for r in result]
        all_stationed = db.query(Fleet).filter(Fleet.base_id.in_(colony_ids), Fleet.is_moving == False).all()
        all_incoming = db.query(Fleet).filter(Fleet.destination_base_id.in_(colony_ids), Fleet.is_moving == True).all()
        # Cache guild tags
        _gtag_cache = {}
        def _get_gtag(uid):
            if uid not in _gtag_cache:
                gm = db.query(GuildMember).filter(GuildMember.user_id == uid).first()
                _gtag_cache[uid] = db.query(Guild).filter(Guild.id == gm.guild_id).first().tag if gm else ""
            return _gtag_cache[uid]

        fleets_by_base = {}
        for f in all_stationed:
            if _fleet_total_ships(f) == 0:
                continue
            fleets_by_base.setdefault(f.base_id, []).append({
                "id": f.id, "name": f.name, "player": f.user.username,
                "guild_tag": _get_gtag(f.user_id),
                "is_mine": f.user_id == user.id, "size": _fleet_value(f, db),
            })
        incoming_by_base = {}
        for f in all_incoming:
            if _fleet_total_ships(f) == 0:
                continue
            incoming_by_base.setdefault(f.destination_base_id, []).append({
                "id": f.id, "name": f.name, "player": f.user.username,
                "guild_tag": _get_gtag(f.user_id),
                "is_mine": f.user_id == user.id, "size": _fleet_value(f, db),
                "arrival": f.arrival_time.isoformat() if f.arrival_time else None,
            })
        for r in result:
            r["fleets"] = fleets_by_base.get(r["id"], [])
            r["incoming_fleets"] = incoming_by_base.get(r["id"], [])

        return result

    @app.get("/api/all-bases")
    def get_all_bases(token: str = Depends(get_token_from_header), db: Session = Depends(get_db)):
        user = get_current_user(token, db)
        colonies = db.query(Colony).all()
        result = []
        for c in colonies:
            p = c.planet
            result.append({
                "id": c.id, "name": c.name, "owner": c.user.username, "owner_id": c.user_id,
                "is_mine": c.user_id == user.id, "planet_id": p.id, "planet_name": p.name,
            })
        return result

    @app.get("/api/my-bases-coords")
    def my_bases_coords(token: str = Depends(get_token_from_header), db: Session = Depends(get_db)):
        user = get_current_user(token, db)
        result = []
        for colony in user.colonies:
            planet = colony.planet
            system = planet.system
            region = system.region
            result.append({
                "base_name": colony.name, "planet_name": planet.name,
                "galaxy_id": region.galaxy_id, "region_id": region.id, "region_name": region.name,
                "system_id": system.id, "system_name": system.name,
            })
        return result

    @app.post("/api/bases/{base_id}/rename")
    def rename_base(base_id: int, req: BaseRename, token: str = Depends(get_token_from_header), db: Session = Depends(get_db)):
        user = get_current_user(token, db)
        colony = db.query(Colony).filter(Colony.id == base_id, Colony.user_id == user.id).first()
        if not colony:
            raise HTTPException(404, "Base not found")
        colony.name = req.name[:40]
        db.commit()
        return {"success": True, "name": colony.name}

    @app.post("/api/bases/set-home")
    def set_home_base(req: BaseSetHome, token: str = Depends(get_token_from_header), db: Session = Depends(get_db)):
        user = get_current_user(token, db)
        colony = db.query(Colony).filter(Colony.id == req.base_id, Colony.user_id == user.id).first()
        if not colony:
            raise HTTPException(404, "Base not found")
        # Clear old home base
        for c in user.colonies:
            c.is_home_base = False
        colony.is_home_base = True
        db.commit()
        return {"success": True}

    @app.post("/api/bases/reorder")
    def reorder_bases(req: BaseReorder, token: str = Depends(get_token_from_header), db: Session = Depends(get_db)):
        user = get_current_user(token, db)
        user_colony_ids = {c.id for c in user.colonies}
        if set(req.base_ids) != user_colony_ids:
            raise HTTPException(400, "Must include all bases exactly once")
        for i, cid in enumerate(req.base_ids):
            db.query(Colony).filter(Colony.id == cid).update({Colony.sort_order: i})
        db.commit()
        return {"success": True}

    # ======================== BUILDING UPGRADES ========================

    @app.post("/api/bases/upgrade")
    def upgrade_building(req: UpgradeBuildingRequest, token: str = Depends(get_token_from_header), db: Session = Depends(get_db)):
        user = get_current_user(token, db)
        game_speed = get_config_float(db, "game_speed", 1.0)
        collect_resources(user, db, game_speed)

        colony = db.query(Colony).filter(Colony.id == req.base_id, Colony.user_id == user.id).first()
        if not colony:
            raise HTTPException(404, "Base not found")

        building = next((b for b in colony.buildings if b.building_type == req.building_type), None)
        if not building:
            raise HTTPException(404, "Building not found")

        spec = get_effective_building_spec(db, req.building_type)
        if is_building_disabled(db, req.building_type):
            raise HTTPException(400, f"{spec.get('name', req.building_type)} has been disabled")
        if not spec:
            raise HTTPException(400, "Invalid building type")

        # Check planet resource compatibility — can't build resource buildings on planets without that resource
        planet = colony.planet
        resource_buildings = {
            "crystal_mines": ("crystal", planet.crystal),
            "solar_plants": ("solar", planet.solar),
            "gas_plants": ("gas", planet.gas),
            "metal_refineries": ("metal", planet.metal),
        }
        if req.building_type in resource_buildings:
            res_name, res_val = resource_buildings[req.building_type]
            if res_val <= 0:
                raise HTTPException(400, f"This planet has no {res_name} — {spec.get('name', req.building_type)} cannot be built here")

        # Check construction queue size (engine flag; defaults to the constant)
        queue_max = get_config_int(db, "construction_queue_max", CONSTRUCTION_QUEUE_MAX)
        queue = (db.query(ConstructionQueue)
                 .filter(ConstructionQueue.colony_id == colony.id,
                         ConstructionQueue.user_id == user.id)
                 .order_by(ConstructionQueue.position).all())
        if len(queue) >= queue_max:
            raise HTTPException(400, f"Construction queue full (max {queue_max} items)")

        # Figure out effective level (current + any queued upgrades for same building)
        effective_level = building.level
        for q in queue:
            if q.item_category == 'building' and q.item_type == req.building_type:
                effective_level = q.target_level
        max_lv = spec.get("max_level", 0)
        if max_lv > 0 and effective_level >= max_lv:
            raise HTTPException(400, "Max level reached (including queued upgrades)")

        # Capital uniqueness: only one base across the empire can have a Capital
        if spec.get("unique") and req.building_type == "capital":
            for other_colony in user.colonies:
                if other_colony.id != colony.id and get_building_level(other_colony, "capital") > 0:
                    raise HTTPException(400, f"You already have a Capital at {other_colony.name}. Only one base can have a Capital.")

        # Check tech requirements
        for tech, level_needed in spec.get("tech_req", {}).items():
            if get_tech_level(user, tech) < level_needed:
                raise HTTPException(400, f"Requires {get_effective_research_spec(db, tech).get('name', tech)} level {level_needed}")

        stats = calc_base_stats(colony, user, game_speed)

        # Smart queue validation: project resources AFTER all queued items complete
        projected = project_resources_after_queue(colony, user, queue, db)
        energy_req = spec.get("energy_req", 0)
        pop_req = spec.get("pop_req", 0)
        area_req = spec.get("area_req", 0)
        energy_free = projected["energy"] - projected["energy_used"]
        pop_free = projected["population"] - projected["pop_used"]
        area_free = projected["area"] - projected["area_used"]
        if energy_req > 0 and energy_free < energy_req:
            raise HTTPException(400, f"Not enough energy after queue completes (need {energy_req}, will have {max(0,energy_free)} free). Queue more power plants first!")
        if pop_req > 0 and pop_free < pop_req:
            raise HTTPException(400, f"Not enough population after queue completes (need {pop_req}, will have {max(0,pop_free)} free). Queue more Urban Structures first!")
        if area_req > 0 and area_free < area_req:
            raise HTTPException(400, f"Not enough area after queue completes (need {area_req}, will have {max(0,area_free)} free). Queue Terraform or MLP first!")

        cost, build_time = calc_building_cost(db, req.building_type, effective_level, stats, game_speed, colony_id=colony.id, user=user)

        target_level = effective_level + 1
        position = len(queue)
        now = datetime.utcnow()

        # Only check credits for the active slot (position 0); queued items wait
        if position == 0 and not can_afford(user, cost):
            raise HTTPException(400, f"Need {format_cost(cost)} credits")

        action_points.debit_action_points(user, db, "building_upgrade")

        if position == 0:
            # No queue — start immediately, deduct cost now
            deduct_cost(user, cost)
            log_credits(db, user.id, -total_cost_value(cost), f"Construction of {spec.get('name', req.building_type)} lvl {target_level} at {colony.name}", "construction")
            building.is_constructing = True
            building.construction_end = now + timedelta(seconds=build_time)
            finish_at = building.construction_end
            started_at = now
        else:
            # Queue it — will start when previous items finish
            finish_at = None
            started_at = None

        queue_item = ConstructionQueue(
            colony_id=colony.id, user_id=user.id, position=position,
            item_category='building', item_type=req.building_type,
            target_level=target_level, cost=cost, build_time=build_time,
            started_at=started_at, finish_at=finish_at
        )
        db.add(queue_item)

        spec_name = spec.get("name", req.building_type)
        if position == 0:
            log_event(db, user.id, "construction", f"Started upgrading {spec_name} to Lv{target_level} at {colony.name}")
        else:
            log_event(db, user.id, "construction", f"Queued {spec_name} Lv{target_level} at {colony.name} (position {position + 1})")
        db.commit()
        return {"success": True, "cost": round_cost(cost, 1), "time": round(build_time),
                "finish": finish_at.isoformat() if finish_at else None,
                "queued": position > 0, "queue_position": position + 1}

    @app.get("/api/bases/{base_id}/construction-queue")
    def get_construction_queue(base_id: int, token: str = Depends(get_token_from_header), db: Session = Depends(get_db)):
        user = get_current_user(token, db)
        queue = (db.query(ConstructionQueue)
                 .filter(ConstructionQueue.colony_id == base_id,
                         ConstructionQueue.user_id == user.id)
                 .order_by(ConstructionQueue.position).all())
        result = []
        for q in queue:
            if q.item_category == 'building':
                name = get_effective_building_spec(db, q.item_type).get("name", q.item_type)
            else:
                name = get_effective_defense_spec(db, q.item_type).get("name", q.item_type)
            result.append({
                "id": q.id, "position": q.position,
                "category": q.item_category, "type": q.item_type,
                "name": name, "target_level": q.target_level,
                "cost": round(q.cost, 1), "build_time": round(q.build_time),
                "started_at": q.started_at.isoformat() if q.started_at else None,
                "finish_at": q.finish_at.isoformat() if q.finish_at else None,
            })
        return result

    @app.delete("/api/bases/{base_id}/construction-queue/{queue_id}")
    def cancel_construction_queue(base_id: int, queue_id: int, token: str = Depends(get_token_from_header), db: Session = Depends(get_db)):
        user = get_current_user(token, db)
        item = db.query(ConstructionQueue).filter(
            ConstructionQueue.id == queue_id,
            ConstructionQueue.colony_id == base_id,
            ConstructionQueue.user_id == user.id
        ).first()
        if not item:
            raise HTTPException(404, "Queue item not found")
        position = item.position
        # Refund credits only if item was active (already paid)
        if position == 0:
            add_resources(user, item.cost)
            log_credits(db, user.id, total_cost_value(item.cost), f"Cancelled {item.item_type} at base {base_id}", "construction")
        # If cancelling active item, stop the construction
        if position == 0:
            colony = db.query(Colony).filter(Colony.id == base_id).first()
            if colony:
                if item.item_category == 'building':
                    building = next((b for b in colony.buildings if b.building_type == item.item_type), None)
                    if building:
                        building.is_constructing = False
                        building.construction_end = None
                elif item.item_category == 'defense':
                    defense = next((d for d in colony.defenses if d.defense_type == item.item_type), None)
                    if defense:
                        defense.is_constructing = False
                        defense.construction_end = None
        db.delete(item)
        # Re-number remaining queue items
        remaining = (db.query(ConstructionQueue)
                     .filter(ConstructionQueue.colony_id == base_id,
                             ConstructionQueue.user_id == user.id)
                     .order_by(ConstructionQueue.position).all())
        for i, q in enumerate(remaining):
            q.position = i
        # If we cancelled position 0 and there's a new position 0, start it (deduct credits)
        if position == 0 and remaining:
            new_active = remaining[0]
            if can_afford(user, new_active.cost):
                deduct_cost(user, new_active.cost)
                log_credits(db, user.id, -total_cost_value(new_active.cost), f"Construction of {new_active.item_type} at base {base_id}", "construction")
                now = datetime.utcnow()
                new_active.started_at = now
                new_active.finish_at = now + timedelta(seconds=new_active.build_time)
                colony = db.query(Colony).filter(Colony.id == base_id).first()
                if colony and new_active.item_category == 'building':
                    building = next((b for b in colony.buildings if b.building_type == new_active.item_type), None)
                    if building:
                        building.is_constructing = True
                        building.construction_end = new_active.finish_at
                elif colony and new_active.item_category == 'defense':
                    defense = next((d for d in colony.defenses if d.defense_type == new_active.item_type), None)
                    if defense:
                        defense.is_constructing = True
                        defense.construction_end = new_active.finish_at
        db.commit()
        return {"success": True, "refunded": round_cost(item.cost, 1)}

    # ======================== DEFENSES ========================

    @app.post("/api/bases/build-defense")
    def build_defense(req: BuildDefenseRequest, token: str = Depends(get_token_from_header), db: Session = Depends(get_db)):
        user = get_current_user(token, db)
        game_speed = get_config_float(db, "game_speed", 1.0)
        collect_resources(user, db, game_speed)

        colony = db.query(Colony).filter(Colony.id == req.base_id, Colony.user_id == user.id).first()
        if not colony:
            raise HTTPException(404, "Base not found")

        dspec = get_effective_defense_spec(db, req.defense_type)
        if not dspec:
            raise HTTPException(400, "Invalid defense type")
        if is_defense_disabled(db, req.defense_type):
            raise HTTPException(400, f"{dspec['name']} has been disabled by the server admin")

        # Check tech requirements
        for tech, level_needed in dspec.get("req", {}).items():
            if get_tech_level(user, tech) < level_needed:
                raise HTTPException(400, f"Requires {get_effective_research_spec(db, tech).get('name', tech)} level {level_needed}")

        # Check construction queue size (shared with buildings; engine flag)
        queue_max = get_config_int(db, "construction_queue_max", CONSTRUCTION_QUEUE_MAX)
        queue = (db.query(ConstructionQueue)
                 .filter(ConstructionQueue.colony_id == colony.id,
                         ConstructionQueue.user_id == user.id)
                 .order_by(ConstructionQueue.position).all())
        if len(queue) >= queue_max:
            raise HTTPException(400, f"Construction queue full (max {queue_max} items)")

        # Get current defense record (or create one)
        defense = next((d for d in colony.defenses if d.defense_type == req.defense_type), None)
        current_level = defense.level if defense else 0
        # Account for queued upgrades of same defense type
        for q in queue:
            if q.item_category == 'defense' and q.item_type == req.defense_type:
                current_level = q.target_level

        defense_model = get_defense_model()
        if defense_model == "count":
            # Count model: build N units, no max level
            build_count = max(1, req.count)
            next_level = current_level + build_count
        else:
            # Level model: upgrade one level at a time
            build_count = 1
            next_level = current_level + 1
            max_level = dspec.get("max_level", 50)
            if current_level >= max_level:
                raise HTTPException(400, f"{dspec['name']} is at max level ({max_level})")

        # Calculate cost using defense model-aware function
        upgrade_cost, _, _ = calc_defense_cost(db, req.defense_type, current_level, game_speed, build_count)

        # Smart queue validation: project resources after all queued items complete
        projected = project_resources_after_queue(colony, user, queue, db)
        energy_req = dspec.get("energy_req", 0)
        area_req = dspec.get("area_req", 0)
        energy_free = projected["energy"] - projected["energy_used"]
        area_free = projected["area"] - projected["area_used"]
        if energy_req > 0 and energy_free < energy_req:
            raise HTTPException(400, f"Not enough energy after queue completes (need {energy_req}, will have {max(0,energy_free)} free). Queue more power plants first!")
        if area_req > 0 and area_free < area_req:
            raise HTTPException(400, f"Not enough area after queue completes (need {area_req}, will have {max(0,area_free)} free).")

        # Ensure defense record exists
        if not defense:
            defense = Defense(colony_id=colony.id, defense_type=req.defense_type, level=0)
            db.add(defense)
            db.flush()

        position = len(queue)
        now = datetime.utcnow()
        _, build_time, _ = calc_defense_cost(db, req.defense_type, current_level, game_speed, build_count)

        # Only check credits for the active slot (position 0); queued items wait
        if position == 0 and not can_afford(user, upgrade_cost):
            raise HTTPException(400, f"Need {format_cost(upgrade_cost)} credits")

        action_points.debit_action_points(user, db, "defense_build")

        if position == 0:
            # Start immediately — deduct cost now
            deduct_cost(user, upgrade_cost)
            label = f"lvl {next_level}" if defense_model == "level" else f"x{build_count}"
            log_credits(db, user.id, -total_cost_value(upgrade_cost), f"Construction of {defense.defense_type} {label} at {colony.name}", "construction")
            defense.is_constructing = True
            defense.construction_end = now + timedelta(seconds=build_time)
            finish_at = defense.construction_end
            started_at = now
        else:
            finish_at = None
            started_at = None

        queue_item = ConstructionQueue(
            colony_id=colony.id, user_id=user.id, position=position,
            item_category='defense', item_type=req.defense_type,
            target_level=next_level, cost=upgrade_cost, build_time=build_time,
            started_at=started_at, finish_at=finish_at
        )
        db.add(queue_item)
        user.score += 5
        db.commit()
        return {"success": True, "type": req.defense_type, "new_level": next_level,
                "units": next_level if defense_model == "count" else next_level * 5,
                "cost": upgrade_cost, "defense_model": defense_model,
                "time": round(build_time), "finish": finish_at.isoformat() if finish_at else None,
                "queued": position > 0, "queue_position": position + 1}

    # ======================== REVOLT ========================

    @app.post("/api/bases/revolt")
    def revolt_base(req: RevoltRequest, token: str = Depends(get_token_from_header), db: Session = Depends(get_db)):
        """Free your base from occupation when unrest reaches 100%."""
        user = get_current_user(token, db)
        colony = db.query(Colony).filter(Colony.id == req.base_id, Colony.user_id == user.id).first()
        if not colony:
            raise HTTPException(404, "Base not found")
        if not colony.occupied_by:
            raise HTTPException(400, "Base is not occupied")
        _update_unrest(colony, db)
        if colony.unrest < 1.0:
            raise HTTPException(400, f"Unrest is {colony.unrest*100:.0f}% — must reach 100% to revolt")
        # Free the base
        colony.occupied_by = None
        colony.occupation_start = None
        colony.unrest = POST_REVOLT_UNREST  # drops to 40% after revolt
        colony.defense_effectiveness = 1.0  # defenses restored
        db.commit()
        return {"success": True, "message": "Base freed from occupation!"}

    # ======================== DOWNGRADE STRUCTURE ========================

    @app.post("/api/bases/downgrade")
    def downgrade_structure(req: DowngradeStructureRequest, token: str = Depends(get_token_from_header), db: Session = Depends(get_db)):
        """Disband one or more levels of a building or defense.
        Refunds 50% of the removed levels' cost into the player's base reserve
        (a discount toward the next base)."""
        user = get_current_user(token, db)
        colony = db.query(Colony).filter(Colony.id == req.base_id, Colony.user_id == user.id).first()
        if not colony:
            raise HTTPException(404, "Base not found")
        kind = req.kind if req.kind in ("building", "defense") else "building"
        levels = max(1, int(req.levels))

        if kind == "defense":
            row = db.query(Defense).filter(
                Defense.colony_id == colony.id, Defense.defense_type == req.type_key
            ).first()
            type_label = get_effective_defense_spec(db, req.type_key).get("name", req.type_key)
        else:
            row = db.query(Building).filter(
                Building.colony_id == colony.id, Building.building_type == req.type_key
            ).first()
            type_label = get_effective_building_spec(db, req.type_key).get("name", req.type_key)
        if not row or row.level <= 0:
            raise HTTPException(400, "Nothing to disband at this structure")

        # Block downgrade while this structure has active/queued construction —
        # otherwise a pending queue item would later jump the level back up.
        pending = db.query(ConstructionQueue).filter(
            ConstructionQueue.colony_id == colony.id,
            ConstructionQueue.item_category == kind,
            ConstructionQueue.item_type == req.type_key,
        ).first()
        if pending or getattr(row, "is_constructing", False):
            raise HTTPException(400, "Finish or cancel construction on this structure before disbanding levels")

        from_level = row.level
        to_level = max(0, from_level - levels)
        if to_level >= from_level:
            raise HTTPException(400, "Invalid level count")

        refund = structure_refund_value(db, kind, req.type_key, from_level, to_level)
        row.level = to_level
        user.base_reserve = (user.base_reserve or 0.0) + refund
        log_event(db, user.id, "construction",
                  f"Disbanded {type_label} {from_level}→{to_level} at {colony.name} "
                  f"(+{int(refund)} to base reserve)")
        db.commit()
        return {
            "success": True,
            "new_level": to_level,
            "reserve_gain": round(refund),
            "base_reserve": round(user.base_reserve or 0.0),
        }

    @app.get("/api/bases/downgrade-preview")
    def downgrade_preview(base_id: int = Query(...), kind: str = Query("building"),
                          type_key: str = Query(...),
                          token: str = Depends(get_token_from_header), db: Session = Depends(get_db)):
        """Per-level build cost + disband refund for a structure (drives the disband UI)."""
        user = get_current_user(token, db)
        colony = db.query(Colony).filter(Colony.id == base_id, Colony.user_id == user.id).first()
        if not colony:
            raise HTTPException(404, "Base not found")
        kind = kind if kind in ("building", "defense") else "building"
        if kind == "defense":
            row = db.query(Defense).filter(
                Defense.colony_id == colony.id, Defense.defense_type == type_key).first()
            name = get_effective_defense_spec(db, type_key).get("name", type_key)
        else:
            row = db.query(Building).filter(
                Building.colony_id == colony.id, Building.building_type == type_key).first()
            name = get_effective_building_spec(db, type_key).get("name", type_key)
        level = row.level if row else 0

        levels = []
        for lvl in range(1, level + 1):
            refund = structure_refund_value(db, kind, type_key, lvl, lvl - 1)
            build_cost = refund / STRUCTURE_DOWNGRADE_REFUND_PERCENT if STRUCTURE_DOWNGRADE_REFUND_PERCENT else refund
            levels.append({"level": lvl, "build_cost": round(build_cost), "refund": round(refund)})

        pending = db.query(ConstructionQueue).filter(
            ConstructionQueue.colony_id == colony.id,
            ConstructionQueue.item_category == kind,
            ConstructionQueue.item_type == type_key).first()
        blocked = bool(pending) or getattr(row, "is_constructing", False)

        return {
            "name": name, "kind": kind, "type": type_key, "level": level,
            "levels": levels,
            "one_level_refund": round(structure_refund_value(db, kind, type_key, level, level - 1)) if level > 0 else 0,
            "full_refund": round(structure_refund_value(db, kind, type_key, level, 0)) if level > 0 else 0,
            "refund_percent": STRUCTURE_DOWNGRADE_REFUND_PERCENT,
            "blocked": blocked,
            "base_reserve": round(getattr(user, "base_reserve", 0.0) or 0.0),
        }

    # ======================== ABANDON ========================

    @app.post("/api/bases/{base_id}/abandon")
    def abandon_base(base_id: int, token: str = Depends(get_token_from_header), db: Session = Depends(get_db)):
        user = get_current_user(token, db)
        colony = db.query(Colony).filter(Colony.id == base_id, Colony.user_id == user.id).first()
        if not colony:
            raise HTTPException(404, "Base not found")
        if len(user.colonies) <= 1:
            raise HTTPException(400, "Cannot abandon your last base")
        # Remember peak base count so the rebuild discount applies after disbanding.
        user.bases_founded_peak = max(getattr(user, "bases_founded_peak", 0) or 0, len(user.colonies))
        # Remove all associated data
        planet = colony.planet
        # Refund 50% of every structure's build cost into the base reserve.
        reserve_gain = 0.0
        for b in db.query(Building).filter(Building.colony_id == colony.id).all():
            if b.level > 0:
                reserve_gain += structure_refund_value(db, "building", b.building_type, b.level, 0)
        for d in db.query(Defense).filter(Defense.colony_id == colony.id).all():
            if d.level > 0:
                reserve_gain += structure_refund_value(db, "defense", d.defense_type, d.level, 0)
        if reserve_gain > 0:
            user.base_reserve = (user.base_reserve or 0.0) + reserve_gain
        db.query(Defense).filter(Defense.colony_id == colony.id).delete()
        db.query(Building).filter(Building.colony_id == colony.id).delete()
        db.query(ConstructionQueue).filter(ConstructionQueue.colony_id == colony.id).delete()
        db.query(ResearchQueue).filter(ResearchQueue.colony_id == colony.id).delete()
        db.query(ShipQueue).filter(ShipQueue.colony_id == colony.id).delete()
        # Unassign commanders stationed here
        from models import Commander
        for cmdr in db.query(Commander).filter(Commander.colony_id == colony.id).all():
            cmdr.colony_id = None
            cmdr.is_assigned = False
        # Move fleets stationed here to homeless (location_planet_id)
        for f in db.query(Fleet).filter(Fleet.base_id == colony.id).all():
            f.base_id = None
            f.location_planet_id = planet.id if planet else None
        # Remove trade routes
        db.query(TradeRoute).filter((TradeRoute.base_a_id == colony.id) | (TradeRoute.base_b_id == colony.id)).delete()
        db.delete(colony)
        if planet:
            planet.is_colonized = False
        log_event(db, user.id, "colonize",
                  f"Abandoned base at {planet.name if planet else 'unknown'}"
                  + (f" (+{int(reserve_gain)} to base reserve)" if reserve_gain > 0 else ""))
        db.commit()
        return {"success": True, "reserve_gain": round(reserve_gain), "base_reserve": round(user.base_reserve or 0.0)}

    # ======================== EMPIRE ECONOMY ========================

    @app.get("/api/empire/economy")
    def empire_economy(token: str = Depends(get_token_from_header), db: Session = Depends(get_db)):
        user = get_current_user(token, db)
        game_speed = get_config_float(db, "game_speed", 1.0)
        collect_resources(user, db, game_speed)

        # Bases economy table
        bases_econ = []
        total_economy = 0
        total_income = 0
        for colony in user.colonies:
            stats = calc_base_stats(colony, user, game_speed)
            econ = stats["economy"]
            penalty = getattr(colony, 'economy_penalty', 0) or 0
            econ_max = econ + int(penalty * game_speed)
            income = econ  # economy rate already includes game_speed
            occupier_name = colony.occupier.username if colony.occupied_by else None
            # Pillage info
            pillage_str = ""
            if colony.last_pillaged:
                hours_since = (datetime.utcnow() - colony.last_pillaged).total_seconds() / 3600.0
                pillage_str = f"{int(hours_since)}h ago"
            bases_econ.append({
                "id": colony.id,
                "name": colony.name,
                "coords": colony.planet.name if colony.planet else "",
                "economy": econ,
                "economy_max": econ_max,
                "pillage": pillage_str,
                "occupier": occupier_name,
                "income": round(income, 1),
            })
            total_economy += econ
            total_income += income

        # Occupied bases (bases this player occupies)
        occupied = db.query(Colony).filter(Colony.occupied_by == user.id).all()
        occupied_bases = []
        total_occ_income = 0
        for colony in occupied:
            owner = colony.user
            stats = calc_base_stats(colony, owner, game_speed)
            econ = stats["economy"]
            penalty = getattr(colony, 'economy_penalty', 0) or 0
            econ_max = econ + int(penalty * game_speed)
            rate = econ  # economy rate already includes game_speed
            occ_income = round(rate * OCCUPIER_INCOME_SHARE, 1)
            occupied_bases.append({
                "id": colony.id,
                "name": colony.name,
                "coords": colony.planet.name if colony.planet else "",
                "owner": owner.username,
                "economy": econ,
                "economy_max": econ_max,
                "income": occ_income,
            })
            total_occ_income += occ_income

        # CC capacity
        total_cc = sum(get_building_level(c, "command_centers") for c in user.colonies)

        # Trade routes
        trade_routes = db.query(TradeRoute).filter(
            TradeRoute.owner_id == user.id, TradeRoute.is_closing == False
        ).all()
        total_trade_income = sum(tr.income * game_speed for tr in trade_routes)

        # Capital occupied penalty: -15% empire income
        capital_penalty_active = is_capital_occupied(user)
        raw_empire_income = total_income + total_occ_income + total_trade_income
        if capital_penalty_active:
            effective_empire_income = raw_empire_income * (1 - CAPITAL_OCCUPIED_PENALTY)
        else:
            effective_empire_income = raw_empire_income

        return {
            "bases": bases_econ,
            "occupied_bases": occupied_bases,
            "summary": {
                "base_count": len(user.colonies),
                "base_income": round(total_income, 1),
                "occupied_count": len(occupied),
                "max_occupied": total_cc,
                "occupied_income": round(total_occ_income, 1),
                "trade_count": len(trade_routes),
                "trade_income": round(total_trade_income, 1),
                "total_economy": total_economy,
                "empire_income": round(effective_empire_income, 1),
                "capital_penalty": capital_penalty_active,
                "capital_penalty_pct": int(CAPITAL_OCCUPIED_PENALTY * 100),
            },
        }
