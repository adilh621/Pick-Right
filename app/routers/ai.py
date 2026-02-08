"""AI endpoints using Gemini."""

import json
import logging
import re
import traceback
from typing import Dict, Any
from uuid import UUID

from fastapi import APIRouter, HTTPException, Depends
from pydantic import BaseModel, field_validator
from sqlalchemy.orm import Session

from app.services.gemini_client import generate_text, generate_text_with_system
from app.services.places_client import (
    DEFAULT_NEARBY_RADIUS_M,
    find_place_with_hours,
    search_places_text,
)
from app.core.auth import get_current_user_optional
from app.core.geo import haversine_distance_km, km_to_miles
from app.db.session import get_db
from app.models.user import User
from app.models.business import Business

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/ai", tags=["ai"])

# System: main role + behavior for chat (one specific place, use context only when relevant)
CHAT_SYSTEM_PROMPT = """You are PickRight, an AI guide helping a single user decide whether ONE specific business is a good fit for them.

You are given:
- Structured business info (name, category, address, coordinates, rating, price, tags).
- Optional AI context snapshot: summary, pros, cons, vibe, best_for_user_profile (personalized when user prefs available).
- Cached "AI notes" summarizing what people like/dislike and key details.
- The user's onboarding preferences (e.g. halal, spice level, budget, ambiance).
- The approximate distance between the user and the business in kilometers and miles (when available).
- The conversation history for this user and this business (stay on-topic for this business).

Rules:
- Stay on-topic: the user is asking about THIS business. Do not suggest other places unless they explicitly ask.
- Always treat the provided business info and distance as ground truth.
- For questions about "how far" or "distance", answer using distance_miles / distance_km from the context instead of telling the user to check a maps app. You can phrase it like "about 1.4 miles (≈ 5–10 minutes by car depending on traffic)".
- If you know the full address, give it when the user asks "where is this place".
- Use preferences as background context. Only mention them when they clearly affect the answer (e.g. halal questions, budget suitability). Do not repeat the user's preferences in every answer.
- Be concrete and specific. Avoid saying "I don't have information" if the data is present in the context.
- Tone: friendly, concise, and clear. Return markdown."""

# System prompt for main chat (no specific business): place discovery and choice
MAIN_CHAT_SYSTEM_PROMPT = """You are PickRight, an assistant that helps the user choose a place to go (coffee, food, gym, etc.) based on:
- Their location and preferences
- A list of candidate businesses returned by the backend (when provided)

You are given:
- user_location_context.area_hint: the user's area (e.g. "Queens, NY") when available.
- Optional onboarding_preferences (e.g. halal, spice level, budget, ambiance).
- Optional candidate_businesses: list of {name, place_id} — use ONLY these when giving options; never invent places.
- The user's message.

LOCATION & OFF-TOPIC (check first):
- If area_hint is null or empty, respond with exactly: "I don't have your location. Try setting or changing your location in the app, then ask again."
- If the user asks something clearly not about local places (e.g. random facts, math, coding, politics), respond with exactly: "Sorry, I can only help with places near you. Try changing your location and ask me again."

CORE RULES when the user is asking about places:

1) OPTION FORMAT
   - For ANY message where they are exploring or undecided, reply with:
     - A 1–2 sentence summary of how you interpreted their request.
     - Then a short, numbered list of 2–4 options, e.g.:
       1) Name — ultra short reason
       2) Name — ultra short reason
     - Each option MUST map to a business in candidate_businesses. Do not invent places.

2) FOLLOW-UP QUESTIONS
   - If the user refines ("something quieter?", "better parking?", "closer to me?"): treat as REFINING the search. Re-rank or filter the given businesses and return a new numbered list of 2–4 options.
   - Only stop giving multiple options when the user clearly picks one, e.g. "Let's do option 2", "I'm going with Dunkin'", "Tell me more about #3". Then focus on that single business (pros/cons, vibe, best for) and keep the answer short.

3) CONTEXT
   - Use the businesses and preferences you are given. Favor preferences (e.g. quiet, cheap, study-friendly) when ranking.

4) TONE
   - Be concise, friendly, and practical. Bullets and short lists over long paragraphs. Do not mention "JSON", "objects", or "API" to the user.

5) SAFETY / HONESTY
   - If no candidate_businesses are provided (or the list is empty), say you don't see any good matches right now and suggest widening the radius or changing filters. Never fabricate a business that isn't in the provided list."""

