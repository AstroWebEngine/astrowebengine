"""
Tutorial & Galaxy Selection endpoints for AstroWebEngine.
Handles: galaxy picker after registration, tutorial progress, mission checking, reward collection.
"""
import json
from datetime import datetime
from fastapi import HTTPException, Depends
from sqlalchemy.orm import Session
from sqlalchemy import func

from models import (
    User, Galaxy, Colony, Building, Defense, Research, Fleet, TradeRoute,
    TutorialProgress, GalaxySelectRequest,
)
from auth import get_db, get_token_from_header, get_current_user, log_event, log_credits
from universe import _assign_homeworld_in_galaxy
from resources import add_resources, get_user_resources
from tutorial_data import TUTORIAL_STEPS


def active_tutorial_steps():
    """Tutorial is owner-authored content from the active game definition:
      - a list under definition["tutorial"]  -> the mod's own steps
      - the string "classic"                  -> the engine-bundled classic tutorial
      - absent / false / empty                -> no tutorial

    The lean engine default ships NO tutorial; a definition opts in (classic
    rides with game_definitions/classic_space.json).
    """
    from game_definition import get_game_definition
    t = get_game_definition().get("tutorial", None)
    if t == "classic":
        return TUTORIAL_STEPS
    if isinstance(t, list):
        return t
    return []


