from sqlalchemy import Column, String, DateTime
from app.core.database import Base
from datetime import datetime, UTC


class User(Base):
    __tablename__ = "users"

    id         = Column(String, primary_key=True, index=True)
    username   = Column(String, unique=True, nullable=False, index=True)
    hashed_password = Column(String, nullable=False)
    role       = Column(String, nullable=False)  # 'commander' | 'dispatcher' | 'viewer'
    created_at = Column(DateTime, default=lambda: datetime.now(UTC))