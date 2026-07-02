"""
Guild / Alliance system routes and guild board.
Split from routes_admin.py for readability.
"""
from fastapi import HTTPException, Depends
from sqlalchemy.orm import Session
from datetime import datetime, timedelta
from typing import Optional

from models import (User, Guild, GuildMember, GuildBoardPost, GuildApplication,
                    GuildLog, GuildHistorySnapshot, CreateGuildRequest)
from auth import (get_token_from_header, get_current_user, get_config_float, get_db,
                  get_effective_ship_spec, get_effective_research_spec, log_event)
from game_logic import calc_base_stats, calc_player_level, calc_economy_rate
from specs import ALL_SHIP_TYPES


GUILD_GRAPH_VIEW_META = {
    "level": {"label": "Level", "field": "guild_level"},
    "members": {"label": "Members", "field": "member_count"},
    "economy": {"label": "Economy", "field": "total_economy"},
    "fleet": {"label": "Fleet", "field": "total_fleet"},
    "technology": {"label": "Technology", "field": "total_technology"},
    "comb_exp": {"label": "Combat Experience", "field": "total_experience"},
}


def _guild_log(db, guild_id, done_by_id, description, member_name=""):
    """Add an entry to the guild log."""
    entry = GuildLog(guild_id=guild_id, done_by_id=done_by_id,
                     description=description, member_name=member_name)
    db.add(entry)


def _compute_guild_summary(db: Session, guild: Guild, game_speed: Optional[float] = None):
    """Compute the live guild totals used by lists, profile pages, and graph snapshots."""
    if game_speed is None:
        game_speed = get_config_float(db, "game_speed", 1.0)
    members = db.query(GuildMember).filter(GuildMember.guild_id == guild.id).all()
    member_list = []
    total_econ = 0.0
    total_fleet = 0.0
    total_tech = 0.0
    total_xp = 0.0
    for membership in members:
        user = db.query(User).filter(User.id == membership.user_id).first()
        if not user:
            continue
        member_econ = sum(calc_base_stats(c, user, game_speed)["economy"] for c in user.colonies)
        member_fleet = sum(
            sum(f.get_ship_count(st) * get_effective_ship_spec(db, st).get("cost", 0) for st in ALL_SHIP_TYPES)
            for f in user.fleets
        )
        member_tech = sum(
            get_effective_research_spec(db, r.tech_type).get("base_cost", 0)
            * (get_effective_research_spec(db, r.tech_type).get("cost_mult", 2) ** r.level - 1)
            for r in user.research if r.level > 0
        )
        member_level = calc_player_level(user, db, game_speed)
        member_xp = round(user.experience or 0, 0)
        last_active = user.last_seen or user.last_collected or user.created_at
        inactivity_mins = int((datetime.utcnow() - last_active).total_seconds() / 60) if last_active else 0
        total_econ += member_econ
        total_fleet += member_fleet
        total_tech += member_tech
        total_xp += member_xp
        member_list.append({
            "id": user.id,
            "username": user.username,
            "rank": membership.rank,
            "title": membership.title or "",
            "permissions": membership.permissions or "",
            "level": member_level,
            "economy": member_econ,
            "fleet": member_fleet,
            "technology": round(member_tech),
            "experience": member_xp,
            "inactivity_mins": inactivity_mins,
            "joined_at": membership.joined_at.isoformat() if membership.joined_at else None,
        })
    member_list.sort(key=lambda x: x["level"], reverse=True)
    guild_level = round(max(1, (total_econ * 100 + total_fleet) ** 0.25), 2)
    return {
        "members": member_list,
        "member_count": len(member_list),
        "total_economy": total_econ,
        "total_fleet": total_fleet,
        "total_technology": round(total_tech),
        "total_experience": round(total_xp),
        "guild_level": guild_level,
    }


def _guild_info_pages(guild: Guild):
    return [
        {"slot": 1, "title": guild.info_title_1 or "Info 1", "body": guild.info_body_1 or ""},
        {"slot": 2, "title": guild.info_title_2 or "Info 2", "body": guild.info_body_2 or ""},
        {"slot": 3, "title": guild.info_title_3 or "Info 3", "body": guild.info_body_3 or ""},
        {"slot": 4, "title": guild.info_title_4 or "Info 4", "body": guild.info_body_4 or ""},
    ]


