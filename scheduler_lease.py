"""One owner for the game's background jobs across server workers.

Each uvicorn worker starts the same tick loops (income, queues, fleet arrivals,
NPC bots, ...). Running them in every worker made the bots act once per worker
and let two workers race on the same completions. A single row in
scheduler_leases names the worker that runs them; it renews the lease every
sync (a few seconds) and another worker takes over only once it has expired.

Claims are a compare-and-set UPDATE (WHERE owner/expiry still match what was
read), so two workers grabbing an expired lease at once can't both win.
Known limit: a worker frozen past the lease (LEASE_SECONDS) may finish one tick
after another has taken over; ticks are time-based, so that costs at most one
overlapping pass, not a loop of them.
"""
import os
import uuid
from datetime import datetime, timedelta

from sqlalchemy import update
from sqlalchemy.exc import IntegrityError

LEASE_NAME = "game_ticks"
LEASE_SECONDS = 30
WORKER_ID = f"{os.getpid()}-{uuid.uuid4().hex[:8]}"

_leader = False


def try_acquire(db, worker_id: str = WORKER_ID, now: datetime = None) -> bool:
    """Take or renew the lease for `worker_id`. True if it holds the lease now."""
    from models import SchedulerLease
    now = now or datetime.utcnow()
    expires = now + timedelta(seconds=LEASE_SECONDS)
    row = db.query(SchedulerLease).filter(SchedulerLease.name == LEASE_NAME).first()
    if row is None:
        db.add(SchedulerLease(name=LEASE_NAME, owner=worker_id, expires_at=expires))
        try:
            db.commit()
            return True
        except IntegrityError:          # another worker inserted it first
            db.rollback()
            return False
    if row.owner != worker_id and row.expires_at > now:
        db.rollback()
        return False
    seen_owner, seen_expiry = row.owner, row.expires_at
    result = db.execute(
        update(SchedulerLease)
        .where(SchedulerLease.name == LEASE_NAME,
               SchedulerLease.owner == seen_owner,
               SchedulerLease.expires_at == seen_expiry)
        .values(owner=worker_id, expires_at=expires)
        .execution_options(synchronize_session=False))
    db.commit()
    return result.rowcount == 1


def renew(db, now: datetime = None) -> bool:
    """Called from the per-worker sync loop. Updates is_leader()."""
    global _leader
    try:
        _leader = try_acquire(db, WORKER_ID, now)
    except Exception:
        db.rollback()
        _leader = False
    return _leader


def is_leader() -> bool:
    return _leader
