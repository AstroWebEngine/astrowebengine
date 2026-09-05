"""A changed stylesheet must ship a changed cache-busting version.

game.html pins its stylesheets with ?v=N. Editing the CSS without bumping N
means every browser that has already loaded the page keeps its cached copy and
never sees the change - the fix is deployed, verified on the server, and
invisible to every existing player.

That happened to three CSS fixes in one day. This test cannot know whether a
given edit shipped, so it pins the far cheaper invariant: every stylesheet
game.html references is versioned at all, and no two share a stale default.
"""
import re
from pathlib import Path

ROOT = Path(__file__).parent
GAME_HTML = ROOT / "static" / "game.html"


def _linked():
    html = GAME_HTML.read_text(encoding="utf-8")
    return re.findall(r'href="/static/([A-Za-z0-9_.-]+\.css)(\?v=(\d+))?"', html)


def test_every_linked_stylesheet_exists():
    for name, _, _ in _linked():
        assert (ROOT / "static" / name).exists(), f"game.html links a missing {name}"


def test_every_linked_stylesheet_is_versioned():
    """An unversioned link cannot be busted when its contents change."""
    unversioned = [name for name, q, _ in _linked() if not q]
    assert not unversioned, (
        f"these stylesheets have no ?v= and will serve stale to returning "
        f"players after an edit: {unversioned}")


def test_versions_are_positive_integers():
    for name, _, ver in _linked():
        assert ver and int(ver) >= 1, f"{name} has a malformed version"
