from fastapi import HTTPException, Depends
from sqlalchemy.orm import Session
from datetime import datetime, timedelta
import random

from models import User, Colony, Commander, GameConfig, CommanderRecruit, CommanderAssign, CommanderMove
from auth import (get_token_from_header, get_current_user, get_config_float, get_db, log_event, log_credits)
from resources import can_afford, deduct_cost, format_cost
from game_logic import get_tech_level, _calc_distance, collect_resources, get_building_level
from specs import (generate_commander_name, COMMANDER_SKILL_TYPES, COMMANDER_SKILL_INFO,
                   SHIP_SPECS)
from config_defaults import *


def _commander_train_cost(level):
    """XP cost to train commander from current level to level+1. Formula: 20 * 1.5^level."""
    return round(COMMANDER_TRAIN_XP_BASE * (COMMANDER_TRAIN_XP_MULT ** level))


def _commander_train_time(current_level, game_speed):
    """Training time in seconds. 1 hour per current level, capped at 8 hours."""
    raw = min(current_level * COMMANDER_TRAIN_TIME_PER_LEVEL, COMMANDER_TRAIN_TIME_CAP)
    return raw / game_speed


def _colony_coords(colony, db):
    """Get formatted coordinate string for a colony."""
    if not colony or not colony.planet:
        return None
    planet = colony.planet
    system = planet.system
    region = system.region
    galaxy = region.galaxy
    return f"{galaxy.name}:{region.grid_x}{region.grid_y}:{system.name}:{planet.orbit_position}0"


def _colony_numeral(user, colony, db):
    """Get roman numeral index for a colony (I, II, III, etc.)."""
    numerals = ["I", "II", "III", "IV", "V", "VI", "VII", "VIII", "IX", "X",
                "XI", "XII", "XIII", "XIV", "XV", "XVI", "XVII", "XVIII", "XIX", "XX"]
    colonies = sorted(user.colonies, key=lambda c: c.id)
    for i, c in enumerate(colonies):
        if c.id == colony.id:
            return numerals[i] if i < len(numerals) else str(i + 1)
    return None


