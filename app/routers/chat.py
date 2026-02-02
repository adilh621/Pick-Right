"""Conversational chat endpoint for a specific business.

Uses GEMINI_API_KEY2 only. Context is built from the authenticated user's
onboarding preferences, the business (including ai_context and ai_notes),
and conversation history from the request body (messages). Stateless: no
server-side chat storage. On 429/quota, returns 503 with a friendly
model_overloaded message.
"""

import logging
import traceback
from datetime import datetime, timezone
from typing import Any, Dict, Literal
from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel
from sqlalchemy.orm import Session

from app.core.auth import get_current_user
from app.core.config import settings
from app.db.session import get_db
from app.models.business import Business
from app.models.user import User
from app.routers.ai import (
    _build_business_context_payload,
    _build_user_content_with_history,
    _business_context_json_section,
    _user_preferences_json_section,
)
from app.services.gemini_client import generate_text_with_system_chat

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/chat", tags=["chat"])

# System prompt for the business chat assistant. Ground answers in user prefs,
# business.ai_context, business.ai_notes, and Places data; do not hallucinate.
CHAT_BUSINESS_SYSTEM_PROMPT = """You are PickRight, a recommendation assistant helping the user decide whether ONE specific business is a good fit for them.

You are given:
- Structured business info (name, category, address, coordinates, rating, price, ai_notes, and optional AI context: summary, pros, cons, vibe, best_for_user_profile).
- Optional distance: when present, the business context may include distance_miles and a note that the user is approximately X miles away.
- The user's onboarding preferences (e.g. halal, budget, vibe, dietary).
- The conversation history for this user and this business.

Rules:
- Stay on-topic: the user is asking about THIS business. Do not suggest other places unless they explicitly ask.
- ALWAYS ground your answers in: the user's preferences, the business.ai_context, the business.ai_notes, and the business/Places data provided. If something is unknown or not present in the data, say so clearly (e.g. "We don't have that information") instead of inventing or guessing.
- Distance: When distance_miles or user_distance_note is present in the context, do NOT say you lack distance information. Answer using that distance. Only use phrasing like "I don't have information about your distance to this business" when the context truly has no distance info (no distance_miles, no user_distance_note).
- Time estimates: If the user asks how long it will take to get there and distance is available, you may give rough walking and driving time estimates. Assume walking speed approximately 3 mph and local driving speed approximately 20-25 mph; clearly label these as approximate. Example: "It's about 1.3 miles away, which is roughly a 25-minute walk or a 5- to 10-minute drive, depending on traffic."
- Be concrete and specific when the data is present. Do not repeat the user's preferences in every answer; use them as background when relevant.
- Tone: friendly, concise, and clear. Return markdown."""


def build_chat_system_prompt(
    business_context_payload: Dict[str, Any] | None = None,
    user_preferences: Dict[str, Any] | None = None,
) -> str:
    """
    Build the full system instruction for the business chat endpoint.
    Composes CHAT_BUSINESS_SYSTEM_PROMPT with business context and user preferences (JSON).
    """
    parts: list[str] = [CHAT_BUSINESS_SYSTEM_PROMPT]
    if business_context_payload:
        parts.append("")
        parts.append(_business_context_json_section(business_context_payload))
        if business_context_payload.get("distance_miles") is not None or business_context_payload.get("user_distance_note"):
            parts.append("")
            parts.append(
                "The BusinessContext above includes the user's distance; use it for distance and "
                "'how long will it take' questions."
            )
    if user_preferences and isinstance(user_preferences, dict):
        parts.append("")
        parts.append(_user_preferences_json_section(user_preferences))
    return "\n\n".join(parts).strip()


class ChatMessageTurn(BaseModel):
    """One prior turn in the conversation."""

    role: Literal["user", "assistant"]
    content: str


