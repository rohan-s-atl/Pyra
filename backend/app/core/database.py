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
    # pool_size=10:        10 persistent connections (was 5 — too small for sim + API)
    # max_overflow=20:     20 additional burst connections allowed
    # pool_timeout=30:     wait up to 30s for a connection before raising
    # pool_recycle=1800:   recycle connections every 30min to avoid stale TCP
    # pool_pre_ping=True:  test connection health before use — prevents "lost connection" errors
    engine = create_engine(
        settings.database_url,
        connect_args=connect_args,
        pool_size=10,
        max_overflow=20,
        pool_timeout=30,
        pool_recycle=1800,
        pool_pre_ping=True,
    )

SessionLocal = sessionmaker(
    autocommit=False,
    autoflush=False,
    bind=engine,
)


class Base(DeclarativeBase):
    pass


def get_db():
    db = SessionLocal()
    try:
        yield db
    finally:
        db.close()