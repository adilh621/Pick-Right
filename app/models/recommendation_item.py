import uuid
from sqlalchemy import Column, String, Integer, Boolean, Float, Text, DateTime, ForeignKey, func
from sqlalchemy.dialects.postgresql import UUID
from sqlalchemy.orm import relationship

from app.db.base import Base


class RecommendationItem(Base):
    __tablename__ = "recommendation_items"

    id = Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    scan_session_id = Column(UUID(as_uuid=True), ForeignKey("scan_sessions.id"), nullable=False, index=True)
    menu_item_id = Column(UUID(as_uuid=True), ForeignKey("menu_items.id"), nullable=False, index=True)
    rank = Column(Integer, nullable=False)
    is_recommended = Column(Boolean, nullable=False)
    recommendation_label = Column(String, nullable=False)  # HIGHLY_RECOMMENDED, RECOMMENDED, NOT_RECOMMENDED
    display_mention_count = Column(Integer, nullable=False)
    display_avg_rating = Column(Float, nullable=True)
    display_positive_snippet = Column(Text, nullable=True)
    display_negative_snippet = Column(Text, nullable=True)
    created_at = Column(DateTime(timezone=True), server_default=func.now(), nullable=False)

    # Relationships
    scan_session = relationship("ScanSession", back_populates="recommendation_items")
    menu_item = relationship("MenuItem", back_populates="recommendation_items")

