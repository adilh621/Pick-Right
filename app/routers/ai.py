"""AI endpoints using Gemini."""

import logging
import re
import traceback
from typing import Dict, Any

from fastapi import APIRouter, HTTPException, Depends
from pydantic import BaseModel
from sqlalchemy.orm import Session

from app.services.gemini_client import generate_text, generate_text_with_system, STRICT_SYSTEM_INSTRUCTION
from app.services.places_client import find_place_with_hours
from app.core.auth import get_current_user_optional
from app.db.session import get_db
from app.models.user import User

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/ai", tags=["ai"])

# Keywords that indicate the user is asking about hours
HOURS_KEYWORDS = re.compile(
    r'\b(hours|open|close|closing|opening|when\s+do|what\s+time)\b',
    re.IGNORECASE
)

# Keywords that indicate the user is asking about their preferences/onboarding
PREFERENCES_KEYWORDS = re.compile(
    r'\b(my\s+(onboarding|preferences?|answers?|settings?|dietary|restrictions?)|what\s+(are|did)\s+(my|i))\b',
    re.IGNORECASE
)


class HelloRequest(BaseModel):
    message: str


class HelloResponse(BaseModel):
    reply: str


class ChatRequest(BaseModel):
    message: str
    location_hint: str | None = None


class ChatResponse(BaseModel):
    reply: str


def _is_hours_query(message: str) -> bool:
    """Check if the message is asking about business hours."""
    return bool(HOURS_KEYWORDS.search(message))


def _is_preferences_query(message: str) -> bool:
    """Check if the message is asking about user's onboarding answers/preferences."""
    return bool(PREFERENCES_KEYWORDS.search(message))


def _format_hours_response(place_data: dict) -> str:
    """Format place data into a markdown response with hours."""
    name = place_data.get("name", "This location")
    address = place_data.get("formatted_address", "")
    hours = place_data.get("opening_hours")
    
    lines = [f"**{name}**"]
    if address:
        lines.append(f"📍 {address}")
    lines.append("")
    
    if hours:
        lines.append("**Hours:**")
        for day_hours in hours:
            lines.append(f"- {day_hours}")
    else:
        lines.append("_Hours not available for this location._")
    
    return "\n".join(lines)


def _format_preferences_response(preferences: Dict[str, Any] | None) -> str:
    """Format user preferences into a markdown response."""
    if not preferences:
        return "You haven't completed onboarding yet, so I don't have any saved preferences for you."
    
    lines = ["**Your Preferences:**", ""]
    
    for key, value in preferences.items():
        # Format key nicely (e.g., "dietary_restrictions" -> "Dietary Restrictions")
        formatted_key = key.replace("_", " ").title()
        
        if isinstance(value, list):
            if value:
                lines.append(f"- **{formatted_key}:** {', '.join(str(v) for v in value)}")
            else:
                lines.append(f"- **{formatted_key}:** None selected")
        elif isinstance(value, bool):
            lines.append(f"- **{formatted_key}:** {'Yes' if value else 'No'}")
        elif value is not None:
            lines.append(f"- **{formatted_key}:** {value}")
    
    return "\n".join(lines)


def _build_system_prompt_with_preferences(preferences: Dict[str, Any] | None) -> str:
    """Build system prompt that includes user preferences."""
    base_prompt = STRICT_SYSTEM_INSTRUCTION
    
    if not preferences:
        return base_prompt
    
    # Format preferences for context
    pref_lines = []
    for key, value in preferences.items():
        formatted_key = key.replace("_", " ")
        if isinstance(value, list) and value:
            pref_lines.append(f"- {formatted_key}: {', '.join(str(v) for v in value)}")
        elif isinstance(value, bool):
            pref_lines.append(f"- {formatted_key}: {'yes' if value else 'no'}")
        elif value is not None:
            pref_lines.append(f"- {formatted_key}: {value}")
    
    if not pref_lines:
        return base_prompt
    
    preferences_section = "\n".join(pref_lines)
    
    return f"""{base_prompt}

USER PREFERENCES (use these to personalize responses when relevant):
{preferences_section}

When making recommendations, take these preferences into account (e.g., if user has dietary restrictions like halal or vegetarian, prioritize those options)."""


