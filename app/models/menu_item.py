import uuid
from sqlalchemy import Column, String, Integer, Float, Text, DateTime, ForeignKey, func
from sqlalchemy.dialects.postgresql import UUID
from sqlalchemy.orm import relationship

from app.db.base import Base


class MenuItem(Base):
    __tablename__ = "menu_items"

    id = Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    business_id = Column(UUID(as_uuid=True), ForeignKey("businesses.id"), nullable=False, index=True)
    name = Column(String, nullable=False)
    item_type = Column(String, nullable=False)  # FOOD, DRINK, SERVICE, PERSON, OTHER
    total_mentions = Column(Integer, default=0, nullable=False)
    positive_mentions = Column(Integer, default=0, nullable=False)
    negative_mentions = Column(Integer, default=0, nullable=False)
    avg_rating = Column(Float, nullable=True)
    top_positive_snippet = Column(Text, nullable=True)
    top_negative_snippet = Column(Text, nullable=True)
    created_at = Column(DateTime(timezone=True), server_default=func.now(), nullable=False)
    updated_at = Column(DateTime(timezone=True), server_default=func.now(), onupdate=func.now(), nullable=False)

    # Relationships
    business = relationship("Business", back_populates="menu_items")
    recommendation_items = relationship("RecommendationItem", back_populates="menu_item", cascade="all, delete-orphan")

