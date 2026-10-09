"""Admin API tokens for the MCP endpoint.

A token acts as its owning admin. Only a SHA-256 of the secret is stored, so a
leaked database does not leak usable tokens; the raw secret is shown once.
"""
import hashlib
import secrets
from datetime import datetime, timedelta

from models import ApiToken, User

TOKEN_PREFIX = "awe_"
LAST_USED_WRITE_INTERVAL = timedelta(minutes=5)


def _hash(raw: str) -> str:
    return hashlib.sha256(raw.encode("utf-8")).hexdigest()


def create_token(db, user, name: str):
    if not user or not user.is_admin:
        raise ValueError("Only admins can create API tokens")
    name = (name or "").strip()
    if not name or len(name) > 60:
        raise ValueError("Token name must be 1-60 characters")
    raw = TOKEN_PREFIX + secrets.token_urlsafe(32)
    row = ApiToken(user_id=user.id, name=name, token_hash=_hash(raw), prefix=raw[:8])
    db.add(row)
    db.commit()
    return row, raw


def verify_token(db, raw):
    if not raw or not raw.startswith(TOKEN_PREFIX):
        return None
    row = db.query(ApiToken).filter(ApiToken.token_hash == _hash(raw)).first()
    if not row or row.revoked_at is not None:
        return None
    user = db.query(User).filter(User.id == row.user_id).first()
    if not user or not user.is_admin:
        return None
    now = datetime.utcnow()
    if row.last_used_at is None or now - row.last_used_at >= LAST_USED_WRITE_INTERVAL:
        row.last_used_at = now  # throttled: no DB write on every request
        db.commit()
    return user, row


def list_tokens(db, user) -> list:
    rows = (db.query(ApiToken).filter(ApiToken.user_id == user.id)
            .order_by(ApiToken.created_at.desc()).all())
    return [{
        "id": r.id, "name": r.name, "prefix": r.prefix,
        "created_at": r.created_at.isoformat() if r.created_at else None,
        "last_used_at": r.last_used_at.isoformat() if r.last_used_at else None,
        "revoked": r.revoked_at is not None,
    } for r in rows]


def revoke_token(db, user, token_id: int) -> bool:
    row = db.query(ApiToken).filter(ApiToken.id == token_id, ApiToken.user_id == user.id).first()
    if not row:
        return False
    if row.revoked_at is None:
        row.revoked_at = datetime.utcnow()
        db.commit()
    return True
