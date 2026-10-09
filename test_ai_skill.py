"""The downloadable skill zip must match its source and only name real MCP tools."""
import os
import re

ROOT = os.path.dirname(os.path.abspath(__file__))


def test_zip_matches_source():
    from ai.build_skill_zip import build_zip_bytes
    with open(os.path.join(ROOT, "static", "ai", "awe-game-designer.zip"), "rb") as f:
        assert f.read() == build_zip_bytes(), "run: python -m ai.build_skill_zip"


def test_skill_frontmatter_and_tool_names():
    with open(os.path.join(ROOT, "ai", "awe-game-designer", "SKILL.md"), encoding="utf-8") as f:
        text = f.read()
    assert text.startswith("---\nname: awe-game-designer\ndescription: ")
    import mcp_server
    real = {t.name for t in mcp_server.mcp._tool_manager.list_tools()}
    named = set(re.findall(r"`([a-z_]+)\(", text))
    assert named and named <= real, f"skill names unknown tools: {named - real}"