NO_LOCATION_MESSAGE = "I don't have your location. Try setting or changing your location in the app, then ask again."
OFF_TOPIC_MESSAGE = "Sorry, I can only help with places near you. Try changing your location and ask me again."

# Marker for structured recommended places in model output (legacy; we now build recommended_places server-side)
RECOMMENDED_PLACES_MARKER = "RECOMMENDED_PLACES_JSON:"

MAX_RECOMMENDED_PLACES = 5
# Same default as GET /api/v1/places/nearby so recommended_places are biased to same area
PLACES_SEARCH_RADIUS_M = DEFAULT_NEARBY_RADIUS_M

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

# Keywords that indicate the user is asking about places (for server-side recommended_places lookup)
PLACE_LIKE_KEYWORDS = re.compile(
    r'\b(restaurant|restaurants|cafe|cafes|coffee|gym|gyms|bjj|jiu\s*jitsu|brazilian\s*jiu|bar|bars|'
    r'salon|salons|spa|spas|bakery|pizza|halal|date\s*night|brunch|breakfast|dinner| lunch)\b',
    re.IGNORECASE
)
# Map message keywords to (Google-style search query, optional type hint)
PLACE_QUERY_MAP = [
    (re.compile(r'\bbjj\b|jiu\s*jitsu|brazilian\s*jiu', re.IGNORECASE), "Brazilian Jiu-Jitsu gym"),
    (re.compile(r'\bgym\b|\bfitness\b', re.IGNORECASE), "gym fitness"),
    (re.compile(r'\brestaurant\b|\bhalal\b|date\s*night|dinner|lunch|brunch', re.IGNORECASE), "restaurant"),
    (re.compile(r'\bcafe\b|coffee', re.IGNORECASE), "cafe coffee"),
    (re.compile(r'\bbar\b', re.IGNORECASE), "bar"),
    (re.compile(r'\bsalon\b|hair', re.IGNORECASE), "hair salon"),
    (re.compile(r'\bspa\b', re.IGNORECASE), "spa"),
    (re.compile(r'\bbakery\b', re.IGNORECASE), "bakery"),
    (re.compile(r'\bpizza\b', re.IGNORECASE), "pizza restaurant"),
]


class HelloRequest(BaseModel):
    message: str


class HelloResponse(BaseModel):
    reply: str


class ChatRequest(BaseModel):
    """Request for POST /ai/chat. Backward compatible: extra fields optional."""
    message: str
    location_hint: str | None = None  # Human-readable area for main chat (e.g. "Queens, NY")
    business_id: UUID | None = None
    business_context: dict | None = None
    onboarding_preferences: dict | None = None
    # User location for distance-to-business (optional; use same lat/lng as Discover when user overrides location)
    latitude: float | None = None
    longitude: float | None = None

    @field_validator("latitude")
    @classmethod
    def latitude_in_range(cls, v: float | None) -> float | None:
        if v is not None and (v < -90 or v > 90):
            raise ValueError("latitude must be between -90 and 90")
        return v

    @field_validator("longitude")
    @classmethod
    def longitude_in_range(cls, v: float | None) -> float | None:
        if v is not None and (v < -180 or v > 180):
            raise ValueError("longitude must be between -180 and 180")
        return v

    @field_validator("location_hint")
    @classmethod
    def location_hint_empty_as_none(cls, v: str | None) -> str | None:
        if v is not None and isinstance(v, str) and not v.strip():
            return None
        return v


class RecommendedPlace(BaseModel):
    name: str
    place_id: str


