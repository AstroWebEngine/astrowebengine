from fastapi import HTTPException, Depends, Query
from sqlalchemy.orm import Session
from datetime import datetime
from models import User, Colony, Planet, Message, Contact, Guild, GuildMember, GuildBoardPost, EventLog, Bookmark, BugReport, CreditLog, FleetAuditLog
from auth import (get_token_from_header, get_current_user, get_config, get_config_float,
                  set_config, get_db, hash_password, verify_password, log_event)
from game_logic import (calc_base_stats, calc_economy_rate, _fleet_total_ships, _fleet_value,
                        calc_player_level, calc_total_production, calc_max_fleet_size,
                        calc_colony_cost, apply_colony_reserve, calc_max_fleet_count, calc_tech_cost)
from resources import get_user_resources
from config_defaults import NEWBIE_PROTECTION_LEVEL
from pydantic import BaseModel
import logging


class BookmarkCreate(BaseModel):
    name: str
    planet_id: int

class BookmarkByCoords(BaseModel):
    name: str
    coords: str

class SendMessageRequest(BaseModel):
    recipient: str
    subject: str
    body: str

class ChangePasswordRequest(BaseModel):
    old_password: str
    new_password: str


def register_social_routes(app):

    # ======================== LEADERBOARD ========================

    @app.get("/api/leaderboard")
    def leaderboard(db: Session = Depends(get_db)):
        users = db.query(User).filter(User.is_admin == False, User.is_bot == False).order_by(User.score.desc()).limit(50).all()
        game_speed = get_config_float(db, "game_speed", 1.0)
        result = []
        for u in users:
            base_count = len(u.colonies)
            total_ships = sum(_fleet_total_ships(f) for f in u.fleets)
            total_econ = sum(calc_base_stats(c, u, game_speed)["economy"] for c in u.colonies)
            total_fleet_val = sum(_fleet_value(f, db) for f in u.fleets)
            total_tech = round(calc_tech_cost(u, db))
            level = round((total_econ * 100 + total_fleet_val + total_tech) ** 0.25, 1)
            protection_broken = bool(u.protection_broken_until and u.protection_broken_until > datetime.utcnow())
            result.append({
                "username": u.username,
                "score": u.score,
                "credits": round(u.credits, 0),
                "bases": base_count,
                "ships": total_ships,
                "level": level,
                "experience": round(u.experience, 0),
                "economy": total_econ,
                "technology": total_tech,
                "fleet_value": total_fleet_val,
                "protection_broken": protection_broken,
            })
        return result

    # ======================== WIN CONDITION CHECK ========================

    @app.get("/api/game/check-win")
    def check_win(db: Session = Depends(get_db)):
        if get_config(db, "game_status") != "active":
            return {"winner": None}
        condition = get_config(db, "win_condition", "domination")
        winner = None

        # A behavioral mod may fully own victory logic (e.g. annihilation /
        # time_limit conditions the core doesn't implement). If it returns a
        # result, it replaces the built-in checks.
        import mod_hooks
        override = mod_hooks.fire_override("compute_victory", {"db": db, "condition": condition})
        if override is not None:
            winner = override.get("winner") if isinstance(override, dict) else override
            if winner:
                set_config(db, "game_status", "finished")
                set_config(db, "winner", winner)
            return {"winner": winner}

        if condition == "none":
            return {"winner": None}
        elif condition == "domination":
            threshold = get_config_float(db, "domination_threshold", 0.75)
            total_colonized = db.query(Planet).filter(Planet.is_colonized == True).count()
            if total_colonized > 0:
                users = db.query(User).filter(User.is_admin == False, User.is_bot == False).all()
                for u in users:
                    user_bases = len(u.colonies)
                    if user_bases / total_colonized >= threshold:
                        winner = u.username
                        break
        elif condition == "economic":
            target = get_config_float(db, "economic_target", 100000)
            user = db.query(User).filter(
                User.is_admin == False,
                User.is_bot == False,
                User.credits >= target,
            ).order_by(User.credits.desc()).first()
            if user:
                winner = user.username
        elif condition == "annihilation":
            # Last team (guild, else solo player) still holding a base. Only
            # reachable when a ruleset enables conquest capture (occupation_capture).
            import conquest
            winner = conquest.last_team_standing_winner(db)

        if winner:
            set_config(db, "game_status", "finished")
            set_config(db, "winner", winner)
        return {"winner": winner}

    # ======================== MESSAGING SYSTEM ========================

    @app.get("/api/messages")
    def get_messages(token: str = Depends(get_token_from_header), db: Session = Depends(get_db)):
        user = get_current_user(token, db)
        msgs = db.query(Message).filter(Message.recipient_id == user.id).order_by(Message.created_at.desc()).limit(50).all()
        return [{
            "id": m.id,
            "sender": m.sender.username if m.sender else "System",
            "subject": m.subject,
            "body": m.body,
            "is_read": m.is_read,
            "created_at": m.created_at.isoformat() if m.created_at else None,
        } for m in msgs]

    @app.get("/api/messages/sent")
    def get_sent_messages(token: str = Depends(get_token_from_header), db: Session = Depends(get_db)):
        user = get_current_user(token, db)
        msgs = db.query(Message).filter(Message.sender_id == user.id).order_by(Message.created_at.desc()).limit(50).all()
        return [{
            "id": m.id,
            "recipient": m.recipient.username if m.recipient else "Unknown",
            "subject": m.subject,
            "body": m.body,
            "created_at": m.created_at.isoformat() if m.created_at else None,
        } for m in msgs]

    @app.get("/api/messages/unread-count")
    def get_unread_count(token: str = Depends(get_token_from_header), db: Session = Depends(get_db)):
        user = get_current_user(token, db)
        count = db.query(Message).filter(Message.recipient_id == user.id, Message.is_read == False).count()
        return {"count": count}

    @app.post("/api/messages")
    def send_message(req: SendMessageRequest, token: str = Depends(get_token_from_header), db: Session = Depends(get_db)):
        user = get_current_user(token, db)
        recipient = db.query(User).filter(User.username == req.recipient).first()
        if not recipient:
            raise HTTPException(404, "Recipient not found")
        if recipient.id == user.id:
            raise HTTPException(400, "Cannot message yourself")
        if len(req.body) > 5000:
            raise HTTPException(400, "Message too long (max 5000 chars)")
        msg = Message(sender_id=user.id, recipient_id=recipient.id, subject=req.subject[:200], body=req.body[:5000])
        db.add(msg)
        db.commit()
        return {"success": True, "id": msg.id}

    @app.post("/api/messages/{message_id}/read")
    def mark_message_read(message_id: int, token: str = Depends(get_token_from_header), db: Session = Depends(get_db)):
        user = get_current_user(token, db)
        msg = db.query(Message).filter(Message.id == message_id, Message.recipient_id == user.id).first()
        if not msg:
            raise HTTPException(404, "Message not found")
        msg.is_read = True
        db.commit()
        return {"success": True}

    @app.delete("/api/messages/{message_id}")
    def delete_message(message_id: int, token: str = Depends(get_token_from_header), db: Session = Depends(get_db)):
        user = get_current_user(token, db)
        msg = db.query(Message).filter(Message.id == message_id, Message.recipient_id == user.id).first()
        if not msg:
            raise HTTPException(404, "Message not found")
        db.delete(msg)
        db.commit()
        return {"success": True}

    @app.get("/api/messages/saved")
    def get_saved_messages(token: str = Depends(get_token_from_header), db: Session = Depends(get_db)):
        user = get_current_user(token, db)
        msgs = db.query(Message).filter(Message.recipient_id == user.id, Message.is_saved == True).order_by(Message.created_at.desc()).limit(50).all()
        return [{
            "id": m.id,
            "sender": m.sender.username if m.sender else "System",
            "subject": m.subject,
            "body": m.body,
            "is_read": m.is_read,
            "created_at": m.created_at.isoformat() if m.created_at else None,
        } for m in msgs]

    @app.post("/api/messages/{message_id}/save")
    def save_message(message_id: int, token: str = Depends(get_token_from_header), db: Session = Depends(get_db)):
        user = get_current_user(token, db)
        msg = db.query(Message).filter(Message.id == message_id, Message.recipient_id == user.id).first()
        if not msg:
            raise HTTPException(404, "Message not found")
        msg.is_saved = True
        db.commit()
        return {"success": True}

    @app.post("/api/messages/{message_id}/copy-to-board")
    def copy_msg_to_board(message_id: int, token: str = Depends(get_token_from_header), db: Session = Depends(get_db)):
        """Copy a battle report message to the guild board (combat folder)."""
        user = get_current_user(token, db)
        msg = db.query(Message).filter(Message.id == message_id, Message.recipient_id == user.id).first()
        if not msg:
            raise HTTPException(404, "Message not found")
        membership = db.query(GuildMember).filter(GuildMember.user_id == user.id).first()
        if not membership:
            raise HTTPException(400, "You are not in a guild")
        post = GuildBoardPost(
            guild_id=membership.guild_id,
            folder="combat",
            author_id=user.id,
            body=f"[b]{msg.subject}[/b]\n\n{msg.body}",
        )
        db.add(post)
        db.commit()
        return {"success": True}

    @app.post("/api/messages/delete-all")
    def delete_all_messages(token: str = Depends(get_token_from_header), db: Session = Depends(get_db)):
        user = get_current_user(token, db)
        db.query(Message).filter(Message.recipient_id == user.id, Message.is_saved == False).delete()
        db.commit()
        return {"success": True}

    # ======================== CONTACTS ========================

    @app.get("/api/contacts")
    def get_contacts(token: str = Depends(get_token_from_header), db: Session = Depends(get_db)):
        user = get_current_user(token, db)
        contacts = db.query(Contact).filter(Contact.user_id == user.id).order_by(Contact.added_at.desc()).all()
        return [{
            "id": c.id,
            "username": c.contact_user.username if c.contact_user else "Unknown",
            "note": c.note,
            "added_at": c.added_at.isoformat() if c.added_at else None,
        } for c in contacts]

    @app.post("/api/contacts")
    def add_contact(data: dict, token: str = Depends(get_token_from_header), db: Session = Depends(get_db)):
        user = get_current_user(token, db)
        note = (data.get("note") or "").strip()[:100]
        # Accept user_id or username
        target = None
        if data.get("user_id"):
            target = db.query(User).filter(User.id == int(data["user_id"])).first()
        elif data.get("username"):
            target = db.query(User).filter(User.username == data["username"].strip()).first()
        if not target:
            raise HTTPException(404, "Player not found")
        if target.id == user.id:
            raise HTTPException(400, "Cannot add yourself")
        existing = db.query(Contact).filter(Contact.user_id == user.id, Contact.contact_user_id == target.id).first()
        if existing:
            raise HTTPException(400, "Already in contacts")
        contact = Contact(user_id=user.id, contact_user_id=target.id, note=note)
        db.add(contact)
        db.commit()
        return {"success": True, "id": contact.id}

    @app.get("/api/contacts/search-player")
    def search_player(q: str = Query(""), token: str = Depends(get_token_from_header), db: Session = Depends(get_db)):
        """Search players by ID or nickname."""
        get_current_user(token, db)
        q = q.strip()
        if not q:
            return []
        results = []
        # Try as ID first
        if q.isdigit():
            u = db.query(User).filter(User.id == int(q)).first()
            if u:
                results.append(u)
        # Also search by username (partial match)
        if not results:
            matches = db.query(User).filter(User.username.ilike(f"%{q}%")).limit(10).all()
            results = matches
        out = []
        for u in results:
            guild_tag = ""
            gm = db.query(GuildMember).filter(GuildMember.user_id == u.id).first()
            if gm:
                g = db.query(Guild).filter(Guild.id == gm.guild_id).first()
                if g:
                    guild_tag = g.tag
            out.append({"id": u.id, "username": u.username, "guild_tag": guild_tag})
        return out

    @app.get("/api/contacts/search-guild")
    def search_guild(q: str = Query(""), token: str = Depends(get_token_from_header), db: Session = Depends(get_db)):
        """Search guilds by ID, tag, or name."""
        get_current_user(token, db)
        q = q.strip()
        if not q:
            return []
        results = []
        if q.isdigit():
            g = db.query(Guild).filter(Guild.id == int(q)).first()
            if g:
                results.append(g)
        if not results:
            results = db.query(Guild).filter(
                (Guild.tag.ilike(f"%{q}%")) | (Guild.name.ilike(f"%{q}%"))
            ).limit(10).all()
        out = []
        for g in results:
            member_count = db.query(GuildMember).filter(GuildMember.guild_id == g.id).count()
            out.append({"id": g.id, "tag": g.tag, "name": g.name, "member_count": member_count})
        return out

    @app.put("/api/contacts/{contact_id}")
    def update_contact(contact_id: int, data: dict, token: str = Depends(get_token_from_header), db: Session = Depends(get_db)):
        user = get_current_user(token, db)
        contact = db.query(Contact).filter(Contact.id == contact_id, Contact.user_id == user.id).first()
        if not contact:
            raise HTTPException(404, "Contact not found")
        if "note" in data:
            contact.note = (data["note"] or "")[:100]
        db.commit()
        return {"success": True}

    @app.delete("/api/contacts/{contact_id}")
    def delete_contact(contact_id: int, token: str = Depends(get_token_from_header), db: Session = Depends(get_db)):
        user = get_current_user(token, db)
        contact = db.query(Contact).filter(Contact.id == contact_id, Contact.user_id == user.id).first()
        if not contact:
            raise HTTPException(404, "Contact not found")
        db.delete(contact)
        db.commit()
        return {"success": True}

    # ======================== ACCOUNT ========================

    @app.get("/api/account")
    def get_account(token: str = Depends(get_token_from_header), db: Session = Depends(get_db)):
        user = get_current_user(token, db)
        game_speed = get_config_float(db, "game_speed", 1.0)
        total_econ = sum(calc_economy_rate(c, user, game_speed) for c in user.colonies)
        total_fleet_val = sum(_fleet_value(f, db) for f in user.fleets)
        total_tech = round(calc_tech_cost(user, db))
        base_count = len(user.colonies)
        total_ships = sum(_fleet_total_ships(f) for f in user.fleets)
        level = calc_player_level(user, db, game_speed)
        empire_income = round(total_econ, 1)
        fleet_limit = calc_max_fleet_size(user, game_speed)
        next_colony = calc_colony_cost(user)
        next_colony_net, next_colony_reserve_used = apply_colony_reserve(user, next_colony)
        max_fleets = calc_max_fleet_count(user, db)
        player_id = user.id
        rank = db.query(User).filter(User.is_admin == False, User.is_bot == False, User.score > user.score).count() + 1
        return {
            "username": user.username,
            "email": user.email,
            "is_admin": user.is_admin,
            "created_at": user.created_at.isoformat() if user.created_at else None,
            "credits": round(user.credits, 1),
            "resources": {k: round(v, 1) for k, v in get_user_resources(user).items()},
            "score": user.score,
            "experience": round(user.experience, 1),
            "level": level,
            "bases": base_count,
            "ships": total_ships,
            "economy": round(total_econ, 1),
            "empire_income": empire_income,
            "fleet_value": round(total_fleet_val),
            "fleet_limit": fleet_limit,
            "max_fleets": max_fleets,
            "technology": total_tech,
            "next_colony_cost": next_colony,
            "next_colony_net": round(next_colony_net),
            "base_reserve": round(getattr(user, "base_reserve", 0.0) or 0.0),
            "bases_founded_peak": getattr(user, "bases_founded_peak", 0) or 0,
            "player_id": player_id,
            "rank": rank,
            "level_protected": level < NEWBIE_PROTECTION_LEVEL,
            "date_format": user.date_format or "MDY",
            "show_bbcode_images": bool(user.show_bbcode_images),
        }

    @app.post("/api/account/change-password")
    def change_password(req: ChangePasswordRequest, token: str = Depends(get_token_from_header), db: Session = Depends(get_db)):
        user = get_current_user(token, db)
        if not verify_password(req.old_password, user.hashed_password):
            raise HTTPException(400, "Current password is incorrect")
        if len(req.new_password) < 4:
            raise HTTPException(400, "New password must be at least 4 characters")
        user.hashed_password = hash_password(req.new_password)
        db.commit()
        return {"success": True}

    @app.post("/api/account/settings")
    def update_settings(req: dict, token: str = Depends(get_token_from_header), db: Session = Depends(get_db)):
        user = get_current_user(token, db)
        if "date_format" in req:
            fmt = req["date_format"]
            if fmt in ("MDY", "DMY", "YMD"):
                user.date_format = fmt
        if "show_bbcode_images" in req:
            user.show_bbcode_images = bool(req["show_bbcode_images"])
        db.commit()
        return {"success": True}

    # ======================== EVENT LOG ========================

    @app.get("/api/events")
    def get_events(token: str = Depends(get_token_from_header), db: Session = Depends(get_db)):
        user = get_current_user(token, db)
        events = db.query(EventLog).filter(EventLog.user_id == user.id).order_by(EventLog.created_at.desc()).limit(50).all()
        return [{"id": e.id, "type": e.event_type, "message": e.message, "created_at": e.created_at.isoformat() if e.created_at else None} for e in events]

    # ======================== BOOKMARKS ========================

    @app.get("/api/bookmarks")
    def get_bookmarks(token: str = Depends(get_token_from_header), db: Session = Depends(get_db)):
        user = get_current_user(token, db)
        bookmarks = db.query(Bookmark).filter(Bookmark.user_id == user.id).all()
        return [{"id": b.id, "name": b.name, "planet_id": b.planet_id,
                 "coords": b.planet.name if b.planet else ""} for b in bookmarks]

    @app.post("/api/bookmarks")
    def create_bookmark(req: BookmarkCreate, token: str = Depends(get_token_from_header), db: Session = Depends(get_db)):
        user = get_current_user(token, db)
        count = db.query(Bookmark).filter(Bookmark.user_id == user.id).count()
        if count >= 20:
            raise HTTPException(400, "Maximum 20 bookmarks")
        planet = db.query(Planet).filter(Planet.id == req.planet_id).first()
        if not planet:
            raise HTTPException(404, "Planet not found")
        bm = Bookmark(user_id=user.id, name=req.name.strip()[:50], planet_id=req.planet_id)
        db.add(bm)
        db.commit()
        return {"id": bm.id, "name": bm.name, "planet_id": bm.planet_id, "coords": planet.name}

    @app.post("/api/bookmarks/by-coords")
    def create_bookmark_by_coords(req: BookmarkByCoords,
                                   token: str = Depends(get_token_from_header), db: Session = Depends(get_db)):
        """Create bookmark by coordinate string instead of planet_id."""
        user = get_current_user(token, db)
        count = db.query(Bookmark).filter(Bookmark.user_id == user.id).count()
        if count >= 20:
            raise HTTPException(400, "Maximum 20 bookmarks")
        planet = db.query(Planet).filter(Planet.name == req.coords).first()
        if not planet:
            raise HTTPException(404, f"No astro at {req.coords}")
        bm = Bookmark(user_id=user.id, name=req.name.strip()[:50], planet_id=planet.id)
        db.add(bm)
        db.commit()
        return {"id": bm.id, "name": bm.name, "planet_id": bm.planet_id, "coords": planet.name}

    @app.delete("/api/bookmarks/{bookmark_id}")
    def delete_bookmark(bookmark_id: int, token: str = Depends(get_token_from_header), db: Session = Depends(get_db)):
        user = get_current_user(token, db)
        bm = db.query(Bookmark).filter(Bookmark.id == bookmark_id, Bookmark.user_id == user.id).first()
        if not bm:
            raise HTTPException(404, "Bookmark not found")
        db.delete(bm)
        db.commit()
        return {"success": True}

    # ======================== BUG REPORTS ========================

    @app.post("/api/bug-report")
    def submit_bug_report(
        token: str = Depends(get_token_from_header),
        db: Session = Depends(get_db),
        body: dict = None
    ):
        user = get_current_user(token, db)
        title = (body or {}).get("title", "").strip()
        if not title or len(title) < 3:
            raise HTTPException(400, "Title is required (min 3 characters)")
        description = (body or {}).get("description", "").strip()
        category = (body or {}).get("category", "bug")
        page = (body or {}).get("page", "")
        if category not in ("bug", "request", "feedback"):
            category = "bug"
        report = BugReport(
            user_id=user.id,
            username=user.username,
            category=category,
            title=title[:200],
            description=description[:2000],
            page=page[:50],
        )
        db.add(report)
        db.commit()
        import logging
        logging.getLogger("awe").info(f"[BUG REPORT] #{report.id} by {user.username}: [{category}] {title}")
        return {"success": True, "id": report.id}

    @app.get("/api/bug-reports")
    def list_bug_reports(
        token: str = Depends(get_token_from_header),
        db: Session = Depends(get_db)
    ):
        user = get_current_user(token, db)
        if user.is_admin:
            reports = db.query(BugReport).order_by(BugReport.created_at.desc()).limit(100).all()
        else:
            reports = db.query(BugReport).filter(BugReport.user_id == user.id).order_by(BugReport.created_at.desc()).limit(50).all()
        return [{
            "id": r.id,
            "username": r.username,
            "category": r.category,
            "title": r.title,
            "description": r.description,
            "page": r.page,
            "status": r.status,
            "admin_notes": r.admin_notes if user.is_admin else "",
            "created_at": r.created_at.isoformat() if r.created_at else None,
        } for r in reports]

    @app.post("/api/bug-reports/{report_id}/update")
    def update_bug_report(
        report_id: int,
        token: str = Depends(get_token_from_header),
        db: Session = Depends(get_db),
        body: dict = None
    ):
        user = get_current_user(token, db)
        if not user.is_admin:
            raise HTTPException(403, "Admin only")
        report = db.query(BugReport).filter(BugReport.id == report_id).first()
        if not report:
            raise HTTPException(404, "Report not found")
        if "status" in (body or {}):
            report.status = body["status"][:20]
        if "admin_notes" in (body or {}):
            report.admin_notes = body["admin_notes"][:2000]
        db.commit()
        return {"success": True}

    # ======================== CREDIT HISTORY ========================

    @app.get("/api/credits/history")
    def get_credit_history(token: str = Depends(get_token_from_header), db: Session = Depends(get_db)):
        """Return credit ledger in Credits History format."""
        user = get_current_user(token, db)
        logs = (db.query(CreditLog)
                .filter(CreditLog.user_id == user.id)
                .order_by(CreditLog.created_at.desc())
                .limit(200).all())

        # 24h summary by category
        from datetime import timedelta
        cutoff = datetime.utcnow() - timedelta(hours=24)
        recent = (db.query(CreditLog)
                  .filter(CreditLog.user_id == user.id, CreditLog.created_at >= cutoff)
                  .all())
        summary = {}
        for r in recent:
            cat = r.category or "other"
            summary[cat] = summary.get(cat, 0) + r.amount

        entries = []
        for log in logs:
            entries.append({
                "id": log.id,
                "date": log.created_at.isoformat(),
                "description": log.description,
                "amount": round(log.amount, 2),
                "balance": round(log.balance, 2),
                "category": log.category,
            })
        return {
            "entries": entries,
            "summary_24h": {k: round(v, 2) for k, v in summary.items()},
            "current_balance": round(user.credits, 2),
            "resources": {k: round(v, 2) for k, v in get_user_resources(user).items()},
        }

    # ======================== FLEET AUDIT LOG ========================

    @app.get("/api/fleets/audit")
    def get_fleet_audit(token: str = Depends(get_token_from_header), db: Session = Depends(get_db)):
        """Return fleet change audit trail for the player."""
        user = get_current_user(token, db)
        logs = (db.query(FleetAuditLog)
                .filter(FleetAuditLog.user_id == user.id)
                .order_by(FleetAuditLog.created_at.desc())
                .limit(200).all())
        import json
        entries = []
        for log in logs:
            entries.append({
                "id": log.id,
                "date": log.created_at.isoformat(),
                "fleet_id": log.fleet_id,
                "fleet_name": log.fleet_name,
                "action": log.action,
                "ships_before": json.loads(log.ships_before or "{}"),
                "ships_after": json.loads(log.ships_after or "{}"),
                "details": log.details,
            })
        return {"entries": entries}