def capture_guild_history_snapshots(db: Session, force: bool = False, now: Optional[datetime] = None):
    """Capture a live snapshot of all guild totals at most once per hour."""
    now = now or datetime.utcnow()
    latest = db.query(GuildHistorySnapshot).order_by(GuildHistorySnapshot.captured_at.desc()).first()
    if not force and latest and latest.captured_at and (now - latest.captured_at) < timedelta(hours=1):
        return False
    guilds = db.query(Guild).all()
    if not guilds:
        return False
    game_speed = get_config_float(db, "game_speed", 1.0)
    for guild in guilds:
        summary = _compute_guild_summary(db, guild, game_speed)
        db.add(GuildHistorySnapshot(
            guild_id=guild.id,
            captured_at=now,
            guild_level=summary["guild_level"],
            member_count=summary["member_count"],
            total_economy=summary["total_economy"],
            total_fleet=summary["total_fleet"],
            total_technology=summary["total_technology"],
            total_experience=summary["total_experience"],
        ))
    db.commit()
    return True


def _ensure_requested_guild_snapshots(db: Session, guild_ids: list[int], now: Optional[datetime] = None):
    """If a brand new guild has no graph history yet, seed it with one live point."""
    now = now or datetime.utcnow()
    guild_ids = [gid for gid in guild_ids if gid]
    if not guild_ids:
        return False
    existing_ids = {
        row[0] for row in db.query(GuildHistorySnapshot.guild_id)
        .filter(GuildHistorySnapshot.guild_id.in_(guild_ids))
        .distinct()
        .all()
    }
    missing_ids = [gid for gid in guild_ids if gid not in existing_ids]
    if not missing_ids:
        return False
    game_speed = get_config_float(db, "game_speed", 1.0)
    guilds = db.query(Guild).filter(Guild.id.in_(missing_ids)).all()
    for guild in guilds:
        summary = _compute_guild_summary(db, guild, game_speed)
        db.add(GuildHistorySnapshot(
            guild_id=guild.id,
            captured_at=now,
            guild_level=summary["guild_level"],
            member_count=summary["member_count"],
            total_economy=summary["total_economy"],
            total_fleet=summary["total_fleet"],
            total_technology=summary["total_technology"],
            total_experience=summary["total_experience"],
        ))
    db.commit()
    return bool(guilds)


def _month_floor(dt: datetime) -> datetime:
    return dt.replace(day=1, hour=0, minute=0, second=0, microsecond=0)


