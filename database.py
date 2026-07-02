"""
Database configuration and setup for AstroWebEngine
"""

import os
import secrets
from sqlalchemy.engine import make_url
from sqlalchemy import create_engine, Column, Integer, String, Float, Boolean, DateTime, JSON, ForeignKey, Text, func, event
from sqlalchemy import text as import_text
from sqlalchemy.ext.declarative import declarative_base
from sqlalchemy.orm import sessionmaker, Session, relationship

# ======================== DATABASE SETUP ========================
DATABASE_URL = os.environ.get("DATABASE_URL", "sqlite:///./astroclone.db")
_url = make_url(DATABASE_URL)
DB_DIALECT = _url.get_backend_name()
IS_SQLITE = DB_DIALECT == "sqlite"
IS_POSTGRES = DB_DIALECT == "postgresql"
# Backward-compatible alias used by older modules.
_is_sqlite = IS_SQLITE

DB_POOL_SIZE = int(os.environ.get("AWE_DB_POOL_SIZE", "30"))
DB_MAX_OVERFLOW = int(os.environ.get("AWE_DB_MAX_OVERFLOW", "30"))
DB_POOL_TIMEOUT = int(os.environ.get("AWE_DB_POOL_TIMEOUT", "30"))
DB_POOL_RECYCLE = int(os.environ.get("AWE_DB_POOL_RECYCLE", "1800"))

if IS_SQLITE:
    engine = create_engine(
        DATABASE_URL,
        connect_args={"check_same_thread": False},
        pool_size=DB_POOL_SIZE,
        max_overflow=DB_MAX_OVERFLOW,
        pool_timeout=DB_POOL_TIMEOUT,
        pool_pre_ping=True,
    )

    # Set PRAGMAs on EVERY new SQLite connection (not just one)
    @event.listens_for(engine, "connect")
    def _set_sqlite_pragmas(dbapi_conn, connection_record):
        cursor = dbapi_conn.cursor()
        cursor.execute("PRAGMA journal_mode=WAL")
        cursor.execute("PRAGMA synchronous=NORMAL")
        cursor.execute("PRAGMA busy_timeout=120000")  # 120 second wait for locks
        cursor.execute("PRAGMA wal_autocheckpoint=1000")  # checkpoint every 1000 pages
        cursor.execute("PRAGMA cache_size=-64000")  # 64MB page cache
        cursor.close()
else:
    connect_args = {}
    if IS_POSTGRES:
        statement_timeout_ms = int(os.environ.get("AWE_DB_STATEMENT_TIMEOUT_MS", "45000"))
        lock_timeout_ms = int(os.environ.get("AWE_DB_LOCK_TIMEOUT_MS", "15000"))
        idle_tx_timeout_ms = int(os.environ.get("AWE_DB_IDLE_TX_TIMEOUT_MS", "60000"))
        connect_args["options"] = (
            f"-c statement_timeout={statement_timeout_ms} "
            f"-c lock_timeout={lock_timeout_ms} "
            f"-c idle_in_transaction_session_timeout={idle_tx_timeout_ms}"
        )
        connect_args["application_name"] = os.environ.get("AWE_DB_APP_NAME", "AstroWebEngine")

    engine = create_engine(
        DATABASE_URL,
        pool_size=DB_POOL_SIZE,
        max_overflow=DB_MAX_OVERFLOW,
        pool_timeout=DB_POOL_TIMEOUT,
        pool_recycle=DB_POOL_RECYCLE,
        pool_pre_ping=True,
        pool_use_lifo=True,
        connect_args=connect_args,
    )

SessionLocal = sessionmaker(autocommit=False, autoflush=False, expire_on_commit=False, bind=engine)
ModelBase = declarative_base()

SECRET_KEY = os.environ.get("AWE_SECRET_KEY", secrets.token_hex(32))
ALGORITHM = "HS256"
ACCESS_TOKEN_EXPIRE_HOURS = 72
