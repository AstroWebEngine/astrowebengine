"""The schema doc is what an AI reads to write a definition - it must not fall behind the engine."""
import json
import os

import schema_doc
from game_definition import SETUP_ONLY, HOTSWAP_SAFE, BALANCE_SENSITIVE

ROOT = os.path.dirname(os.path.abspath(__file__))


def test_every_section_present():
    for s in schema_doc.SECTIONS:
        body = schema_doc.get_section(s)
        assert body and len(body.strip()) > 80, f"section '{s}' missing or empty"


def test_every_bundled_top_level_key_documented():
    for fname in ("deep_frontier.json", "classic_space.json"):
        with open(os.path.join(ROOT, "game_definitions", fname), encoding="utf-8") as f:
            for key in json.load(f):
                assert schema_doc.get_section(key), f"{fname}: top-level key '{key}' undocumented"


def test_default_definition_top_level_keys_documented():
    from game_definition import build_default_definition
    for key in build_default_definition():
        assert schema_doc.get_section(key), f"default definition key '{key}' undocumented"


def test_every_engine_flag_documented():
    engine = schema_doc.get_section("engine")
    for flag in sorted(SETUP_ONLY | HOTSWAP_SAFE | BALANCE_SENSITIVE):
        assert f"`{flag}`" in engine, f"engine flag '{flag}' undocumented"


def test_required_fields_documented():
    ships = schema_doc.get_section("ships")
    for field in ("name", "cost", "attack", "armour", "shield", "weapon"):
        assert f"`{field}`" in ships
    buildings = schema_doc.get_section("buildings")
    for field in ("name", "base_cost", "cost_mult"):
        assert f"`{field}`" in buildings
    assert "`shield_passthrough`" in schema_doc.get_section("weapon_types")


def test_unknown_section_returns_none():
    assert schema_doc.get_section("nope") is None


def test_dockerignore_keeps_schema_doc():
    """The MCP tools read docs/definition_schema.md at runtime; the image must contain it."""
    import fnmatch
    target = "docs/definition_schema.md"
    excluded = False
    dir_excluded = False  # a directory rule cannot be re-included from inside
    with open(os.path.join(ROOT, ".dockerignore"), encoding="utf-8") as f:
        for line in f:
            rule = line.strip()
            if not rule or rule.startswith("#"):
                continue
            negate = rule.startswith("!")
            pat = rule[1:] if negate else rule
            if pat.endswith("/"):
                matched = target.startswith(pat)
                if matched and not negate:
                    dir_excluded = True
                continue
            else:
                matched = fnmatch.fnmatch(target, pat)
            if matched:
                excluded = not negate
    assert not (excluded or dir_excluded), ".dockerignore excludes docs/definition_schema.md"
