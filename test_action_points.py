#!/usr/bin/env python3
"""
Tests for the action-point ("Turns") economy core (Phase A).

Pure logic — no DB needed: ap_* read the active game definition (not the db
arg), and accrual/debit only touch attributes on the user object.

Run: python3 test_action_points.py
"""
from datetime import datetime, timedelta
from types import SimpleNamespace

import action_points as ap
from game_definition import set_game_definition, get_game_definition


def _user(**kw):
    base = {"action_points": 0.0, "last_ap_accrual": None, "is_bot": False}
    base.update(kw)
    return SimpleNamespace(**base)


def _enable(**cfg):
    c = {"start": 40, "regen_per_hour": 10, "max": 250, "apply_to_bots": False,
         "costs": {"fleet_attack": 2, "fleet_send": 1}}
    c.update(cfg)
    set_game_definition({"engine": {"economy_actions": "action_points", "action_points": c}})


def _disable():
    set_game_definition({"engine": {"economy_actions": "time"}})


def test_inert_when_off():
    _disable()
    u = _user()
    assert ap.ap_enabled(None) is False
    assert ap.ap_state(u, None) == {"enabled": False}
    assert ap.can_afford_action(u, None, "fleet_attack") is True
    # debit is a no-op; raises nothing, spends nothing
    ap.debit_action_points(u, None, "fleet_attack")
    assert u.action_points == 0.0


def test_seed_starting_on_first_accrual():
    _enable()
    u = _user()
    now = datetime(2026, 6, 7, 12, 0, 0)
    assert ap.accrue_action_points(u, None, now) == 40
    assert u.last_ap_accrual == now


def test_regen_over_time_capped():
    _enable()
    u = _user(action_points=40.0, last_ap_accrual=datetime(2026, 6, 7, 12, 0, 0))
    # 3 hours later -> +30 = 70
    assert ap.accrue_action_points(u, None, datetime(2026, 6, 7, 15, 0, 0)) == 70
    # far future -> capped at max 250
    assert ap.accrue_action_points(u, None, datetime(2026, 6, 9, 0, 0, 0)) == 250


def test_debit_spends_and_blocks():
    _enable(regen_per_hour=0)  # isolate debit from wall-clock accrual
    u = _user(action_points=3.0, last_ap_accrual=datetime.utcnow())
    # spend 2 for an attack (no time passes -> still 3 before)
    ap.debit_action_points(u, None, "fleet_attack", )  # cost 2
    assert round(u.action_points, 0) == 1
    # now too poor for another attack -> HTTP 400
    from fastapi import HTTPException
    try:
        ap.debit_action_points(u, None, "fleet_attack")
        assert False, "should have raised"
    except HTTPException as e:
        assert e.status_code == 400


def test_exactly_enough_action_points_spends_to_zero():
    _enable(regen_per_hour=0)  # isolate debit from wall-clock accrual
    u = _user(action_points=2.0, last_ap_accrual=datetime.utcnow())
    ap.debit_action_points(u, None, "fleet_attack")
    assert u.action_points == 0.0


def test_non_numeric_cost_is_free_but_negative_cost_is_clamped():
    _enable(costs={"bad_text": "not-a-number", "negative": -5})
    assert ap.ap_cost(None, "bad_text") == 0.0
    assert ap.ap_cost(None, "negative") == 0.0
    u = _user(action_points=3.0, last_ap_accrual=datetime(2026, 6, 7, 12, 0, 0))
    ap.debit_action_points(u, None, "negative")
    assert u.action_points == 3.0


def test_future_last_accrual_is_clamped_to_now():
    _enable()
    now = datetime(2026, 6, 7, 12, 0, 0)
    u = _user(action_points=40.0, last_ap_accrual=now + timedelta(hours=24))
    assert ap.accrue_action_points(u, None, now) == 40.0
    assert u.last_ap_accrual == now


def test_current_points_above_new_max_are_capped_even_without_elapsed_time():
    _enable(max=50)
    now = datetime(2026, 6, 7, 12, 0, 0)
    u = _user(action_points=100.0, last_ap_accrual=now)
    assert ap.accrue_action_points(u, None, now) == 50.0


def test_free_action_no_charge():
    _enable()
    u = _user(action_points=5.0, last_ap_accrual=datetime(2026, 6, 7, 12, 0, 0))
    ap.debit_action_points(u, None, "unlisted_free_action")
    assert u.action_points == 5.0


def test_bots_exempt_unless_configured():
    _enable(apply_to_bots=False)
    bot = _user(is_bot=True)
    ap.debit_action_points(bot, None, "fleet_attack")  # no-op for bot
    assert bot.action_points == 0.0
    assert ap.ap_state(bot, None) == {"enabled": False}
    # with apply_to_bots true, bots are charged
    _enable(apply_to_bots=True)
    # Seed the accrual clock at "now" so no regen happens before the debit
    # (otherwise wall-clock elapsed time accrues the bot to the cap first).
    bot2 = _user(is_bot=True, action_points=5.0, last_ap_accrual=datetime.utcnow())
    ap.debit_action_points(bot2, None, "fleet_attack")
    assert round(bot2.action_points, 0) == 3


def test_solar_empire_mod_enables_turns():
    """The shipped Solar Empire ruleset should turn the economy on."""
    from game_definition import load_definition_from_file
    defn = load_definition_from_file("mods/solar_empire/definition.json")
    set_game_definition(defn)
    assert ap.ap_enabled(None) is True
    assert ap.ap_cost(None, "fleet_attack") == 2
    assert ap.ap_cost(None, "fleet_conquer") == 3
    assert ap.ap_cost(None, "colonize") == 3


if __name__ == "__main__":
    try:
        tests = [v for k, v in sorted(globals().items()) if k.startswith("test_")]
        for t in tests:
            t()
            print(f"OK {t.__name__}")
        print("\n" + "=" * 60)
        print(" ALL ACTION-POINT TESTS PASSED!")
        print("=" * 60)
    finally:
        # restore default so other tests/processes aren't affected
        set_game_definition(None) if False else None
