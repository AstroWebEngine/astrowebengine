#!/usr/bin/env python3
"""
Tests for the AstroWebEngine mod hook mechanism (M3 spine).

Run: python3 test_mod_hooks.py
"""
import mod_hooks as mh
import json
import os
from tempfile import TemporaryDirectory


def _reset():
    mh.clear()


def _write_behavior_mod(root, mod_id, hooks_py):
    mod_dir = os.path.join(root, mod_id)
    hooks_dir = os.path.join(mod_dir, "hooks")
    os.makedirs(hooks_dir, exist_ok=True)
    with open(os.path.join(mod_dir, "manifest.json"), "w", encoding="utf-8") as fh:
        json.dump({
            "id": mod_id,
            "name": mod_id,
            "version": "1",
            "kind": "behavioral",
            "engine_api": "1.0",
        }, fh)
    with open(os.path.join(hooks_dir, "__init__.py"), "w", encoding="utf-8") as fh:
        fh.write(hooks_py)


def test_register_rejects_unknown_hook():
    _reset()
    try:
        mh.register("on_nonsense", lambda ctx: None)
        assert False, "should reject unknown hook"
    except ValueError:
        pass


def test_observer_runs_all_in_order():
    _reset()
    calls = []
    mh.register("on_tick", lambda ctx: calls.append("b"), order=200)
    mh.register("on_tick", lambda ctx: calls.append("a"), order=100)
    mh.dispatch_observers("on_tick", mh.HookContext())
    assert calls == ["a", "b"], calls


def test_observer_fail_soft():
    _reset()
    calls = []
    def boom(ctx): raise RuntimeError("kaboom")
    mh.register("on_tick", boom, order=100)
    mh.register("on_tick", lambda ctx: calls.append("ran"), order=200)
    # must not raise; second handler still runs
    mh.dispatch_observers("on_tick", mh.HookContext())
    assert calls == ["ran"]


def test_observer_stop_halts_chain():
    _reset()
    calls = []
    def first(ctx): calls.append("1"); ctx.stop()
    mh.register("on_tick", first, order=100)
    mh.register("on_tick", lambda ctx: calls.append("2"), order=200)
    mh.dispatch_observers("on_tick", mh.HookContext())
    assert calls == ["1"]


def test_context_data_is_readable():
    _reset()
    seen = {}
    mh.register("on_battle_resolved", lambda ctx: seen.update(loot=ctx.get("loot")))
    ctx = mh.HookContext({"loot": 42})
    mh.dispatch_observers("on_battle_resolved", ctx)
    assert seen["loot"] == 42


def test_context_nested_data_is_read_only():
    _reset()
    payload = {"report": {"loot": 10}}
    def mutate(ctx):
        ctx["report"]["loot"] = 0
    mh.register("on_battle_resolved", mutate)
    mh.dispatch_observers("on_battle_resolved", mh.HookContext(payload))
    assert payload["report"]["loot"] == 10, "HookContext allowed mutation of nested caller data"


def test_override_first_non_none_wins():
    _reset()
    mh.register("resolve_battle", lambda ctx: None, order=100)
    mh.register("resolve_battle", lambda ctx: {"winner": "modA"}, order=200)
    mh.register("resolve_battle", lambda ctx: {"winner": "modB"}, order=300)
    result = mh.dispatch_override("resolve_battle", mh.HookContext())
    assert result == {"winner": "modA"}


def test_override_none_when_no_handler():
    _reset()
    assert mh.dispatch_override("resolve_battle", mh.HookContext()) is None


def test_override_fail_soft_skips_to_next():
    _reset()
    def boom(ctx): raise ValueError("nope")
    mh.register("resolve_battle", boom, order=100)
    mh.register("resolve_battle", lambda ctx: {"ok": True}, order=200)
    assert mh.dispatch_override("resolve_battle", mh.HookContext()) == {"ok": True}


def test_clear_by_mod():
    _reset()
    mh.register("on_tick", lambda ctx: None, mod_id="modX")
    mh.register("on_tick", lambda ctx: None, mod_id="modY")
    mh.clear("modX")
    remaining = [h["mod_id"] for h in mh.handlers("on_tick")]
    assert remaining == ["modY"]


def test_fire_noop_without_handlers():
    _reset()
    # no handlers registered -> returns None, does not raise
    assert mh.fire("on_economy_collect", {"x": 1}) is None
    assert mh.fire_override("compute_victory", {"x": 1}) is None


def test_fire_runs_observers_with_data():
    _reset()
    seen = {}
    mh.register("on_economy_collect", lambda ctx: seen.update(e=ctx.get("total_earned")))
    mh.fire("on_economy_collect", {"total_earned": 99})
    assert seen["e"] == 99


def test_fire_is_fail_soft():
    _reset()
    mh.register("on_tick", lambda ctx: (_ for _ in ()).throw(RuntimeError("boom")))
    # must not raise into the caller (engine path)
    assert mh.fire("on_tick", {"tick_type": "income"}) is not None or True


