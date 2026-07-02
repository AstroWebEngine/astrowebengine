"""Auth endpoints: register and login."""
from fastapi import HTTPException, Depends
from sqlalchemy.orm import Session
from datetime import datetime, timedelta

from models import User, UserCreate, UserLogin
from auth import (
    get_config, get_config_float, get_config_int,
    hash_password, verify_password, create_access_token, get_db,
)
from universe import _assign_homeworld
from resources import seed_starting_resources


def register_auth_routes(app):

    @app.post("/api/register")
    def register(req: UserCreate, db: Session = Depends(get_db)):
        reg_open = get_config(db, "registration_open", "true")
        if reg_open.lower() != "true":
            raise HTTPException(403, "Registration is closed")
        max_players = get_config_int(db, "max_players", 100)
        current_count = db.query(User).count()
        is_first = current_count == 0
        if db.query(User).filter(User.username == req.username).first():
            raise HTTPException(400, "Username taken")
        if db.query(User).filter(User.email == req.email).first():
            raise HTTPException(400, "Email already registered")
        # Admin is the first account — plays normally but hidden from leaderboard
        if is_first:
            starting_credits = get_config_float(db, "starting_credits", 500)
            newbie_days = get_config_int(db, "newbie_protection_days", 7)
            user = User(
                username=req.username,
                email=req.email,
                hashed_password=hash_password(req.password),
                is_admin=True,
                credits=starting_credits,
                newbie_protection_until=datetime.utcnow() + timedelta(days=newbie_days) if newbie_days > 0 else None,
            )
            db.add(user)
            seed_starting_resources(user)  # multi-resource economies: starting stash
            db.commit()
            db.refresh(user)
            token = create_access_token({"sub": str(user.id)})
            needs_galaxy = get_config(db, "game_status") == "active"
            return {"access_token": token, "username": user.username, "is_admin": True, "needs_galaxy_select": needs_galaxy}
        # Normal player registration
        player_count = db.query(User).filter(User.is_admin == False, User.is_bot == False).count()
        if player_count >= max_players:
            raise HTTPException(403, "Server is full")
        starting_credits = get_config_float(db, "starting_credits", 500)
        newbie_days = get_config_int(db, "newbie_protection_days", 7)
        user = User(
            username=req.username,
            email=req.email,
            hashed_password=hash_password(req.password),
            is_admin=False,
            credits=starting_credits,
            newbie_protection_until=datetime.utcnow() + timedelta(days=newbie_days) if newbie_days > 0 else None,
        )
        db.add(user)
        seed_starting_resources(user)  # multi-resource economies: starting stash
        db.commit()
        db.refresh(user)
        token = create_access_token({"sub": str(user.id)})
        needs_galaxy = get_config(db, "game_status") == "active"
        return {
            "access_token": token,
            "username": user.username,
            "is_admin": False,
            "needs_galaxy_select": needs_galaxy,
        }

    @app.post("/api/login")
    def login(req: UserLogin, db: Session = Depends(get_db)):
        user = db.query(User).filter(User.email == req.email).first()
        if not user or not verify_password(req.password, user.hashed_password):
            raise HTTPException(401, "Invalid credentials")
        token = create_access_token({"sub": str(user.id)})
        # Check if player still needs to pick a galaxy or do the tutorial
        from models import Colony, TutorialProgress
        has_base = db.query(Colony).filter(Colony.user_id == user.id).first() is not None
        # Only redirect to tutorial/galaxy select for players without a base (new accounts)
        needs_galaxy = not has_base
        tp = db.query(TutorialProgress).filter(TutorialProgress.user_id == user.id).first()
        needs_tutorial = needs_galaxy and tp is not None and not tp.is_finished
        return {
            "access_token": token,
            "username": user.username,
            "is_admin": user.is_admin,
            "needs_galaxy_select": needs_galaxy,
            "needs_tutorial": needs_tutorial,
        }
