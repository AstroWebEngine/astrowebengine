"""Admin API tokens: hash-only storage, verify, revoke, admin-only."""
import uuid
import pytest

from database import SessionLocal
from models import User, ApiToken
import api_tokens


@pytest.fixture
def db():
    s = SessionLocal()
    yield s
    s.close()


@pytest.fixture
def admin(db):
    u = User(username=f"tok_admin_{uuid.uuid4().hex[:8]}", hashed_password="x", is_admin=True)
    db.add(u); db.commit()
    yield u
    db.query(ApiToken).filter(ApiToken.user_id == u.id).delete()
    db.delete(u); db.commit()


@pytest.fixture
def player(db):
    u = User(username=f"tok_player_{uuid.uuid4().hex[:8]}", hashed_password="x", is_admin=False)
    db.add(u); db.commit()
    yield u
    db.delete(u); db.commit()


def test_create_returns_secret_once_and_stores_only_hash(db, admin):
    row, raw = api_tokens.create_token(db, admin, "laptop")
    assert raw.startswith("awe_") and len(raw) > 30
    assert row.token_hash != raw and raw not in row.token_hash
    assert row.prefix == raw[:8]


def test_verify_accepts_valid_and_updates_last_used(db, admin):
    row, raw = api_tokens.create_token(db, admin, "laptop")
    assert row.last_used_at is None
    got = api_tokens.verify_token(db, raw)
    assert got is not None
    user, tok = got
    assert user.id == admin.id and tok.id == row.id
    db.refresh(row)
    assert row.last_used_at is not None


@pytest.mark.parametrize("bad", [None, "", "awe_nope", "Bearer x"])
def test_verify_rejects_garbage(db, bad):
    assert api_tokens.verify_token(db, bad) is None


def test_revoked_token_rejected(db, admin):
    row, raw = api_tokens.create_token(db, admin, "laptop")
    assert api_tokens.revoke_token(db, admin, row.id) is True
    assert api_tokens.verify_token(db, raw) is None


def test_token_rejected_after_owner_loses_admin(db, admin):
    _row, raw = api_tokens.create_token(db, admin, "laptop")
    admin.is_admin = False; db.commit()
    assert api_tokens.verify_token(db, raw) is None


def test_non_admin_cannot_create(db, player):
    with pytest.raises(ValueError):
        api_tokens.create_token(db, player, "nope")


def test_list_hides_secret(db, admin):
    api_tokens.create_token(db, admin, "a")
    listed = api_tokens.list_tokens(db, admin)
    assert listed and set(listed[0]) == {"id", "name", "prefix", "created_at", "last_used_at", "revoked"}


def test_cannot_revoke_someone_elses_token(db, admin, player):
    row, _ = api_tokens.create_token(db, admin, "a")
    assert api_tokens.revoke_token(db, player, row.id) is False


def test_verify_does_not_rewrite_last_used_within_interval(db, admin, monkeypatch):
    from datetime import datetime, timedelta
    row, raw = api_tokens.create_token(db, admin, "laptop")
    recent = datetime.utcnow() - timedelta(minutes=2)
    row.last_used_at = recent; db.commit()
    commits = []
    monkeypatch.setattr(db, "commit", lambda: commits.append(1))
    assert api_tokens.verify_token(db, raw) is not None
    assert row.last_used_at == recent and not commits


def test_verify_refreshes_stale_last_used(db, admin):
    from datetime import datetime, timedelta
    row, raw = api_tokens.create_token(db, admin, "laptop")
    stale = datetime.utcnow() - api_tokens.LAST_USED_WRITE_INTERVAL - timedelta(seconds=1)
    row.last_used_at = stale; db.commit()
    assert api_tokens.verify_token(db, raw) is not None
    db.refresh(row)
    assert row.last_used_at > stale
