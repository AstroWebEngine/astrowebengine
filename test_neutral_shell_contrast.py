"""The neutral shell must not paint text the same colour as its background.

`[data-theme="neutral"] .awe-tab-bar a.active` overrode the background to
var(--accent) but not the colour, which the rule it cascades from sets to
var(--accent) as well. The result was a 1.00:1 contrast ratio: the active base
subtab rendered as a solid blue block with its label invisible. "Structures"
was there the whole time, painted in the background colour.

An active state that repaints its background has to repaint its foreground.
"""
import re
from pathlib import Path

import pytest

CSS = Path(__file__).parent / "static" / "style_neutral.css"


def _rules():
    text = CSS.read_text(encoding="utf-8")
    text = re.sub(r"/\*.*?\*/", "", text, flags=re.S)      # strip comments
    return re.findall(r"([^{}]+)\{([^{}]*)\}", text)


def _luminance(hex_colour):
    h = hex_colour.lstrip("#")
    if len(h) == 3:
        h = "".join(c * 2 for c in h)
    parts = [int(h[i:i + 2], 16) / 255 for i in (0, 2, 4)]
    parts = [(v / 12.92 if v <= 0.03928 else ((v + 0.055) / 1.055) ** 2.4) for v in parts]
    return 0.2126 * parts[0] + 0.7152 * parts[1] + 0.0722 * parts[2]


def contrast(a, b):
    hi, lo = sorted([_luminance(a), _luminance(b)], reverse=True)
    return (hi + 0.05) / (lo + 0.05)


def test_active_states_that_repaint_background_also_set_colour():
    offenders = []
    for sel, body in _rules():
        if ".active" not in sel:
            continue
        if not re.search(r"background(-color)?\s*:\s*var\(--accent", body):
            continue
        if not re.search(r"(^|;|\s)color\s*:", body):
            offenders.append(sel.strip().replace("\n", " ")[:80])
    assert not offenders, (
        "these active states paint an accent background without a foreground, "
        f"so their text can vanish into it: {offenders}")


def test_the_tab_bar_rule_is_readable():
    """Pin the specific regression with a real contrast figure."""
    body = next(b for s, b in _rules()
                if ".awe-tab-bar a.active" in s and "neutral" in s)
    assert re.search(r"color\s*:", body), "no foreground on the active tab"
    # accent background, --bg-dark foreground, per the neutral palette
    assert contrast("#0e1014", "#6ea8fe") >= 4.5


@pytest.mark.parametrize("fg,bg,ok", [("#0e1014", "#6ea8fe", True),
                                      ("#6ea8fe", "#6ea8fe", False)])
def test_contrast_helper_agrees_with_wcag(fg, bg, ok):
    assert (contrast(fg, bg) >= 4.5) is ok
