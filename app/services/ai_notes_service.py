"""
Generate and cache AI notes for businesses.

Uses Gemini (same as /ai/chat) to produce short Markdown bullet summaries
from business + Google Place data. Used by /places/details to populate
businesses.ai_notes on first load.
"""

import logging
from typing import Optional

from app.models.business import Business
from app.services.gemini_client import generate_text_with_system

logger = logging.getLogger(__name__)

SYSTEM_PROMPT = """You are PickRight, an AI guide that summarizes a SINGLE local business for a user. You never make things up that contradict the data you are given. You write in a friendly, concise tone.

You are given structured data about the business (name, address, rating, price level, tags, review snippets). Based only on that data, produce short "AI notes" that help future chats answer questions about:
- what people usually like or dislike
- the vibe and best situations to come here (family, friends, solo, late-night, etc.)
- any stand-out menu items mentioned
- anything important for halal / vegetarian / dietary needs IF present in the data

Output a short Markdown-style bullet list (3–7 bullets) with no extra explanations."""


def _format_review_snippets(place_data: dict) -> str:
    """Extract up to 5 review text snippets from Google Place details."""
    reviews = place_data.get("reviews") or []
    snippets = []
    for r in reviews[:5]:
        text = (r or {}).get("text") or (r or {}).get("review")
        if text:
            snippets.append(text.strip()[:500])  # cap length per review
    return "\n\n".join(snippets) if snippets else "(No review snippets available)"


def _price_level_str(level: Optional[int]) -> str:
    if level is None:
        return "Not specified"
    return str(level) if level else "Not specified"


def _extract_city(place_data: dict) -> str:
    """Extract city/locality from Google Place address_components."""
    for comp in place_data.get("address_components") or []:
        if "locality" in (comp.get("types") or []):
            return comp.get("long_name") or comp.get("short_name") or ""
    return ""


def generate_ai_notes_for_business(business: Business, place_data: dict) -> Optional[str]:
    """
    Generate AI notes for a business using structured data from the DB and Google Place details.

    Args:
        business: SQLAlchemy Business model (name, address, state, category, etc.).
        place_data: Raw Google Place Details API result (rating, review_count, types, reviews, price_level).

    Returns:
        Concise Markdown-style bullet summary string, or None on quota/cooldown or LLM failure.
    """
    name = business.name or "Unknown"
    primary_category = business.category or (place_data.get("types") or [""])[0] if place_data.get("types") else "Not specified"
    address = business.address or business.address_full or ""
    city = _extract_city(place_data)
    state = business.state or ""
    latitude = business.latitude or business.lat
    longitude = business.longitude or business.lng
    rating = place_data.get("rating")
    rating_count = place_data.get("user_ratings_total") or 0
    price_level = place_data.get("price_level")
    types = place_data.get("types") or []
    tags = ", ".join(types) if types else "None"
    review_snippets = _format_review_snippets(place_data)

    user_prompt = f"""Business name: {name}
Category: {primary_category}
Address: {address}, {city}, {state}
Coordinates: {latitude}, {longitude}
Rating: {rating} from {rating_count} reviews
Price: {_price_level_str(price_level)}
Tags: {tags}
Sample review snippets (if any):
{review_snippets}

Using ONLY this information, generate the AI notes."""

    result = generate_text_with_system(user_prompt, SYSTEM_PROMPT)
    return result if result else None
