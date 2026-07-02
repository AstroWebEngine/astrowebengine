"""
Universe Manager for the AstroWebEngine.

Manages multiple game universe instances, each running as a separate
subprocess with its own database and game definition.

Universe registry is stored in universes.json.
Database files live in universes/ directory.
"""

import json
import os
import sys
import signal
import subprocess
import time
import uuid
from datetime import datetime, timezone
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parent
REGISTRY_FILE = PROJECT_ROOT / "universes.json"
UNIVERSES_DIR = PROJECT_ROOT / "universes"
GAME_DEFS_DIR = PROJECT_ROOT / "game_definitions"

# Track running subprocesses in memory (PIDs in registry may be stale)
_running_procs = {}  # {universe_id: subprocess.Popen}


# ---------------------------------------------------------------------------
# Registry I/O
# ---------------------------------------------------------------------------

def _ensure_dirs():
    UNIVERSES_DIR.mkdir(exist_ok=True)

def load_registry() -> dict:
    """Load the universe registry from disk."""
    if not REGISTRY_FILE.exists():
        return {"universes": []}
    with open(REGISTRY_FILE, 'r', encoding='utf-8') as f:
        return json.load(f)

def save_registry(data: dict):
    """Save the universe registry to disk."""
    with open(REGISTRY_FILE, 'w', encoding='utf-8') as f:
        json.dump(data, f, indent=2, ensure_ascii=False)

def get_universe(universe_id: str) -> dict:
    """Get a single universe entry by ID."""
    reg = load_registry()
    for u in reg["universes"]:
        if u["id"] == universe_id:
            return u
    return None

def list_universes() -> list:
    """Get all universe entries with live status checks."""
    reg = load_registry()
    for u in reg["universes"]:
        if u.get("status") == "running":
            if not _is_pid_alive(u.get("pid")):
                u["status"] = "stopped"
                u["pid"] = None
    save_registry(reg)
    return reg["universes"]


# ---------------------------------------------------------------------------
# Universe CRUD
# ---------------------------------------------------------------------------

def create_universe(name: str, game_definition: str = "classic_space.json",
                    port: int = 8100, description: str = "",
                    game_speed: float = 1.0, max_players: int = 100,
                    subdomain: str = "") -> dict:
    """Create a new universe entry (does not start it)."""
    _ensure_dirs()
    reg = load_registry()

    # Validate port uniqueness
    for u in reg["universes"]:
        if u["port"] == port:
            raise ValueError(f"Port {port} is already used by universe '{u['name']}'")

    # Validate subdomain uniqueness (if provided)
    subdomain = subdomain.strip().lower()
    if subdomain:
        for u in reg["universes"]:
            if u.get("subdomain") == subdomain:
                raise ValueError(f"Subdomain '{subdomain}' is already used by universe '{u['name']}'")

    universe_id = f"u{uuid.uuid4().hex[:8]}"
    db_filename = f"{name.lower().replace(' ', '_')}.db"

    entry = {
        "id": universe_id,
        "name": name,
        "game_definition": game_definition,
        "database": f"universes/{db_filename}",
        "port": port,
        "status": "stopped",
        "pid": None,
        "created_at": datetime.now(timezone.utc).isoformat(),
        "description": description,
        "game_speed": game_speed,
        "max_players": max_players,
        "subdomain": subdomain,
    }

    reg["universes"].append(entry)
    save_registry(reg)
    return entry


def delete_universe(universe_id: str) -> bool:
    """Delete a stopped universe. Returns True if deleted."""
    reg = load_registry()
    entry = None
    for u in reg["universes"]:
        if u["id"] == universe_id:
            entry = u
            break
    if not entry:
        raise ValueError(f"Universe '{universe_id}' not found")
    if entry["status"] == "running":
        raise ValueError("Cannot delete a running universe. Stop it first.")

    reg["universes"] = [u for u in reg["universes"] if u["id"] != universe_id]
    save_registry(reg)
    return True


# ---------------------------------------------------------------------------
# Process lifecycle
# ---------------------------------------------------------------------------

