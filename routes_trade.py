from fastapi import HTTPException, Depends
from sqlalchemy.orm import Session
from sqlalchemy import or_
from datetime import datetime, timedelta
from models import User, Colony, Fleet, TradeRoute, Planet, GuildMember, Galaxy, Region, StarSystem, Message
from auth import (get_token_from_header, get_current_user, get_config_float, get_db, log_event, log_credits)
from game_logic import (calc_base_stats, calc_trade_income, calc_economy_rate,
                        collect_resources, get_building_level, _calc_distance)
from resources import can_afford, deduct_cost, add_resources, format_cost
from config_defaults import *
from pydantic import BaseModel
import action_points


class TradeRouteCreate(BaseModel):
    base_a_id: int
    base_b_id: int

class TradeRoutePlunder(BaseModel):
    trade_route_id: int


def register_trade_routes(app):

    def _count_trade_players(user, db):
        """Count unique players in a user's trade network (for the Players formula variable).
        Includes self if trading with self. Per FAQ: 'you only count as one trading partner'."""
        player_ids = set()
        routes = db.query(TradeRoute).filter(
            or_(TradeRoute.owner_id == user.id, TradeRoute.partner_id == user.id),
            TradeRoute.is_closing == False,
            TradeRoute.is_pending == False,
        ).all()
        for r in routes:
            ba = db.query(Colony).filter(Colony.id == r.base_a_id).first()
            bb = db.query(Colony).filter(Colony.id == r.base_b_id).first()
            if ba:
                player_ids.add(ba.user_id)
            if bb:
                player_ids.add(bb.user_id)
        return len(player_ids)

    @app.get("/api/trade-routes")
    def get_trade_routes(token: str = Depends(get_token_from_header), db: Session = Depends(get_db)):
        """Return all trade routes with DYNAMICALLY recalculated income.
        Includes routes you own AND pending requests from other players."""
        user = get_current_user(token, db)
        game_speed = get_config_float(db, "game_speed", 1.0)

        # Routes you own (active, pending, closing)
        own_routes = db.query(TradeRoute).filter(TradeRoute.owner_id == user.id).all()
        # Routes where you're the partner (active accepted routes + pending incoming)
        partner_routes = db.query(TradeRoute).filter(
            TradeRoute.partner_id == user.id,
        ).all()
        # Split into incoming (pending) and active partner routes
        incoming = [r for r in partner_routes if r.is_pending]
        active_partner = [r for r in partner_routes if not r.is_pending]

        num_players = _count_trade_players(user, db)
        total_income = 0
        result = []

        for tr in own_routes:
            base_a = db.query(Colony).filter(Colony.id == tr.base_a_id).first()
            base_b = db.query(Colony).filter(Colony.id == tr.base_b_id).first()
            distance = _calc_distance(base_a.planet, base_b.planet) if base_a and base_b else 0

            # Dynamic income recalc (only for active routes)
            if tr.is_closing or tr.is_pending or not base_a or not base_b:
                income = 0 if tr.is_closing else tr.income
            else:
                income = calc_trade_income(base_a, base_b, distance, num_players, game_speed)
                tr.income = income

            econ_a = calc_base_stats(base_a, base_a.user, game_speed)["economy"] if base_a else 0
            econ_b = calc_base_stats(base_b, base_b.user, game_speed)["economy"] if base_b else 0
            if not tr.is_pending and not tr.is_closing:
                total_income += income

            status = "Pending" if tr.is_pending else ("Closing" if tr.is_closing else "Active")
            result.append({
                "id": tr.id,
                "base_a": {
                    "id": tr.base_a_id,
                    "name": base_a.name if base_a else "?",
                    "owner": base_a.user.username if base_a else "?",
                    "economy": econ_a,
                    "coords": base_a.planet.name if base_a and base_a.planet else "",
                },
                "base_b": {
                    "id": tr.base_b_id,
                    "name": base_b.name if base_b else "?",
                    "owner": base_b.user.username if base_b else "?",
                    "economy": econ_b,
                    "coords": base_b.planet.name if base_b and base_b.planet else "",
                },
                "distance": round(distance, 1),
                "cost": round(tr.cost, 1),
                "income": round(income, 2),
                "status": status,
                "is_pending": tr.is_pending,
                "is_closing": tr.is_closing,
                "closing_at": tr.closing_at.isoformat() if tr.closing_at else None,
                "created_at": tr.created_at.isoformat(),
                "is_incoming": False,
            })

        # Incoming pending requests
        for tr in incoming:
            base_a = db.query(Colony).filter(Colony.id == tr.base_a_id).first()
            base_b = db.query(Colony).filter(Colony.id == tr.base_b_id).first()
            distance = _calc_distance(base_a.planet, base_b.planet) if base_a and base_b else 0
            initiator = db.query(User).filter(User.id == tr.owner_id).first()
            result.append({
                "id": tr.id,
                "base_a": {
                    "id": tr.base_a_id,
                    "name": base_a.name if base_a else "?",
                    "owner": base_a.user.username if base_a else "?",
                    "economy": calc_base_stats(base_a, base_a.user, game_speed)["economy"] if base_a else 0,
                    "coords": base_a.planet.name if base_a and base_a.planet else "",
                },
                "base_b": {
                    "id": tr.base_b_id,
                    "name": base_b.name if base_b else "?",
                    "owner": base_b.user.username if base_b else "?",
                    "economy": calc_base_stats(base_b, base_b.user, game_speed)["economy"] if base_b else 0,
                    "coords": base_b.planet.name if base_b and base_b.planet else "",
                },
                "distance": round(distance, 1),
                "cost": round(tr.cost, 1),
                "income": 0,
                "status": "Incoming Request",
                "is_pending": True,
                "is_closing": False,
                "closing_at": None,
                "created_at": tr.created_at.isoformat(),
                "is_incoming": True,
                "from_player": initiator.username if initiator else "?",
            })

        # Active routes where you're the partner (accepted inter-player trades)
        for tr in active_partner:
            base_a = db.query(Colony).filter(Colony.id == tr.base_a_id).first()
            base_b = db.query(Colony).filter(Colony.id == tr.base_b_id).first()
            distance = _calc_distance(base_a.planet, base_b.planet) if base_a and base_b else 0
            income = calc_trade_income(base_a, base_b, distance, num_players, game_speed) if base_a and base_b and not tr.is_closing else 0
            if not tr.is_closing:
                total_income += income
            status = "Closing" if tr.is_closing else "Active"
            result.append({
                "id": tr.id,
                "base_a": {
                    "id": tr.base_a_id,
                    "name": base_a.name if base_a else "?",
                    "owner": base_a.user.username if base_a else "?",
                    "economy": calc_base_stats(base_a, base_a.user, game_speed)["economy"] if base_a else 0,
                    "coords": base_a.planet.name if base_a and base_a.planet else "",
                },
                "base_b": {
                    "id": tr.base_b_id,
                    "name": base_b.name if base_b else "?",
                    "owner": base_b.user.username if base_b else "?",
                    "economy": calc_base_stats(base_b, base_b.user, game_speed)["economy"] if base_b else 0,
                    "coords": base_b.planet.name if base_b and base_b.planet else "",
                },
                "distance": round(distance, 1),
                "cost": round(tr.cost, 1),
                "income": round(income, 2),
                "status": status,
                "is_pending": False,
                "is_closing": tr.is_closing,
                "closing_at": tr.closing_at.isoformat() if tr.closing_at else None,
                "created_at": tr.created_at.isoformat(),
                "is_incoming": False,
            })

        db.commit()  # persist updated incomes
        return {
            "routes": result,
            "total_income": round(total_income, 2),
            "num_players": num_players,
        }

    @app.post("/api/trade-routes")
    def create_trade_route(req: TradeRouteCreate, token: str = Depends(get_token_from_header), db: Session = Depends(get_db)):
        """Create a trade route. Self-trade = instant active, inter-player = pending acceptance."""
        user = get_current_user(token, db)
        game_speed = get_config_float(db, "game_speed", 1.0)
        collect_resources(user, db, game_speed)

        base_a = db.query(Colony).filter(Colony.id == req.base_a_id).first()
        base_b = db.query(Colony).filter(Colony.id == req.base_b_id).first()
        if not base_a or not base_b:
            raise HTTPException(404, "Base not found")
        if req.base_a_id == req.base_b_id:
            raise HTTPException(400, "Cannot create trade route to same base")

        # At least one base must be yours
        if base_a.user_id != user.id and base_b.user_id != user.id:
            raise HTTPException(400, "At least one base must be yours")

        # Check for existing route between these two bases (either direction)
        existing = db.query(TradeRoute).filter(
            TradeRoute.is_closing == False,
            or_(
                (TradeRoute.base_a_id == req.base_a_id) & (TradeRoute.base_b_id == req.base_b_id),
                (TradeRoute.base_a_id == req.base_b_id) & (TradeRoute.base_b_id == req.base_a_id),
            )
        ).first()
        if existing:
            raise HTTPException(400, "A trade route already exists between these two bases")

        # Check if either base was recently pirated (24hr cooldown)
        now = datetime.utcnow()
        for b in [base_a, base_b]:
            if b.last_pillaged:
                hours_since = (now - b.last_pillaged).total_seconds() / 3600.0
                if hours_since < PILLAGE_COOLDOWN_HOURS:
                    remaining = PILLAGE_COOLDOWN_HOURS - hours_since
                    raise HTTPException(400, f"Base {b.name} was recently pirated — cannot create trade routes for {remaining:.0f} more hours")

        # Determine which base is ours
        my_base = base_a if base_a.user_id == user.id else base_b
        other_base = base_b if my_base == base_a else base_a
        is_self_trade = base_a.user_id == base_b.user_id

        # Check spaceport level — 1 route at lv1, +1 at lv5, lv10, lv15, lv20...
        spaceport_lv = get_building_level(my_base, "spaceports")
        if spaceport_lv < 1:
            raise HTTPException(400, "Need Spaceports level 1 to create trade routes")

        # Count existing routes for this base (including pending)
        existing_routes = db.query(TradeRoute).filter(
            TradeRoute.owner_id == user.id,
            TradeRoute.is_closing == False,
            ((TradeRoute.base_a_id == my_base.id) | (TradeRoute.base_b_id == my_base.id))
        ).count()
        max_routes = spaceport_lv // TRADE_ROUTES_PER_SPACEPORT_LEVELS + 1
        if existing_routes >= max_routes:
            raise HTTPException(400, f"Max {max_routes} trade routes from this base (Spaceports Lv{spaceport_lv})")

        # Calculate distance and cost
        distance = _calc_distance(base_a.planet, base_b.planet)
        total_cost = TRADE_ROUTE_COST_MULTIPLIER * distance

        if is_self_trade:
            # Self-trade: you pay full cost (2 x distance)
            player_cost = total_cost
        else:
            # Inter-player: each pays half (distance each)
            player_cost = total_cost / 2

        if not can_afford(user, player_cost):
            raise HTTPException(400, f"Need {format_cost(player_cost)} credits ({format_cost(player_cost)} = your share of {format_cost(total_cost)} total)")

        # Calc initial income estimate
        num_players = _count_trade_players(user, db)
        # Include new partner in count
        all_pids = set()
        for r in db.query(TradeRoute).filter(or_(TradeRoute.owner_id == user.id, TradeRoute.partner_id == user.id), TradeRoute.is_closing == False, TradeRoute.is_pending == False).all():
            ba = db.query(Colony).filter(Colony.id == r.base_a_id).first()
            bb = db.query(Colony).filter(Colony.id == r.base_b_id).first()
            if ba: all_pids.add(ba.user_id)
            if bb: all_pids.add(bb.user_id)
        all_pids.add(base_a.user_id)
        all_pids.add(base_b.user_id)
        num_players = len(all_pids)

        trade_income = calc_trade_income(base_a, base_b, distance, num_players, game_speed)

        action_points.debit_action_points(user, db, "trade_create")
        deduct_cost(user, player_cost)
        log_credits(db, user.id, -player_cost, f"Trade route: {my_base.name} - {other_base.name}", "trade")
        partner_id = other_base.user_id if not is_self_trade else None
        is_pending = not is_self_trade  # inter-player trades need acceptance

        tr = TradeRoute(
            base_a_id=req.base_a_id, base_b_id=req.base_b_id,
            owner_id=user.id, partner_id=partner_id,
            cost=total_cost, income=trade_income if not is_pending else 0,
            is_pending=is_pending,
        )
        db.add(tr)

        if is_pending:
            log_event(db, user.id, "trade",
                      f"Trade request sent: {my_base.name} \u2194 {other_base.name} (awaiting acceptance)")
            log_event(db, partner_id, "trade",
                      f"Trade request from {user.username}: {my_base.name} \u2194 {other_base.name}")
            # Send in-game message to partner
            msg = Message(
                sender_id=user.id,
                recipient_id=partner_id,
                subject="Trade Route Request",
                body=f"{user.username} wants to establish a trade route between {my_base.name} ({my_base.planet.name}) and {other_base.name} ({other_base.planet.name}).\n\nDistance: {round(distance)} | Your cost: {round(total_cost/2)} credits\n\nGo to Trade Routes to accept or reject this request.",
            )
            db.add(msg)
        else:
            log_event(db, user.id, "trade",
                      f"Trade route: {base_a.name} \u2194 {base_b.name} ({round(distance)}d, +{round(trade_income,1)} cr/hr)")
        db.commit()
        return {
            "success": True, "trade_route_id": tr.id,
            "cost": round(player_cost, 1), "income": round(trade_income, 2),
            "distance": distance, "is_pending": is_pending,
        }

    @app.post("/api/trade-routes/{route_id}/accept")
    def accept_trade_route(route_id: int, token: str = Depends(get_token_from_header), db: Session = Depends(get_db)):
        """Accept an incoming trade request. Partner pays their half of the cost."""
        user = get_current_user(token, db)
        game_speed = get_config_float(db, "game_speed", 1.0)
        collect_resources(user, db, game_speed)

        tr = db.query(TradeRoute).filter(TradeRoute.id == route_id, TradeRoute.partner_id == user.id, TradeRoute.is_pending == True).first()
        if not tr:
            raise HTTPException(404, "No pending trade request found")

        # Partner pays their half
        partner_cost = tr.cost / 2
        if not can_afford(user, partner_cost):
            raise HTTPException(400, f"Need {format_cost(partner_cost)} credits to accept this trade route")

        # Check spaceport capacity on partner's base
        base_a = db.query(Colony).filter(Colony.id == tr.base_a_id).first()
        base_b = db.query(Colony).filter(Colony.id == tr.base_b_id).first()
        my_base = base_a if base_a and base_a.user_id == user.id else base_b
        if my_base:
            spaceport_lv = get_building_level(my_base, "spaceports")
            existing = db.query(TradeRoute).filter(
                ((TradeRoute.owner_id == user.id) | (TradeRoute.partner_id == user.id)),
                TradeRoute.is_closing == False,
                ((TradeRoute.base_a_id == my_base.id) | (TradeRoute.base_b_id == my_base.id))
            ).count()
            max_routes = spaceport_lv // TRADE_ROUTES_PER_SPACEPORT_LEVELS + 1
            if existing > max_routes:
                raise HTTPException(400, f"No trade slots available on {my_base.name} (Spaceports Lv{spaceport_lv})")

        action_points.debit_action_points(user, db, "trade_accept")
        deduct_cost(user, partner_cost)
        log_credits(db, user.id, -partner_cost, f"Trade route accepted", "trade")
        tr.is_pending = False

        # Calc income now that it's active
        if base_a and base_b:
            distance = _calc_distance(base_a.planet, base_b.planet)
            num_players = _count_trade_players(db.query(User).filter(User.id == tr.owner_id).first(), db)
            tr.income = calc_trade_income(base_a, base_b, distance, num_players, game_speed)

        initiator = db.query(User).filter(User.id == tr.owner_id).first()
        log_event(db, user.id, "trade", f"Accepted trade route from {initiator.username if initiator else '?'}")
        log_event(db, tr.owner_id, "trade", f"{user.username} accepted your trade request")
        db.commit()
        return {"success": True, "cost": round(partner_cost, 1), "income": round(tr.income, 2)}

    @app.post("/api/trade-routes/{route_id}/reject")
    def reject_trade_route(route_id: int, token: str = Depends(get_token_from_header), db: Session = Depends(get_db)):
        """Reject an incoming trade request. Initiator gets their cost refunded."""
        user = get_current_user(token, db)
        tr = db.query(TradeRoute).filter(TradeRoute.id == route_id, TradeRoute.partner_id == user.id, TradeRoute.is_pending == True).first()
        if not tr:
            raise HTTPException(404, "No pending trade request found")

        # Refund initiator
        initiator = db.query(User).filter(User.id == tr.owner_id).first()
        if initiator:
            add_resources(initiator, tr.cost / 2)
            log_credits(db, tr.owner_id, tr.cost / 2, f"Trade route rejected — refund", "trade")
            log_event(db, tr.owner_id, "trade", f"{user.username} rejected your trade request (refunded {round(tr.cost/2)} cr)")

        log_event(db, user.id, "trade", f"Rejected trade request")
        db.delete(tr)
        db.commit()
        return {"success": True}

    @app.delete("/api/trade-routes/{route_id}")
    def cancel_trade_route(route_id: int, token: str = Depends(get_token_from_header), db: Session = Depends(get_db)):
        """Cancel a trade route. Each trading partner receives 50% refund.
        Enters 'Closing' for 12hrs (<1000 dist) or 24hrs (>=1000)."""
        user = get_current_user(token, db)
        tr = db.query(TradeRoute).filter(
            TradeRoute.id == route_id,
            or_(TradeRoute.owner_id == user.id, TradeRoute.partner_id == user.id)
        ).first()
        if not tr:
            raise HTTPException(404, "Trade route not found")

        if tr.is_pending:
            # Cancel pending request -- full refund of initiator's share
            add_resources(user, tr.cost / 2)
            log_credits(db, user.id, tr.cost / 2, f"Trade route cancelled — refund", "trade")
            db.delete(tr)
            db.commit()
            return {"success": True, "refund": round(tr.cost / 2, 1), "closing_hours": 0}

        if tr.is_closing:
            raise HTTPException(400, "Trade route is already closing")

        # 50% refund to each partner
        refund_each = tr.cost * TRADE_CLOSING_REFUND_PERCENT  # 50% of each player's share (which was cost/2)
        is_self_trade = tr.partner_id is None
        if is_self_trade:
            # Self-trade: you paid full cost, get 50% back
            add_resources(user, tr.cost * 0.5)
            log_credits(db, user.id, tr.cost * 0.5, f"Trade route cancelled — refund", "trade")
            refund_display = tr.cost * 0.5
        else:
            # Inter-player: each gets 50% of their share back
            add_resources(user, refund_each)
            log_credits(db, user.id, refund_each, f"Trade route cancelled — refund", "trade")
            if tr.partner_id:
                partner = db.query(User).filter(User.id == tr.partner_id).first()
                if partner:
                    add_resources(partner, refund_each)
                    log_credits(db, tr.partner_id, refund_each, f"Trade route cancelled — refund", "trade")
            refund_display = refund_each

        distance = tr.cost / 2
        close_hours = TRADE_CLOSING_HOURS_LONG if distance >= TRADE_CLOSING_DISTANCE_THRESHOLD else TRADE_CLOSING_HOURS_SHORT
        tr.is_closing = True
        tr.income = 0
        tr.closing_at = datetime.utcnow() + timedelta(hours=close_hours)
        log_event(db, user.id, "trade", f"Cancelled trade route (refunded {round(refund_display)} cr)")
        db.commit()
        return {"success": True, "refund": round(refund_display, 1), "closing_hours": close_hours}

    @app.post("/api/trade-routes/plunder")
    def plunder_trade_route(req: TradeRoutePlunder, token: str = Depends(get_token_from_header), db: Session = Depends(get_db)):
        """Plunder an enemy trade route via Piracy.
        Fleet must be at target base, no opposing fleets present.
        Profit = route's setting cost. Route is terminated."""
        user = get_current_user(token, db)
        tr = db.query(TradeRoute).filter(TradeRoute.id == req.trade_route_id).first()
        if not tr:
            raise HTTPException(404, "Trade route not found")
        if tr.owner_id == user.id or tr.partner_id == user.id:
            raise HTTPException(400, "Cannot plunder your own trade route")

        # Must have a fleet at one of the bases
        target_base_id = None
        for fleet in user.fleets:
            if not fleet.is_moving:
                if fleet.base_id == tr.base_a_id or fleet.base_id == tr.base_b_id:
                    target_base_id = fleet.base_id
                    break
        if not target_base_id:
            raise HTTPException(400, "Need a fleet stationed at one of the trade route's bases")

        target_colony = db.query(Colony).filter(Colony.id == target_base_id).first()

        # Can't plunder at a guildmate's base
        my_guild = db.query(GuildMember).filter(GuildMember.user_id == user.id).first()
        if my_guild and target_colony:
            guild_ids = {m.user_id for m in db.query(GuildMember).filter(GuildMember.guild_id == my_guild.guild_id).all()}
            if target_colony.user_id in guild_ids:
                raise HTTPException(400, "Cannot plunder at a guildmate's base")

        # Can't plunder if the base owner is someone you're trading with
        if target_colony:
            my_trade_partner_ids = set()
            my_routes = db.query(TradeRoute).filter(
                or_(TradeRoute.owner_id == user.id, TradeRoute.partner_id == user.id),
                TradeRoute.is_closing == False, TradeRoute.is_pending == False,
            ).all()
            for mr in my_routes:
                if mr.owner_id != user.id: my_trade_partner_ids.add(mr.owner_id)
                if mr.partner_id and mr.partner_id != user.id: my_trade_partner_ids.add(mr.partner_id)
            if target_colony.user_id in my_trade_partner_ids:
                raise HTTPException(400, "Cannot plunder a trade partner's route")

        # Check opposing fleets: base owner, their guildmates, or destination base owner
        if target_colony:
            fleet_owner_ids = {f.user_id for f in db.query(Fleet).filter(
                Fleet.base_id == target_base_id,
                Fleet.user_id != user.id,
                Fleet.is_moving == False,
            ).all()}
            if fleet_owner_ids:
                # Base owner + their guildmates block
                base_owner_id = target_colony.user_id
                owner_guild = db.query(GuildMember).filter(GuildMember.user_id == base_owner_id).first()
                blocking_ids = {base_owner_id}
                if owner_guild:
                    blocking_ids |= {m.user_id for m in db.query(GuildMember).filter(GuildMember.guild_id == owner_guild.guild_id).all()}
                # Destination base owner of this route also blocks
                linked_base_id = tr.base_b_id if tr.base_a_id == target_base_id else tr.base_a_id
                linked_colony = db.query(Colony).filter(Colony.id == linked_base_id).first()
                if linked_colony:
                    blocking_ids.add(linked_colony.user_id)
                if fleet_owner_ids & blocking_ids:
                    raise HTTPException(400, "Cannot plunder -- opposing fleets present at the base")

        # Profit: full setup cost of the active route
        if tr.is_closing:
            raise HTTPException(400, "Cannot plunder a closing trade route")
        plunder_amount = round(tr.cost)
        action_points.debit_action_points(user, db, "trade_plunder")
        add_resources(user, plunder_amount)
        log_credits(db, user.id, plunder_amount, f"Pirated trade route at {target_colony.name if target_colony else '?'}", "trade")

        # Set 24hr cooldown on the pirated base
        now = datetime.utcnow()
        if target_colony:
            target_colony.last_pillaged = now

        # Notify owner and partner
        log_event(db, user.id, "trade", f"Pirated trade route for {round(plunder_amount)} cr")
        for uid in set(filter(None, [tr.owner_id, tr.partner_id])):
            if uid != user.id:
                log_event(db, uid, "trade", f"Trade route pirated by {user.username} (-{round(plunder_amount)} cr)")
                db.add(Message(
                    sender_id=user.id,
                    recipient_id=uid,
                    subject="Trade Route Pirated",
                    body=f"{user.username} pirated your trade route at {target_colony.name if target_colony else '?'}. You lost {round(plunder_amount)} credits worth of trade infrastructure.",
                    created_at=now,
                ))

        db.delete(tr)
        db.commit()
        return {"success": True, "plunder": round(plunder_amount)}

    @app.post("/api/trade-routes/{route_id}/make-public")
    def make_trade_public(route_id: int, token: str = Depends(get_token_from_header), db: Session = Depends(get_db)):
        """List a trade route on the public trade finder for 48 hours."""
        user = get_current_user(token, db)
        tr = db.query(TradeRoute).filter(TradeRoute.id == route_id, TradeRoute.owner_id == user.id).first()
        if not tr:
            raise HTTPException(404, "Trade route not found")
        if tr.is_pending or tr.is_closing:
            raise HTTPException(400, "Cannot list a pending or closing trade route")
        tr.is_public = True
        tr.public_until = datetime.utcnow() + timedelta(hours=PUBLIC_TRADE_LISTING_HOURS)
        db.commit()
        return {"success": True, "public_until": tr.public_until.isoformat()}

    @app.get("/api/piracy/{base_id}")
    def get_piracy_targets(base_id: int, token: str = Depends(get_token_from_header), db: Session = Depends(get_db)):
        """Get trade routes at a base that can be pirated by the requesting player."""
        user = get_current_user(token, db)
        colony = db.query(Colony).filter(Colony.id == base_id).first()
        if not colony:
            raise HTTPException(404, "Base not found")

        # Must have a fleet at this base
        has_fleet = db.query(Fleet).filter(
            Fleet.user_id == user.id,
            Fleet.base_id == base_id,
            Fleet.is_moving == False,
        ).first()
        if not has_fleet:
            return {"routes": [], "error": "No fleet stationed at this base"}

        # Find all active (non-closing, non-pending) trade routes connected to this base
        routes = db.query(TradeRoute).filter(
            or_(TradeRoute.base_a_id == base_id, TradeRoute.base_b_id == base_id),
            TradeRoute.is_closing == False,
            TradeRoute.is_pending == False,
        ).all()

        # Build set of fleet owner IDs at this base (excluding pirate)
        fleets_at_base = db.query(Fleet).filter(
            Fleet.base_id == base_id,
            Fleet.user_id != user.id,
            Fleet.is_moving == False,
        ).all()
        fleet_owner_ids = {f.user_id for f in fleets_at_base}

        # Base owner and their guild members block piracy
        base_owner_id = colony.user_id
        base_owner_guild_ids = set()
        owner_guild = db.query(GuildMember).filter(GuildMember.user_id == base_owner_id).first()
        if owner_guild:
            base_owner_guild_ids = {m.user_id for m in db.query(GuildMember).filter(GuildMember.guild_id == owner_guild.guild_id).all()}

        # IDs that block piracy if they have a fleet here: base owner + their guildmates
        blocking_ids = {base_owner_id} | base_owner_guild_ids
        # Global block: any of these have a fleet at the base
        global_blocking_fleet = bool(fleet_owner_ids & blocking_ids)

        # Check if base belongs to pirate's guildmate
        my_guild = db.query(GuildMember).filter(GuildMember.user_id == user.id).first()
        my_guild_ids = set()
        if my_guild:
            my_guild_ids = {m.user_id for m in db.query(GuildMember).filter(GuildMember.guild_id == my_guild.guild_id).all()}
        base_is_guildmate = base_owner_id in my_guild_ids

        # Get all player IDs the user is actively trading with
        my_trade_partner_ids = set()
        my_routes = db.query(TradeRoute).filter(
            or_(TradeRoute.owner_id == user.id, TradeRoute.partner_id == user.id),
            TradeRoute.is_closing == False,
            TradeRoute.is_pending == False,
        ).all()
        for mr in my_routes:
            if mr.owner_id != user.id:
                my_trade_partner_ids.add(mr.owner_id)
            if mr.partner_id and mr.partner_id != user.id:
                my_trade_partner_ids.add(mr.partner_id)

        result = []
        for tr in routes:
            base_a = db.query(Colony).filter(Colony.id == tr.base_a_id).first()
            base_b = db.query(Colony).filter(Colony.id == tr.base_b_id).first()
            linked_base = base_b if tr.base_a_id == base_id else base_a
            owner = db.query(User).filter(User.id == tr.owner_id).first()
            partner = db.query(User).filter(User.id == tr.partner_id).first() if tr.partner_id else None

            # Player = owner of the linked (other) base
            linked_owner = db.query(User).filter(User.id == linked_base.user_id).first() if linked_base else None
            player_name = linked_owner.username if linked_owner else "?"

            # Blocking rules
            is_own = tr.owner_id == user.id or tr.partner_id == user.id
            # Block if the base owner is someone you're trading with
            is_trade_partner = base_owner_id in my_trade_partner_ids
            # Per-route: destination base owner's fleet also blocks
            dest_owner_id = linked_base.user_id if linked_base else None
            dest_owner_has_fleet = dest_owner_id in fleet_owner_ids if dest_owner_id else False

            reason = ""
            if is_own:
                reason = "You can't plunder your own route"
            elif base_is_guildmate:
                reason = "You can't plunder at a guildmate's base"
            elif is_trade_partner:
                reason = "You can't plunder a trade partner's route"
            elif global_blocking_fleet or dest_owner_has_fleet:
                reason = "Opposing fleets present"

            can_pirate = not reason

            distance = _calc_distance(base_a.planet, base_b.planet) if base_a and base_b and base_a.planet and base_b.planet else 0

            result.append({
                "id": tr.id,
                "linked_base": linked_base.name if linked_base else "?",
                "linked_coords": linked_base.planet.name if linked_base and linked_base.planet else "",
                "player": player_name,
                "distance": round(distance),
                "plunder_value": round(tr.cost),
                "can_pirate": can_pirate,
                "reason": reason,
            })

        return {"routes": result}

    def _colony_coords_str(colony, db):
        """Get coordinate string for a colony (uses stored planet name)."""
        if not colony or not colony.planet:
            return ""
        return colony.planet.name or ""

    @app.get("/api/trade-finder")
    def trade_finder(base_id: int = None, token: str = Depends(get_token_from_header), db: Session = Depends(get_db)):
        """Trade finder: shows listed bases with available trade slots.
        If base_id is provided, calculates distance from that base."""
        user = get_current_user(token, db)
        now = datetime.utcnow()

        # Origin base for distance calculation
        origin = db.query(Colony).filter(Colony.id == base_id).first() if base_id else None

        # Get user's guild membership
        my_membership = db.query(GuildMember).filter(GuildMember.user_id == user.id).first()
        guild_member_ids = set()
        if my_membership:
            members = db.query(GuildMember).filter(GuildMember.guild_id == my_membership.guild_id).all()
            guild_member_ids = {m.user_id for m in members}

        result = []
        seen_colony_ids = set()
        my_base_ids = [c.id for c in db.query(Colony).filter(Colony.user_id == user.id).all()]

        # 1. Public listed bases (trade_listed_until not expired, not own)
        listed_colonies = db.query(Colony).filter(
            Colony.trade_listed_until > now,
            Colony.user_id != user.id,
        ).all()
        for col in listed_colonies:
            if col.id in seen_colony_ids:
                continue
            seen_colony_ids.add(col.id)
            # Count open trade slots
            spaceport_lv = get_building_level(col, "spaceports")
            existing = db.query(TradeRoute).filter(
                TradeRoute.is_closing == False,
                ((TradeRoute.base_a_id == col.id) | (TradeRoute.base_b_id == col.id))
            ).count()
            max_routes = spaceport_lv // TRADE_ROUTES_PER_SPACEPORT_LEVELS + 1
            if existing >= max_routes:
                continue  # no open slots

            owner = col.user
            econ = calc_base_stats(col, owner, game_speed)["economy"] if owner else 0
            distance = _calc_distance(origin.planet, col.planet) if origin and col.planet else 0
            # Count trades between you and this player
            their_base_ids = [c.id for c in db.query(Colony).filter(Colony.user_id == col.user_id).all()]
            trade_count = db.query(TradeRoute).filter(
                TradeRoute.is_closing == False,
                or_(
                    (TradeRoute.base_a_id.in_(my_base_ids)) & (TradeRoute.base_b_id.in_(their_base_ids)),
                    (TradeRoute.base_a_id.in_(their_base_ids)) & (TradeRoute.base_b_id.in_(my_base_ids)),
                )
            ).count()
            coords = _colony_coords_str(col, db)
            result.append({
                "base_name": col.name,
                "owner": f"{owner.username} ({trade_count})" if owner else "?",
                "economy": econ,
                "distance": round(distance, 1),
                "coords": coords,
                "source": "public",
            })

        # 2. Guild bases with empty trade slots (not own)
        guild_bases = []
        if guild_member_ids:
            guildmate_ids = guild_member_ids - {user.id}
            if guildmate_ids:
                for gm_id in guildmate_ids:
                    gm_colonies = db.query(Colony).filter(Colony.user_id == gm_id).all()
                    for col in gm_colonies:
                        if col.id in seen_colony_ids:
                            continue
                        seen_colony_ids.add(col.id)
                        spaceport_lv = get_building_level(col, "spaceports")
                        if spaceport_lv < 1:
                            continue
                        existing = db.query(TradeRoute).filter(
                            TradeRoute.is_closing == False,
                            ((TradeRoute.base_a_id == col.id) | (TradeRoute.base_b_id == col.id))
                        ).count()
                        max_routes = spaceport_lv // TRADE_ROUTES_PER_SPACEPORT_LEVELS + 1
                        if existing >= max_routes:
                            continue
                        owner = col.user
                        econ = calc_base_stats(col, owner, game_speed)["economy"] if owner else 0
                        distance = _calc_distance(origin.planet, col.planet) if origin and col.planet else 0
                        their_base_ids = [c.id for c in gm_colonies]
                        trade_count = db.query(TradeRoute).filter(
                            TradeRoute.is_closing == False,
                            or_(
                                (TradeRoute.base_a_id.in_(my_base_ids)) & (TradeRoute.base_b_id.in_(their_base_ids)),
                                (TradeRoute.base_a_id.in_(their_base_ids)) & (TradeRoute.base_b_id.in_(my_base_ids)),
                            )
                        ).count()
                        coords = _colony_coords_str(col, db)
                        guild_bases.append({
                            "base_name": col.name,
                            "owner": f"{owner.username} ({trade_count})" if owner else "?",
                            "economy": econ,
                            "distance": round(distance, 1),
                            "coords": coords,
                            "source": "guild",
                        })

        return {"trades": result, "guild_trades": guild_bases}

    @app.get("/api/trade-preview")
    def trade_preview(base_id: int, coords: str, token: str = Depends(get_token_from_header), db: Session = Depends(get_db)):
        """Preview trade route cost/distance before creating it."""
        user = get_current_user(token, db)
        base_a = db.query(Colony).filter(Colony.id == base_id, Colony.user_id == user.id).first()
        if not base_a:
            raise HTTPException(404, "Base not found")

        # Resolve destination by planet name
        coords = coords.strip()
        planet = db.query(Planet).filter(Planet.name == coords).first()
        if not planet:
            if coords[-1:] == '0' and len(coords.split(':')) == 4:
                planet = db.query(Planet).filter(Planet.name == coords[:-1]).first()
            elif len(coords.split(':')) == 4:
                planet = db.query(Planet).filter(Planet.name == coords + '0').first()
        if not planet:
            raise HTTPException(404, f"No astro found at '{coords}'")

        distance = _calc_distance(base_a.planet, planet)
        cost = TRADE_ROUTE_COST_MULTIPLIER * distance

        colony_b = db.query(Colony).filter(Colony.planet_id == planet.id).first()
        is_self = colony_b and colony_b.user_id == user.id
        player_cost = cost if is_self else cost / 2

        return {
            "distance": round(distance, 1),
            "cost": round(player_cost, 1),
            "total_cost": round(cost, 1),
            "is_self_trade": is_self,
            "has_base": colony_b is not None,
        }

    @app.post("/api/trade-finder/list-base")
    def list_base_on_trade_finder(req: dict, token: str = Depends(get_token_from_header), db: Session = Depends(get_db)):
        """List a base on the public trade finder for 48 hours.
        Other players can then see it and start trade routes to it."""
        user = get_current_user(token, db)
        colony_id = req.get("colony_id")
        colony = db.query(Colony).filter(Colony.id == colony_id, Colony.user_id == user.id).first()
        if not colony:
            raise HTTPException(404, "Base not found")
        spaceport_lv = get_building_level(colony, "spaceports")
        if spaceport_lv < 1:
            raise HTTPException(400, "Need Spaceports to list on trade finder")

        # Check existing route count
        existing_routes = db.query(TradeRoute).filter(
            TradeRoute.owner_id == user.id,
            TradeRoute.is_closing == False,
            ((TradeRoute.base_a_id == colony.id) | (TradeRoute.base_b_id == colony.id))
        ).count()
        max_routes = spaceport_lv // TRADE_ROUTES_PER_SPACEPORT_LEVELS + 1
        if existing_routes >= max_routes:
            raise HTTPException(400, f"All trade slots full ({existing_routes}/{max_routes})")

        # Create a self-pending "listing" trade route
        # Actually, use the colony's public listing flag
        colony.trade_listed_until = datetime.utcnow() + timedelta(hours=PUBLIC_TRADE_LISTING_HOURS)
        log_event(db, user.id, "trade", f"Listed {colony.name} on trade finder for 48h")
        db.commit()
        return {"success": True, "listed_until": colony.trade_listed_until.isoformat()}


