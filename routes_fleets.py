from fastapi import HTTPException, Depends, Query
from sqlalchemy.orm import Session
from sqlalchemy import or_
from datetime import datetime, timedelta
from models import (User, Colony, Building, Defense, Fleet, ShipQueue, Planet, BattleReport, Galaxy, Region, StarSystem, TradeRoute, Message, Wormhole)
from auth import (get_token_from_header, get_current_user, get_config, get_config_float, get_config_int, get_db,
                  get_effective_ship_spec, is_ship_disabled,
                  is_defense_disabled, get_effective_research_spec, get_effective_building_spec,
                  is_building_disabled, get_all_building_specs, get_all_defense_specs, log_event, log_credits, log_fleet_change,
                  fleet_capability_ship, ships_with_capability)
from resources import can_afford, deduct_cost, add_resources, format_cost, total_cost_value, scale_cost, round_cost
from game_logic import (calc_base_stats, calc_economy_rate, collect_resources,
                        _process_fleet_arrivals, _process_ship_queues, _ship_build_time,
                        resolve_battle, _fleet_ship_counts, _fleet_total_ships,
                        _fleet_value, calc_max_fleet_size, calc_max_fleet_count,
                        check_hangar_capacity, get_building_level, get_tech_level,
                        _record_region_snapshot, _update_unrest, _fleet_is_empty,
                        calc_player_level, calc_colony_cost, apply_colony_reserve)
from specs import SHIP_SPECS, ALL_SHIP_TYPES, DEFENSE_SPECS, GOODS_SPEC
from config_defaults import *
from typing import Optional
import json
from combat_locks import acquire_combat_lock, CombatLockBusy, combat_location_lock_key
from fleet_schemas import BuildShipRequest, FleetSend, FleetAttack, ColonizeRequest
from fleet_travel_helpers import _calc_fleet_travel
import action_points
from fleet_attack_helpers import (
    _get_attack_location,
    _build_attack_targets,
    _find_attack_target,
    _build_attack_confirm_preview,
    _resolve_fleet_battle,
)


