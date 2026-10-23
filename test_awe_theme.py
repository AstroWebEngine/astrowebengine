"""The AWE theme is the engine's default look, so its palette has to stay readable.

Every text colour is checked against the surfaces it is drawn on, using the
values actually declared in static/style_awe.css (not copies of them), so a
palette tweak that drops below WCAG AA fails here rather than in a player's eyes.
"""
import re
from pathlib import Path

import pytest

from test_neutral_shell_contrast import contrast

STATIC = Path(__file__).parent / "static"


def _palette():
    """Theme colours, with var(--awe-*) references resolved from the brand tokens."""
    brand = dict(re.findall(r"--(awe-[\w-]+)\s*:\s*(#[0-9a-fA-F]{6})",
                            (STATIC / "brand" / "tokens.css").read_text(encoding="utf-8")))
    css = (STATIC / "style_awe.css").read_text(encoding="utf-8")
    block = re.search(r'\[data-theme="awe"\]:not\(\[data-skin\]\)\s*\{([^}]*)\}', css).group(1)
    palette = {}
    for name, value in re.findall(r"--([\w-]+)\s*:\s*([^;]+);", block):
        ref = re.fullmatch(r"var\(--(awe-[\w-]+)\)", value.strip())
        palette[name] = brand[ref.group(1)] if ref else value.strip()
    return palette


PALETTE = _palette()
SURFACES = ["bg-dark", "bg-panel", "bg-card", "bg-header"]
TEXT = ["text", "text-dim", "text-bright", "link", "accent", "warn", "danger", "success",
        "structures", "defenses", "research", "production", "player-guild", "player-npc"]


@pytest.mark.parametrize("fg", TEXT)
@pytest.mark.parametrize("bg", SURFACES)
def test_text_is_readable_on_every_surface(fg, bg):
    ratio = contrast(PALETTE[fg], PALETTE[bg])
    assert ratio >= 4.5, f"--{fg} on --{bg} is {ratio:.2f}:1 (needs 4.5)"


def test_dark_text_on_amber_buttons_is_readable():
    # .btn-primary and active tabs paint --accent and write in --bg-dark.
    assert contrast(PALETTE["bg-dark"], PALETTE["accent"]) >= 4.5


@pytest.mark.parametrize("page", ["game", "index", "admin", "setup", "lobby", "gallery"])
def test_pages_load_tokens_then_neutral_then_awe(page):
    html = (STATIC / f"{page}.html").read_text(encoding="utf-8")
    assert html.index("brand/tokens.css") < html.index("style_neutral.css") < html.index("style_awe.css")


def test_awe_is_the_default_theme():
    core = (STATIC / "core.js").read_text(encoding="utf-8")
    assert "|| 'awe'" in core
    html = (STATIC / "game.html").read_text(encoding="utf-8")
    assert "||'awe'" in html, "pre-paint script must default to awe too, or the page flashes"


def test_website_token_copy_matches_canonical():
    """The website deploys from website/ alone (Cloudflare Pages), so it can't load
    /static/brand/tokens.css and keeps a copy. The copy must not drift."""
    copy = Path(__file__).parent / "website" / "brand" / "tokens.css"
    if not copy.exists():
        pytest.skip("website has no token copy yet")
    assert copy.read_bytes() == (STATIC / "brand" / "tokens.css").read_bytes(), (
        "website/brand/tokens.css differs from static/brand/tokens.css - copy the canonical file")


SURFACES_BY_PAGE = {"index": "game", "setup": "game", "admin": "engine",
                    "gallery": "engine", "lobby": "engine"}


@pytest.mark.parametrize("page,surface", SURFACES_BY_PAGE.items())
def test_pages_declare_their_theme_surface(page, surface):
    html = (STATIC / f"{page}.html").read_text(encoding="utf-8")
    tag = re.search(r'<script src="/static/theme_boot\.js[^"]*"([^>]*)>', html)
    assert tag, f"{page}.html doesn't load theme_boot.js"
    assert f'data-surface="{surface}"' in tag.group(1)


def test_outside_pages_ignore_the_game_theme_cache():
    """Engine pages and a game's login must not take the theme of whichever game
    this browser visited last, so theme_boot.js never reads the game's cache."""
    boot = (STATIC / "theme_boot.js").read_text(encoding="utf-8")
    code = "\n".join(l for l in boot.splitlines() if not l.strip().startswith("//"))
    assert "awe_theme" not in code


@pytest.mark.parametrize("page", ["game", "setup"])
def test_pages_that_apply_player_skins_load_the_skin_palettes(page):
    """setup applies the player's skin attribute; without the skin palettes it
    silently fell back to the classic colours instead of the chosen skin."""
    html = (STATIC / f"{page}.html").read_text(encoding="utf-8")
    assert "style_skins.css" in html
    for skin in ("amber-grid", "dark-astros"):
        assert f'[data-skin="{skin}"] {{' in (STATIC / "style_skins.css").read_text(encoding="utf-8")


def test_setup_galaxy_cards_are_keyboard_selectable():
    html = (STATIC / "setup.html").read_text(encoding="utf-8")
    assert 'role="radiogroup"' in html and 'role="radio"' in html and 'tabindex="0"' in html
    assert "onkeydown=\"galaxyCardKey(" in html
