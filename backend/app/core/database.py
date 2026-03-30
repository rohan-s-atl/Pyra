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
    # pool_size=5:         5 persistent connections (sim now uses 1 at a time per phase)
    # max_overflow=10:     10 additional burst connections for concurrent API requests
    # pool_timeout=10:     fail fast — 30s was masking the real problem
    # pool_recycle=1800:   recycle connections every 30min to avoid stale TCP
    # pool_pre_ping=True:  test connection health before use — prevents "lost connection" errors
    engine = create_engine(
        settings.database_url,
        connect_args=connect_args,
        pool_size=5,
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