"""Conversational chat endpoint for a specific business.

Uses GEMINI_API_KEY2 only. Context is built from the authenticated user's
onboarding preferences, the business (including ai_context and ai_notes),
and conversation history from the request body (messages). Stateless: no
server-side chat storage. On 429/quota, returns 503 with a friendly
model_overloaded message.
"""

import json
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
from app.routers.ai import _build_user_content_with_history
from app.services.gemini_client import generate_business_chat_with_search

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/chat", tags=["chat"])

# System prompt for the business chat endpoint. Context (business + user_profile) is passed in user content as JSON.
CHAT_BUSINESS_SYSTEM_PROMPT = """You are PickRight, an AI guide helping a single specific user decide whether one specific business is a good fit for them.

You receive a JSON object with:
- business: objective info and AI summary of the place (name, address, category, summary, pros, cons, vibe, ai_notes, and optional distance_miles / user_distance_note).
- user_profile: this user's onboarding preferences from onboarding.

Your job:
- Always reason from both business info AND user_profile.
- For vague questions like "Is this good?" or "What's the vibe?", interpret them as: "Is this a good fit for ME personally given my preferences?"
- Explicitly mention how the place matches or conflicts with key preferences when relevant (e.g. "You said ambiance and halal options matter. This place has a cozy vibe, but there's no clear indication it's halal-friendly…").
- If there are clear conflicts (dietary restriction vs business type, budget vs price_level, need for quiet vs lively sports-bar vibe), gently flag that and suggest what to double-check.
- Use only concrete details from the business context; do not guess or invent.
- Stay on-topic: the user is asking about THIS business. Do not suggest other places unless they explicitly ask.
- When distance_miles or user_distance_note is present in the context, use it for distance and "how long will it take" questions. You may give rough walking (~3 mph) and driving (~20–25 mph) time estimates; label them as approximate.
- Answer in concise markdown, friendly but not overly verbose.

Google Search (web search):
- You MAY use Google Search when the business context and user_profile do NOT contain the needed information (e.g. "when was this location established?", "is there a mosque nearby?", "what time is the Friday khutbah?").
- Priorities: (1) Use the provided business JSON and user_profile JSON as the primary source. (2) If the context is silent on the question, you MAY use web search, using the business name, address, category, and city/state as search hints. (3) Never contradict the business context; if web search conflicts with our data, business data wins. (4) If neither context nor search can answer, say so clearly and recommend the user contact the business directly.
- Attribution: When a statement is based on web search, say so explicitly (e.g. "Based on web search results, it appears that…"). When from our data, you may say "From your business profile…" or similar. Never present web search results as if they came from our business context.
- If both business context and web search fail to provide a reliable answer, respond with a short explanation that you don't have the information and suggest contacting the business directly. Never invent dates, prices, or allergy information. If the user asks something clearly unrelated to the business or their preferences, politely refuse."""


def build_business_chat_context(
    business: Business,
    distance_miles: float | None,
    user_preferences: dict,
) -> dict:
    """
    Build a single structured context dict for the business chat model.
    Contains business (identity, address, ai_context fields, ai_notes, distance) and user_profile.
    """
    addr_full = getattr(business, "address", None) or business.address_full
    addr_state = getattr(business, "state", None)
    address = None
    if addr_full or addr_state:
        address = {k: v for k, v in ({"full": addr_full, "state": addr_state}.items()) if v is not None}
    elif business.address_full:
        address = {"full": business.address_full}

    lat_val = business.latitude if getattr(business, "latitude", None) is not None else business.lat
    lng_val = business.longitude if getattr(business, "longitude", None) is not None else business.lng
    coordinates = {"lat": lat_val, "lng": lng_val} if (lat_val is not None and lng_val is not None) else None

    ai_context = getattr(business, "ai_context", None) or {}
    if not isinstance(ai_context, dict):
        ai_context = {}

    business_dict: Dict[str, Any] = {
        "id": str(business.id),
        "name": business.name,
        "address": address,
        "category": business.category,
        "coordinates": coordinates,
        "ai_summary": ai_context.get("summary") if ai_context else None,
        "ai_pros": (ai_context.get("pros") if ai_context else []) or [],
        "ai_cons": (ai_context.get("cons") if ai_context else []) or [],
        "ai_vibe": ai_context.get("vibe") if ai_context else None,
        "ai_notes": getattr(business, "ai_notes", None),
    }
    if distance_miles is not None:
        business_dict["distance_miles"] = distance_miles
        business_dict["user_distance_note"] = (
            f"The user is approximately {distance_miles:.1f} miles away from this business."
        )
    # Drop None values so JSON is minimal
    business_dict = {k: v for k, v in business_dict.items() if v is not None}

    return {
        "business": business_dict,
        "user_profile": user_preferences if isinstance(user_preferences, dict) else {},
    }


def build_chat_system_prompt() -> str:
    """Return the system instruction for the business chat endpoint (no context embedded; context goes in user content)."""
    return CHAT_BUSINESS_SYSTEM_PROMPT.strip()


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

    Context (business + user_profile) is passed in the user content as JSON;
    distance_miles when provided is included in context.business.
    """
    message = request.user_message.strip()
    if not message:
        raise HTTPException(status_code=400, detail="user_message must be non-empty")

    business = db.query(Business).filter(Business.id == business_id).first()
    if not business:
        raise HTTPException(status_code=404, detail="Business not found")

    user_preferences = current_user.onboarding_preferences or {}
    context = build_business_chat_context(
        business,
        request.distance_miles,
        user_preferences,
    )
    logger.info(
        "business_chat distance_miles=%s",
        request.distance_miles,
    )

    history_from_request: list[tuple[str, str]] = []
    if request.messages:
        history_from_request = [(m.role, m.content) for m in request.messages]

    system_instruction = build_chat_system_prompt()
    context_blob = "Context (JSON):\n" + json.dumps(context, indent=2)
    user_content = context_blob + "\n\n" + _build_user_content_with_history(history_from_request, message)

    logger.info(
        "Chat business: business_id=%s user_id=%s message_len=%d history_len=%d",
        business_id,
        current_user.id,
        len(message),
        len(request.messages or []),
    )

    try:
        result = generate_business_chat_with_search(
            system_prompt=system_instruction,
            messages=[{"role": "user", "content": user_content}],
        )
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