def register_commander_routes(app):

    @app.get("/api/commanders")
    def get_commanders(token: str = Depends(get_token_from_header), db: Session = Depends(get_db)):
        user = get_current_user(token, db)
        computer_level = get_tech_level(user, "computer")
        max_capacity = computer_level

        commanders = db.query(Commander).filter(Commander.user_id == user.id).all()

        result = []
        for cmdr in commanders:
            colony_name = None
            colony_coords = None
            colony_numeral_str = None
            if cmdr.colony_id:
                col = cmdr.colony
                if col:
                    colony_name = col.name
                    colony_coords = _colony_coords(col, db)
                    colony_numeral_str = _colony_numeral(user, col, db)

            train_cost = _commander_train_cost(cmdr.level)
            skill_info = COMMANDER_SKILL_INFO.get(cmdr.skill_type, {})

            result.append({
                "id": cmdr.id,
                "name": cmdr.name,
                "skill_type": cmdr.skill_type,
                "skill_name": skill_info.get("name", cmdr.skill_type),
                "level": cmdr.level,
                "xp": cmdr.xp,
                "colony_id": cmdr.colony_id,
                "colony_name": colony_name,
                "colony_coords": colony_coords,
                "colony_numeral": colony_numeral_str,
                "is_assigned": cmdr.is_assigned,
                "is_traveling": cmdr.is_traveling,
                "arrival_time": cmdr.arrival_time.isoformat() if cmdr.arrival_time else None,
                "is_training": cmdr.is_training,
                "training_complete_time": cmdr.training_complete_time.isoformat() if cmdr.training_complete_time else None,
                "train_xp_cost": train_cost,
                "train_credit_cost": train_cost * COMMANDER_TRAIN_CREDIT_MULT,
                "can_train_credits": cmdr.level < COMMANDER_XP_ONLY_ABOVE,
            })

        return {
            "commanders": result,
            "max_capacity": max_capacity,
            "current_count": len(commanders),
            "xp_pool": round(user.experience),
            "skill_info": COMMANDER_SKILL_INFO,
        }

    @app.post("/api/commanders/recruit")
    def recruit_commander(req: CommanderRecruit, token: str = Depends(get_token_from_header), db: Session = Depends(get_db)):
        user = get_current_user(token, db)
        computer_level = get_tech_level(user, "computer")
        current_count = db.query(Commander).filter(Commander.user_id == user.id).count()

        # Must have at least 1 Command Center to recruit
        has_cc = any(
            get_building_level(c, "command_centers") >= 1
            for c in user.colonies
        )
        if not has_cc:
            raise HTTPException(400, "You must have at least 1 Command Center to recruit a new commander")
        if computer_level < 1:
            raise HTTPException(400, "Requires Computer tech level 1 to recruit commanders")
        if current_count >= computer_level:
            raise HTTPException(400, f"Commander capacity full ({current_count}/{computer_level}). Research Computer for more slots.")

        # Validate skill type
        skill = req.skill_type
        if skill is not None and skill not in COMMANDER_SKILL_TYPES:
            raise HTTPException(400, f"Invalid skill type. Choose from: {', '.join(COMMANDER_SKILL_TYPES)}")
        if skill is None:
            skill = random.choice(COMMANDER_SKILL_TYPES)

        # Pay cost
        if req.use_credits:
            if not can_afford(user, COMMANDER_RECRUIT_CREDIT_COST):
                raise HTTPException(400, f"Need {format_cost(COMMANDER_RECRUIT_CREDIT_COST)} credits")
            deduct_cost(user, COMMANDER_RECRUIT_CREDIT_COST)
            log_credits(db, user.id, -COMMANDER_RECRUIT_CREDIT_COST,
                       f"Recruited commander ({skill})", "commander")
        else:
            if user.experience < COMMANDER_RECRUIT_XP_COST:
                raise HTTPException(400, f"Need {COMMANDER_RECRUIT_XP_COST} XP (you have {int(user.experience)})")
            user.experience -= COMMANDER_RECRUIT_XP_COST

        name = generate_commander_name()
        cmdr = Commander(
            user_id=user.id,
            name=name,
            skill_type=skill,
            level=1,
            xp=0,
        )
        db.add(cmdr)
        skill_name = COMMANDER_SKILL_INFO.get(skill, {}).get("name", skill)
        log_event(db, user.id, "commander", f"Recruited {name} ({skill_name})")
        db.commit()

        return {"success": True, "commander_id": cmdr.id, "name": name, "skill_type": skill}

    @app.post("/api/commanders/{commander_id}/assign")
    def assign_commander(commander_id: int, req: CommanderAssign,
                        token: str = Depends(get_token_from_header), db: Session = Depends(get_db)):
        user = get_current_user(token, db)
        cmdr = db.query(Commander).filter(
            Commander.id == commander_id, Commander.user_id == user.id
        ).first()
        if not cmdr:
            raise HTTPException(404, "Commander not found")
        if cmdr.is_traveling:
            raise HTTPException(400, "Commander is traveling")

        if req.colony_id is None:
            # Unassign
            cmdr.is_assigned = False
            log_event(db, user.id, "commander", f"Unassigned {cmdr.name}")
            db.commit()
            return {"success": True, "action": "unassigned"}

        # Verify colony belongs to user
        colony = db.query(Colony).filter(Colony.id == req.colony_id, Colony.user_id == user.id).first()
        if not colony:
            raise HTTPException(400, "Colony not found or not yours")

        # Commander must be physically at this colony
        if cmdr.colony_id != req.colony_id:
            raise HTTPException(400, "Commander must be at this base to be assigned. Move them first.")

        # Unassign any existing Base Commander at this colony
        existing = db.query(Commander).filter(
            Commander.colony_id == req.colony_id,
            Commander.is_assigned == True,
            Commander.id != commander_id
        ).all()
        for ex in existing:
            ex.is_assigned = False

        cmdr.is_assigned = True
        numeral = _colony_numeral(user, colony, db)
        log_event(db, user.id, "commander", f"Assigned {cmdr.name} as Base Commander at {numeral or colony.name}")
        db.commit()
        return {"success": True, "action": "assigned"}

    @app.post("/api/commanders/{commander_id}/move")
    def move_commander(commander_id: int, req: CommanderMove,
                      token: str = Depends(get_token_from_header), db: Session = Depends(get_db)):
        user = get_current_user(token, db)
        game_speed = get_config_float(db, "game_speed", 1.0)

        cmdr = db.query(Commander).filter(
            Commander.id == commander_id, Commander.user_id == user.id
        ).first()
        if not cmdr:
            raise HTTPException(404, "Commander not found")
        if cmdr.is_traveling:
            raise HTTPException(400, "Commander is already traveling")

        # Destination must be player's colony
        dest_colony = db.query(Colony).filter(Colony.id == req.colony_id, Colony.user_id == user.id).first()
        if not dest_colony:
            raise HTTPException(400, "Destination colony not found or not yours")
        if cmdr.colony_id == req.colony_id:
            raise HTTPException(400, "Commander is already at this base")

        now = datetime.utcnow()

        if cmdr.colony_id is None:
            # Fresh recruit or pool — fixed 10 min travel
            travel_time = COMMANDER_TRAVEL_INITIAL_SECONDS / game_speed
        else:
            # Calculate distance between current base and destination
            origin_colony = cmdr.colony
            if not origin_colony:
                travel_time = COMMANDER_TRAVEL_INITIAL_SECONDS / game_speed
            else:
                origin_planet = origin_colony.planet
                dest_planet = dest_colony.planet
                distance = _calc_distance(origin_planet, dest_planet)
                # Commander travels at a scout ship's speed (capability-resolved,
                # falling back to any autoscout-capable ship, then a default).
                scout_spec = SHIP_SPECS.get("small_ship_8") or next(
                    (s for s in SHIP_SPECS.values() if s.get("can_autoscout")), {})
                scout_speed = scout_spec.get("speed", 12)
                warp_level = get_tech_level(user, "warp_drive")
                effective_speed = scout_speed * (1 + warp_level * 0.05)
                travel_divisor = get_config_float(db, "FLEET_TRAVEL_DIVISOR", FLEET_TRAVEL_DIVISOR)
                travel_time = distance * travel_divisor / (effective_speed * game_speed)
                travel_time = max(60, travel_time)  # min 1 minute

        # Unassign if currently assigned
        cmdr.is_assigned = False
        cmdr.is_traveling = True
        cmdr.colony_id = req.colony_id  # destination
        cmdr.arrival_time = now + timedelta(seconds=travel_time)

        numeral = _colony_numeral(user, dest_colony, db)
        log_event(db, user.id, "commander", f"{cmdr.name} traveling to {numeral or dest_colony.name}")
        db.commit()

        return {
            "success": True,
            "travel_time": round(travel_time),
            "arrival_time": cmdr.arrival_time.isoformat(),
        }

    @app.post("/api/commanders/{commander_id}/train")
    def train_commander(commander_id: int, use_credits: bool = False,
                       token: str = Depends(get_token_from_header), db: Session = Depends(get_db)):
        user = get_current_user(token, db)
        game_speed = get_config_float(db, "game_speed", 1.0)
        cmdr = db.query(Commander).filter(
            Commander.id == commander_id, Commander.user_id == user.id
        ).first()
        if not cmdr:
            raise HTTPException(404, "Commander not found")
        if cmdr.level >= COMMANDER_MAX_LEVEL:
            raise HTTPException(400, f"Commander already at max level {COMMANDER_MAX_LEVEL}")
        if cmdr.is_training:
            raise HTTPException(400, "Commander is already training")

        xp_cost = _commander_train_cost(cmdr.level)
        credit_cost = xp_cost * COMMANDER_TRAIN_CREDIT_MULT

        # Above level 8, can only use XP
        if use_credits and cmdr.level >= COMMANDER_XP_ONLY_ABOVE:
            raise HTTPException(400, f"Above level {COMMANDER_XP_ONLY_ABOVE}, commanders can only be trained with XP")

        if use_credits:
            if not can_afford(user, credit_cost):
                raise HTTPException(400, f"Need {format_cost(credit_cost)} credits")
            deduct_cost(user, credit_cost)
            log_credits(db, user.id, -credit_cost, f"Training {cmdr.name} to Lv{cmdr.level + 1}", "commander")
        else:
            if cmdr.xp < xp_cost:
                raise HTTPException(400, f"Commander needs {xp_cost} XP to train (has {cmdr.xp})")
            cmdr.xp -= xp_cost

        target_level = cmdr.level + 1
        train_seconds = _commander_train_time(cmdr.level, game_speed)
        now = datetime.utcnow()
        cmdr.is_training = True
        cmdr.training_complete_time = now + timedelta(seconds=train_seconds)

        skill_name = COMMANDER_SKILL_INFO.get(cmdr.skill_type, {}).get("name", cmdr.skill_type)
        log_event(db, user.id, "commander", f"Started training {cmdr.name} to {skill_name} {target_level} ({round(train_seconds)}s)")
        db.commit()

        return {
            "success": True,
            "training_time": round(train_seconds),
            "training_complete_time": cmdr.training_complete_time.isoformat(),
        }

    @app.delete("/api/commanders/{commander_id}")
    def dismiss_commander(commander_id: int,
                         token: str = Depends(get_token_from_header), db: Session = Depends(get_db)):
        user = get_current_user(token, db)
        cmdr = db.query(Commander).filter(
            Commander.id == commander_id, Commander.user_id == user.id
        ).first()
        if not cmdr:
            raise HTTPException(404, "Commander not found")

        name = cmdr.name
        log_event(db, user.id, "commander", f"Dismissed {name}")
        db.delete(cmdr)
        db.commit()

        return {"success": True, "dismissed": name}
