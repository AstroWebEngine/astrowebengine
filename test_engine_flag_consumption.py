"""Every engine flag a ruleset can set must actually do something.

Twice now a flag has been declared, documented, set by shipped rulesets and read
by nothing: `combat_model` selected a battle model the resolver never consulted,
and `rapid_fire` tables sat in a definition that combat.py never opened. Both
looked configured and changed nothing, which is worse than an unsupported flag
that errors, because there is no symptom to notice.

This test walks the flags the shipped rulesets actually declare and fails when
one has no consumer anywhere in the engine or the client. A genuinely
descriptive flag goes in DESCRIPTIVE below with the reason - that list is meant
to be short and to shrink.
"""
import glob
import json
import re
from pathlib import Path

import pytest

ROOT = Path(__file__).parent

# Flags carried for documentation rather than behaviour. Each needs a reason,
# and anything unimplemented should be rejected by validate_definition instead
# of living here.
DESCRIPTIVE = {
    "map_levels": "human-readable tier names; map_depth is what universe.py branches on",
    "buildings_destructible": "not implemented; validate_definition rejects the true value",
    "ships_always_destroyed": "not implemented; validate_definition rejects the false value",
}


def _declared_flags():
    flags = {}
    patterns = ["game_definitions/*.json", "mods/*/definition.json",
                "game_definitions/fragments/*/*.json"]
    for pattern in patterns:
        for path in glob.glob(str(ROOT / pattern)):
            data = json.loads(Path(path).read_text(encoding="utf-8"))
            for flag in (data.get("engine") or {}):
                flags.setdefault(flag, []).append(Path(path).name)
    return flags


def _sources():
    out = {}
    for pattern in ("*.py", "static/*.js", "static/*.html"):
        for path in glob.glob(str(ROOT / pattern)):
            name = Path(path).name
            if name.startswith("test_") or name == "game_definition.py":
                # game_definition declares and validates flags; it never consumes them,
                # so counting it would let any dead flag pass.
                continue
            out[name] = Path(path).read_text(encoding="utf-8", errors="ignore")
    return out


@pytest.mark.parametrize("flag", sorted(_declared_flags()))
def test_declared_flag_has_a_consumer(flag):
    if flag in DESCRIPTIVE:
        pytest.skip(f"documented as descriptive: {DESCRIPTIVE[flag]}")
    needle = re.compile(rf'["\']{re.escape(flag)}["\']')
    consumers = [name for name, text in _sources().items() if needle.search(text)]
    assert consumers, (
        f"engine.{flag} is set by a shipped ruleset but read by nothing. "
        f"Either wire it up, have validate_definition reject the unsupported "
        f"value, or record it in DESCRIPTIVE with a reason."
    )


def test_descriptive_list_has_no_stale_entries():
    """A flag that gained a consumer should leave the exemption list."""
    sources = _sources()
    for flag, reason in DESCRIPTIVE.items():
        if flag in ("buildings_destructible", "ships_always_destroyed"):
            continue  # rejected by validation, not consumed by design
        needle = re.compile(rf'["\']{re.escape(flag)}["\']')
        consumers = [n for n, t in sources.items() if needle.search(t)]
        assert not consumers, (
            f"engine.{flag} is listed as descriptive but is read by {consumers}; "
            f"remove it from DESCRIPTIVE")


def test_unimplemented_flags_are_rejected_not_ignored():
    """The dishonest value must fail validation rather than pass silently."""
    import game_definition as gd

    base = json.loads((ROOT / "game_definitions" / "classic_space.json").read_text(encoding="utf-8"))
    compiled = gd.compile_definition(base, base_dir=str(ROOT / "game_definitions"))
    assert not gd.validate_definition(compiled), "baseline ruleset should be valid"

    for flag, bad_value in (("buildings_destructible", True), ("ships_always_destroyed", False)):
        broken = json.loads(json.dumps(compiled))
        broken["engine"][flag] = bad_value
        errors = gd.validate_definition(broken)
        assert errors, f"engine.{flag}={bad_value!r} was accepted despite doing nothing"
        assert any(flag in str(e) for e in errors), f"error should name {flag}: {errors}"


def test_multi_resource_with_scalar_costs_is_rejected():
    """The Build Game UI can offer this combination, so validation has to catch it.

    Base default resources + the multi-resource component gives resource_model
    'multi' over a roster whose costs are plain numbers. normalize_cost maps a
    bare number onto the primary resource, so the other two are mined and never
    spent - a degenerate economy that raises nothing at runtime.
    """
    import game_definition as gd

    compiled = gd.compile_definition(
        {"extends": ["classic_space.json", "fragments/resources/multi_mcd.json"],
         "meta": {"name": "Classic Space Custom", "version": "1.0", "description": "x"}},
        base_dir=str(ROOT / "game_definitions"))
    assert compiled["engine"]["resource_model"] == "multi", "fixture no longer reproduces"

    errors = gd.validate_definition(compiled)
    assert errors, "a multi-resource economy with scalar costs was accepted"
    assert any("resource_model" in str(e) for e in errors)


@pytest.mark.parametrize("path", [
    "game_definitions/classic_space.json",
    "game_definitions/deep_frontier.json",
    "mods/stellar_conquest/definition.json",
])
def test_shipped_rulesets_stay_valid(path):
    """The new check must not catch anything that legitimately ships."""
    import game_definition as gd
    data = json.loads((ROOT / path).read_text(encoding="utf-8"))
    compiled = gd.compile_definition(data, base_dir=str(ROOT / "game_definitions"))
    assert not gd.validate_definition(compiled)