def _shift_month(dt: datetime, months: int) -> datetime:
    month_index = (dt.month - 1) + months
    year = dt.year + (month_index // 12)
    month = (month_index % 12) + 1
    return dt.replace(year=year, month=month, day=1, hour=0, minute=0, second=0, microsecond=0)


def register_guild_routes(app):

    # ======================== GUILD / ALLIANCE SYSTEM ========================

    @app.post("/api/guilds")
    def create_guild(req: CreateGuildRequest, token: str = Depends(get_token_from_header), db: Session = Depends(get_db)):
        user = get_current_user(token, db)
        existing = db.query(GuildMember).filter(GuildMember.user_id == user.id).first()
        if existing:
            raise HTTPException(400, "You are already in a guild. Leave your current guild first.")
        game_speed = get_config_float(db, "game_speed", 1.0)
        total_econ = sum(calc_base_stats(c, user, game_speed)["economy"] for c in user.colonies)
        if total_econ < 21:
            raise HTTPException(400, f"You need at least 21 economy to create a guild (you have {total_econ})")
        if len(req.name) < 2 or len(req.name) > 36:
            raise HTTPException(400, "Guild name must be 2-36 characters")
        if len(req.tag) < 1 or len(req.tag) > 5:
            raise HTTPException(400, "Guild tag must be 1-5 characters")
        tag_upper = req.tag.upper()
        if db.query(Guild).filter(Guild.name == req.name).first():
            raise HTTPException(400, "Guild name already taken")
        if db.query(Guild).filter(Guild.tag == tag_upper).first():
            raise HTTPException(400, "Guild tag already taken")
        guild = Guild(name=req.name, tag=tag_upper, description=req.description, leader_id=user.id)
        db.add(guild)
        db.flush()
        member = GuildMember(guild_id=guild.id, user_id=user.id, rank="leader", permissions="RKMITF+")
        db.add(member)
        _guild_log(db, guild.id, user.id, "Guild created", user.username)
        log_event(db, user.id, "guild", f"Created guild [{tag_upper}] {req.name}")
        db.commit()
        return {"success": True, "guild_id": guild.id}

    @app.get("/api/guilds")
    def list_guilds(db: Session = Depends(get_db)):
        guilds = db.query(Guild).all()
        game_speed = get_config_float(db, "game_speed", 1.0)
        result = []
        for g in guilds:
            summary = _compute_guild_summary(db, g, game_speed)
            result.append({
                "id": g.id, "name": g.name, "tag": g.tag,
                "description": g.description, "leader": g.leader.username if g.leader else "?",
                "members": summary["member_count"], "created_at": g.created_at.isoformat() if g.created_at else None,
                "total_economy": summary["total_economy"],
                "total_fleet": summary["total_fleet"],
                "guild_level": summary["guild_level"],
            })
        result.sort(key=lambda x: x["guild_level"], reverse=True)
        return result

    @app.get("/api/guilds/my")
    def my_guild(token: str = Depends(get_token_from_header), db: Session = Depends(get_db)):
        user = get_current_user(token, db)
        membership = db.query(GuildMember).filter(GuildMember.user_id == user.id).first()
        if not membership:
            return {"guild": None}
        guild = db.query(Guild).filter(Guild.id == membership.guild_id).first()
        if not guild:
            return {"guild": None}
        game_speed = get_config_float(db, "game_speed", 1.0)
        summary = _compute_guild_summary(db, guild, game_speed)
        member_list = []
        for member in summary["members"]:
            row = dict(member)
            row["inactivity_mins"] = member["inactivity_mins"] if membership.has_perm("+") else None
            member_list.append(row)
        # Count unread announcements
        unread_announcements = 0
        ann_query = db.query(GuildBoardPost).filter(
            GuildBoardPost.guild_id == guild.id,
            GuildBoardPost.folder == "announcements")
        if membership.last_announcement_seen:
            unread_announcements = ann_query.filter(
                GuildBoardPost.created_at > membership.last_announcement_seen).count()
        else:
            unread_announcements = ann_query.count()
        can_edit_internal = membership.has_perm("I")
        return {
            "guild": {
                "id": guild.id, "name": guild.name, "tag": guild.tag,
                "description": guild.description, "leader": guild.leader.username if guild.leader else "?",
                "homepage": guild.homepage or "", "forum_url": guild.forum_url or "",
                "created_at": guild.created_at.isoformat() if guild.created_at else None,
                "board_name_3": guild.board_name_3 or "Trade",
                "board_name_4": guild.board_name_4 or "Strategy",
                "my_rank": membership.rank, "members": member_list,
                "total_economy": summary["total_economy"],
                "total_fleet": summary["total_fleet"],
                "guild_level": summary["guild_level"],
                "member_count": summary["member_count"],
                "unread_announcements": unread_announcements,
                "can_edit_internal": can_edit_internal,
                "info_pages": _guild_info_pages(guild),
            }
        }

    @app.get("/api/guilds/{guild_id}/view")
    def view_guild(guild_id: int, token: str = Depends(get_token_from_header), db: Session = Depends(get_db)):
        """Public guild profile — anyone can view basic guild info and member list."""
        viewer = get_current_user(token, db)
        guild = db.query(Guild).filter(Guild.id == guild_id).first()
        if not guild:
            raise HTTPException(404, "Guild not found")
        game_speed = get_config_float(db, "game_speed", 1.0)
        summary = _compute_guild_summary(db, guild, game_speed)
        viewer_membership = db.query(GuildMember).filter(GuildMember.user_id == viewer.id).first()
        public_members = []
        for member in summary["members"]:
            row = dict(member)
            row["inactivity_mins"] = None
            public_members.append(row)
        return {
            "id": guild.id, "name": guild.name, "tag": guild.tag,
            "description": guild.description,
            "homepage": guild.homepage or "",
            "forum_url": guild.forum_url or "",
            "created_at": guild.created_at.isoformat() if guild.created_at else None,
            "leader": guild.leader.username if guild.leader else "?",
            "member_count": summary["member_count"],
            "members": public_members,
            "total_economy": summary["total_economy"],
            "total_fleet": summary["total_fleet"],
            "total_technology": summary["total_technology"],
            "total_experience": summary["total_experience"],
            "guild_level": summary["guild_level"],
            "info_pages": _guild_info_pages(guild),
            "viewer_in_guild": bool(viewer_membership),
            "viewer_same_guild": bool(viewer_membership and viewer_membership.guild_id == guild.id),
        }

    @app.post("/api/guilds/{guild_id}/edit")
    def edit_guild(guild_id: int, data: dict, token: str = Depends(get_token_from_header), db: Session = Depends(get_db)):
        user = get_current_user(token, db)
        guild = db.query(Guild).filter(Guild.id == guild_id).first()
        if not guild:
            raise HTTPException(404, "Guild not found")
        if guild.leader_id != user.id:
            raise HTTPException(403, "Only the guild leader can edit the guild")
        new_name = data.get("name", "").strip()
        new_tag = data.get("tag", "").strip().upper()
        new_desc = data.get("description", "")
        if len(new_name) < 2 or len(new_name) > 36:
            raise HTTPException(400, "Guild name must be 2-36 characters")
        if len(new_tag) < 1 or len(new_tag) > 5:
            raise HTTPException(400, "Guild tag must be 1-5 characters")
        if len(new_desc) > 1200:
            raise HTTPException(400, "Description too long (max 1200 chars)")
        now = datetime.utcnow()
        if new_name != guild.name:
            if guild.name_changed_at and (now - guild.name_changed_at).days < 7:
                days_left = 7 - (now - guild.name_changed_at).days
                raise HTTPException(400, f"Guild name can only be changed once per 7 days ({days_left} days remaining)")
            if db.query(Guild).filter(Guild.name == new_name, Guild.id != guild.id).first():
                raise HTTPException(400, "Guild name already taken")
            guild.name_changed_at = now
        if new_tag != guild.tag:
            if guild.tag_changed_at and (now - guild.tag_changed_at).days < 7:
                days_left = 7 - (now - guild.tag_changed_at).days
                raise HTTPException(400, f"Guild tag can only be changed once per 7 days ({days_left} days remaining)")
            if db.query(Guild).filter(Guild.tag == new_tag, Guild.id != guild.id).first():
                raise HTTPException(400, "Guild tag already taken")
            guild.tag_changed_at = now
        guild.name = new_name
        guild.tag = new_tag
        guild.description = new_desc
        if "homepage" in data:
            guild.homepage = data["homepage"][:64]
        if "forum_url" in data:
            guild.forum_url = data["forum_url"][:64]
        if "board_name_3" in data:
            guild.board_name_3 = data["board_name_3"][:20]
        if "board_name_4" in data:
            guild.board_name_4 = data["board_name_4"][:20]
        log_event(db, user.id, "guild", f"Edited guild [{new_tag}] {new_name}")
        db.commit()
        return {"success": True}

    @app.post("/api/guilds/{guild_id}/info/{slot}")
    def edit_guild_info(guild_id: int, slot: int, data: dict, token: str = Depends(get_token_from_header), db: Session = Depends(get_db)):
        user = get_current_user(token, db)
        membership = db.query(GuildMember).filter(GuildMember.user_id == user.id).first()
        if not membership or membership.guild_id != guild_id:
            raise HTTPException(403, "You are not in this guild")
        if not membership.has_perm("I"):
            raise HTTPException(403, "You need Internal (I) permission to edit guild pages")
        guild = db.query(Guild).filter(Guild.id == guild_id).first()
        if not guild:
            raise HTTPException(404, "Guild not found")
        if slot not in (1, 2, 3, 4):
            raise HTTPException(400, "Invalid info slot")
        title = (data.get("title") or f"Info {slot}").strip()
        body = data.get("body") or ""
        if len(title) > 30:
            raise HTTPException(400, "Title too long (max 30 characters)")
        if len(body) > 5000:
            raise HTTPException(400, "Body too long (max 5000 characters)")
        setattr(guild, f"info_title_{slot}", title or f"Info {slot}")
        setattr(guild, f"info_body_{slot}", body)
        _guild_log(db, guild.id, user.id, f"Updated guild info page {slot}", user.username)
        log_event(db, user.id, "guild", f"Updated guild info page {slot} for [{guild.tag}]")
        db.commit()
        return {"success": True, "slot": slot, "title": getattr(guild, f"info_title_{slot}"), "body": getattr(guild, f"info_body_{slot}")}

    @app.post("/api/guilds/{guild_id}/join")
    def apply_to_guild(guild_id: int, token: str = Depends(get_token_from_header), db: Session = Depends(get_db)):
        """Apply to join a guild (pending approval by R-perm member)."""
        user = get_current_user(token, db)
        existing = db.query(GuildMember).filter(GuildMember.user_id == user.id).first()
        if existing:
            raise HTTPException(400, "You are already in a guild")
        guild = db.query(Guild).filter(Guild.id == guild_id).first()
        if not guild:
            raise HTTPException(404, "Guild not found")
        # Check for existing application
        existing_app = db.query(GuildApplication).filter(
            GuildApplication.guild_id == guild.id, GuildApplication.user_id == user.id).first()
        if existing_app:
            raise HTTPException(400, "You already have a pending application to this guild")
        app_entry = GuildApplication(guild_id=guild.id, user_id=user.id)
        db.add(app_entry)
        db.commit()
        return {"success": True, "message": "Application submitted. Waiting for approval."}

    @app.get("/api/guilds/applications")
    def get_applications(token: str = Depends(get_token_from_header), db: Session = Depends(get_db)):
        """Get pending applications for my guild (R-perm required)."""
        user = get_current_user(token, db)
        membership = db.query(GuildMember).filter(GuildMember.user_id == user.id).first()
        if not membership or not membership.has_perm("R"):
            return {"applications": []}
        apps = db.query(GuildApplication).filter(GuildApplication.guild_id == membership.guild_id).all()
        result = []
        for a in apps:
            u = db.query(User).filter(User.id == a.user_id).first()
            if u:
                result.append({
                    "id": a.id, "user_id": u.id, "username": u.username,
                    "applied_at": a.applied_at.isoformat() if a.applied_at else None,
                })
        return {"applications": result}

    @app.post("/api/guilds/applications/{app_id}/accept")
    def accept_application(app_id: int, token: str = Depends(get_token_from_header), db: Session = Depends(get_db)):
        """Accept a guild application (R-perm required)."""
        user = get_current_user(token, db)
        membership = db.query(GuildMember).filter(GuildMember.user_id == user.id).first()
        if not membership or not membership.has_perm("R"):
            raise HTTPException(403, "You need Recruit (R) permission to accept applications")
        application = db.query(GuildApplication).filter(GuildApplication.id == app_id).first()
        if not application:
            raise HTTPException(404, "Application not found")
        if application.guild_id != membership.guild_id:
            raise HTTPException(403, "Not your guild's application")
        # Check applicant isn't already in a guild
        existing = db.query(GuildMember).filter(GuildMember.user_id == application.user_id).first()
        if existing:
            db.delete(application)
            db.commit()
            raise HTTPException(400, "Player is already in a guild")
        applicant = db.query(User).filter(User.id == application.user_id).first()
        if not applicant:
            db.delete(application)
            db.commit()
            raise HTTPException(404, "Player not found")
        # Add as member
        member = GuildMember(guild_id=membership.guild_id, user_id=applicant.id, rank="member", permissions="")
        db.add(member)
        db.delete(application)
        _guild_log(db, membership.guild_id, user.id, "Accept member", applicant.username)
        log_event(db, applicant.id, "guild", f"Accepted into guild by {user.username}")
        db.commit()
        return {"success": True}

    @app.post("/api/guilds/applications/{app_id}/reject")
    def reject_application(app_id: int, token: str = Depends(get_token_from_header), db: Session = Depends(get_db)):
        """Reject a guild application (R-perm required)."""
        user = get_current_user(token, db)
        membership = db.query(GuildMember).filter(GuildMember.user_id == user.id).first()
        if not membership or not membership.has_perm("R"):
            raise HTTPException(403, "You need Recruit (R) permission to reject applications")
        application = db.query(GuildApplication).filter(GuildApplication.id == app_id).first()
        if not application:
            raise HTTPException(404, "Application not found")
        if application.guild_id != membership.guild_id:
            raise HTTPException(403, "Not your guild's application")
        applicant = db.query(User).filter(User.id == application.user_id).first()
        db.delete(application)
        _guild_log(db, membership.guild_id, user.id, "Reject application",
                   applicant.username if applicant else "?")
        db.commit()
        return {"success": True}

    @app.get("/api/guilds/log")
    def get_guild_log(token: str = Depends(get_token_from_header), db: Session = Depends(get_db)):
        """Get guild activity log."""
        user = get_current_user(token, db)
        membership = db.query(GuildMember).filter(GuildMember.user_id == user.id).first()
        if not membership:
            return {"logs": []}
        logs = (db.query(GuildLog)
            .filter(GuildLog.guild_id == membership.guild_id)
            .order_by(GuildLog.created_at.desc())
            .limit(100).all())
        result = []
        for log in logs:
            done_by_name = log.done_by.username if log.done_by else "System"
            result.append({
                "date": log.created_at.isoformat() if log.created_at else None,
                "done_by": done_by_name,
                "description": log.description,
                "member": log.member_name,
            })
        return {"logs": result}

    @app.get("/api/guilds/graphs")
    def get_guild_graphs(
        view: str = "level",
        scale: str = "days",
        guild0: Optional[int] = None,
        guild1: Optional[int] = None,
        guild2: Optional[int] = None,
        guild3: Optional[int] = None,
        guild4: Optional[int] = None,
        guild5: Optional[int] = None,
        token: str = Depends(get_token_from_header),
        db: Session = Depends(get_db),
    ):
        """Guild historical graphs — compare view with up to 6 guild IDs."""
        user = get_current_user(token, db)
        membership = db.query(GuildMember).filter(GuildMember.user_id == user.id).first()
        view = view if view in GUILD_GRAPH_VIEW_META else "level"
        scale = "months" if scale == "months" else "days"

        slot_ids = [guild0, guild1, guild2, guild3, guild4, guild5]
        if not any(slot_ids) and membership:
            slot_ids[0] = membership.guild_id
        guild_ids = [gid for gid in slot_ids if gid]

        now = datetime.utcnow()
        capture_guild_history_snapshots(db, force=False, now=now)
        _ensure_requested_guild_snapshots(db, guild_ids, now=now)

        guilds_by_id = {}
        if guild_ids:
            guilds_by_id = {g.id: g for g in db.query(Guild).filter(Guild.id.in_(guild_ids)).all()}

        if scale == "months":
            end_bucket = _month_floor(now)
            bucket_starts = [_shift_month(end_bucket, offset) for offset in range(-11, 1)]
            labels = [b.strftime("%b") for b in bucket_starts]
            bucket_index = {(b.year, b.month): idx for idx, b in enumerate(bucket_starts)}
            start_cutoff = bucket_starts[0]
        else:
            end_bucket = now.replace(hour=0, minute=0, second=0, microsecond=0)
            bucket_starts = [end_bucket - timedelta(days=offset) for offset in range(30, -1, -1)]
            labels = [str(int(b.strftime("%d"))) for b in bucket_starts]
            bucket_index = {b.date(): idx for idx, b in enumerate(bucket_starts)}
            start_cutoff = bucket_starts[0]

        snapshots = []
        if guild_ids:
            snapshots = (
                db.query(GuildHistorySnapshot)
                .filter(
                    GuildHistorySnapshot.guild_id.in_(guild_ids),
                    GuildHistorySnapshot.captured_at >= start_cutoff,
                )
                .order_by(GuildHistorySnapshot.captured_at.asc())
                .all()
            )

        field = GUILD_GRAPH_VIEW_META[view]["field"]
        series_by_guild = {gid: [None] * len(labels) for gid in guild_ids if gid in guilds_by_id}
        for snap in snapshots:
            if snap.guild_id not in series_by_guild:
                continue
            if scale == "months":
                idx = bucket_index.get((snap.captured_at.year, snap.captured_at.month))
            else:
                idx = bucket_index.get(snap.captured_at.date())
            if idx is None:
                continue
            value = getattr(snap, field, None)
            series_by_guild[snap.guild_id][idx] = round(value, 2) if isinstance(value, float) else value

        compare_slots = []
        for idx, gid in enumerate(slot_ids):
            guild = guilds_by_id.get(gid) if gid else None
            compare_slots.append({
                "index": idx,
                "guild_id": gid,
                "tag": guild.tag if guild else "",
                "name": guild.name if guild else "",
            })

        datasets = []
        for gid in slot_ids:
            guild = guilds_by_id.get(gid) if gid else None
            if not guild:
                continue
            datasets.append({
                "guild_id": gid,
                "tag": guild.tag,
                "name": guild.name,
                "values": series_by_guild.get(gid, [None] * len(labels)),
            })

        return {
            "view": view,
            "scale": scale,
            "title": GUILD_GRAPH_VIEW_META[view]["label"],
            "x_label": "Months" if scale == "months" else "Days",
            "labels": labels,
            "compare_slots": compare_slots,
            "datasets": datasets,
            "current_guild_id": membership.guild_id if membership else None,
        }

    @app.post("/api/guilds/leave")
    def leave_guild(token: str = Depends(get_token_from_header), db: Session = Depends(get_db)):
        user = get_current_user(token, db)
        membership = db.query(GuildMember).filter(GuildMember.user_id == user.id).first()
        if not membership:
            raise HTTPException(400, "You are not in a guild")
        guild = db.query(Guild).filter(Guild.id == membership.guild_id).first()
        if membership.rank == "leader":
            other_members = db.query(GuildMember).filter(GuildMember.guild_id == membership.guild_id, GuildMember.user_id != user.id).all()
            if other_members:
                new_leader = other_members[0]
                new_leader.rank = "leader"
                if guild:
                    guild.leader_id = new_leader.user_id
            else:
                db.query(GuildMember).filter(GuildMember.guild_id == membership.guild_id).delete()
                if guild:
                    db.delete(guild)
                db.commit()
                return {"success": True, "message": "Guild disbanded (you were the last member)"}
        _guild_log(db, membership.guild_id, user.id, "Member left guild", user.username)
        db.delete(membership)
        log_event(db, user.id, "guild", f"Left guild [{guild.tag if guild else '?'}]")
        db.commit()
        return {"success": True}

    @app.post("/api/guilds/kick")
    def kick_from_guild(data: dict, token: str = Depends(get_token_from_header), db: Session = Depends(get_db)):
        user = get_current_user(token, db)
        my_membership = db.query(GuildMember).filter(GuildMember.user_id == user.id).first()
        if not my_membership or not my_membership.has_perm("K"):
            raise HTTPException(403, "You need Kick (K) permission to kick members")
        target_name = data.get("username", "")
        target = db.query(User).filter(User.username == target_name).first()
        if not target:
            raise HTTPException(404, "Player not found")
        target_membership = db.query(GuildMember).filter(GuildMember.guild_id == my_membership.guild_id, GuildMember.user_id == target.id).first()
        if not target_membership:
            raise HTTPException(400, "Player is not in your guild")
        if target_membership.rank == "leader":
            raise HTTPException(400, "Cannot kick the guild leader")
        if target_membership.rank == "vice_leader" and my_membership.rank != "leader":
            raise HTTPException(400, "Only the guild leader can kick a Vice Leader")
        _guild_log(db, my_membership.guild_id, user.id, "Kick member", target.username)
        db.delete(target_membership)
        # Also delete any pending applications from kicked user
        db.query(GuildApplication).filter(
            GuildApplication.guild_id == my_membership.guild_id,
            GuildApplication.user_id == target.id).delete()
        log_event(db, target.id, "guild", f"Kicked from guild by {user.username}")
        db.commit()
        return {"success": True}

    @app.post("/api/guilds/promote")
    def promote_member(data: dict, token: str = Depends(get_token_from_header), db: Session = Depends(get_db)):
        """Set rank and/or permissions for a guild member."""
        user = get_current_user(token, db)
        my_membership = db.query(GuildMember).filter(GuildMember.user_id == user.id).first()
        if not my_membership or not my_membership.has_perm("T"):
            raise HTTPException(403, "You need Titles (T) permission to manage members")
        target_name = data.get("username", "")
        target = db.query(User).filter(User.username == target_name).first()
        if not target:
            raise HTTPException(404, "Player not found")
        target_membership = db.query(GuildMember).filter(GuildMember.guild_id == my_membership.guild_id, GuildMember.user_id == target.id).first()
        if not target_membership:
            raise HTTPException(400, "Player is not in your guild")
        if target_membership.rank == "leader":
            raise HTTPException(400, "Cannot modify the guild leader")
        if "rank" in data:
            new_rank = data["rank"]
            if new_rank not in ("vice_leader", "member"):
                raise HTTPException(400, "Invalid rank (vice_leader or member)")
            if new_rank == "vice_leader" and my_membership.rank != "leader":
                raise HTTPException(403, "Only the guild leader can appoint Vice Leaders")
            target_membership.rank = new_rank
        if "permissions" in data:
            valid_flags = set("RKMITF+-")
            new_perms = "".join(c for c in data["permissions"].upper() if c in valid_flags)
            if my_membership.rank != "leader":
                my_perms = set(my_membership.permissions or "")
                for flag in new_perms:
                    if flag not in my_perms:
                        raise HTTPException(403, f"You cannot grant the '{flag}' permission (you don't have it)")
            target_membership.permissions = new_perms
        if "title" in data:
            target_membership.title = data["title"][:30]
        old_perms = data.get("old_permissions", "")
        new_perms_display = target_membership.permissions or ""
        _guild_log(db, my_membership.guild_id, user.id,
                   f"Permissions changed from ({old_perms}) to ({new_perms_display})", target_name)
        db.commit()
        return {"success": True}

    # ======================== GUILD BOARD ========================

    @app.get("/api/guilds/board")
    def get_guild_board(folder: str = "general", token: str = Depends(get_token_from_header), db: Session = Depends(get_db)):
        """Get guild board posts by folder."""
        user = get_current_user(token, db)
        membership = db.query(GuildMember).filter(GuildMember.user_id == user.id).first()
        if not membership:
            return {"posts": [], "folder": folder}
        # Auto-delete posts older than 5 days
        cutoff = datetime.utcnow() - timedelta(days=5)
        db.query(GuildBoardPost).filter(
            GuildBoardPost.guild_id == membership.guild_id,
            GuildBoardPost.created_at < cutoff,
        ).delete()
        db.commit()
        valid_folders = ("general", "announcements", "combat", "trade", "strategy")
        if folder not in valid_folders:
            folder = "general"
        # Mark announcements as seen
        if folder == "announcements":
            membership.last_announcement_seen = datetime.utcnow()
            db.commit()
        posts = db.query(GuildBoardPost).filter(
            GuildBoardPost.guild_id == membership.guild_id,
            GuildBoardPost.folder == folder,
        ).order_by(GuildBoardPost.created_at.desc()).limit(50).all()
        result = []
        for p in posts:
            result.append({
                "id": p.id,
                "folder": p.folder,
                "author": p.author.username if p.author else "System",
                "body": p.body,
                "battle_report_id": p.battle_report_id,
                "likes": p.likes,
                "created_at": p.created_at.isoformat() if p.created_at else None,
            })
        return {"posts": result, "folder": folder}

    @app.post("/api/guilds/board")
    def post_to_guild_board(data: dict, token: str = Depends(get_token_from_header), db: Session = Depends(get_db)):
        """Post to guild board."""
        user = get_current_user(token, db)
        membership = db.query(GuildMember).filter(GuildMember.user_id == user.id).first()
        if not membership:
            raise HTTPException(400, "You are not in a guild")
        folder = data.get("folder", "general")
        body = data.get("body", "").strip()
        if not body:
            raise HTTPException(400, "Post body cannot be empty")
        if len(body) > 5000:
            raise HTTPException(400, "Post body too long (max 5000 characters)")
        valid_folders = ("general", "announcements", "combat", "trade", "strategy")
        if folder not in valid_folders:
            folder = "general"
        if folder == "announcements" and not membership.has_perm("M"):
            raise HTTPException(403, "You need Announcements (M) permission to post here")
        post = GuildBoardPost(
            guild_id=membership.guild_id,
            folder=folder,
            author_id=user.id,
            body=body,
        )
        db.add(post)
        db.commit()
        return {"success": True, "post_id": post.id}

    @app.delete("/api/guilds/board/{post_id}")
    def delete_board_post(post_id: int, token: str = Depends(get_token_from_header), db: Session = Depends(get_db)):
        """Delete a board post."""
        user = get_current_user(token, db)
        post = db.query(GuildBoardPost).filter(GuildBoardPost.id == post_id).first()
        if not post:
            raise HTTPException(404, "Post not found")
        membership = db.query(GuildMember).filter(GuildMember.user_id == user.id, GuildMember.guild_id == post.guild_id).first()
        if not membership:
            raise HTTPException(403, "Not your guild")
        if post.author_id != user.id and not membership.has_perm("M"):
            raise HTTPException(403, "Only the author or members with Announcements (M) permission can delete posts")
        db.delete(post)
        db.commit()
        return {"success": True}