def register_tutorial_routes(app):

    # ── Galaxy selection (post-registration) ──

    @app.get("/api/galaxies/list")
    def list_galaxies_for_selection(
        token: str = Depends(get_token_from_header),
        db: Session = Depends(get_db),
    ):
        """Return all galaxies with player counts for the galaxy picker screen."""
        user = get_current_user(token, db)
        galaxies = db.query(Galaxy).order_by(Galaxy.name).all()

        from models import Planet, StarSystem, Region
        result = []
        # Find recommended galaxy (least populated)
        pop_counts = {}
        for g in galaxies:
            count = (
                db.query(func.count(Colony.id))
                .select_from(Colony)
                .join(Planet, Colony.planet_id == Planet.id)
                .join(StarSystem, Planet.system_id == StarSystem.id)
                .join(Region, StarSystem.region_id == Region.id)
                .filter(Region.galaxy_id == g.id)
                .scalar()
            )
            pop_counts[g.id] = count

        min_pop = min(pop_counts.values()) if pop_counts else 0
        recommended_ids = [gid for gid, c in pop_counts.items() if c == min_pop]

        for g in galaxies:
            result.append({
                "id": g.id,
                "name": g.name,
                "player_count": pop_counts.get(g.id, 0),
                "is_recommended": g.id in recommended_ids,
            })

        return {"galaxies": result}

    @app.post("/api/select-galaxy")
    def select_galaxy(
        req: GalaxySelectRequest,
        token: str = Depends(get_token_from_header),
        db: Session = Depends(get_db),
    ):
        """Player picks a galaxy after registration. Assigns their homeworld there."""
        user = get_current_user(token, db)

        # Check they don't already have a base
        existing = db.query(Colony).filter(Colony.user_id == user.id).first()
        if existing:
            raise HTTPException(400, "You already have a base")

        galaxy = db.query(Galaxy).filter(Galaxy.id == req.galaxy_id).first()
        if not galaxy:
            raise HTTPException(404, "Galaxy not found")

        # Assign homeworld in the chosen galaxy
        _assign_homeworld_in_galaxy(user, galaxy.id, db)
        user.chosen_galaxy_id = galaxy.id

        # Create tutorial progress
        tp = db.query(TutorialProgress).filter(TutorialProgress.user_id == user.id).first()
        if not tp:
            tp = TutorialProgress(user_id=user.id, chosen_galaxy_id=galaxy.id)
            db.add(tp)

        db.commit()
        return {"ok": True, "message": f"Homeworld assigned in {galaxy.name}"}

    # ── Tutorial progress ──

    @app.get("/api/tutorial/progress")
    def get_tutorial_progress(
        token: str = Depends(get_token_from_header),
        db: Session = Depends(get_db),
    ):
        """Return the player's tutorial state + step data."""
        user = get_current_user(token, db)
        tp = db.query(TutorialProgress).filter(TutorialProgress.user_id == user.id).first()

        if not tp:
            # Player has no tutorial row — old account or admin
            # If they already have bases, auto-complete the tutorial
            existing_base = db.query(Colony).filter(Colony.user_id == user.id).first()
            if existing_base or user.is_admin:
                tp = TutorialProgress(user_id=user.id, is_finished=True, finished_at=datetime.utcnow())
                user.has_completed_tutorial = True
            else:
                tp = TutorialProgress(user_id=user.id)
            db.add(tp)
            db.commit()
            db.refresh(tp)

        # Tutorial content comes from the active definition (owner-authored).
        # If the ruleset provides none, auto-finish so players aren't shown steps
        # for content their roster doesn't have.
        tutorial_steps = active_tutorial_steps()
        if not tutorial_steps and not tp.is_finished:
            tp.is_finished = True
            tp.finished_at = datetime.utcnow()
            user.has_completed_tutorial = True
            db.commit()

        completed = json.loads(tp.completed_steps or "[]")
        collected = json.loads(tp.collected_steps or "[]")

        # Build step data with live completion status
        steps = []
        for i, step in enumerate(tutorial_steps):
            step_data = {
                "index": i,
                "id": step["id"],
                "title": step["title"],
                "description": step["description"],
                "reward": step["reward"],
                "is_completed": i in completed,
                "is_collected": i in collected,
                "mission": None,
                "requirements": [
                    {**req, **(lambda p: {"met": p.get("done", False), "current": p.get("current", 0), "target": p.get("target", 0)})(_check_mission_progress(user, req, db))}
                    for req in step.get("requirements", [])
                ],
            }
            if step.get("mission"):
                mission = step["mission"].copy()
                # Check live progress for the mission
                mission["progress"] = _check_mission_progress(user, step["mission"], db)
                step_data["mission"] = mission
            if step.get("optional_mission"):
                opt = step["optional_mission"].copy()
                opt["progress"] = _check_mission_progress(user, step["optional_mission"], db)
                opt["is_optional"] = True
                step_data["optional_mission"] = opt
            steps.append(step_data)

        return {
            "current_step": tp.current_step,
            "is_finished": tp.is_finished,
            "steps": steps,
            "completed_steps": completed,
            "collected_steps": collected,
        }

    @app.post("/api/tutorial/advance")
    def advance_tutorial(
        token: str = Depends(get_token_from_header),
        db: Session = Depends(get_db),
    ):
        """Move to the next tutorial step (used for intro 'Start Tutorial' button)."""
        user = get_current_user(token, db)
        tp = db.query(TutorialProgress).filter(TutorialProgress.user_id == user.id).first()
        if not tp:
            raise HTTPException(404, "No tutorial in progress")

        if tp.current_step == 0:
            # Mark introduction as completed and move to step 1
            completed = json.loads(tp.completed_steps or "[]")
            if 0 not in completed:
                completed.append(0)
            tp.completed_steps = json.dumps(completed)
            tp.current_step = 1
            db.commit()

        return {"ok": True, "current_step": tp.current_step}

    @app.post("/api/tutorial/check/{step_index}")
    def check_tutorial_step(
        step_index: int,
        token: str = Depends(get_token_from_header),
        db: Session = Depends(get_db),
    ):
        """Check if a tutorial step's mission is complete. Mark it if so."""
        user = get_current_user(token, db)
        tp = db.query(TutorialProgress).filter(TutorialProgress.user_id == user.id).first()
        if not tp:
            raise HTTPException(404, "No tutorial in progress")

        if step_index < 0 or step_index >= len(active_tutorial_steps()):
            raise HTTPException(400, "Invalid step index")

        step = active_tutorial_steps()[step_index]
        completed = json.loads(tp.completed_steps or "[]")

        if step_index in completed:
            return {"ok": True, "already_completed": True}

        # Check if mission is done
        if step.get("mission") is None:
            # No mission (intro/end) — auto-complete
            is_done = True
        else:
            progress = _check_mission_progress(user, step["mission"], db)
            is_done = progress.get("done", False)

        if is_done:
            completed.append(step_index)
            tp.completed_steps = json.dumps(completed)
            db.commit()
            return {"ok": True, "completed": True, "reward": step["reward"]}

        return {"ok": True, "completed": False}

    @app.post("/api/tutorial/collect/{step_index}")
    def collect_tutorial_reward(
        step_index: int,
        token: str = Depends(get_token_from_header),
        db: Session = Depends(get_db),
    ):
        """Collect credits reward for a completed tutorial step."""
        user = get_current_user(token, db)
        tp = db.query(TutorialProgress).filter(TutorialProgress.user_id == user.id).first()
        if not tp:
            raise HTTPException(404, "No tutorial in progress")

        if step_index < 0 or step_index >= len(active_tutorial_steps()):
            raise HTTPException(400, "Invalid step index")

        completed = json.loads(tp.completed_steps or "[]")
        collected = json.loads(tp.collected_steps or "[]")

        if step_index not in completed:
            raise HTTPException(400, "Step not completed yet")
        if step_index in collected:
            raise HTTPException(400, "Reward already collected")

        reward = active_tutorial_steps()[step_index]["reward"]
        if reward > 0:
            add_resources(user, reward)
            log_credits(db, user.id, reward, f"Tutorial: {active_tutorial_steps()[step_index]['title']}", "income")
            log_event(db, user.id, "tutorial", f"Collected {reward} credits for tutorial: {active_tutorial_steps()[step_index]['title']}")

        collected.append(step_index)
        tp.collected_steps = json.dumps(collected)

        # Advance to next step
        if step_index == tp.current_step and tp.current_step < len(active_tutorial_steps()) - 1:
            tp.current_step = step_index + 1

        # Check if tutorial is finished
        if step_index >= len(active_tutorial_steps()) - 2:  # Combat Fleets is second-to-last
            tp.is_finished = True
            tp.finished_at = datetime.utcnow()
            user.has_completed_tutorial = True

        db.commit()
        return {"ok": True, "credits_awarded": reward, "new_credits": user.credits, "resources": get_user_resources(user)}

    @app.post("/api/tutorial/finish")
    def finish_tutorial(
        token: str = Depends(get_token_from_header),
        db: Session = Depends(get_db),
    ):
        """End Tutorial step — marks tutorial as fully complete."""
        user = get_current_user(token, db)
        tp = db.query(TutorialProgress).filter(TutorialProgress.user_id == user.id).first()
        if not tp:
            raise HTTPException(404, "No tutorial in progress")

        tp.is_finished = True
        tp.finished_at = datetime.utcnow()
        user.has_completed_tutorial = True

        # Mark end tutorial step as completed
        completed = json.loads(tp.completed_steps or "[]")
        last_idx = len(active_tutorial_steps()) - 1
        if last_idx not in completed:
            completed.append(last_idx)
        tp.completed_steps = json.dumps(completed)

        db.commit()
        return {"ok": True}

    @app.post("/api/tutorial/skip")
    def skip_tutorial(
        token: str = Depends(get_token_from_header),
        db: Session = Depends(get_db),
    ):
        """Allow player to skip the tutorial entirely."""
        user = get_current_user(token, db)
        tp = db.query(TutorialProgress).filter(TutorialProgress.user_id == user.id).first()
        if not tp:
            tp = TutorialProgress(user_id=user.id)
            db.add(tp)

        tp.is_finished = True
        tp.finished_at = datetime.utcnow()
        user.has_completed_tutorial = True
        db.commit()
        return {"ok": True}


