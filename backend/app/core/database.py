from sqlalchemy import create_engine, event
from sqlalchemy.orm import sessionmaker, DeclarativeBase

from app.core.config import settings

is_sqlite = "sqlite" in settings.database_url
connect_args = {"check_same_thread": False} if is_sqlite else {}

if is_sqlite:
    engine = create_engine(
        settings.database_url,
        connect_args=connect_args,
    )
else:
    # PostgreSQL on Railway — sized for single-worker uvicorn + 2s simulation tick.
    # pool_size=10:        10 persistent connections — covers ~10 concurrent API clients
    # max_overflow=15:     15 burst connections for request spikes
    # pool_timeout=10:     fail fast — don't queue forever, surface pressure early
    # pool_recycle=1800:   recycle connections every 30min to avoid stale TCP
    # pool_pre_ping=True:  test connection health before use — prevents "lost connection" errors
    # Note: sim tick uses 1 connection at a time (per-phase sessions), so the pool
    # is sized for the API layer. With frontend polling deduplicated, peak concurrent
    # connections should stay well under pool_size.
    engine = create_engine(
        settings.database_url,
        connect_args=connect_args,
        # Railway Postgres hard limit: 25 connections total.
        # pool_size=7 + max_overflow=10 = 17 max pooled connections.
        # The remaining ~8 headroom covers health checks and Railway
        # internal monitoring. Previously size=10+overflow=15=25 exactly
        # hit the ceiling, leaving nothing for health checks — DB refused
        # new connections and SQLAlchemy reported it as pool timeout.
        pool_size=7,
        max_overflow=10,
        pool_timeout=10,
        pool_recycle=1800,
        pool_pre_ping=True,
    )

SessionLocal = sessionmaker(
    autocommit=False,
    autoflush=False,
    bind=engine,
)

# Short-lived sessions for the simulation tick.
# expire_on_commit=False avoids lazy-load queries after commit,
# which is important for phases that read committed data immediately after.
SimSessionLocal = sessionmaker(
    autocommit=False,
    autoflush=False,
    bind=engine,
    expire_on_commit=False,
)


class Base(DeclarativeBase):
    pass


def get_db():
    db = SessionLocal()
    try:
        yield db
    finally:
        db.close()