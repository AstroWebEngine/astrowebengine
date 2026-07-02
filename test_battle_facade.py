#!/usr/bin/env python3
"""
Tests for the resolve_battle override facade (combat.resolve_battle).

The facade routes every caller through one path: a mod-provided overriding
resolver replaces the engine resolver entirely; otherwise the built-in
_resolve_battle_default runs. on_battle_resolved observers fire once either way.

These tests exercise the facade wiring without a full DB battle: the override
path short-circuits the default, and the fall-through is checked by stubbing
_resolve_battle_default.

Run: python3 test_battle_facade.py
"""
import combat
import mod_hooks as mh


def test_override_replaces_default_and_fires_observers():
    mh.clear()
    seen = {}
    # an overriding resolver that ignores the (None) battle args entirely
    mh.register("resolve_battle", lambda ctx: {"result": "mod_won", "debris": 7})
    mh.register("on_battle_resolved", lambda ctx: seen.update(report=ctx.get("report")))
    # default must NOT run (args are all None) — override short-circuits it
    report = combat.resolve_battle(None, None, None, None, 1.0, None)
    assert report == {"result": "mod_won", "debris": 7}
    assert seen["report"]["result"] == "mod_won"  # observer saw the modded report
    mh.clear()


def test_no_override_calls_default(monkeypatch_default=True):
    mh.clear()
    called = {}
    def fake_default(*args, **kwargs):
        called["yes"] = True
        return {"result": "default_ran"}
    orig = combat._resolve_battle_default
    combat._resolve_battle_default = fake_default
    try:
        seen = {}
        mh.register("on_battle_resolved", lambda ctx: seen.update(r=ctx.get("report")))
        report = combat.resolve_battle("a", "b", "c", "d", 1.0, "db")
        assert called.get("yes") is True
        assert report == {"result": "default_ran"}
        assert seen["r"]["result"] == "default_ran"  # observers fire on default path too
    finally:
        combat._resolve_battle_default = orig
        mh.clear()


def test_override_passes_battle_args_in_context():
    mh.clear()
    got = {}
    def resolver(ctx):
        got["atk"] = ctx.get("attacker_user")
        got["tfid"] = ctx.get("target_fleet_id")
        return {"result": "ok"}
    mh.register("resolve_battle", resolver)
    combat.resolve_battle("FLEET", "ATTACKER", "COLONY", "DEFENDER", 2.0, "DB", target_fleet_id=42)
    assert got["atk"] == "ATTACKER" and got["tfid"] == 42
    mh.clear()


def test_override_wrong_shape_falls_back_to_default():
    mh.clear()
    called = {}
    def fake_default(*args, **kwargs):
        called["yes"] = True
        return {"result": "default_ran", "debris": 0}
    orig = combat._resolve_battle_default
    combat._resolve_battle_default = fake_default
    try:
        mh.register("resolve_battle", lambda ctx: "not-a-report")
        report = combat.resolve_battle("a", "b", "c", "d", 1.0, "db")
        assert called.get("yes") is True
        assert report["result"] == "default_ran"
    finally:
        combat._resolve_battle_default = orig
        mh.clear()


if __name__ == "__main__":
    tests = [v for k, v in sorted(globals().items()) if k.startswith("test_")]
    for t in tests:
        t()
        print(f"OK {t.__name__}")
    print("\n" + "=" * 60)
    print(" ALL BATTLE-FACADE TESTS PASSED!")
    print("=" * 60)
