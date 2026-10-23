"""Where AstroWebEngine keeps runtime state.

Everything the server writes while running — the active ruleset, the recorded
mod base, definitions saved by creators or the AI assistant — lives under
AWE_DATA_DIR. It defaults to the project folder, so a source checkout behaves as
it always has; the Docker image sets it to /data, the persistent volume, so an
image update no longer reverts the game's rules.

Functions rather than constants: the environment is read on each call, which
keeps tests (and a future multi-instance runner) honest.
"""
import os
import shutil
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parent
BUNDLED_DEFINITIONS_DIR = PROJECT_ROOT / "game_definitions"

_LEGACY_FILES = ("_active_definition.json", "_mod_base_definition.json")
_LEGACY_DEFINITION_GLOB = "ai_*.json"   # AI-assistant drafts; bundled definitions stay put


def data_dir() -> Path:
    return Path(os.environ.get("AWE_DATA_DIR") or PROJECT_ROOT).resolve()


def active_definition_path() -> Path:
    return data_dir() / "_active_definition.json"


def mod_base_path() -> Path:
    return data_dir() / "_mod_base_definition.json"


def user_definitions_dir() -> Path:
    """Creator- and AI-saved definitions. Same folder as the bundled ones unless
    AWE_DATA_DIR points elsewhere."""
    return data_dir() / "game_definitions"


def definition_dirs() -> list:
    """Folders that hold selectable definitions, user copies first."""
    dirs = [user_definitions_dir(), BUNDLED_DEFINITIONS_DIR]
    return [d for i, d in enumerate(dirs) if d not in dirs[:i]]


def find_definition_file(filename: str):
    """Resolve a plain definition filename (no folders) to a path, preferring a
    user copy over the bundled one. None if invalid or missing."""
    name = str(filename or "")
    if not name or name != os.path.basename(name) or "/" in name or "\\" in name \
            or ":" in name or name in (".", ".."):
        return None
    for d in definition_dirs():
        candidate = d / name
        if candidate.is_file():
            return candidate
    return None


def migrate_legacy_runtime_files() -> list:
    """Move state written next to the code by older versions into AWE_DATA_DIR.

    Runs at startup. Moves only when the target doesn't exist yet, so it never
    overwrites newer data; a skipped legacy file is left in place for the
    operator. Returns a description of each file moved.
    """
    target_root = data_dir()
    if target_root == PROJECT_ROOT.resolve():
        return []
    moves = [(PROJECT_ROOT / f, target_root / f) for f in _LEGACY_FILES]
    if BUNDLED_DEFINITIONS_DIR.is_dir():
        moves += [(p, user_definitions_dir() / p.name)
                  for p in sorted(BUNDLED_DEFINITIONS_DIR.glob(_LEGACY_DEFINITION_GLOB))]
    moved = []
    for src, dst in moves:
        if not src.is_file() or dst.exists():
            continue
        dst.parent.mkdir(parents=True, exist_ok=True)
        shutil.move(str(src), str(dst))
        moved.append(f"{src} -> {dst}")
    return moved


def load_or_create_secret_key() -> str:
    """The JWT signing key: AWE_SECRET_KEY if set, otherwise one generated once
    and kept in AWE_DATA_DIR/.secret_key.

    A fresh random key per process logged every player out on each restart and
    gave each uvicorn worker a different key. Creation uses exclusive open, so
    workers starting together agree on the first key written.
    """
    env = os.environ.get("AWE_SECRET_KEY")
    if env:
        return env
    import secrets
    path = data_dir() / ".secret_key"
    if not path.exists():
        path.parent.mkdir(parents=True, exist_ok=True)
        try:
            with open(path, "x", encoding="utf-8") as f:
                f.write(secrets.token_hex(32))
            try:
                os.chmod(path, 0o600)
            except OSError:
                pass
        except FileExistsError:
            pass   # another worker won the race; use its key
    return path.read_text(encoding="utf-8").strip()
