"""Chat messages between a user and the AI about a specific business."""

import uuid
from sqlalchemy import Column, String, Text, DateTime, ForeignKey, func
from sqlalchemy.dialects.postgresql import UUID
from sqlalchemy.orm import relationship

from app.db.base import Base


class BusinessChatMessage(Base):
    """
    One message in the conversation between a user and the AI about a single business.

    Used so the chat endpoint always has access to conversation history
    and the user never has to re-explain which business they're talking about.
    """

    __tablename__ = "business_chat_messages"

    id = Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    user_id = Column(UUID(as_uuid=True), ForeignKey("users.id"), nullable=False, index=True)
    business_id = Column(UUID(as_uuid=True), ForeignKey("businesses.id"), nullable=False, index=True)
    role = Column(String(16), nullable=False)  # "user" | "assistant"
    content = Column(Text, nullable=False)
    created_at = Column(DateTime(timezone=True), server_default=func.now(), nullable=False)

    # Relationships
    user = relationship("User", back_populates="business_chat_messages")
    business = relationship("Business", back_populates="business_chat_messages")
