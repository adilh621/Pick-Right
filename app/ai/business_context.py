"""
Generate and store structured AI context for a single business.

Used by GET /places/details to populate Business.ai_context. One LLM call
produces a structured snapshot (summary, pros, cons, vibe, best_for_user_profile, etc.)
that is then used by the chat endpoint so the user never has to re-explain the business.
"""

import json
import logging
import re
from typing import Any

from app.models.business import Business
from app.schemas.ai_context import BusinessAIContext
from app.services.gemini_client import generate_text_with_system

logger = logging.getLogger(__name__)

SYSTEM_PROMPT = """You are PickRight, an AI that summarizes a SINGLE local business for a user.

You are given:
1. Structured data about the business (name, address, category, rating, reviews, etc.).
2. Optional: the user's onboarding preferences (budget, vibe, distance, dietary, etc.).

Your task: Produce a single JSON object with exactly these keys (use empty strings or empty arrays if you have no info):
- "summary": string — 1–3 sentence overview of the place.
- "pros": array of strings — 3–7 positive points (what people like, standout items, strengths).
- "cons": array of strings — 0–5 drawbacks or caveats (e.g. wait times, price, limited options).
- "best_for_user_profile": string — Who this place is best for; if user preferences are given, personalize this (e.g. "Great for your budget and love of spicy food").
- "vibe": string — Ambiance / atmosphere (e.g. casual, date night, family-friendly).
- "reliability_notes": string — How reliable the info is (e.g. "Based on Google reviews and place details").
- "source_notes": string — Brief note on what sources were used (e.g. "Google Place details and reviews").

Rules:
- Use ONLY the data provided. Do not invent facts.
- Output valid JSON only. No markdown, no code fence, no explanation before or after."""


def _format_review_snippets(place_data: dict) -> str:
    """Extract up to 5 review text snippets from Google Place details."""
    reviews = place_data.get("reviews") or []
    snippets = []
    for r in reviews[:5]:
        text = (r or {}).get("text") or (r or {}).get("review")
        if text:
            snippets.append(text.strip()[:500])
    return "\n\n".join(snippets) if snippets else "(No review snippets available)"


def _extract_user_prefs_summary(preferences: dict | None) -> str:
    """Format user onboarding preferences for the prompt."""
    if not preferences or not isinstance(preferences, dict):
        return "(No user preferences provided)"
    return json.dumps(preferences, indent=2)


def _build_user_prompt(business: Business, place_data: dict, user_preferences: dict | None) -> str:
    """Build the user prompt with business + place data + optional user prefs."""
    name = business.name or "Unknown"
    category = business.category or (place_data.get("types") or [""])[0] if place_data.get("types") else "Not specified"
    address = business.address or business.address_full or ""
    state = getattr(business, "state", None) or ""
    rating = place_data.get("rating")
    review_count = place_data.get("user_ratings_total") or 0
    price_level = place_data.get("price_level")
    types = place_data.get("types") or []
    review_snippets = _format_review_snippets(place_data)
    prefs_summary = _extract_user_prefs_summary(user_preferences)

    return f"""Business:
- name: {name}
- category: {category}
- address: {address}, {state}
- rating: {rating} (from {review_count} reviews)
- price_level: {price_level}
- types: {", ".join(types) if types else "None"}

Sample review snippets:
{review_snippets}

User onboarding preferences (use to personalize best_for_user_profile):
{prefs_summary}

Respond with a single JSON object only (keys: summary, pros, cons, best_for_user_profile, vibe, reliability_notes, source_notes)."""


def _parse_json_from_response(text: str) -> dict[str, Any]:
    """Extract JSON from model response; may be wrapped in markdown code block."""
    if not text or not text.strip():
        return {}
    raw = text.strip()
    # Remove optional markdown code block
    match = re.search(r"```(?:json)?\s*([\s\S]*?)\s*```", raw)
    if match:
        raw = match.group(1).strip()
    try:
        return json.loads(raw)
    except json.JSONDecodeError as e:
        logger.warning("AI context JSON parse failed: %s; raw snippet: %s", e, raw[:200])
        return {}


def generate_business_ai_context(
    business: Business,
    place_data: dict,
    user_preferences: dict | None = None,
) -> dict[str, Any] | None:
    """
    Generate structured AI context for a business with one LLM call.

    Args:
        business: SQLAlchemy Business model (name, address, category, etc.).
        place_data: Raw Google Place Details API result (rating, reviews, types, etc.).
        user_preferences: Optional user onboarding_preferences for personalization.

    Returns:
        Dict suitable for Business.ai_context (JSONB), with keys from BusinessAIContext;
        or None on LLM/network error so the endpoint can still return 200 with ai_context omitted.
        On parse failure or empty response, returns a minimal dict (e.g. summary only).
    """
    user_prompt = _build_user_prompt(business, place_data, user_preferences)
    try:
        response_text = generate_text_with_system(user_prompt, SYSTEM_PROMPT)
    except Exception as e:
        logger.exception("generate_business_ai_context LLM failed for business %s: %s", business.id, e)
        return None

    if response_text is None:
        return None

    raw_dict = _parse_json_from_response(response_text)
    if not raw_dict:
        return {"summary": "AI context could not be generated.", "source_notes": "Generation failed."}

    # Normalize into our schema (allow extra keys from model for forward compat)
    try:
        ctx = BusinessAIContext.model_validate(raw_dict)
        return ctx.to_store_dict() if hasattr(ctx, "to_store_dict") else ctx.model_dump(exclude_none=True)
    except Exception as e:
        logger.warning("BusinessAIContext validation failed, using raw dict: %s", e)
        return {k: v for k, v in raw_dict.items() if k in BusinessAIContext.model_fields}
