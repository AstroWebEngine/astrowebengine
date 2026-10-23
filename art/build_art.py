"""Build the AWE default artwork set.

Masters (large PNGs, ideally 1024x1024 with a transparent background) live in
art/awe/<kind>/<catalog_key>.png. This script writes sized WebP derivatives to
static/art/awe/<kind>/<key>-<px>.webp and an index the game reads:

    static/art/awe/index.json
    {"version": 1, "assets": {"ships": {"cruiser": {"sizes": [96, 192], "active": true}}}}

An asset appears in-game only when it is listed in art/awe/active.json
({"ships": ["cruiser"], ...}); everything else is built for review but unused.
art/awe/aliases.json ({"buildings": {"metal_extractor": "metal_refineries"}})
lets one master serve equivalent keys in different rulesets.

Run:  python art/build_art.py
"""
import json
import re
import sys
from pathlib import Path

from PIL import Image

ROOT = Path(__file__).resolve().parent.parent
SRC = ROOT / "art" / "awe"
OUT = ROOT / "static" / "art" / "awe"

# kind -> output pixel sizes. Units are shown at 48 CSS px (96/192 for 1x/2x+
# screens); planets up to 240 CSS px.
SIZES = {
    "ships": [96, 192],
    "buildings": [96, 192],
    "defenses": [96, 192],
    "research": [96, 192],
    "terrain": [128, 256, 512],
}
_KEY = re.compile(r"[a-z0-9_]+")
WEBP_QUALITY = 82


def _masters(src: Path):
    for path in sorted(src.glob("*/*.png")):
        kind, key = path.parent.name, path.stem
        if kind not in SIZES:
            raise ValueError(f"{path}: unknown kind {kind!r}; use one of {sorted(SIZES)}")
        if not _KEY.fullmatch(key):
            raise ValueError(f"{path}: name must be the catalog key (lowercase letters, digits, _)")
        yield kind, key, path


def _active(src: Path) -> dict:
    f = src / "active.json"
    return json.loads(f.read_text(encoding="utf-8")) if f.exists() else {}


def plan_index(src: Path = SRC) -> dict:
    """The index the masters and active.json describe (no files written)."""
    active = _active(src)
    assets = {}
    for kind, key, _ in _masters(src):
        assets.setdefault(kind, {})[key] = {"sizes": list(SIZES[kind]),
                                            "active": key in active.get(kind, [])}
    for kind, keys in active.items():
        for key in keys:
            if key not in assets.get(kind, {}):
                raise ValueError(f"active.json lists {kind}/{key}, but there is no master for it")
    # Aliases let one master serve equivalent keys in different rulesets
    # (e.g. buildings/metal_extractor -> metal_refineries). They inherit the
    # target's sizes and active state and point at its files.
    aliases_file = src / "aliases.json"
    aliases = json.loads(aliases_file.read_text(encoding="utf-8")) if aliases_file.exists() else {}
    for kind, mapping in aliases.items():
        for alias, target in mapping.items():
            if target not in assets.get(kind, {}):
                raise ValueError(f"aliases.json maps {kind}/{alias} to {target!r}, which has no master")
            if not _KEY.fullmatch(alias):
                raise ValueError(f"aliases.json: {alias!r} is not a catalog key")
            assets[kind].setdefault(alias, {**assets[kind][target], "file": target})
    return {"version": 1, "assets": assets}


def _square(img: Image.Image) -> Image.Image:
    """Pad to a square on a transparent canvas (never stretch)."""
    img = img.convert("RGBA")
    side = max(img.size)
    if img.size == (side, side):
        return img
    canvas = Image.new("RGBA", (side, side), (0, 0, 0, 0))
    canvas.paste(img, ((side - img.width) // 2, (side - img.height) // 2))
    return canvas


def build(src: Path = SRC, out: Path = OUT) -> dict:
    index = plan_index(src)
    for kind, key, path in _masters(src):
        (out / kind).mkdir(parents=True, exist_ok=True)
        with Image.open(path) as im:
            square = _square(im)
        for px in SIZES[kind]:
            square.resize((px, px), Image.LANCZOS).save(
                out / kind / f"{key}-{px}.webp", "WEBP", quality=WEBP_QUALITY, method=6)
    out.mkdir(parents=True, exist_ok=True)
    (out / "index.json").write_text(json.dumps(index, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    return index


if __name__ == "__main__":
    idx = build()
    n = sum(len(v) for v in idx["assets"].values())
    live = sum(a["active"] for v in idx["assets"].values() for a in v.values())
    print(f"built {n} assets ({live} active) into {OUT}")
    sys.exit(0)
