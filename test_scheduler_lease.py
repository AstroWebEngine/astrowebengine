"""Only one server worker may run the game's background jobs (income, queues,
fleet arrivals, NPC bots...). Each uvicorn worker used to start its own copy, so
with two workers the bots acted twice as often and completions could race.

scheduler_lease hands the jobs to one owner through a row in the database; the
owner renews it, and another worker takes over only after it expires.
"""
from datetime import datetime, timedelta

import pytest

import scheduler_lease as sl
from database import SessionLocal
from models import SchedulerLease


@pytest.fixture
def db():
    s = SessionLocal()
    s.query(SchedulerLease).filter(SchedulerLease.name == sl.LEASE_NAME).delete(); s.commit()
    yield s
    s.query(SchedulerLease).filter(SchedulerLease.name == sl.LEASE_NAME).delete(); s.commit()
    s.close()


T0 = datetime(2026, 10, 14, 12, 0, 0)


def test_first_worker_takes_the_lease(db):
    assert sl.try_acquire(db, "worker-a", now=T0) is True


def test_second_worker_is_refused_while_lease_is_fresh(db):
    sl.try_acquire(db, "worker-a", now=T0)
    assert sl.try_acquire(db, "worker-b", now=T0 + timedelta(seconds=5)) is False


def test_owner_renews_its_own_lease(db):
    sl.try_acquire(db, "worker-a", now=T0)
    later = T0 + timedelta(seconds=sl.LEASE_SECONDS - 1)
    assert sl.try_acquire(db, "worker-a", now=later) is True
    # renewed: still fresh for b just after the original expiry
    assert sl.try_acquire(db, "worker-b", now=T0 + timedelta(seconds=sl.LEASE_SECONDS + 1)) is False


def test_another_worker_takes_over_after_expiry(db):
    sl.try_acquire(db, "worker-a", now=T0)
    after = T0 + timedelta(seconds=sl.LEASE_SECONDS + 1)
    assert sl.try_acquire(db, "worker-b", now=after) is True
    assert sl.try_acquire(db, "worker-a", now=after + timedelta(seconds=1)) is False


def test_only_one_of_two_simultaneous_claims_wins(db):
    """Both see the same expired lease; the compare-and-set lets only one through."""
    sl.try_acquire(db, "worker-a", now=T0)
    after = T0 + timedelta(seconds=sl.LEASE_SECONDS + 1)
    db2 = SessionLocal()
    try:
        results = [sl.try_acquire(db, "worker-b", now=after), sl.try_acquire(db2, "worker-c", now=after)]
    finally:
        db2.close()
    assert results.count(True) == 1


def test_is_leader_reflects_last_renewal(db):
    sl.renew(db, now=T0)
    assert sl.is_leader() is True
    other = SessionLocal()
    try:
        row = other.query(SchedulerLease).filter(SchedulerLease.name == sl.LEASE_NAME).one()
        row.owner = "someone-else"; row.expires_at = datetime.utcnow() + timedelta(hours=1)
        other.commit()
    finally:
        other.close()
    sl.renew(db)
    assert sl.is_leader() is False
