"""
Combat lock helpers for high-concurrency battle resolution.

PostgreSQL uses transaction-scoped advisory locks so multiple workers cannot
resolve combat on the same location simultaneously. SQLite falls back to an
in-process threading lock.
"""

from __future__ import annotations

import hashlib
import os
import threading
import time

from sqlalchemy import text

from database import IS_POSTGRES


COMBAT_LOCK_TIMEOUT_SECONDS = float(os.environ.get("AWE_COMBAT_LOCK_TIMEOUT_SECONDS", "15"))
_LOCAL_LOCKS: dict[str, threading.RLock] = {}
_LOCAL_LOCKS_GUARD = threading.Lock()


class CombatLockBusy(Exception):
    """Raised when another combat is already being resolved for the same location."""


def combat_location_lock_key(planet_id: int) -> str:
    return f"combat:planet:{planet_id}"


def _lock_key_to_bigint(lock_key: str) -> int:
    digest = hashlib.blake2b(lock_key.encode("utf-8"), digest_size=8).digest()
    value = int.from_bytes(digest, "big", signed=False)
    if value >= (1 << 63):
        value -= (1 << 64)
    return value


def _get_local_lock(lock_key: str) -> threading.RLock:
    with _LOCAL_LOCKS_GUARD:
        lock = _LOCAL_LOCKS.get(lock_key)
        if lock is None:
            lock = threading.RLock()
            _LOCAL_LOCKS[lock_key] = lock
        return lock


def acquire_combat_lock(db, lock_key: str, timeout_seconds: float | None = None):
    timeout = COMBAT_LOCK_TIMEOUT_SECONDS if timeout_seconds is None else timeout_seconds
    if IS_POSTGRES:
        advisory_key = _lock_key_to_bigint(lock_key)
        deadline = time.monotonic() + timeout
        while True:
            acquired = db.execute(
                text("SELECT pg_try_advisory_xact_lock(:lock_key)"),
                {"lock_key": advisory_key},
            ).scalar()
            if acquired:
                return None
            if time.monotonic() >= deadline:
                raise CombatLockBusy(lock_key)
            time.sleep(0.1)

    lock = _get_local_lock(lock_key)
    if not lock.acquire(timeout=timeout):
        raise CombatLockBusy(lock_key)
    db.info.setdefault("_combat_lock_handles", []).append(lock)
    return None


def release_session_locks(db) -> None:
    handles = db.info.pop("_combat_lock_handles", [])
    while handles:
        handles.pop().release()
