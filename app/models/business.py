import uuid
from sqlalchemy import Column, String, Text, Float, DateTime, func, Index
from sqlalchemy.dialects.postgresql import UUID, JSONB
from sqlalchemy.orm import relationship

from app.db.base import Base


class Business(Base):
    __tablename__ = "businesses"

    id = Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    name = Column(String, nullable=False, index=True)
    provider = Column(String, nullable=False, default="google")
    provider_place_id = Column(String, nullable=False, index=True)
    external_id_google = Column(String, nullable=True, index=True)
    address_full = Column(String, nullable=True)
    address = Column(Text, nullable=True)  # full/primary address from Google Places (iOS/Supabase)
    state = Column(Text, nullable=True)
    lat = Column(Float, nullable=True)
    lng = Column(Float, nullable=True)
    latitude = Column(Float, nullable=True)  # DOUBLE PRECISION, from Google Places (iOS/Supabase)
    longitude = Column(Float, nullable=True)  # DOUBLE PRECISION, from Google Places (iOS/Supabase)
    category = Column(String, nullable=True)
    photo_reference = Column(String, nullable=True)  # Google Places first photo reference for card image
    photo_url = Column(String, nullable=True)  # Precomputed photo URL (from _build_photo_url) for home-feed/details
    ai_notes = Column(Text, nullable=True)  # AI-generated summary for chat context (top items, halal, etc.)
    ai_context = Column(JSONB, nullable=True)  # Structured LLM snapshot for business detail / AI context
    ai_tags = Column(JSONB, nullable=True)  # AI-generated tags for home feed sections (e.g. ["date-night", "coffee"])
    ai_context_last_updated = Column(DateTime(timezone=True), nullable=True)  # TTL for when to regenerate
    created_at = Column(DateTime(timezone=True), server_default=func.now(), nullable=False)

    # Relationships
    menu_items = relationship("MenuItem", back_populates="business", cascade="all, delete-orphan")
    scan_sessions = relationship("ScanSession", back_populates="business", cascade="all, delete-orphan")
    business_chat_messages = relationship(
        "BusinessChatMessage", back_populates="business", cascade="all, delete-orphan"
    )