class ChatBusinessRequest(BaseModel):
    """Request for POST /chat/business/{business_id}."""

    user_message: str
    chat_session_id: UUID | None = None  # Optional; client use
    messages: list[ChatMessageTurn] | None = None  # Prior turns; order preserved
    distance_miles: float | None = None  # Optional; when present, injected into context for distance questions


class ChatBusinessMetadata(BaseModel):
    """Metadata returned with the chat response."""

    model: str
    created_at: datetime
    business_id: UUID


class ChatBusinessResponse(BaseModel):
    """Response from POST /chat/business/{business_id}."""

    assistant_message: str
    chat_session_id: UUID | None = None  # Optional; e.g. business_id for client consistency
    metadata: ChatBusinessMetadata


@router.post("/business/{business_id}", response_model=ChatBusinessResponse)
def chat_business(
    business_id: UUID,
    request: ChatBusinessRequest,
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
) -> ChatBusinessResponse:
    """
    Conversational chat for a specific business.

    Conversation history is taken from the request body (messages). Stateless:
    no server-side chat storage. Uses the authenticated user's onboarding
    preferences and the business (name, category, address, ai_context,
    ai_notes). Responses are generated with GEMINI_API_KEY2. On quota/overload
    (429), returns 503 with error "model_overloaded" and a friendly message.

    Manual verification (distance): Run the backend, then POST
    /api/v1/chat/business/{business_id} with JSON body including
    distance_miles: 1.3. In logs, confirm distance_miles=1.3 and
    user_distance_note is non-null. The system_instruction passed to Gemini
    includes the BusinessContext JSON with distance_miles and user_distance_note.
    """
    message = request.user_message.strip()
    if not message:
        raise HTTPException(status_code=400, detail="user_message must be non-empty")

    business = db.query(Business).filter(Business.id == business_id).first()
    if not business:
        raise HTTPException(status_code=404, detail="Business not found")

    business_context_payload = _build_business_context_payload(
        business,
        None,
        ai_context=getattr(business, "ai_context", None),
    )
    if request.distance_miles is not None:
        business_context_payload["distance_miles"] = request.distance_miles
        business_context_payload["user_distance_note"] = (
            f"The user is approximately {request.distance_miles:.1f} miles away from this business."
        )
    logger.info(
        "business_chat distance_miles=%s user_distance_note=%s",
        request.distance_miles,
        business_context_payload.get("user_distance_note"),
    )
    user_preferences = current_user.onboarding_preferences or {}

    history_from_request: list[tuple[str, str]] = []
    if request.messages:
        history_from_request = [(m.role, m.content) for m in request.messages]

    system_instruction = build_chat_system_prompt(
        business_context_payload=business_context_payload,
        user_preferences=user_preferences,
    )
    user_content = _build_user_content_with_history(history_from_request, message)

    logger.info(
        "Chat business: business_id=%s user_id=%s message_len=%d history_len=%d",
        business_id,
        current_user.id,
        len(message),
        len(request.messages or []),
    )

    try:
        result = generate_text_with_system_chat(user_content, system_instruction)
    except ValueError as e:
        logger.error("Chat Gemini config error: %s", e)
        raise HTTPException(status_code=500, detail={"error": str(e)})
    except Exception as e:
        logger.error(
            "Chat Gemini API error: %s\nTraceback:\n%s",
            e,
            traceback.format_exc(),
        )
        raise HTTPException(
            status_code=500,
            detail={"error": "gemini_error", "message": "Something went wrong. Please try again."},
        )

    if result is None:
        raise HTTPException(
            status_code=503,
            detail={
                "error": "model_overloaded",
                "message": "AI is temporarily busy. Please try again in a bit.",
            },
        )

    created_at = datetime.now(timezone.utc)
    return ChatBusinessResponse(
        assistant_message=result,
        chat_session_id=business_id,
        metadata=ChatBusinessMetadata(
            model=settings.gemini_model,
            created_at=created_at,
            business_id=business_id,
        ),
    )