# Fleet travel, request schemas, and attack preview helpers live in dedicated
# modules so this file can stay focused on the route handlers themselves.
def register_fleet_routes(app):

    # ======================== FLEETS ========================

    @app.get("/api/fleets")
    def get_fleets(token: str = Depends(get_token_from_header), db: Session = Depends(get_db)):
        user = get_current_user(token, db)
        game_speed = get_config_float(db, "game_speed", 1.0)
        _process_fleet_arrivals(user, db)
        _process_ship_queues(user, db, game_speed)

        result = []
        # Capability-derived ship keys (data-driven, not hard-coded roster keys),
        # resolved once per request and matched per fleet below.
        _colonizer_keys = ships_with_capability(db, "can_colonize")
        _autoscout_keys = ships_with_capability(db, "can_autoscout")
        _recycle_keys = ships_with_capability(db, "can_recycle")

        def _present_key(fl, keys):
            """First capability ship key actually present in the fleet, else ''."""
            for k in keys:
                if fl.get_ship_count(k) > 0:
                    return k
            return ""

        for fleet in user.fleets:
            ships = _fleet_ship_counts(fleet)
            total = _fleet_total_ships(fleet)
            base_name = ""
            base_owner = ""
            base_is_mine = True
            if fleet.base_id:
                base = db.query(Colony).filter(Colony.id == fleet.base_id).first()
                if base:
                    base_name = base.name
                    base_owner = base.user.username
                    base_is_mine = base.user_id == user.id

            dest_name = ""
            dest_coords = ""
            if fleet.destination_base_id:
                dest = db.query(Colony).filter(Colony.id == fleet.destination_base_id).first()
                if dest:
                    dest_name = dest.name
                    if dest.planet:
                        dest_coords = dest.planet.name
            elif fleet.destination_planet_id:
                dp = db.query(Planet).filter(Planet.id == fleet.destination_planet_id).first()
                if dp:
                    dest_name = dp.name + " (uncolonized)"
                    dest_coords = dp.name

            # Fleet at uncolonized planet (only when no base)
            location_name = ""
            if fleet.location_planet_id and not fleet.base_id:
                lp = db.query(Planet).filter(Planet.id == fleet.location_planet_id).first()
                if lp:
                    location_name = lp.name + " (uncolonized)"

            # Determine location coords
            location_coords = ""
            if fleet.base_id:
                base_obj = db.query(Colony).filter(Colony.id == fleet.base_id).first()
                if base_obj and base_obj.planet:
                    location_coords = base_obj.planet.name
            elif fleet.location_planet_id:
                lp2 = db.query(Planet).filter(Planet.id == fleet.location_planet_id).first()
                if lp2:
                    location_coords = lp2.name

            # Hangar info
            hangar_info = check_hangar_capacity(fleet, db)

            # Capability ships present in this fleet (key, or '' if none). The UI
            # filters/labels off these instead of hard-coded roster keys.
            colonizer_ship = _present_key(fleet, _colonizer_keys)
            autoscout_ship = _present_key(fleet, _autoscout_keys)
            recycle_ship = _present_key(fleet, _recycle_keys)
            has_outpost = bool(colonizer_ship)

            # Detection time (for overview display)
            fleet_size = _fleet_value(fleet, db)
            stealth_level = get_tech_level(user, "stealth")
            det_hours = DETECTION_HOURS_CAP * (-DETECTION_SENSOR_BASE / (fleet_size * DETECTION_FLEET_SIZE_MULT * (DETECTION_STEALTH_BASE ** stealth_level) + DETECTION_SENSOR_BASE) + 1) + DETECTION_MIN_HOURS
            det_hours = max(DETECTION_MIN_HOURS, min(DETECTION_MAX_HOURS, det_hours))
            detection_time = round(det_hours * 3600)

            result.append({
                "id": fleet.id,
                "name": fleet.name,
                "base_id": fleet.base_id,
                "base_name": base_name,
                "base_owner": base_owner,
                "base_is_mine": base_is_mine,
                "location_planet_id": fleet.location_planet_id,
                "location_name": location_name,
                "location_coords": location_coords,
                "ships": ships,
                "total_ships": total,
                "is_moving": fleet.is_moving,
                "destination_name": dest_name,
                "destination_coords": dest_coords,
                "arrival_time": fleet.arrival_time.isoformat() if fleet.arrival_time else None,
                "value": round(fleet_size),
                "detection_time": detection_time,
                "hangar_available": hangar_info.get("available", 0),
                "hangar_needed": hangar_info.get("needed", 0),
                "has_outpost": has_outpost,
                "colonizer_ship": colonizer_ship,
                "autoscout_ship": autoscout_ship,
                "recycle_ship": recycle_ship,
                "auto_recycle": fleet.auto_recycle if fleet.auto_recycle is not None else True,
                "guild_hidden_until": fleet.guild_hidden_until.isoformat() if fleet.guild_hidden_until and fleet.guild_hidden_until > datetime.utcnow() else None,
                "is_autoscout": fleet.is_autoscout or False,
                "autoscout_galaxy": db.query(Galaxy).filter(Galaxy.id == fleet.autoscout_galaxy_id).first().name if fleet.is_autoscout and fleet.autoscout_galaxy_id else None,
                "ship_damage": json.loads(fleet.ship_damage or "{}"),
                "sort_order": fleet.sort_order or 0,
            })
        result.sort(key=lambda f: (f["sort_order"], f["id"]))
        return result

    @app.post("/api/fleets/build")
    def build_ships(req: BuildShipRequest, token: str = Depends(get_token_from_header), db: Session = Depends(get_db)):
        user = get_current_user(token, db)
        game_speed = get_config_float(db, "game_speed", 1.0)
        collect_resources(user, db, game_speed)
        _process_ship_queues(user, db, game_speed)

        colony = db.query(Colony).filter(Colony.id == req.base_id, Colony.user_id == user.id).first()
        if not colony:
            raise HTTPException(404, "Base not found")

        is_goods = req.ship_type == "goods"
        if is_goods:
            ship_spec = GOODS_SPEC
        else:
            ship_spec = get_effective_ship_spec(db, req.ship_type)
            if not ship_spec:
                raise HTTPException(400, "Invalid ship type")
            if is_ship_disabled(db, req.ship_type):
                raise HTTPException(400, f"{ship_spec['name']} has been disabled by the server admin")

        # Check shipyard level (ground + orbital)
        stats = calc_base_stats(colony, user, game_speed)
        shipyard_level = stats["shipyard_level"]
        req_shipyard = ship_spec.get("shipyard", 0)
        if shipyard_level < req_shipyard:
            raise HTTPException(400, f"Need Shipyard level {req_shipyard} (have {shipyard_level})")

        # Check tech requirements (Goods have none)
        for tech, level_needed in ship_spec.get("req", {}).items():
            if get_tech_level(user, tech) < level_needed:
                tech_name = get_effective_research_spec(db, tech).get("name", tech)
                raise HTTPException(400, f"Requires {tech_name} level {level_needed}")

        # Fleet size limit (skip for Goods â€” they don't go into fleet)
        if not is_goods:
            current_fleet_size = sum(_fleet_value(f, db) for f in user.fleets)
            max_fleet = calc_max_fleet_size(user, game_speed)
            new_fleet_value = total_cost_value(ship_spec["cost"]) * req.count
            if current_fleet_size + new_fleet_value > max_fleet and max_fleet > 0:
                raise HTTPException(400, f"Fleet limit reached ({int(current_fleet_size)}/{max_fleet}). Increase production to support more ships.")

        # Check production queue size (engine flag; defaults to constant)
        queue_max = get_config_int(db, "production_queue_max", PRODUCTION_QUEUE_MAX)
        base_queue = (db.query(ShipQueue)
                      .filter(ShipQueue.colony_id == colony.id, ShipQueue.user_id == user.id)
                      .order_by(ShipQueue.position).all())
        if len(base_queue) >= queue_max:
            raise HTTPException(400, f"Production queue full (max {queue_max} items per base)")

        # Cost (fast production = +40% cost) â€” always deducted immediately
        cost_mult = 1.4 if req.fast_production else 1.0
        total_cost = scale_cost(ship_spec["cost"], req.count * cost_mult)
        if not can_afford(user, total_cost):
            raise HTTPException(400, f"Need {format_cost(total_cost)} credits")

        position = len(base_queue)

        # Production time: total_time = (cost_per_ship * count) / production hours
        # Fast production = half the time
        time_mult = 0.5 if req.fast_production else 1.0
        per_ship_time = _ship_build_time(req.ship_type, colony, user, game_speed, db) * time_mult
        total_time = per_ship_time * req.count

        now = datetime.utcnow()
        fp_label = " (fast)" if req.fast_production else ""

        # Credits always deducted upfront for production
        action_points.debit_action_points(user, db, "ship_build")
        deduct_cost(user, total_cost)
        log_credits(db, user.id, -total_cost_value(total_cost), f"Production of {req.count} {ship_spec.get('name', req.ship_type)} at {colony.name}{fp_label}", "production")

        if position == 0:
            started_at = now
            finish_at = now + timedelta(seconds=total_time)
            log_event(db, user.id, "construction",
                      f"Started building {req.count}x {ship_spec['name']} at {colony.name} ({int(total_time)}s)")
        else:
            started_at = None
            finish_at = None
            log_event(db, user.id, "construction",
                      f"Queued {req.count}x {ship_spec['name']} at {colony.name} (position {position + 1})")

        queue_item = ShipQueue(
            colony_id=colony.id,
            user_id=user.id,
            ship_type=req.ship_type,
            count=req.count,
            built=0,
            position=position,
            cost=total_cost,
            started_at=started_at,
            next_complete=finish_at,
        )
        db.add(queue_item)
        db.commit()
        return {
            "success": True, "ship_type": req.ship_type, "count": req.count,
            "cost": round_cost(total_cost, 1),
            "time_each": round(per_ship_time),
            "total_time": round(total_time),
            "completes_at": finish_at.isoformat() if finish_at else None,
            "queued": position > 0, "queue_position": position + 1,
        }


    @app.get("/api/ship-queue")
    def get_ship_queue(token: str = Depends(get_token_from_header), db: Session = Depends(get_db)):
        """Get all active ship build queues for the current player."""
        user = get_current_user(token, db)
        game_speed = get_config_float(db, "game_speed", 1.0)
        _process_ship_queues(user, db, game_speed)
        queues = (db.query(ShipQueue)
                  .filter(ShipQueue.user_id == user.id)
                  .order_by(ShipQueue.colony_id, ShipQueue.position).all())
        result = []
        for q in queues:
            colony = db.query(Colony).filter(Colony.id == q.colony_id).first()
            ship_name = GOODS_SPEC["name"] if q.ship_type == "goods" else get_effective_ship_spec(db, q.ship_type).get("name", q.ship_type)
            result.append({
                "id": q.id,
                "base_id": q.colony_id,
                "base_name": colony.name if colony else "?",
                "ship_type": q.ship_type,
                "ship_name": ship_name,
                "count": q.count,
                "built": q.built,
                "remaining": q.count - q.built,
                "position": getattr(q, 'position', 0) or 0,
                "cost": round(getattr(q, 'cost', 0) or 0, 1),
                "next_complete": q.next_complete.isoformat() if q.next_complete else None,
                "started_at": q.started_at.isoformat() if q.started_at else None,
            })
        return result


    @app.delete("/api/ship-queue/{queue_id}")
    def cancel_ship_queue(queue_id: int, token: str = Depends(get_token_from_header), db: Session = Depends(get_db)):
        """Cancel a ship build queue. Refund credits if item was active (paid)."""
        user = get_current_user(token, db)
        game_speed = get_config_float(db, "game_speed", 1.0)
        _process_ship_queues(user, db, game_speed)
        item = db.query(ShipQueue).filter(ShipQueue.id == queue_id, ShipQueue.user_id == user.id).first()
        if not item:
            raise HTTPException(404, "Build queue not found")
        position = getattr(item, 'position', 0) or 0
        base_id = item.colony_id
        # Always refund â€” credits are deducted upfront for production
        refund = getattr(item, 'cost', 0) or 0
        refund_value = total_cost_value(refund)
        ship_name = GOODS_SPEC["name"] if item.ship_type == "goods" else get_effective_ship_spec(db, item.ship_type).get('name', item.ship_type)
        if refund_value > 0:
            add_resources(user, refund)
            log_credits(db, user.id, refund_value, f"Cancelled {item.count}x {ship_name}", "production")
        log_event(db, user.id, "construction",
                  f"Cancelled {item.count}x {ship_name} â€” refunded {int(refund_value)} cr")
        db.delete(item)
        db.flush()
        # Re-number remaining queue items for this base
        remaining = (db.query(ShipQueue)
                     .filter(ShipQueue.colony_id == base_id, ShipQueue.user_id == user.id)
                     .order_by(ShipQueue.position).all())
        for i, q in enumerate(remaining):
            q.position = i
        # If we cancelled position 0 and there's a new first item, start it (already paid)
        if position == 0 and remaining:
            nxt = remaining[0]
            if nxt.started_at is None:
                ship_name = GOODS_SPEC["name"] if nxt.ship_type == "goods" else get_effective_ship_spec(db, nxt.ship_type).get('name', nxt.ship_type)
                colony = db.query(Colony).filter(Colony.id == base_id).first()
                per_ship_time = _ship_build_time(nxt.ship_type, colony, user, game_speed, db)
                total_time = per_ship_time * nxt.count
                now = datetime.utcnow()
                nxt.started_at = now
                nxt.next_complete = now + timedelta(seconds=total_time)
                log_event(db, user.id, "construction",
                          f"Started building {nxt.count}x {ship_name} at {colony.name if colony else '?'}")
        db.commit()
        return {"success": True, "refunded": round(refund_value)}

    @app.post("/api/fleets/send")
    def send_fleet(req: FleetSend, token: str = Depends(get_token_from_header), db: Session = Depends(get_db)):
        """Move fleet to any planet/astro.
        If req.ships is provided, only those ships move (partial send = auto-split + move).
        If req.ships is None, the entire fleet moves."""
        user = get_current_user(token, db)
        fleet = db.query(Fleet).filter(Fleet.id == req.fleet_id, Fleet.user_id == user.id).first()
        if not fleet:
            raise HTTPException(404, "Fleet not found")
        if fleet.is_moving:
            raise HTTPException(400, "Fleet is already moving")
        if _fleet_total_ships(fleet) == 0:
            raise HTTPException(400, "Fleet has no ships")
        # Damaged ships cannot move until repaired
        damage_state = json.loads(fleet.ship_damage or "{}")
        if damage_state:
            raise HTTPException(400, "Fleet has damaged ships â€” repair before moving")

        # Resolve destination: either planet_id or coordinate string
        if req.destination_coords:
            dest_planet = db.query(Planet).filter(Planet.name == req.destination_coords).first()
            if not dest_planet:
                raise HTTPException(404, f"No astro found at coordinates {req.destination_coords}")
        elif req.destination_planet_id:
            dest_planet = db.query(Planet).filter(Planet.id == req.destination_planet_id).first()
            if not dest_planet:
                raise HTTPException(404, "Destination planet not found")
        else:
            raise HTTPException(400, "Provide destination_planet_id or destination_coords")

        # Cannot land on gas giants or asteroid belts
        if dest_planet.planet_type in ("gas_giant", "asteroid_belt"):
            raise HTTPException(400, "Cannot land on gas giants or asteroid belts")

        # â”€â”€ Partial send: split selected ships into a new fleet, then send that â”€â”€
        moving_fleet = fleet
        if req.ships is not None:
            # Validate quantities
            total_selected = 0
            for st, qty in req.ships.items():
                if st not in ALL_SHIP_TYPES:
                    raise HTTPException(400, f"Invalid ship type: {st}")
                available = fleet.get_ship_count(st)
                if qty < 0 or qty > available:
                    raise HTTPException(400, f"Invalid quantity for {st}: {qty} (have {available})")
                total_selected += qty
            if total_selected == 0:
                raise HTTPException(400, "Select at least one ship to send")

            # Check if sending ALL ships (no need to split)
            all_ships = True
            for st in ALL_SHIP_TYPES:
                avail = fleet.get_ship_count(st)
                requested = req.ships.get(st, 0)
                if avail != requested and avail > 0:
                    all_ships = False
                    break

            if not all_ships:
                # Create new fleet with selected ships, deduct from original
                fleet_before = fleet.get_all_ship_counts()
                new_fleet = Fleet(
                    user_id=user.id,
                    name=fleet.name,
                    base_id=fleet.base_id,
                    location_planet_id=fleet.location_planet_id,
                )
                for st in ALL_SHIP_TYPES:
                    qty = req.ships.get(st, 0)
                    new_fleet.set_ship_count(st, qty)
                    if qty > 0:
                        fleet.set_ship_count(st, fleet.get_ship_count(st) - qty)
                db.add(new_fleet)
                db.flush()  # get new_fleet.id
                log_fleet_change(db, user.id, fleet, "split", fleet_before, f"Partial send â€” split to fleet {new_fleet.id}")
                log_fleet_change(db, user.id, new_fleet, "split", {}, f"Partial send from fleet {fleet.id}")
                moving_fleet = new_fleet

        # Check hangar capacity on the fleet that will actually move
        hangar = check_hangar_capacity(moving_fleet, db)
        if not hangar["ok"]:
            db.rollback()
            raise HTTPException(400, f"Need {hangar['needed']} hangar space but only have {hangar['available']}. Add ships with hangar space to transport carried ships.")

        # Determine origin planet for distance calc
        origin_planet = None
        if fleet.base_id:
            origin_base = db.query(Colony).filter(Colony.id == fleet.base_id).first()
            if origin_base:
                origin_planet = origin_base.planet
        elif fleet.location_planet_id:
            origin_planet = db.query(Planet).filter(Planet.id == fleet.location_planet_id).first()
        if not origin_planet:
            raise HTTPException(400, "Fleet has no origin location")

        game_speed = get_config_float(db, "game_speed", 1.0)

        # Graph map: a destination must be link-reachable from the origin system.
        import graph_map
        if graph_map.is_graph_map(db) and origin_planet.system_id != dest_planet.system_id:
            if not graph_map.reachable(origin_planet.system_id, dest_planet.system_id, db):
                db.rollback()
                raise HTTPException(400, "No route: that system isn't reachable over the link network.")

        trav = _calc_fleet_travel(moving_fleet, user, db, origin_planet, dest_planet, game_speed, use_jump_gate=req.use_jump_gate, use_wormhole=req.use_wormhole)
        if "error" in trav:
            db.rollback()
            raise HTTPException(400, trav["error"])
        travel_time = trav["travel_time"]
        if trav.get("wormhole_damage_pct"):
            import wormhole
            wormhole.apply_wormhole_damage(moving_fleet, trav["wormhole_damage_pct"])

        action_points.debit_action_points(user, db, "fleet_send")
        moving_fleet.is_moving = True
        moving_fleet.origin_base_id = fleet.base_id
        moving_fleet.origin_planet_id = origin_planet.id if origin_planet else None

        dest_colony = dest_planet.colony
        if dest_colony:
            moving_fleet.destination_base_id = dest_colony.id
            moving_fleet.destination_planet_id = dest_planet.id  # fallback if colony abandoned mid-flight
            dest_name = dest_colony.name
        else:
            moving_fleet.destination_base_id = None
            moving_fleet.destination_planet_id = dest_planet.id
            dest_name = dest_planet.name

        moving_fleet.arrival_time = datetime.utcnow() + timedelta(seconds=travel_time)
        moving_fleet.base_id = None
        moving_fleet.location_planet_id = None
        log_event(db, user.id, "fleet", f"Fleet '{moving_fleet.name}' sent to {dest_name} (ETA: {round(travel_time)}s)")
        db.commit()

        return {
            "success": True,
            "travel_time": round(travel_time),
            "arrival": moving_fleet.arrival_time.isoformat(),
            "destination": dest_name,
        }

    @app.get("/api/fleets/{fleet_id}/estimate")
    def estimate_travel(fleet_id: int, coords: str = Query(None), planet_id: int = Query(None),
                        drive_override: int = Query(None), use_jump_gate: bool = Query(False),
                        use_wormhole: bool = Query(False),
                        token: str = Depends(get_token_from_header), db: Session = Depends(get_db)):
        """Estimate travel time without actually sending the fleet.
        drive_override: optional tech level to use instead of player's actual level."""
        user = get_current_user(token, db)
        fleet = db.query(Fleet).filter(Fleet.id == fleet_id, Fleet.user_id == user.id).first()
        if not fleet:
            raise HTTPException(404, "Fleet not found")

        if coords:
            dest_planet = db.query(Planet).filter(Planet.name == coords).first()
            if not dest_planet:
                raise HTTPException(404, f"No astro at {coords}")
        elif planet_id:
            dest_planet = db.query(Planet).filter(Planet.id == planet_id).first()
            if not dest_planet:
                raise HTTPException(404, "Planet not found")
        else:
            raise HTTPException(400, "Provide coords or planet_id")

        origin_planet = None
        if fleet.base_id:
            origin_base = db.query(Colony).filter(Colony.id == fleet.base_id).first()
            if origin_base:
                origin_planet = origin_base.planet
        elif fleet.location_planet_id:
            origin_planet = db.query(Planet).filter(Planet.id == fleet.location_planet_id).first()
        if not origin_planet:
            raise HTTPException(400, "Fleet has no origin")

        game_speed = get_config_float(db, "game_speed", 1.0)

        trav = _calc_fleet_travel(fleet, user, db, origin_planet, dest_planet, game_speed, drive_override, use_jump_gate=use_jump_gate, use_wormhole=use_wormhole)
        if "error" in trav:
            raise HTTPException(400, trav["error"])
        travel_time = trav["travel_time"]
        if trav.get("wormhole_damage_pct"):
            import wormhole
            wormhole.apply_wormhole_damage(fleet, trav["wormhole_damage_pct"])

        # Detected-in-before-arrival formula
        fleet_size = _fleet_value(fleet, db)
        stealth_level = get_tech_level(user, "stealth")
        det_hours = DETECTION_HOURS_CAP * (-DETECTION_SENSOR_BASE / (fleet_size * DETECTION_FLEET_SIZE_MULT * (DETECTION_STEALTH_BASE ** stealth_level) + DETECTION_SENSOR_BASE) + 1) + DETECTION_MIN_HOURS
        det_hours = max(DETECTION_MIN_HOURS, min(DETECTION_MAX_HOURS, det_hours))
        detected_in = round(det_hours * 3600)
        if detected_in > travel_time:
            detected_in = round(travel_time)

        return {
            "distance": round(trav["distance"], 2),
            "speed": round(trav["min_speed"], 1),
            "travel_time": round(travel_time),
            "destination": dest_planet.name,
            "ship_speeds": trav["ship_speeds"],
            "drive_types": sorted(trav["drive_types"]),
            "stellar_level": trav["stellar_level"],
            "warp_level": trav["warp_level"],
            "detected_in": detected_in,
            "jg_available": trav["jg_available"],
            "jg_level": trav["jg_level"],
            "wh_available": trav["wh_available"],
        }

    @app.post("/api/fleets/recall")
    def recall_fleet(fleet_id: int = Query(...), token: str = Depends(get_token_from_header), db: Session = Depends(get_db)):
        user = get_current_user(token, db)
        fleet = db.query(Fleet).filter(Fleet.id == fleet_id, Fleet.user_id == user.id).first()
        if not fleet:
            raise HTTPException(404, "Fleet not found")
        if not fleet.is_moving:
            raise HTTPException(400, "Fleet is not moving")

        # Swap origin and destination
        old_origin = fleet.origin_base_id
        old_origin_planet = fleet.origin_planet_id
        if not old_origin and not old_origin_planet:
            raise HTTPException(400, "Fleet has no origin to recall to")
        action_points.debit_action_points(user, db, "fleet_recall")
        fleet.destination_base_id = old_origin
        fleet.destination_planet_id = None
        if not old_origin and old_origin_planet:
            fleet.destination_planet_id = old_origin_planet
        fleet.origin_base_id = None
        fleet.origin_planet_id = None
        # Halve remaining travel time
        if fleet.arrival_time:
            remaining = (fleet.arrival_time - datetime.utcnow()).total_seconds()
            fleet.arrival_time = datetime.utcnow() + timedelta(seconds=max(10, remaining * 0.5))
        db.commit()
        return {"success": True}

    @app.get("/api/fleets/{fleet_id}/attack-preview")
    def attack_preview(
        fleet_id: int,
        target_user_id: Optional[int] = Query(None),
        target_fleet_id: Optional[int] = Query(None),
        attack_mode: Optional[str] = Query(None),
        token: str = Depends(get_token_from_header),
        db: Session = Depends(get_db)
    ):
        """Return either the target list or a target-specific confirm preview."""
        user = get_current_user(token, db)
        fleet = db.query(Fleet).filter(Fleet.id == fleet_id, Fleet.user_id == user.id).first()
        if not fleet:
            raise HTTPException(404, "Fleet not found")
        if fleet.is_moving:
            raise HTTPException(400, "Fleet is still in transit")

        game_speed = get_config_float(db, "game_speed", 1.0)
        colony, planet, location_name, coords = _get_attack_location(fleet, db)
        target_data = _build_attack_targets(fleet, user, db, game_speed, colony, planet, location_name, coords)

        if target_user_id is not None or target_fleet_id is not None or attack_mode is not None:
            selected_target = _find_attack_target(target_data["targets"], target_user_id, target_fleet_id, attack_mode)
            if not selected_target:
                raise HTTPException(404, "Attack target not found")
            if selected_target.get("can_attack") is False:
                raise HTTPException(400, selected_target.get("reason") or "Cannot attack this target")
            defender = db.query(User).filter(User.id == selected_target["player_id"]).first()
            if not defender:
                raise HTTPException(404, "Target player not found")
            return _build_attack_confirm_preview(
                fleet, user, defender, colony, planet, location_name, coords, game_speed, db, selected_target
            )

        return target_data

    @app.post("/api/fleets/attack")
    def attack_fleet(req: FleetAttack, token: str = Depends(get_token_from_header), db: Session = Depends(get_db)):
        """Attack a specific player at your fleet's location.
        - If targeting the base owner's fleet: full battle (that fleet + defenses), level protection applies
        - If targeting visiting fleets: fleet-vs-fleet only, no level protection
        - Fleets away from their own bases have no level protection"""
        user = get_current_user(token, db)
        user_id = user.id
        fleet = db.query(Fleet).filter(Fleet.id == req.fleet_id, Fleet.user_id == user.id).first()
        if not fleet:
            raise HTTPException(404, "Fleet not found")
        if fleet.is_moving:
            raise HTTPException(400, "Fleet is still in transit")
        if _fleet_total_ships(fleet) == 0:
            raise HTTPException(400, "Fleet has no ships")

        game_speed = get_config_float(db, "game_speed", 1.0)
        now = datetime.utcnow()

        colony, planet, location_name, coords = _get_attack_location(fleet, db)
        if not planet:
            raise HTTPException(400, "Fleet has no valid combat location")
        try:
            acquire_combat_lock(db, combat_location_lock_key(planet.id))
        except CombatLockBusy:
            raise HTTPException(409, "Another combat is already being resolved at this location. Please try again in a moment.")

        db.expire_all()
        user = db.query(User).filter(User.id == user_id).first()
        if not user:
            raise HTTPException(404, "User not found")
        fleet = db.query(Fleet).filter(Fleet.id == req.fleet_id, Fleet.user_id == user_id).first()
        if not fleet:
            raise HTTPException(404, "Fleet not found")
        if fleet.is_moving:
            raise HTTPException(400, "Fleet is still in transit")
        if _fleet_total_ships(fleet) == 0:
            raise HTTPException(400, "Fleet has no ships")
        game_speed = get_config_float(db, "game_speed", 1.0)
        now = datetime.utcnow()
        colony, planet, location_name, coords = _get_attack_location(fleet, db)
        target_data = _build_attack_targets(fleet, user, db, game_speed, colony, planet, location_name, coords)
        selected_target = _find_attack_target(target_data["targets"], req.target_user_id, req.target_fleet_id, req.attack_mode)
        if not selected_target and req.target_user_id is None and req.target_fleet_id is None and req.attack_mode is None and len(target_data["targets"]) == 1:
            selected_target = target_data["targets"][0]
        if not selected_target:
            raise HTTPException(404, "Attack target not found")
        if selected_target.get("can_attack") is False:
            raise HTTPException(400, selected_target.get("reason") or "Cannot attack this target")

        defender = db.query(User).filter(User.id == selected_target["player_id"]).first()
        if not defender:
            raise HTTPException(404, "Target player not found")

        if defender.id == user.id:
            raise HTTPException(400, "Cannot attack yourself")
        attacker_is_npc_faction = bool(user.is_bot and user.bot_strategy in ("settlers", "raiders"))
        defender_is_npc_faction = bool(defender.is_bot and defender.bot_strategy in ("settlers", "raiders"))

        # Guild members cannot attack each other
        from models import GuildMember
        atk_guild = db.query(GuildMember).filter(GuildMember.user_id == user.id).first()
        def_guild = db.query(GuildMember).filter(GuildMember.user_id == defender.id).first()
        if atk_guild and def_guild and atk_guild.guild_id == def_guild.guild_id:
            raise HTTPException(400, "Cannot attack a member of your own guild")

        selected_attack_mode = selected_target.get("attack_mode") or req.attack_mode or (
            "base" if selected_target.get("uses_defenses") else "fleet"
        )

        # Attacking the base owner's row or the base buttons pulls defenses in; visiting fleets never do.
        attacking_base_owner = bool(colony and colony.user_id == defender.id)
        defended_battle = bool(attacking_base_owner and selected_attack_mode in ("base", "conquer", "destroy_moon"))
        conquer_attack = selected_attack_mode == "conquer"
        destroy_moon_attack = selected_attack_mode == "destroy_moon"
        if destroy_moon_attack:
            from game_definition import get_game_definition
            from auth import ships_with_capability
            if not (get_game_definition().get("engine", {}) or {}).get("moon_destruction"):
                raise HTTPException(400, "Moon destruction is not enabled in this game")
            if not colony or not colony.planet or (colony.planet.orbit_row or 0) == 0:
                raise HTTPException(400, "Target is not a moon")
            if not any(fleet.get_ship_count(k) for k in ships_with_capability(db, "can_destroy_moons")):
                raise HTTPException(400, "Fleet has no ships capable of destroying moons")

        # Level protection only applies when the defender is being attacked on their own base.
        defender_at_own_base = defended_battle

        # Level-based protection: only applies when attacking a player's own base.
        # NPC bases are intentional public targets and still give XP.
        if defender_at_own_base and not defender_is_npc_faction:
            attacker_level = calc_player_level(user, db, game_speed)
            defender_level = calc_player_level(defender, db, game_speed)

            # Attacking someone on your own base (e.g. occupier) = always allowed
            is_defending_own_base = (colony and colony.occupied_by == user.id) or any(
                c.planet_id == colony.planet_id for c in user.colonies
            ) if colony else False

            if not is_defending_own_base:
                # Check defender protection
                defender_protected = defender_level < NEWBIE_PROTECTION_LEVEL
                if defender.protection_broken_until and defender.protection_broken_until > now:
                    defender_protected = False
                if defender_protected:
                    raise HTTPException(400, f"Target player is under level {NEWBIE_PROTECTION_LEVEL} (level {defender_level:.1f}) and has protection")

                # Check attacker protection
                attacker_protected = attacker_level < NEWBIE_PROTECTION_LEVEL
                if user.protection_broken_until and user.protection_broken_until > now:
                    attacker_protected = False
                if attacker_protected:
                    raise HTTPException(400, f"You are under level {NEWBIE_PROTECTION_LEVEL} (level {attacker_level:.1f}) and still have protection")

                # Level range check
                min_target = attacker_level * 2 / 3
                max_target = attacker_level * 3 / 2

                if defender_level < min_target:
                    raise HTTPException(400, f"Target is level {defender_level:.1f} â€” too weak to attack (minimum: {min_target:.1f}, your level: {attacker_level:.1f})")

                if defender_level > max_target:
                    user.protection_broken_until = now + timedelta(hours=PROTECTION_BROKEN_HOURS)
                    log_event(db, user.id, "protection", f"Protection broken for {PROTECTION_BROKEN_HOURS}h by attacking level {defender_level:.1f} player (your level: {attacker_level:.1f})")

        attack_base_target = defended_battle

        # Full battle (with defenses) only when hitting the base owner's defended row.
        if defended_battle:
            if conquer_attack:
                _update_unrest(colony, db)
                if colony.unrest >= 0.5:
                    raise HTTPException(400, "Base unrest is too high (â‰¥50%) â€” cannot be attacked for occupation")
            action_points.debit_action_points(user, db, "fleet_conquer" if conquer_attack else "fleet_attack")
            report = resolve_battle(
                fleet,
                user,
                colony,
                defender,
                game_speed,
                db,
                target_fleet_id=None,
            )
        else:
            # Fleet-vs-fleet only: resolve without base defenses
            action_points.debit_action_points(user, db, "fleet_conquer" if conquer_attack else "fleet_attack")
            report = _resolve_fleet_battle(
                fleet,
                user,
                defender,
                colony,
                game_speed,
                db,
                target_fleet_id=selected_target.get("fleet_id"),
            )

        # Pillage/occupation belong to the conquer path, not the plain base-assault path.
        pillage_credits = 0
        additional_pillage = 0
        if conquer_attack and attack_base_target and defended_battle and report.get("result") == "attacker_wins":
            base_econ = calc_economy_rate(colony, defender, game_speed)
            owner_base_count = len(defender.colonies)
            pillage_cooldown_hours = max(0.0, get_config_float(db, "PILLAGE_COOLDOWN_HOURS", PILLAGE_COOLDOWN_HOURS))
            pillage_max_hours = max(1.0, get_config_float(db, "PILLAGE_MAX_HOURS", PILLAGE_MAX_HOURS))
            pillage_economy_mult = get_config_float(db, "PILLAGE_ECONOMY_MULT", PILLAGE_ECONOMY_MULT)
            pillage_npc_mult = get_config_float(db, "PILLAGE_NPC_MULT", PILLAGE_NPC_MULT)
            pillage_bonus_mult = get_config_float(db, "PILLAGE_ADDITIONAL_BONUS_MULT", PILLAGE_ADDITIONAL_BONUS_MULT)
            occupier_income_share = max(0.0, min(1.0, get_config_float(db, "OCCUPIER_INCOME_SHARE", OCCUPIER_INCOME_SHARE)))

            hours_since = None
            if colony.last_pillaged:
                hours_since = (now - colony.last_pillaged).total_seconds() / 3600.0

            if hours_since is not None and hours_since < pillage_cooldown_hours:
                # 24h cooldown between pillages.
                pillage_credits = 0
            elif defender_is_npc_faction:
                # NPC base: hours_since% * Base Economy * configured multiplier.
                pct = 1.0 if hours_since is None else min(hours_since, pillage_max_hours) / pillage_max_hours
                pillage_credits = pct * base_econ * pillage_npc_mult
            elif hours_since is None or hours_since >= pillage_max_hours:
                # Base not occupied/pillaged recently: 2 * Base Economy * owner's base count.
                pillage_credits = 2 * base_econ * max(owner_base_count, 1)
            else:
                # Base occupied/pillaged recently: hours_since% * Base Economy * configured multiplier.
                pct = min(hours_since, pillage_max_hours) / pillage_max_hours
                pillage_credits = pct * base_econ * pillage_economy_mult

            pillage_credits = round(pillage_credits)
            if pillage_credits > 0:
                deduct_cost(defender, pillage_credits)
                log_credits(db, defender.id, -pillage_credits, f"Pillaged by {user.username} at {colony.name}", "combat")
                add_resources(user, pillage_credits)
                log_credits(db, user.id, pillage_credits, f"Pillage of {colony.name}", "combat")
                colony.last_pillaged = now
                colony.unrest = min(1.0, colony.unrest + 0.1)
                report["pillage"] = pillage_credits
                report["pillage_base"] = pillage_credits

            if conquer_attack:
                remaining_owner_fleets = db.query(Fleet).filter(
                    Fleet.base_id == colony.id,
                    Fleet.user_id == defender.id,
                    Fleet.is_moving == False,
                ).all()
                if any(_fleet_total_ships(owner_fleet) > 0 for owner_fleet in remaining_owner_fleets):
                    report["occupied"] = False
                    report["occupation_blocked"] = "Other defending fleets remain at the base"
                else:
                    # Check command center capacity for occupation (1 occupation per CC level)
                    total_cc = sum(get_building_level(c, "command_centers") for c in user.colonies)
                    current_occupations = db.query(Colony).filter(Colony.occupied_by == user.id).count()
                    can_occupy = current_occupations < total_cc

                    if can_occupy:
                        income_before = base_econ

                        # Occupation
                        colony.occupied_by = user.id
                        colony.occupation_start = now
                        colony.defense_effectiveness = 0.0  # defenses set to 0% on occupation
                        # Economy penalty: 30% of economy lost to occupier, recovers 1 per 8h after liberation
                        base_stats = calc_base_stats(colony, defender)
                        colony.economy_penalty = round(base_stats["economy"] * occupier_income_share)
                        colony.last_economy_recovery = now
                        report["occupied"] = True

                        # Additional pillage bonus: (actual income - new income)^2 * multiplier.
                        # NOT deducted from base owner
                        income_after = income_before * (1 - occupier_income_share)
                        additional_pillage = round(
                            ((income_before - income_after) ** 2) * pillage_bonus_mult
                        )
                        if additional_pillage > 0:
                            add_resources(user, additional_pillage)
                            log_credits(db, user.id, additional_pillage, f"Additional pillage bonus at {colony.name}", "combat")

                        # Pillage closing trade routes: 50% of setup cost
                        trade_piracy = 0
                        pirated_routes = db.query(TradeRoute).filter(
                            or_(TradeRoute.base_a_id == colony.id, TradeRoute.base_b_id == colony.id),
                            TradeRoute.is_closing == True,
                        ).all()
                        for tr in pirated_routes:
                            value = round(tr.cost * 0.5)
                            trade_piracy += value
                            for uid in set(filter(None, [tr.owner_id, tr.partner_id])):
                                if uid != user.id:
                                    log_event(db, uid, "trade", f"Closing trade route at {colony.name} was pillaged by {user.username} (-{value} cr)")
                            db.delete(tr)
                        if trade_piracy > 0:
                            add_resources(user, trade_piracy)
                            log_credits(db, user.id, trade_piracy, f"Pirated trade routes at {colony.name}", "combat")

                        total_pillage = pillage_credits + additional_pillage + trade_piracy
                        report["pillage"] = total_pillage
                        report["pillage_base"] = pillage_credits
                        report["pillage_bonus"] = additional_pillage
                        report["trade_routes_pirated"] = len(pirated_routes)
                    else:
                        report["occupied"] = False
                        report["occupation_blocked"] = f"No Command Center capacity ({current_occupations}/{total_cc})"

        # Moon destruction attempt ("destroy" mission): only on a clear win at a
        # moon; both rolls (moon cracked / destroyers backfire) are independent.
        if destroy_moon_attack and defended_battle and report.get("result") == "attacker_wins":
            from combat import attempt_moon_destruction
            report["moon_destruction"] = attempt_moon_destruction(db, fleet, colony)
            if report["moon_destruction"]["destroyed"]:
                log_event(db, user.id, "attack", f"Destroyed the moon at {location_name}")
                log_event(db, defender.id, "attack", f"Your moon at {location_name} was destroyed by {user.username}")

        # Delete attacker fleet if empty after combat
        if _fleet_is_empty(fleet):
            db.delete(fleet)

        now = datetime.utcnow()
        result_str = report.get("result", "draw")

        # XP is based on total fleet value destroyed on both sides.
        attacker_destroyed = report.get("defender_value_lost", 0)
        defender_destroyed = report.get("attacker_value_lost", 0)
        total_destroyed = attacker_destroyed + defender_destroyed

        if total_destroyed > 0:
            experience_percent = get_config_float(db, "EXPERIENCE_PERCENT", EXPERIENCE_PERCENT)
            if not attacker_is_npc_faction:
                if defender_is_npc_faction:
                    attacker_xp = experience_percent * total_destroyed
                else:
                    atk_level = max(calc_player_level(user, db, game_speed), 0.01)
                    def_level = max(calc_player_level(defender, db, game_speed), 0.01)
                    if def_level > atk_level:
                        attacker_xp = min((def_level / atk_level) / 20, 0.10) * total_destroyed
                    else:
                        attacker_xp = ((def_level / atk_level) ** 2) / 20 * total_destroyed
                user.experience = (user.experience or 0) + attacker_xp
                report["attacker_xp"] = round(attacker_xp)

            if not defender_is_npc_faction:
                if attacker_is_npc_faction:
                    defender_xp = experience_percent * total_destroyed
                else:
                    atk_level = max(calc_player_level(user, db, game_speed), 0.01)
                    def_level = max(calc_player_level(defender, db, game_speed), 0.01)
                    if atk_level > def_level:
                        defender_xp = min((atk_level / def_level) / 20, 0.10) * total_destroyed
                    else:
                        defender_xp = ((atk_level / def_level) ** 2) / 20 * total_destroyed
                defender.experience = (defender.experience or 0) + defender_xp
                report["defender_xp"] = round(defender_xp)

        log_event(db, user.id, "attack", f"Attacked {location_name} ({defender.username}) â€” {result_str}")
        if colony and attacking_base_owner:
            log_event(db, defender.id, "attack", f"Your base {location_name} was attacked by {user.username} â€” {result_str}")
        else:
            log_event(db, defender.id, "attack", f"Your fleet at {location_name} was attacked by {user.username} â€” {result_str}")

        # Send battle report messages to both players
        fmtShips = lambda obj: ', '.join(f"{k.replace('_',' ').title()}: {int(v)}" for k, v in (obj or {}).items() if v > 0) or 'None'
        result_label = 'Attacker Wins' if result_str == 'attacker_wins' else ('Defender Wins' if result_str == 'defender_wins' else 'Draw')
        pillage_parts = []
        if report.get('pillage_base', 0) > 0:
            pillage_parts.append(f"Pillage: {report['pillage_base']} cr")
        if report.get('pillage_bonus', 0) > 0:
            pillage_parts.append(f"Additional pillage bonus: {report['pillage_bonus']} cr")
        pillage_line = ("\n" + "\n".join(pillage_parts)) if pillage_parts else ""
        occupy_line = "\nBase Occupied!" if report.get('occupied') else ("\n" + report["occupation_blocked"] if report.get("occupation_blocked") else "")
        piracy_line = f"\nTrade routes pirated: {report.get('trade_routes_pirated', 0)}" if report.get('trade_routes_pirated', 0) > 0 else ""
        raid_line = ""
        if report.get('raid'):
            raid_items = ', '.join(f"{k.title()}: {v}" for k, v in report['raid'].items())
            raid_line = f"\nRaid plunder: {raid_items}"
        _md = report.get('moon_destruction')
        moon_line = ""
        if _md:
            moon_line = f"\nMoon destruction: {'MOON DESTROYED!' if _md['destroyed'] else 'failed'} (chance {round(_md['chance'] * 100)}%)"
            if _md.get('destroyers_lost'):
                moon_line += f"\nDestroyer ships lost to backfire: {_md['destroyers_lost']}"
        br_body = (
            f"Battle at {location_name}\n"
            f"Result: {result_label}\n\n"
            f"Attacker: {user.username}\n"
            f"  Forces: {fmtShips(report.get('attacker_forces'))}\n"
            f"  Losses: {fmtShips(report.get('attacker_losses'))}\n"
            f"  Value lost: {report.get('attacker_value_lost', 0)} cr\n\n"
            f"Defender: {defender.username}\n"
            f"  Forces: {fmtShips(report.get('defender_forces'))}\n"
            f"  Defenses: {fmtShips(report.get('defender_turrets'))}\n"
            f"  Losses: {fmtShips(report.get('defender_losses'))}\n"
            f"  Defense losses: {fmtShips(report.get('defense_losses'))}\n"
            f"  Value lost: {report.get('defender_value_lost', 0)} cr\n\n"
            f"Debris: {report.get('debris', 0)} cr\n"
            f"Combat loot: {report.get('combat_loot', 0)} cr each"
            f"{pillage_line}{occupy_line}{piracy_line}{raid_line}{moon_line}"
            f"\n\nXP gained â€” Attacker: {report.get('attacker_xp', 0)} Â· Defender: {report.get('defender_xp', 0)}"
        )
        br_subject = f"Battle Report: {user.username} vs {defender.username} â€” {result_label}"
        for uid in [user.id, defender.id]:
            db.add(Message(
                sender_id=user.id if uid == defender.id else defender.id,
                recipient_id=uid,
                subject=br_subject,
                body=br_body,
                created_at=now,
            ))

        # Post to defender's guild board (Combat folder) only for successful conquer/pillage outcomes.
        guild_board_visible = bool(report.get("pillage", 0) > 0 or report.get("occupied"))
        if colony and guild_board_visible:
            from models import GuildBoardPost
            def_membership = db.query(GuildMember).filter(GuildMember.user_id == defender.id).first()
            if def_membership:
                latest_br = db.query(BattleReport).filter(
                    BattleReport.attacker_id == user.id,
                    BattleReport.defender_id == defender.id,
                    BattleReport.base_id == colony.id,
                ).order_by(BattleReport.created_at.desc()).first()
                pillage_text = f" â€” Pillaged {report.get('pillage', 0)} cr" if report.get("pillage", 0) > 0 else ""
                atk_lost = report.get("attacker_damage_dealt", 0)
                def_lost = report.get("defender_damage_dealt", 0)
                post = GuildBoardPost(
                    guild_id=def_membership.guild_id,
                    folder="combat",
                    author_id=None,  # system post
                    body=f"[b]{user.username}[/b] attacked [b]{defender.username}[/b]'s base {colony.name} â€” {result_str}{pillage_text}\nLosses: {atk_lost} / {def_lost}",
                    battle_report_id=latest_br.id if latest_br else None,
                )
                db.add(post)

        db.commit()

        return {"success": True, "report": report}

    # ======================== COLONIZE ========================

    @app.post("/api/colonize")
    def colonize(req: ColonizeRequest, token: str = Depends(get_token_from_header), db: Session = Depends(get_db)):
        """Colonize an uncolonized planet. Requires a fleet with a colonizer ship at that planet."""
        user = get_current_user(token, db)
        game_speed = get_config_float(db, "game_speed", 1.0)
        _process_fleet_arrivals(user, db)
        collect_resources(user, db, game_speed)

        planet = db.query(Planet).filter(Planet.id == req.planet_id).first()
        if not planet:
            raise HTTPException(404, "Planet not found")
        if planet.is_colonized:
            raise HTTPException(400, "Already colonized")
        # Check if this astro type is colonizable.
        from specs import PLANET_TYPE_STATS
        ptype_stats = PLANET_TYPE_STATS.get(planet.planet_type, {})
        if ptype_stats.get("colonizable", True) is False:
            type_name = ptype_stats.get("name", planet.planet_type.replace('_', ' ').title())
            raise HTTPException(400, f"{type_name} cannot be colonized")

        # Check for wormhole on this planet
        wormhole = db.query(Wormhole).filter(Wormhole.planet_id == planet.id).first()
        if wormhole:
            raise HTTPException(400, "Cannot colonize planets with wormholes")

        # Find the fleet; it must be at this planet and have a colonizer ship.
        fleet = db.query(Fleet).filter(Fleet.id == req.fleet_id, Fleet.user_id == user.id).first()
        if not fleet:
            raise HTTPException(404, "Fleet not found")
        if fleet.is_moving:
            raise HTTPException(400, "Fleet is still in transit")

        # Fleet must be at this planet (either via location_planet_id or base_id pointing to a colony on this planet)
        fleet_at_planet = False
        if fleet.location_planet_id == planet.id:
            fleet_at_planet = True
        elif fleet.base_id:
            colony_at = db.query(Colony).filter(Colony.id == fleet.base_id).first()
            if colony_at and colony_at.planet_id == planet.id:
                fleet_at_planet = True
        if not fleet_at_planet:
            raise HTTPException(400, "Fleet must be at the target planet to colonize")

        colonizer_key = fleet_capability_ship(fleet, db, "can_colonize")
        if not colonizer_key:
            raise HTTPException(400, "Fleet needs a colony ship to colonize")
        outpost_count = fleet.get_ship_count(colonizer_key)
        if outpost_count < 1:
            raise HTTPException(400, "Fleet needs a colony ship to colonize")

        # Escalating base cost. base_reserve (from disbanded bases/structures) is applied
        # first, then the remainder is paid in credits. Rebuild discount is baked into the gross.
        base_count_before = len(user.colonies)
        gross_cost = calc_colony_cost(user)
        net_cost, reserve_used = apply_colony_reserve(user, gross_cost)
        if net_cost > 0 and not can_afford(user, net_cost):
            raise HTTPException(400, f"Need {format_cost(net_cost)} credits to found a new base")

        # Consume one colonization unit.
        action_points.debit_action_points(user, db, "colonize")
        fleet.set_ship_count(colonizer_key, outpost_count - 1)

        if reserve_used > 0:
            user.base_reserve = (user.base_reserve or 0.0) - reserve_used
        if net_cost > 0:
            deduct_cost(user, net_cost)
        if gross_cost > 0:
            log_credits(db, user.id, -net_cost,
                        f"Founded base on {planet.name}"
                        + (f" (−{int(reserve_used)} from reserve)" if reserve_used > 0 else ""),
                        "colonize")

        planet.is_colonized = True
        colony = Colony(planet_id=planet.id, user_id=user.id, name=f"Colony on {planet.name}")
        db.add(colony)
        db.flush()
        # Track peak base count for the rebuild discount (never decreases on abandon)
        user.bases_founded_peak = max(getattr(user, "bases_founded_peak", 0) or 0, base_count_before + 1)

        # Parameterized colonize: a ship's `can_colonize` may be a dict carrying
        # `starting_buildings` (an "Advanced Colony Ship" that founds a developed
        # colony). Those levels augment the per-building `start_level` defaults; a
        # plain `can_colonize: true` keeps the default bare founding.
        _colonizer_cap = (get_effective_ship_spec(db, colonizer_key) or {}).get("can_colonize")
        _founding_buildings = _colonizer_cap.get("starting_buildings", {}) if isinstance(_colonizer_cap, dict) else {}

        _bspecs = get_all_building_specs(db)
        for bt in _bspecs.keys():
            if not is_building_disabled(db, bt):
                level = max(_bspecs[bt].get("start_level", 0), int(_founding_buildings.get(bt, 0) or 0))
                db.add(Building(colony_id=colony.id, building_type=bt, level=level))
        for dt in get_all_defense_specs(db).keys():
            if not is_defense_disabled(db, dt):
                db.add(Defense(colony_id=colony.id, defense_type=dt, level=0))

        # Move the fleet to the new colony (or delete if empty)
        if _fleet_is_empty(fleet):
            db.delete(fleet)
        else:
            fleet.base_id = colony.id
            fleet.location_planet_id = None

        user.score += COLONIZE_SCORE_BONUS
        log_event(db, user.id, "colonize", f"Colonized {planet.name} ({planet.planet_type})")
        _record_region_snapshot(user.id, planet.system.region_id, db)
        db.commit()
        import mod_hooks
        mod_hooks.fire("on_colony_founded", {
            "user": user, "colony": colony, "planet": planet, "fleet": fleet, "db": db,
        })
        return {"success": True, "base_id": colony.id, "name": colony.name}

    # ======================== BATTLES ========================

    @app.get("/api/battles")
    def get_battles(token: str = Depends(get_token_from_header), db: Session = Depends(get_db)):
        user = get_current_user(token, db)
        reports = db.query(BattleReport).filter(
            (BattleReport.attacker_id == user.id) | (BattleReport.defender_id == user.id)
        ).order_by(BattleReport.created_at.desc()).limit(50).all()
        result = []
        for r in reports:
            try:
                data = json.loads(r.report)
            except Exception:
                data = {}
            result.append({
                "id": r.id,
                "report": data,
                "created_at": r.created_at.isoformat(),
            })
        return result

    @app.post("/api/fleets/recycle")
    def toggle_recycle(fleet_id: int = Query(...), token: str = Depends(get_token_from_header), db: Session = Depends(get_db)):
        """Toggle auto-collection on/off for a fleet with a recycler ship."""
        user = get_current_user(token, db)
        fleet = db.query(Fleet).filter(Fleet.id == fleet_id, Fleet.user_id == user.id).first()
        if not fleet:
            raise HTTPException(404, "Fleet not found")

        recycler_count = sum(fleet.get_ship_count(k) for k in ships_with_capability(db, "can_recycle"))
        if recycler_count == 0:
            raise HTTPException(400, "Fleet must contain a recycler ship to auto-collect debris")

        fleet.auto_recycle = not (fleet.auto_recycle if fleet.auto_recycle is not None else True)
        db.commit()
        status = "on" if fleet.auto_recycle else "off"
        return {"success": True, "auto_recycle": fleet.auto_recycle, "message": f"Auto-recycle {status}"}
