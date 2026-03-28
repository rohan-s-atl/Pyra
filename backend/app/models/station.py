from sqlalchemy import Column, String, Float
from app.core.database import Base


class Station(Base):
    __tablename__ = "stations"

    id         = Column(String, primary_key=True, index=True)
    name       = Column(String, nullable=False)
    cad_name   = Column(String, nullable=True)
    unit_code  = Column(String, nullable=True)   # e.g. CZU, NEU, LPF
    station_type = Column(String, nullable=True) # FSB, AAB, etc.
    latitude   = Column(Float,  nullable=False)
    longitude  = Column(Float,  nullable=False)
    address    = Column(String, nullable=True)
    city       = Column(String, nullable=True)
    phone      = Column(String, nullable=True)