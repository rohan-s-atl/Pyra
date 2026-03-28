from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker, DeclarativeBase

from app.core.config import settings

# SQLite needs this arg — Postgres doesn't, but it's harmless to keep
connect_args = {"check_same_thread": False} if "sqlite" in settings.database_url else {}

engine = create_engine(
    settings.database_url,
    connect_args=connect_args,
)

SessionLocal = sessionmaker(
    autocommit=False,
    autoflush=False,
    bind=engine,
)


class Base(DeclarativeBase):
    pass


# FastAPI dependency — use this in every route that needs DB access
def get_db():
    db = SessionLocal()
    try:
        yield db
    finally:
        db.close()

# NOTE: Schema is managed by Alembic migrations, NOT create_all().
# To apply migrations: alembic upgrade head
# To create a new migration: alembic revision --autogenerate -m "description"
# To downgrade one step: alembic downgrade -1