import uuid
from sqlalchemy import Column, String, DateTime, func
from sqlalchemy.dialects.postgresql import UUID, JSONB
from sqlalchemy.orm import relationship

from app.db.base import Base


class User(Base):
    __tablename__ = "users"

    id = Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    # Legacy fields (kept for backward compatibility during migration)
    auth_provider_id = Column(String, unique=True, nullable=True, index=True)
    email = Column(String, unique=True, nullable=True, index=True)
    # New external auth fields
    external_auth_provider = Column(String, nullable=True)  # e.g., "firebase", "supabase", "clerk"
    external_auth_uid = Column(String, unique=True, nullable=True, index=True)
    # Onboarding fields
    onboarding_preferences = Column(JSONB, nullable=True)
    onboarding_completed_at = Column(DateTime(timezone=True), nullable=True)
    # Timestamps
    created_at = Column(DateTime(timezone=True), server_default=func.now(), nullable=False)
    updated_at = Column(DateTime(timezone=True), server_default=func.now(), onupdate=func.now(), nullable=False)

    # Relationships
    scan_sessions = relationship("ScanSession", back_populates="user", cascade="all, delete-orphan")

