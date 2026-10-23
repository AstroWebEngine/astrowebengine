"""Every inline <script> in the static pages must parse.

A single syntax error (a stray line break inside a quoted string, say) stops the
whole block from loading, which silently removes every function in it - the
admin panel's buttons all stop working, and no Python test notices.
"""
import re
import shutil
import subprocess
from pathlib import Path

import pytest

STATIC = Path(__file__).parent / "static"
PAGES = sorted(STATIC.glob("*.html"))
NODE = shutil.which("node")


@pytest.mark.skipif(not NODE, reason="node is not installed")
@pytest.mark.parametrize("page", PAGES, ids=lambda p: p.name)
def test_inline_scripts_parse(page, tmp_path):
    html = page.read_text(encoding="utf-8")
    for i, block in enumerate(re.findall(r"<script>(.*?)</script>", html, re.S)):
        f = tmp_path / f"{page.stem}_{i}.js"
        f.write_text(block, encoding="utf-8")
        r = subprocess.run([NODE, "--check", str(f)], capture_output=True, text=True)
        assert r.returncode == 0, f"{page.name} script #{i}:\n{r.stderr[:500]}"


@pytest.mark.skipif(not NODE, reason="node is not installed")
@pytest.mark.parametrize("script", sorted(STATIC.glob("*.js")), ids=lambda p: p.name)
def test_static_js_parses(script):
    r = subprocess.run([NODE, "--check", str(script)], capture_output=True, text=True)
    assert r.returncode == 0, f"{script.name}:\n{r.stderr[:500]}"