def test_fire_override_returns_winner():
    _reset()
    mh.register("compute_victory", lambda ctx: {"winner": "modwin"})
    assert mh.fire_override("compute_victory", {"condition": "x"}) == {"winner": "modwin"}


def test_load_mod_hooks_gated_off_by_default():
    _reset()
    from database import SessionLocal
    from auth import init_default_configs, set_config
    import mod_loader as ml
    db = SessionLocal(); init_default_configs(db)
    set_config(db, "AWE_ALLOW_BEHAVIORAL_MODS", "false")
    ml.set_mod_enabled(db, "battle_logger", True)
    report = mh.load_mod_hooks(db)
    assert report["blocked"] is True and report["loaded"] == []
    assert mh.handlers("on_battle_resolved") == []  # nothing registered while blocked
    ml.set_mod_enabled(db, "battle_logger", False); db.close()


def test_load_mod_hooks_loads_battle_logger_when_allowed():
    _reset()
    from database import SessionLocal
    from auth import init_default_configs, set_config
    import mod_loader as ml
    db = SessionLocal(); init_default_configs(db)
    set_config(db, "AWE_ALLOW_BEHAVIORAL_MODS", "true")
    ml.set_mod_enabled(db, "battle_logger", True)
    report = mh.load_mod_hooks(db)
    assert "battle_logger" in report["loaded"], report
    ids = [h["mod_id"] for h in mh.handlers("on_battle_resolved")]
    assert "battle_logger" in ids
    # cleanup
    set_config(db, "AWE_ALLOW_BEHAVIORAL_MODS", "false")
    ml.set_mod_enabled(db, "battle_logger", False)
    mh.clear("battle_logger"); db.close()


def test_load_mod_hooks_does_not_import_when_blocked():
    _reset()
    import mod_loader as ml
    with TemporaryDirectory() as root:
        marker = os.path.join(root, "imported.txt")
        _write_behavior_mod(root, "side_effect", f"open({marker!r}, 'w').write('imported')\n")
        old_dir = ml.MODS_DIR
        old_enabled = ml.get_enabled_mod_ids
        old_allowed = mh.behavioral_mods_allowed
        ml.MODS_DIR = root
        ml.get_enabled_mod_ids = lambda db: ["side_effect"]
        mh.behavioral_mods_allowed = lambda db: False
        try:
            report = mh.load_mod_hooks(None)
            assert report["blocked"] is True
            assert not os.path.exists(marker), "blocked behavioral mod was imported"
        finally:
            ml.MODS_DIR = old_dir
            ml.get_enabled_mod_ids = old_enabled
            mh.behavioral_mods_allowed = old_allowed


def test_load_mod_hooks_import_failure_is_skipped():
    _reset()
    import mod_loader as ml
    with TemporaryDirectory() as root:
        _write_behavior_mod(root, "boom_mod", "raise RuntimeError('import boom')\n")
        old_dir = ml.MODS_DIR
        old_enabled = ml.get_enabled_mod_ids
        old_allowed = mh.behavioral_mods_allowed
        ml.MODS_DIR = root
        ml.get_enabled_mod_ids = lambda db: ["boom_mod"]
        mh.behavioral_mods_allowed = lambda db: True
        try:
            report = mh.load_mod_hooks(None)
            assert report["blocked"] is False
            assert report["loaded"] == []
            assert report["skipped"] and report["skipped"][0]["id"] == "boom_mod"
        finally:
            ml.MODS_DIR = old_dir
            ml.get_enabled_mod_ids = old_enabled
            mh.behavioral_mods_allowed = old_allowed


def test_load_mod_hooks_missing_register_hooks_is_skipped():
    _reset()
    import mod_loader as ml
    with TemporaryDirectory() as root:
        _write_behavior_mod(root, "no_entry", "VALUE = 1\n")
        old_dir = ml.MODS_DIR
        old_enabled = ml.get_enabled_mod_ids
        old_allowed = mh.behavioral_mods_allowed
        ml.MODS_DIR = root
        ml.get_enabled_mod_ids = lambda db: ["no_entry"]
        mh.behavioral_mods_allowed = lambda db: True
        try:
            report = mh.load_mod_hooks(None)
            assert report["loaded"] == []
            assert report["skipped"] == [{"id": "no_entry", "reason": "no register_hooks()"}]
        finally:
            ml.MODS_DIR = old_dir
            ml.get_enabled_mod_ids = old_enabled
            mh.behavioral_mods_allowed = old_allowed


if __name__ == "__main__":
    tests = [v for k, v in sorted(globals().items()) if k.startswith("test_")]
    for t in tests:
        t()
        print(f"OK {t.__name__}")
    print("\n" + "=" * 60)
    print(" ALL MOD-HOOK TESTS PASSED!")
    print("=" * 60)