class ChatResponse(BaseModel):
    reply: str
    ai_context: dict | None = None  # Optional copy of Business.ai_context for client
    recommended_places: list[RecommendedPlace] | None = None


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


def _get_chat_history(db: Session, user_id: UUID, business_id: UUID, limit: int = 50) -> list[tuple[str, str]]:
    """Return chat history for (user_id, business_id). Stateless: no DB; returns empty list."""
    return []


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


def _merge_ai_context_into_payload(
    payload: Dict[str, Any],
    ai_context: Dict[str, Any] | None,
) -> None:
    """Merge Business.ai_context (summary, pros, cons, vibe, best_for_user_profile) into payload for system prompt."""
    if not ai_context or not isinstance(ai_context, dict):
        return
    if ai_context.get("summary"):
        payload["ai_context_summary"] = ai_context["summary"]
    if ai_context.get("pros"):
        payload["ai_context_pros"] = ai_context["pros"]
    if ai_context.get("cons"):
        payload["ai_context_cons"] = ai_context["cons"]
    if ai_context.get("vibe"):
        payload["ai_context_vibe"] = ai_context["vibe"]
    if ai_context.get("best_for_user_profile"):
        payload["ai_context_best_for"] = ai_context["best_for_user_profile"]


def _build_business_context_payload(
    business: Business | None,
    business_context_dict: Dict[str, Any] | None,
    ai_context: Dict[str, Any] | None = None,
) -> Dict[str, Any]:
    """
    Build a single structured business context dict for the model.
    When business_id is used we load from DB (business is set); otherwise use client-sent business_context dict.
    Merges both when present: DB fields take precedence for identity/address/coordinates/category.
    """
    payload: Dict[str, Any] = {
        "id": None,
        "name": None,
        "address": None,
        "coordinates": None,
        "category": None,
        "tags": None,
        "price_level": None,
        "rating": None,
        "review_count": None,
        "types": None,
        "extra_notes": None,
        "ai_notes": None,
    }
    # From DB model (exact address, coordinates, ai_notes we store)
    if business is not None:
        payload["id"] = str(business.id)
        payload["name"] = business.name
        # Prefer address/state from Google Places columns; fall back to address_full
        addr_full = getattr(business, "address", None) or business.address_full
        addr_state = getattr(business, "state", None)
        if addr_full or addr_state:
            payload["address"] = {k: v for k, v in ({"full": addr_full, "state": addr_state}.items()) if v is not None}
        elif business.address_full:
            payload["address"] = {"full": business.address_full}
        # Prefer latitude/longitude (Google Places); fall back to lat/lng
        lat_val = business.latitude if getattr(business, "latitude", None) is not None else business.lat
        lng_val = business.longitude if getattr(business, "longitude", None) is not None else business.lng
        if lat_val is not None and lng_val is not None:
            payload["coordinates"] = {"lat": lat_val, "lng": lng_val}
        payload["category"] = business.category
        if getattr(business, "ai_notes", None):
            payload["ai_notes"] = business.ai_notes
    # From client-sent business_context (can override or fill in)
    if business_context_dict:
        if payload["id"] is None and business_context_dict.get("id") is not None:
            payload["id"] = str(business_context_dict["id"])
        if payload["name"] is None:
            payload["name"] = business_context_dict.get("name")
        if payload["address"] is None:
            if business_context_dict.get("address"):
                addr = business_context_dict["address"]
                payload["address"] = addr if isinstance(addr, dict) else {"full": addr}
            elif business_context_dict.get("address_full"):
                payload["address"] = {"full": business_context_dict["address_full"]}
        if payload["coordinates"] is None and business_context_dict.get("coordinates"):
            payload["coordinates"] = business_context_dict["coordinates"]
        if payload["category"] is None:
            payload["category"] = business_context_dict.get("category")
        if business_context_dict.get("tags") is not None:
            payload["tags"] = business_context_dict["tags"]
        if business_context_dict.get("price_level") is not None:
            payload["price_level"] = business_context_dict["price_level"]
        if business_context_dict.get("rating") is not None:
            payload["rating"] = business_context_dict["rating"]
        if business_context_dict.get("review_count") is not None:
            payload["review_count"] = business_context_dict["review_count"]
        if business_context_dict.get("types") is not None:
            payload["types"] = business_context_dict["types"]
        if business_context_dict.get("extra_notes") is not None:
            payload["extra_notes"] = business_context_dict["extra_notes"]
        if business_context_dict.get("ai_notes") is not None:
            payload["ai_notes"] = business_context_dict["ai_notes"]
    # Merge Business.ai_context highlights for chat prompt
    _merge_ai_context_into_payload(payload, ai_context)
    # Drop keys that are still None so the JSON is minimal
    return {k: v for k, v in payload.items() if v is not None}


