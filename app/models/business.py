import uuid
from sqlalchemy import Column, String, Float, DateTime, func, Index
from sqlalchemy.dialects.postgresql import UUID
from sqlalchemy.orm import relationship

from app.db.base import Base


class Business(Base):
    __tablename__ = "businesses"

    id = Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    name = Column(String, nullable=False, index=True)
    external_id_yelp = Column(String, nullable=True, index=True)
    external_id_google = Column(String, nullable=True, index=True)
    address_full = Column(String, nullable=True)
    lat = Column(Float, nullable=True)
    lng = Column(Float, nullable=True)
    category = Column(String, nullable=True)
    created_at = Column(DateTime(timezone=True), server_default=func.now(), nullable=False)

    # Relationships
    menu_items = relationship("MenuItem", back_populates="business", cascade="all, delete-orphan")
    scan_sessions = relationship("ScanSession", back_populates="business", cascade="all, delete-orphan")

