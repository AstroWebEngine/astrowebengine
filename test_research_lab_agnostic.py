"""Research must work whatever a ruleset calls its laboratory.

routes_research.py hardcoded the building key "research_labs". Deep Frontier
names the building "research_lab", so every technology was blocked with "This
base has no Research Labs" while the base sat on seven levels of laboratory.
Research was simply impossible in that ruleset, and no test noticed because
none of them went through the endpoint.

The engine already had the data-driven answer: a building declares a
`research_lab_level` contribution, and calc_base_stats sums it.
"""
import glob
import json
from pathlib import Path

import pytest

ROOT = Path(__file__).parent


def _definitions():
    paths = glob.glob(str(ROOT / "game_definitions" / "*.json"))
    paths += glob.glob(str(ROOT / "mods" / "*" / "definition.json"))
    for p in paths:
        d = json.loads(Path(p).read_text(encoding="utf-8"))
        if d.get("buildings") and d.get("research"):
            yield Path(p).name, d


@pytest.mark.parametrize("name,defn", list(_definitions()))
def test_every_ruleset_declares_a_research_lab(name, defn):
    """A ruleset with research must have some building granting lab levels."""
    providers = [k for k, v in defn["buildings"].items()
                 if "research_lab_level" in (v.get("contributions") or {})]
    assert providers, (
        f"{name} has {len(defn['research'])} technologies but no building "
        f"contributing research_lab_level, so nothing can ever be researched")


def test_no_hardcoded_lab_key_in_the_research_path():
    """The regression: an engine file naming one ruleset's building."""
    for fname in ("routes_research.py", "app.py"):
        text = (ROOT / fname).read_text(encoding="utf-8")
        assert '"research_labs"' not in text, (
            f"{fname} hardcodes the building key 'research_labs'; use the "
            f"research_lab_level contribution so other rulesets work too")


def test_lab_level_comes_from_contributions_not_a_name():
    """calc_base_stats must surface the stat the endpoint now relies on."""
    import inspect
    import game_logic
    src = inspect.getsource(game_logic.calc_base_stats)
    assert "research_lab_level" in src