def _business_context_json_section(payload: Dict[str, Any]) -> str:
    """Serialize structured business context to a single system message string (JSON blob)."""
    if not payload:
        return ""
    return f"BusinessContext (JSON): {json.dumps(payload, indent=2)}"


def _user_preferences_json_section(preferences: Dict[str, Any] | None) -> str:
    """Serialize user preferences to a single system message string (JSON blob)."""
    if not preferences or not isinstance(preferences, dict):
        return ""
    return f"UserPreferences (JSON): {json.dumps(preferences, indent=2)}"


def _user_location_context_section(area_hint: str | None) -> str:
    """Serialize user location context for main chat system prompt."""
    payload = {"area_hint": area_hint}
    return f"user_location_context (JSON): {json.dumps(payload)}"


def _candidate_businesses_section(places: list[RecommendedPlace] | None) -> str:
    """Serialize candidate businesses for main chat so the model can reference them by name."""
    if not places:
        return "candidate_businesses (JSON): []"
    payload = [{"name": p.name, "place_id": p.place_id} for p in places]
    return f"candidate_businesses (JSON): {json.dumps(payload)}"


def _build_main_chat_system_instruction(
    location_hint: str | None,
    preferences: Dict[str, Any] | None = None,
    candidate_businesses: list[RecommendedPlace] | None = None,
) -> str:
    """Build system instruction for main chat (local discovery + candidate list)."""
    parts = [MAIN_CHAT_SYSTEM_PROMPT, "", _user_location_context_section(location_hint)]
    parts.append("")
    parts.append(_candidate_businesses_section(candidate_businesses))
    if preferences and isinstance(preferences, dict):
        parts.append("")
        parts.append(_user_preferences_json_section(preferences))
    return "\n\n".join(parts).strip()


def _parse_recommended_places_from_reply(raw_reply: str) -> tuple[str, list[RecommendedPlace] | None]:
    """
    If the reply ends with RECOMMENDED_PLACES_JSON: {...}, split into clean reply and list of places.
    Otherwise return (raw_reply, None).
    """
    if RECOMMENDED_PLACES_MARKER not in raw_reply:
        return (raw_reply.strip(), None)
    parts = raw_reply.split(RECOMMENDED_PLACES_MARKER, 1)
    reply_text = parts[0].strip()
    if len(parts) != 2 or not parts[1].strip():
        return (raw_reply.strip(), None)
    try:
        data = json.loads(parts[1].strip())
        items = data.get("recommended_places")
        if not isinstance(items, list):
            return (reply_text, None)
        places = []
        for item in items:
            if isinstance(item, dict) and item.get("name") and item.get("place_id"):
                places.append(RecommendedPlace(name=str(item["name"]), place_id=str(item["place_id"])))
        return (reply_text, places if places else None)
    except (json.JSONDecodeError, TypeError):
        return (reply_text, None)


def _is_place_like_message(message: str) -> bool:
    """True if the message appears to be asking about places (restaurants, gyms, cafes, etc.)."""
    return bool(PLACE_LIKE_KEYWORDS.search(message))


def _message_to_place_query(message: str) -> str | None:
    """Build a short search query for Google Places from the user message. Returns None if not place-like."""
    if not _is_place_like_message(message):
        return None
    for pattern, query in PLACE_QUERY_MAP:
        if pattern.search(message):
            return query
    # Fallback: use first matched keyword as query
    m = PLACE_LIKE_KEYWORDS.search(message)
    if m:
        return m.group(0).strip()
    return "place"