@router.post("/hello", response_model=HelloResponse)
def ai_hello(request: HelloRequest) -> HelloResponse:
    """
    Simple AI endpoint that sends a message to Gemini and returns the reply.
    (Original endpoint - unchanged behavior)
    """
    try:
        reply = generate_text(request.message)
        return HelloResponse(reply=reply)
    except ValueError as e:
        # Missing API key
        logger.error(f"Gemini config error: {e}")
        raise HTTPException(
            status_code=500,
            detail={"error": str(e)}
        )
    except Exception as e:
        logger.error(
            f"Gemini API error: {e}\n"
            f"Traceback:\n{traceback.format_exc()}"
        )
        raise HTTPException(
            status_code=500,
            detail={"error": "gemini_error", "message": str(e)}
        )


@router.post("/chat", response_model=ChatResponse)
async def ai_chat(
    request: ChatRequest,
    current_user: User | None = Depends(get_current_user_optional),
    db: Session = Depends(get_db)
) -> ChatResponse:
    """
    Production AI chat endpoint with grounded responses.
    
    - For hours queries: Uses Google Places data (no hallucination)
    - For preferences queries: Returns stored onboarding answers
    - For other queries: Uses Gemini with strict system prompt + user preferences
    
    Supports both authenticated users and guests.
    """
    message = request.message.strip()
    location_hint = request.location_hint
    
    # Get user preferences if authenticated
    preferences = None
    if current_user:
        preferences = current_user.onboarding_preferences
        logger.info(f"AI chat (authenticated): user_id={current_user.id}, has_preferences={preferences is not None}")
    else:
        logger.info("AI chat (guest): no user preferences")
    
    logger.info(f"AI chat: message={message[:100]}..., location_hint={location_hint}")
    
    # Check if user is asking about their preferences
    if _is_preferences_query(message):
        if not current_user:
            return ChatResponse(reply="Please sign in to view your saved preferences.")
        reply = _format_preferences_response(preferences)
        return ChatResponse(reply=reply)
    
    # Check if this is a hours-related query
    if _is_hours_query(message):
        return await _handle_hours_query(message, location_hint)
    
    # General query - use Gemini with preferences context
    return _handle_general_query(message, preferences)


async def _handle_hours_query(message: str, location_hint: str | None) -> ChatResponse:
    """Handle queries about business hours using Google Places."""
    try:
        # Search for the place
        place_data = await find_place_with_hours(message, location_hint)
        
        if not place_data:
            # Could not find the place - ask for clarification
            reply = (
                "I couldn't find that exact location in our data. "
                "Could you share the neighborhood, zip code, or cross-street to help me find it?"
            )
            return ChatResponse(reply=reply)
        
        # Check if we have hours
        if not place_data.get("opening_hours"):
            name = place_data.get("name", "that location")
            address = place_data.get("formatted_address", "")
            
            reply = f"I found **{name}**"
            if address:
                reply += f" at {address}"
            reply += ", but I couldn't find official hours for this location in our data.\n\n"
            reply += "Can you share the neighborhood/zip or the exact address so I can find the right one?"
            
            return ChatResponse(reply=reply)
        
        # Format the response with real hours data
        reply = _format_hours_response(place_data)
        return ChatResponse(reply=reply)
        
    except ValueError as e:
        # Missing API key
        logger.error(f"Places config error: {e}")
        raise HTTPException(
            status_code=500,
            detail={"error": str(e)}
        )
    except Exception as e:
        logger.error(f"Hours query failed: {e}\n{traceback.format_exc()}")
        # Fall back to asking for clarification
        return ChatResponse(
            reply="I had trouble looking up that location. Could you provide more details like the neighborhood or zip code?"
        )


def _handle_general_query(message: str, preferences: Dict[str, Any] | None = None) -> ChatResponse:
    """Handle non-hours queries using Gemini with strict prompt and user preferences."""
    try:
        # Build system prompt with preferences if available
        system_prompt = _build_system_prompt_with_preferences(preferences)
        reply = generate_text_with_system(message, system_prompt)
        return ChatResponse(reply=reply)
    except ValueError as e:
        # Missing API key
        logger.error(f"Gemini config error: {e}")
        raise HTTPException(
            status_code=500,
            detail={"error": str(e)}
        )
    except Exception as e:
        logger.error(f"Gemini API error: {e}\n{traceback.format_exc()}")
        raise HTTPException(
            status_code=500,
            detail={"error": "gemini_error", "message": str(e)}
        )
