"""Serve docs/definition_schema.md in per-section slices (one `## name` per section)."""
import os
import re

_PATH = os.path.join(os.path.dirname(os.path.abspath(__file__)), "docs", "definition_schema.md")

SECTIONS = ["overview", "meta", "extends", "engine", "ui", "economy", "combat", "fleet",
            "weapon_types", "ships", "buildings", "research", "defenses", "tutorial", "terrains"]


def full_text() -> str:
    with open(_PATH, encoding="utf-8") as f:
        return f.read()


def get_section(name: str):
    parts = re.split(r"^## +", full_text(), flags=re.MULTILINE)
    for part in parts[1:]:
        heading, _, body = part.partition("\n")
        if heading.strip() == name:
            return f"## {heading.strip()}\n{body.rstrip()}\n"
    return None