def start_universe(universe_id: str) -> dict:
    """Start a universe subprocess. Returns updated entry."""
    reg = load_registry()
    entry = None
    for u in reg["universes"]:
        if u["id"] == universe_id:
            entry = u
            break
    if not entry:
        raise ValueError(f"Universe '{universe_id}' not found")
    if entry["status"] == "running" and _is_pid_alive(entry.get("pid")):
        raise ValueError("Universe is already running")

    _ensure_dirs()
    db_path = str(PROJECT_ROOT / entry["database"])

    env = os.environ.copy()
    env["DATABASE_URL"] = f"sqlite:///{db_path}"
    env["AWE_ADMIN_SEPARATE"] = "1"  # No admin routes on game servers
    env["AWE_UNIVERSE_ID"] = universe_id
    env["AWE_UNIVERSE_NAME"] = entry["name"]

    # Set game definition if specified. A "mod:<id>" value selects a packaged
    # ruleset mod: compose it (resolving fragment extends) to a per-universe file
    # so the child server boots a fully-resolved definition.
    game_def_file = entry.get("game_definition", "")
    if game_def_file:
        if game_def_file.startswith("mod:"):
            try:
                import mod_loader as ml
                import json as _json
                mod = ml._get_mod(game_def_file.split(":", 1)[1])
                if mod:
                    composed = ml.load_mod_definition(mod)
                    tmp_def = UNIVERSES_DIR / f"{universe_id}_definition.json"
                    with open(str(tmp_def), "w", encoding="utf-8") as fh:
                        _json.dump(composed, fh)
                    env["AWE_GAME_DEFINITION"] = str(tmp_def)
            except Exception:
                pass
        else:
            game_def_path = str(GAME_DEFS_DIR / game_def_file)
            if os.path.exists(game_def_path):
                env["AWE_GAME_DEFINITION"] = game_def_path

    # Set game speed
    if entry.get("game_speed"):
        env["AWE_GAME_SPEED"] = str(entry["game_speed"])

    # Log file for this universe
    log_path = UNIVERSES_DIR / f"{universe_id}.log"
    log_file = open(str(log_path), 'a', encoding='utf-8')
    log_file.write(f"\n--- Starting universe '{entry['name']}' at {datetime.now()} ---\n")
    log_file.flush()

    proc = subprocess.Popen(
        [sys.executable, "-m", "uvicorn", "app:app",
         "--host", "0.0.0.0", "--port", str(entry["port"]),
         "--log-level", "info"],
        env=env,
        cwd=str(PROJECT_ROOT),
        stdout=log_file,
        stderr=subprocess.STDOUT,
    )

    entry["pid"] = proc.pid
    entry["status"] = "running"
    _running_procs[universe_id] = proc
    save_registry(reg)
    return entry


def stop_universe(universe_id: str) -> dict:
    """Stop a running universe. Returns updated entry."""
    reg = load_registry()
    entry = None
    for u in reg["universes"]:
        if u["id"] == universe_id:
            entry = u
            break
    if not entry:
        raise ValueError(f"Universe '{universe_id}' not found")

    pid = entry.get("pid")

    # Try the tracked Popen object first
    proc = _running_procs.pop(universe_id, None)
    if proc and proc.poll() is None:
        proc.terminate()
        try:
            proc.wait(timeout=5)
        except subprocess.TimeoutExpired:
            proc.kill()
    elif pid and _is_pid_alive(pid):
        # Fallback: kill by PID (e.g., after admin restart)
        _kill_pid(pid)

    entry["status"] = "stopped"
    entry["pid"] = None
    save_registry(reg)
    return entry


def get_universe_log(universe_id: str, lines: int = 100) -> str:
    """Get the last N lines of a universe's log file."""
    log_path = UNIVERSES_DIR / f"{universe_id}.log"
    if not log_path.exists():
        return "(no log file)"
    with open(str(log_path), 'r', encoding='utf-8', errors='replace') as f:
        all_lines = f.readlines()
    return "".join(all_lines[-lines:])


def check_all_universes():
    """Health check: update status of all universes based on PID liveness."""
    reg = load_registry()
    changed = False
    for u in reg["universes"]:
        if u["status"] == "running":
            if not _is_pid_alive(u.get("pid")):
                u["status"] = "stopped"
                u["pid"] = None
                changed = True
    if changed:
        save_registry(reg)


def get_next_available_port(start: int = 8100) -> int:
    """Find the next unused port in the registry."""
    reg = load_registry()
    used_ports = {u["port"] for u in reg["universes"]}
    port = start
    while port in used_ports:
        port += 1
    return port


# ---------------------------------------------------------------------------
# Platform-aware process helpers
# ---------------------------------------------------------------------------

def _is_pid_alive(pid) -> bool:
    """Check if a process with the given PID is still running."""
    if not pid:
        return False
    try:
        if sys.platform == "win32":
            # Windows: use ctypes to check process existence
            import ctypes
            kernel32 = ctypes.windll.kernel32
            handle = kernel32.OpenProcess(0x1000, False, pid)  # PROCESS_QUERY_LIMITED_INFORMATION
            if handle:
                kernel32.CloseHandle(handle)
                return True
            return False
        else:
            # Unix: signal 0 checks process existence without sending a signal
            os.kill(pid, 0)
            return True
    except (OSError, ProcessLookupError):
        return False


def _kill_pid(pid):
    """Kill a process by PID (cross-platform)."""
    if not pid:
        return
    try:
        if sys.platform == "win32":
            subprocess.run(["taskkill", "/F", "/PID", str(pid)],
                          capture_output=True, timeout=5)
        else:
            os.kill(pid, signal.SIGTERM)
            time.sleep(1)
            try:
                os.kill(pid, 0)
                os.kill(pid, signal.SIGKILL)
            except OSError:
                pass
    except Exception:
        pass
