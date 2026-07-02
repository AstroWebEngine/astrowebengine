from fastapi import HTTPException, Depends, Query
from sqlalchemy.orm import Session
from datetime import datetime, timedelta
from models import User, Research, ResearchQueue, Colony
from auth import (get_token_from_header, get_current_user, get_config_float, get_config_int, get_db,
                  get_effective_research_spec, is_research_disabled, get_all_research_specs, log_event, log_credits)
from game_logic import calc_research_cost, calc_base_stats, get_building_level, get_tech_level, collect_resources
from resources import can_afford, deduct_cost, add_resources, format_cost, round_cost, total_cost_value
from config_defaults import *
from pydantic import BaseModel
import action_points


class ResearchRequest(BaseModel):
    tech_type: str
    base_id: int


def register_research_routes(app):

    @app.get("/api/research")
    def get_research(token: str = Depends(get_token_from_header), db: Session = Depends(get_db),
                     base_id: int = Query(None)):
        user = get_current_user(token, db)
        game_speed = get_config_float(db, "game_speed", 1.0)
        collect_resources(user, db, game_speed)

        # If base_id provided, use that base's labs; otherwise fall back to sum (for global view)
        if base_id:
            colony = db.query(Colony).filter(Colony.id == base_id, Colony.user_id == user.id).first()
            if not colony:
                raise HTTPException(404, "Base not found")
            base_stats = calc_base_stats(colony, user, game_speed)
            base_lab_capacity = base_stats.get("research", 0)
            base_lab_level = get_building_level(colony, "research_labs")
            is_occupied = bool(colony.occupied_by)
        else:
            # Global view — show max lab capacity across bases (informational)
            base_lab_capacity = max((calc_base_stats(c, user, game_speed).get("research", 0) for c in user.colonies), default=0)
            base_lab_level = max((get_building_level(c, "research_labs") for c in user.colonies), default=0)
            is_occupied = False

        # Get all active research across all bases (for conflict display)
        active_research = db.query(ResearchQueue.tech_type, ResearchQueue.colony_id).filter(
            ResearchQueue.user_id == user.id,
            ResearchQueue.position == 0,
            ResearchQueue.finish_at != None,
        ).all()
        active_tech_map = {r[0]: r[1] for r in active_research}

        result = []
        for tech_type, spec in get_all_research_specs(db).items():
            if is_research_disabled(db, tech_type):
                continue
            r = next((r for r in user.research if r.tech_type == tech_type), None)
            current_level = r.level if r else 0
            is_researching = r.is_researching if r else False
            research_end = r.research_end.isoformat() if r and r.research_end else None

            # Effective level includes queued research for this tech across ALL bases
            effective_level = current_level
            all_queued = (db.query(ResearchQueue)
                         .filter(ResearchQueue.user_id == user.id,
                                 ResearchQueue.tech_type == tech_type)
                         .order_by(ResearchQueue.target_level.desc()).first())
            if all_queued:
                effective_level = all_queued.target_level

            next_cost, next_time = calc_research_cost(
                db, tech_type, effective_level, game_speed, base_lab_capacity,
                is_occupied=is_occupied, colony_id=base_id)

            # Check prerequisites
            prereqs_met = True
            prereq_text = []
            for prereq_tech, prereq_level in spec.get("prereqs", {}).items():
                player_level = get_tech_level(user, prereq_tech)
                if player_level < prereq_level:
                    prereqs_met = False
                prereq_name = get_effective_research_spec(db, prereq_tech).get("name", prereq_tech)
                prereq_text.append(f"{prereq_name} {prereq_level}")

            # Check lab requirement against this base's lab level
            lab_met = base_lab_level >= spec.get("lab_req", 1)

            # Check if another base is actively researching this tech
            researching_at = active_tech_map.get(tech_type)
            conflict = False
            if researching_at and base_id and researching_at != base_id:
                conflict = True

            result.append({
                "tech_type": tech_type,
                "name": spec["name"],
                "icon": spec.get("icon", "🔬"),
                "bonus": spec.get("bonus", ""),
                "level": current_level,
                "effective_level": effective_level,
                "is_researching": is_researching,
                "research_end": research_end,
                "next_cost": round_cost(next_cost, 1),
                "next_time": round(next_time),
                "lab_req": spec.get("lab_req", 1),
                "lab_count": base_lab_level,
                "lab_met": lab_met,
                "prereqs": spec.get("prereqs", {}),
                "prereqs_met": prereqs_met,
                "prereq_text": ", ".join(prereq_text) if prereq_text else "",
                "conflict": conflict,
            })
        return result

    @app.post("/api/research")
    def do_research(req: ResearchRequest, token: str = Depends(get_token_from_header), db: Session = Depends(get_db)):
        user = get_current_user(token, db)
        game_speed = get_config_float(db, "game_speed", 1.0)
        collect_resources(user, db, game_speed)

        # Validate base ownership
        colony = db.query(Colony).filter(Colony.id == req.base_id, Colony.user_id == user.id).first()
        if not colony:
            raise HTTPException(404, "Base not found")

        base_lab_level = get_building_level(colony, "research_labs")
        if base_lab_level <= 0:
            raise HTTPException(400, "This base has no Research Labs")

        spec = get_effective_research_spec(db, req.tech_type)
        if is_research_disabled(db, req.tech_type):
            raise HTTPException(400, "This technology has been disabled")
        if not spec:
            raise HTTPException(400, "Invalid tech type")

        # Check this base's research queue size (engine flag; defaults to constant)
        queue_max = get_config_int(db, "research_queue_max", RESEARCH_QUEUE_MAX)
        queue = (db.query(ResearchQueue)
                 .filter(ResearchQueue.user_id == user.id,
                         ResearchQueue.colony_id == colony.id)
                 .order_by(ResearchQueue.position).all())
        if len(queue) >= queue_max:
            raise HTTPException(400, f"Research queue full at this base (max {queue_max} items)")

        r = next((r for r in user.research if r.tech_type == req.tech_type), None)
        if not r:
            raise HTTPException(400, "Research not initialized")

        # Figure out effective level (current + queued across ALL bases)
        effective_level = r.level
        all_queued = (db.query(ResearchQueue)
                     .filter(ResearchQueue.user_id == user.id,
                             ResearchQueue.tech_type == req.tech_type)
                     .order_by(ResearchQueue.target_level.desc()).first())
        if all_queued:
            effective_level = all_queued.target_level

        # Smart prereq check: project tech levels after queued research completes
        projected_tech = {}
        for tech_r in user.research:
            projected_tech[tech_r.tech_type] = tech_r.level
        all_user_queue = db.query(ResearchQueue).filter(ResearchQueue.user_id == user.id).all()
        for q in all_user_queue:
            if q.target_level > projected_tech.get(q.tech_type, 0):
                projected_tech[q.tech_type] = q.target_level

        for prereq_tech, prereq_level in spec.get("prereqs", {}).items():
            proj_level = projected_tech.get(prereq_tech, 0)
            if proj_level < prereq_level:
                prereq_name = get_effective_research_spec(db, prereq_tech).get("name", prereq_tech)
                current = get_tech_level(user, prereq_tech)
                if current < prereq_level:
                    raise HTTPException(400, f"Requires {prereq_name} level {prereq_level} (you have {current}). Queue {prereq_name} upgrades first!")
                else:
                    raise HTTPException(400, f"Requires {prereq_name} level {prereq_level}")

        # Check lab requirement against THIS base's lab level
        if base_lab_level < spec.get("lab_req", 1):
            raise HTTPException(400, f"This base needs Research Lab level {spec['lab_req']} (has {base_lab_level})")

        base_stats = calc_base_stats(colony, user, game_speed)
        base_lab_capacity = base_stats.get("research", 0)
        is_occupied = bool(colony.occupied_by)
        cost, research_time = calc_research_cost(
            db, req.tech_type, effective_level, game_speed, base_lab_capacity,
            is_occupied=is_occupied, colony_id=colony.id)

        target_level = effective_level + 1
        position = len(queue)

        # Only check credits for the active slot (position 0); queued items wait
        if position == 0 and not can_afford(user, cost):
            raise HTTPException(400, f"Need {format_cost(cost)} credits")

        # Check if another base is already actively researching this tech
        # (only blocks starting, not queuing)
        can_start = True
        if position == 0:
            active_conflict = db.query(ResearchQueue).filter(
                ResearchQueue.user_id == user.id,
                ResearchQueue.tech_type == req.tech_type,
                ResearchQueue.position == 0,
                ResearchQueue.finish_at != None,
            ).first()
            if active_conflict:
                can_start = False

        now = datetime.utcnow()

        action_points.debit_action_points(user, db, "research_start")

        if position == 0 and can_start:
            # Start immediately — deduct credits now
            deduct_cost(user, cost)
            log_credits(db, user.id, -total_cost_value(cost), f"Research of {spec.get('name', req.tech_type)} lvl {target_level}", "research")
            r.is_researching = True
            r.research_end = now + timedelta(seconds=research_time)
            finish_at = r.research_end
            started_at = now
        else:
            finish_at = None
            started_at = None

        queue_item = ResearchQueue(
            user_id=user.id, colony_id=colony.id, position=position,
            tech_type=req.tech_type, target_level=target_level,
            cost=cost, research_time=research_time,
            started_at=started_at, finish_at=finish_at
        )
        db.add(queue_item)

        tech_name = spec.get("name", req.tech_type)
        if position == 0 and can_start:
            log_event(db, user.id, "research", f"Started researching {tech_name} Lv{target_level} at {colony.name}")
        else:
            log_event(db, user.id, "research", f"Queued {tech_name} Lv{target_level} at {colony.name} (position {position + 1})")
        db.commit()
        return {"success": True, "cost": round_cost(cost, 1), "time": round(research_time),
                "finish": finish_at.isoformat() if finish_at else None,
                "queued": position > 0 or not can_start, "queue_position": position + 1}

    @app.get("/api/research-queue")
    def get_research_queue(token: str = Depends(get_token_from_header), db: Session = Depends(get_db),
                           base_id: int = Query(None)):
        user = get_current_user(token, db)
        query = db.query(ResearchQueue).filter(ResearchQueue.user_id == user.id)
        if base_id:
            query = query.filter(ResearchQueue.colony_id == base_id)
        queue = query.order_by(ResearchQueue.colony_id, ResearchQueue.position).all()
        result = []
        for q in queue:
            name = get_effective_research_spec(db, q.tech_type).get("name", q.tech_type)
            result.append({
                "id": q.id, "position": q.position,
                "tech_type": q.tech_type, "name": name,
                "target_level": q.target_level,
                "cost": round(q.cost, 1), "research_time": round(q.research_time),
                "started_at": q.started_at.isoformat() if q.started_at else None,
                "finish_at": q.finish_at.isoformat() if q.finish_at else None,
                "colony_id": q.colony_id,
            })
        return result

    @app.delete("/api/research-queue/{queue_id}")
    def cancel_research_queue(queue_id: int, token: str = Depends(get_token_from_header), db: Session = Depends(get_db)):
        user = get_current_user(token, db)
        item = db.query(ResearchQueue).filter(
            ResearchQueue.id == queue_id,
            ResearchQueue.user_id == user.id
        ).first()
        if not item:
            raise HTTPException(404, "Queue item not found")
        position = item.position
        colony_id = item.colony_id
        refund_amount = item.cost
        cancelled_tech = item.tech_type
        # Refund credits only if item was active (already paid)
        if position == 0 and item.finish_at:
            add_resources(user, refund_amount)
            log_credits(db, user.id, total_cost_value(refund_amount), f"Cancelled research of {cancelled_tech}", "research")
        # If cancelling active item, stop the research
        if position == 0:
            for r in user.research:
                if r.tech_type == cancelled_tech:
                    r.is_researching = False
                    r.research_end = None
                    break
        db.delete(item)
        db.flush()
        # Re-number remaining queue items for THIS base
        remaining = (db.query(ResearchQueue)
                     .filter(ResearchQueue.user_id == user.id,
                             ResearchQueue.colony_id == colony_id)
                     .order_by(ResearchQueue.position).all())
        for i, q in enumerate(remaining):
            q.position = i
        # If we cancelled position 0 and there's a new position 0, try to start it
        if position == 0 and remaining:
            new_active = remaining[0]
            # Check tech conflict — is another base actively researching this tech?
            active_conflict = db.query(ResearchQueue).filter(
                ResearchQueue.user_id == user.id,
                ResearchQueue.tech_type == new_active.tech_type,
                ResearchQueue.position == 0,
                ResearchQueue.finish_at != None,
                ResearchQueue.id != new_active.id,
            ).first()
            if not active_conflict and can_afford(user, new_active.cost):
                deduct_cost(user, new_active.cost)
                log_credits(db, user.id, -total_cost_value(new_active.cost), f"Research of {new_active.tech_type} Lv{new_active.target_level}", "research")
                now = datetime.utcnow()
                new_active.started_at = now
                new_active.finish_at = now + timedelta(seconds=new_active.research_time)
                for r in user.research:
                    if r.tech_type == new_active.tech_type:
                        r.is_researching = True
                        r.research_end = new_active.finish_at
                        break
        db.commit()
        return {"success": True, "refunded": round(refund_amount, 1)}