# ── Mission progress checking ──

def _check_mission_progress(user, mission, db):
    """Check how far along a player is on a tutorial mission. Returns {done, current, target}."""
    mtype = mission.get("type")

    if mtype == "building":
        # Check if any base has the building at target level
        bt = mission["building_type"]
        target = mission["target_level"]
        best = (
            db.query(func.max(Building.level))
            .join(Colony, Building.colony_id == Colony.id)
            .filter(Colony.user_id == user.id, Building.building_type == bt)
            .scalar()
        ) or 0
        return {"done": best >= target, "current": best, "target": target}

    elif mtype == "building_any_energy":
        # Check if player built at least 1 level of any energy structure
        # All buildings start at 0 (homeworld only has urban_structures=1)
        energy_types = ["solar_plants", "gas_plants", "fusion_plants", "antimatter_plants", "orbital_plants"]
        best = 0
        for et in energy_types:
            lvl = (
                db.query(func.max(Building.level))
                .join(Colony, Building.colony_id == Colony.id)
                .filter(Colony.user_id == user.id, Building.building_type == et)
                .scalar()
            ) or 0
            if lvl > best:
                best = lvl
        return {"done": best >= 1, "current": best, "target": 1}

    elif mtype == "research":
        tt = mission["tech_type"]
        target = mission["target_level"]
        level = (
            db.query(Research.level)
            .filter(Research.user_id == user.id, Research.tech_type == tt)
            .scalar()
        ) or 0
        return {"done": level >= target, "current": level, "target": target}

    elif mtype == "ship":
        st = mission["ship_type"]
        target = mission["target_count"]
        total = sum(
            fleet.get_ship_count(st)
            for fleet in db.query(Fleet).filter(Fleet.user_id == user.id).all()
        )
        return {"done": total >= target, "current": total, "target": target}

    elif mtype == "defense_any":
        target = mission["target_level"]
        best = (
            db.query(func.max(Defense.level))
            .join(Colony, Defense.colony_id == Colony.id)
            .filter(Colony.user_id == user.id)
            .scalar()
        ) or 0
        return {"done": best >= target, "current": best, "target": target}

    elif mtype == "colony_count":
        target = mission["target_count"]
        count = db.query(func.count(Colony.id)).filter(Colony.user_id == user.id).scalar() or 0
        return {"done": count >= target, "current": count, "target": target}

    elif mtype == "trade_route":
        target = mission["target_count"]
        count = db.query(func.count(TradeRoute.id)).filter(TradeRoute.owner_id == user.id).scalar() or 0
        return {"done": count >= target, "current": count, "target": target}

    elif mtype == "move_fleet":
        # Check if player has moved a fleet (any fleet that is_moving or has arrived at non-home location)
        st = mission.get("ship_type", "corvettes")
        # Check if any fleet with that ship type has ever been sent (is_moving or at a different location)
        fleets = (
            db.query(Fleet)
            .filter(Fleet.user_id == user.id)
            .filter(
                (Fleet.is_moving == True) |
                (Fleet.location_planet_id != None) |
                (Fleet.origin_base_id != None)
            )
            .all()
        )
        moving = next((fleet for fleet in fleets if fleet.get_ship_count(st) >= 1), None)
        return {"done": moving is not None, "current": 1 if moving else 0, "target": 1}

    elif mtype == "move_combat_fleet":
        # Check if player has a moving/moved fleet with required ships
        req_ships = mission.get("required_ships", {})
        fleets = db.query(Fleet).filter(
            Fleet.user_id == user.id,
            (Fleet.is_moving == True) |
            (Fleet.location_planet_id != None) |
            (Fleet.origin_base_id != None)
        ).all()
        for f in fleets:
            has_all = True
            for ship_type, count in req_ships.items():
                if f.get_ship_count(ship_type) < count:
                    has_all = False
                    break
            if has_all:
                return {"done": True, "current": 1, "target": 1}
        return {"done": False, "current": 0, "target": 1}

    return {"done": False, "current": 0, "target": 0}
