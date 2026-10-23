"""AWE default artwork: masters in art/, sized WebP derivatives + an index in static/.

The index is what the browser reads to decide whether the AWE set has a picture
for a catalog key. An asset is only used in-game once it is listed in
art/awe/active.json, so new studies can be built and reviewed without changing
the roster players see.
"""
import json

import pytest
from PIL import Image

import importlib.util
from pathlib import Path

ROOT = Path(__file__).parent
_spec = importlib.util.spec_from_file_location("build_art", ROOT / "art" / "build_art.py")
build_art = importlib.util.module_from_spec(_spec); _spec.loader.exec_module(build_art)


def _master(path, size=1024, opaque=False):
    path.parent.mkdir(parents=True, exist_ok=True)
    img = Image.new("RGBA", (size, size), (22, 19, 16, 255 if opaque else 0))
    for x in range(size // 4, 3 * size // 4):
        for y in range(size // 3, 2 * size // 3):
            img.putpixel((x, y), (236, 170, 104, 255))
    img.save(path)


def test_builds_sizes_and_index(tmp_path):
    src, out = tmp_path / "src", tmp_path / "out"
    _master(src / "ships" / "cruiser.png")
    _master(src / "terrain" / "arid.png")
    (src / "active.json").write_text(json.dumps({"ships": ["cruiser"]}), encoding="utf-8")

    index = build_art.build(src, out)

    assert index["assets"]["ships"]["cruiser"] == {"sizes": [96, 192], "active": True}
    assert index["assets"]["terrain"]["arid"] == {"sizes": [128, 256, 512], "active": False}
    for px in (96, 192):
        with Image.open(out / "ships" / f"cruiser-{px}.webp") as im:
            assert im.size == (px, px) and im.mode == "RGBA"
    assert json.loads((out / "index.json").read_text()) == index


def test_derivatives_are_small(tmp_path):
    src, out = tmp_path / "src", tmp_path / "out"
    _master(src / "buildings" / "metal_extractor.png", size=1254)
    build_art.build(src, out)
    total = sum(p.stat().st_size for p in (out / "buildings").glob("*.webp"))
    assert total < 80_000


def test_non_square_master_is_padded_not_stretched(tmp_path):
    src, out = tmp_path / "src", tmp_path / "out"
    p = src / "defenses" / "light_laser.png"; p.parent.mkdir(parents=True)
    Image.new("RGBA", (800, 400), (236, 170, 104, 255)).save(p)
    build_art.build(src, out)
    with Image.open(out / "defenses" / "light_laser-96.webp") as im:
        assert im.size == (96, 96)
        assert im.getpixel((48, 2))[3] == 0      # padding above stays transparent
        assert im.getpixel((48, 48))[3] == 255   # subject in the middle


@pytest.mark.parametrize("bad", ["ships/Cruiser.png", "ships/cruiser-v1.png", "ufos/x.png"])
def test_rejects_names_that_are_not_catalog_keys_or_unknown_kinds(tmp_path, bad):
    src, out = tmp_path / "src", tmp_path / "out"
    _master(src / bad)
    with pytest.raises(ValueError):
        build_art.build(src, out)


def test_active_list_must_name_built_assets(tmp_path):
    src, out = tmp_path / "src", tmp_path / "out"
    _master(src / "ships" / "cruiser.png")
    (src / "active.json").write_text(json.dumps({"ships": ["destroyer"]}), encoding="utf-8")
    with pytest.raises(ValueError, match="destroyer"):
        build_art.build(src, out)


def test_committed_index_matches_masters():
    """static/art/awe/index.json must be rebuilt whenever masters or active.json change."""
    src = ROOT / "art" / "awe"
    if not any(src.glob("*/*.png")):
        pytest.skip("no masters yet")
    committed = json.loads((ROOT / "static" / "art" / "awe" / "index.json").read_text())
    assert committed == build_art.plan_index(src), "run: python art/build_art.py"


# -- spec "image" field ---------------------------------------------------------

def _with_image(value, section="ships"):
    from game_definition import build_default_definition
    d = build_default_definition()
    key = next(iter(d[section]))
    d[section][key]["image"] = value
    return d


@pytest.mark.parametrize("value", [
    "https://cdn.example.com/art/cruiser.webp",
    "/static/art/mygame/cruiser.webp",
    "art/mygame/cruiser.webp",
])
def test_valid_image_values_pass(value):
    from game_definition import validate_definition
    assert not [e for e in validate_definition(_with_image(value)) if "image" in e]


@pytest.mark.parametrize("value", [
    "javascript:alert(1)", "data:image/png;base64,AAAA", "../../etc/passwd",
    'cruiser.webp" onerror="x', 42, "", "ftp://x/y.png",
])
def test_unsafe_or_malformed_image_values_fail(value):
    from game_definition import validate_definition
    errs = [e for e in validate_definition(_with_image(value, "buildings")) if "image" in e]
    assert errs, value


def test_aliases_share_one_image_across_rulesets(tmp_path):
    """Classic Space calls it metal_refineries, Deep Frontier metal_extractor:
    one master should serve both keys."""
    src, out = tmp_path / "src", tmp_path / "out"
    _master(src / "buildings" / "metal_refineries.png")
    (src / "aliases.json").write_text(json.dumps(
        {"buildings": {"metal_extractor": "metal_refineries"}}), encoding="utf-8")
    (src / "active.json").write_text(json.dumps({"buildings": ["metal_refineries"]}), encoding="utf-8")
    index = build_art.build(src, out)
    alias = index["assets"]["buildings"]["metal_extractor"]
    assert alias == {"sizes": [96, 192], "active": True, "file": "metal_refineries"}
    assert not (out / "buildings" / "metal_extractor-96.webp").exists()   # no duplicate files


def test_alias_to_missing_master_is_an_error(tmp_path):
    src, out = tmp_path / "src", tmp_path / "out"
    _master(src / "buildings" / "metal_refineries.png")
    (src / "aliases.json").write_text(json.dumps({"buildings": {"x_key": "nope"}}), encoding="utf-8")
    with pytest.raises(ValueError, match="nope"):
        build_art.build(src, out)