async def _fetch_recommended_places_for_message(
    message: str,
    lat: float,
    lng: float,
    preferences: Dict[str, Any] | None = None,
) -> list[RecommendedPlace]:
    """
    Fetch nearby places using Google Places Text Search for a place-like message.
    Uses same radius as GET /api/v1/places/nearby. Only called when lat/lng are present.
    Returns up to MAX_RECOMMENDED_PLACES with name and place_id; empty list on no results or error.
    """
    query = _message_to_place_query(message)
    if not query:
        logger.debug("recommended_places skip: message not place-like")
        return []
    logger.info(
        "recommended_places fetch: place_query=%r, lat=%s, lng=%s, radius_m=%s",
        query, lat, lng, PLACES_SEARCH_RADIUS_M,
    )
    try:
        results = await search_places_text(
            query=query,
            lat=lat,
            lng=lng,
            radius_m=PLACES_SEARCH_RADIUS_M,
            limit=MAX_RECOMMENDED_PLACES,
        )
        places = [
            RecommendedPlace(name=p.get("name") or "Place", place_id=p["place_id"])
            for p in results
            if p.get("place_id")
        ]
        if not places:
            logger.debug("recommended_places: Google returned no results for query=%r", query)
        return places
    except Exception as e:
        logger.warning("Failed to fetch recommended places for message: %s", e)
        return []


def _format_business_context_section(business_context: Dict[str, Any] | None) -> str:
    """Format business context dict into a readable section for the system prompt."""
    if not business_context:
        return ""
    lines = ["CONTEXT – The user is asking about this specific place:", ""]
    name = business_context.get("name")
    if name:
        lines.append(f"- Name: {name}")
    address = business_context.get("address")
    if address:
        lines.append(f"- Address: {address}")
    category = business_context.get("category")
    if category:
        lines.append(f"- Category: {category}")
    rating = business_context.get("rating")
    if rating is not None:
        lines.append(f"- Rating: {rating}")
    review_count = business_context.get("review_count")
    if review_count is not None:
        lines.append(f"- Review count: {review_count}")
    price_level = business_context.get("price_level")
    if price_level is not None:
        lines.append(f"- Price level: {price_level}")
    types = business_context.get("types")
    if types:
        lines.append(f"- Types: {', '.join(types)}")
    tags = business_context.get("tags")
    if tags:
        lines.append(f"- Tags: {', '.join(tags)}")
    if len(lines) <= 2:
        return ""
    return "\n".join(lines) + "\n\n"


