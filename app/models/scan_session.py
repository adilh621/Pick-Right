import uuid
from sqlalchemy import Column, String, Text, DateTime, ForeignKey, func, CheckConstraint
from sqlalchemy.dialects.postgresql import UUID
from sqlalchemy.orm import relationship

from app.db.base import Base


class ScanSession(Base):
    __tablename__ = "scan_sessions"

    id = Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    user_id = Column(UUID(as_uuid=True), ForeignKey("users.id"), nullable=True, index=True)
    device_id = Column(String, nullable=True, index=True)  # For guest sessions
    business_id = Column(UUID(as_uuid=True), ForeignKey("businesses.id"), nullable=True, index=True)
    image_url = Column(String, nullable=False)
    detected_text_raw = Column(Text, nullable=False)
    status = Column(String, nullable=False)  # PENDING, PROCESSING, COMPLETED, FAILED
    created_at = Column(DateTime(timezone=True), server_default=func.now(), nullable=False)
    completed_at = Column(DateTime(timezone=True), nullable=True)

    # Relationships
    user = relationship("User", back_populates="scan_sessions")
    business = relationship("Business", back_populates="scan_sessions")
    recommendation_items = relationship("RecommendationItem", back_populates="scan_session", cascade="all, delete-orphan")

    # Note: At least one of (user_id, device_id) must be set - enforced at application level
    # DB-level constraint would be: CheckConstraint("user_id IS NOT NULL OR device_id IS NOT NULL")