@router.post("/hello", response_model=HelloResponse)
def ai_hello(request: HelloRequest) -> HelloResponse:
    """
    Simple AI endpoint that sends a message to Gemini and returns the reply.
    (Original endpoint - unchanged behavior)
    """
    try:
        reply = generate_text(request.message)
        if reply is None:
            raise HTTPException(
                status_code=503,
                detail={"error": "gemini_unavailable", "message": "AI is temporarily unavailable; please try again later."},
            )
        return HelloResponse(reply=reply)
    except HTTPException:
        raise
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
    - For other queries: Uses Gemini with strict system prompt + optional business context + user preferences
    
    Request may include optional business_context and onboarding_preferences (e.g. from business-linked chat).
    Backward compatible: older clients sending only message still work.
    Supports both authenticated users and guests.
    """
    message = request.message.strip()
    location_hint = request.location_hint
    business_id = request.business_id
    business_context_from_client = request.business_context
    onboarding_preferences_from_request = request.onboarding_preferences

    # Optional debug: incoming request (redact message content and prefs; safe for local debugging)
    logger.debug(
        "ai/chat request: message_len=%d, location_hint=%r, business_id=%s, has_business_context=%s, has_onboarding_preferences=%s",
        len(message),
        location_hint,
        business_id,
        business_context_from_client is not None,
        onboarding_preferences_from_request is not None,
    )

    # Resolve business: load from DB when business_id is provided, then build structured context
    business_from_db: Business | None = None
    if business_id is not None:
        business_from_db = db.query(Business).filter(Business.id == business_id).first()
        if not business_from_db:
            raise HTTPException(status_code=404, detail="Business not found")
    business_context_payload = _build_business_context_payload(
        business_from_db,
        business_context_from_client,
        ai_context=getattr(business_from_db, "ai_context", None) if business_from_db else None,
    )

    # Compute user–business distance when both coordinates are available
    user_lat, user_lng = request.latitude, request.longitude
    business_lat, business_lng = None, None
    if business_from_db is not None:
        business_lat = getattr(business_from_db, "latitude", None) or business_from_db.lat
        business_lng = getattr(business_from_db, "longitude", None) or business_from_db.lng
    if business_lat is None and business_context_payload.get("coordinates"):
        coords = business_context_payload["coordinates"]
        if isinstance(coords, dict):
            business_lat = coords.get("lat")
            business_lng = coords.get("lng")
    if (
        user_lat is not None
        and user_lng is not None
        and business_lat is not None
        and business_lng is not None
    ):
        distance_km = round(haversine_distance_km(user_lat, user_lng, business_lat, business_lng), 1)
        distance_miles = round(km_to_miles(distance_km), 1)
        business_context_payload["distance_km"] = distance_km
        business_context_payload["distance_miles"] = distance_miles

    # Prefer preferences from request (client-sent) when present; else from current_user
    preferences = onboarding_preferences_from_request if onboarding_preferences_from_request is not None else None
    if preferences is None and current_user:
        preferences = current_user.onboarding_preferences

    # Chat history for this user + business (when business_id and authenticated user)
    chat_history: list[tuple[str, str]] = []
    if business_id is not None and current_user is not None:
        chat_history = _get_chat_history(db, current_user.id, business_id)
    ai_context_for_response = (
        business_from_db.ai_context if business_from_db and getattr(business_from_db, "ai_context", None) else None
    )

    # Lightweight logging: only presence of context (no auth tokens, PII, or message content)
    has_business = bool(business_context_payload) or business_context_from_client is not None
    has_prefs = preferences is not None or onboarding_preferences_from_request is not None
    logger.info(
        "AI chat: message_len=%d, location_hint=%s, business_context=%s, onboarding_preferences=%s",
        len(message),
        "set" if location_hint else "none",
        "set" if has_business else "none",
        "set" if has_prefs else "none",
    )

    # Check if user is asking about their preferences
    if _is_preferences_query(message):
        if not current_user and not onboarding_preferences_from_request:
            return ChatResponse(reply="Please sign in to view your saved preferences.", ai_context=None)
        reply = _format_preferences_response(preferences)
        return ChatResponse(reply=reply, ai_context=None)

    # Check if this is a hours-related query
    if _is_hours_query(message):
        return await _handle_hours_query(message, location_hint)

    # Main chat (no specific business): local discovery only; require location_hint.
    # Only trigger no-location path when business_id is None AND location_hint is missing/empty
    # (validator already normalizes "" and whitespace-only to None).
    is_main_chat = business_id is None
    no_location_path = is_main_chat and not location_hint
    logger.info(
        "AI chat route: location_hint=%r, business_id=%s, is_main_chat=%s, no_location_path=%s",
        location_hint,
        business_id,
        is_main_chat,
        no_location_path,
    )
    if is_main_chat:
        if not location_hint:
            return ChatResponse(reply=NO_LOCATION_MESSAGE, ai_context=None)
        return await _handle_main_chat_query(
            message,
            location_hint=location_hint,
            preferences=preferences,
            latitude=request.latitude,
            longitude=request.longitude,
        )

    # Business chat: general query with business context + preferences + chat history
    return _handle_general_query(
        message,
        preferences=preferences,
        business_context_payload=business_context_payload,
        chat_history=chat_history,
        db=db,
        current_user=current_user,
        business_id=business_id,
        ai_context_for_response=ai_context_for_response,
    )


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


async def _handle_main_chat_query(
    message: str,
    location_hint: str,
    preferences: Dict[str, Any] | None = None,
    latitude: float | None = None,
    longitude: float | None = None,
) -> ChatResponse:
    """Handle main chat (no business): fetch candidates first, then Gemini with option-format rules and candidate list."""
    try:
        recommended_places: list[RecommendedPlace] | None = None
        if _is_place_like_message(message) and latitude is not None and longitude is not None:
            recommended_places = await _fetch_recommended_places_for_message(
                message, latitude, longitude, preferences
            )
            recommended_places = recommended_places or None  # empty list -> None for response

        system_instruction = _build_main_chat_system_instruction(
            location_hint=location_hint,
            preferences=preferences,
            candidate_businesses=recommended_places,
        )
        reply = generate_text_with_system(message, system_instruction)

        if reply is None:
            raise HTTPException(
                status_code=503,
                detail={"error": "gemini_unavailable", "message": "AI is temporarily unavailable; please try again later."},
            )

        reply_clean = reply.strip()
        return ChatResponse(reply=reply_clean, ai_context=None, recommended_places=recommended_places)
    except HTTPException:
        raise
    except ValueError as e:
        logger.error(f"Gemini config error: {e}")
        raise HTTPException(
            status_code=500,
            detail={"error": str(e)}
        )
    except Exception as e:
        logger.error(f"Gemini main chat error: {e}\n{traceback.format_exc()}")
        raise HTTPException(
            status_code=500,
            detail={"error": "gemini_error", "message": str(e)}
        )


def _build_chat_system_instruction(
    business_context_payload: Dict[str, Any] | None = None,
    preferences: Dict[str, Any] | None = None,
) -> str:
    """
    Build the full system instruction for the chat model.
    Gemini takes a single system_instruction string; we compose it from:
    1. System: main role + behavior (CHAT_SYSTEM_PROMPT)
    2. System: business context (JSON blob when present)
    3. System: user preferences (JSON blob when present)
    """
    parts: list[str] = []

    # System: main role + behavior
    parts.append(CHAT_SYSTEM_PROMPT)

    # System: business context
    if business_context_payload:
        parts.append("")
        parts.append(_business_context_json_section(business_context_payload))

    # System: user preferences
    if preferences and isinstance(preferences, dict):
        parts.append("")
        parts.append(_user_preferences_json_section(preferences))

    return "\n\n".join(parts).strip()


def _build_user_content_with_history(chat_history: list[tuple[str, str]], message: str) -> str:
    """Build the user content string: history (User: ... / Assistant: ...) + latest User: message."""
    parts = []
    for role, content in chat_history:
        label = "User" if role == "user" else "Assistant"
        parts.append(f"{label}: {content}")
    parts.append(f"User: {message}")
    return "\n\n".join(parts)


def _handle_general_query(
    message: str,
    preferences: Dict[str, Any] | None = None,
    business_context_payload: Dict[str, Any] | None = None,
    chat_history: list[tuple[str, str]] | None = None,
    db: Session | None = None,
    current_user: User | None = None,
    business_id: UUID | None = None,
    ai_context_for_response: dict | None = None,
) -> ChatResponse:
    """Handle non-hours queries using Gemini with chat system prompt, BusinessContext (JSON), UserPreferences (JSON), and optional chat history."""
    try:
        system_instruction = _build_chat_system_instruction(
            business_context_payload=business_context_payload,
            preferences=preferences,
        )
        user_content = (
            _build_user_content_with_history(chat_history or [], message)
            if (chat_history or []) or message
            else message
        )
        reply = generate_text_with_system(user_content, system_instruction)

        if reply is None:
            raise HTTPException(
                status_code=503,
                detail={"error": "gemini_unavailable", "message": "AI is temporarily unavailable; please try again later."},
            )

        return ChatResponse(reply=reply, ai_context=ai_context_for_response)
    except HTTPException:
        raise
    except ValueError as e:
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
