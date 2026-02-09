"""
Unified AI insights for a business: one LLM call returns both ai_notes and ai_context.

Replaces separate generate_ai_notes_for_business and generate_business_ai_context calls
so GET /places/details can trigger a single background job and avoid blocking.
"""

import json
import logging
import re
from typing import Any
from uuid import UUID

from app.models.business import Business
from app.schemas.ai_context import BusinessAIContext
from app.services.gemini_client import generate_text_with_system

logger = logging.getLogger(__name__)

# Fixed vocabulary for AI tags (home feed sections). Model must choose 1–4 from this set.
AI_TAG_VOCABULARY = frozenset({
    "date-night", "groups", "solo", "quick-bite", "healthy",
    "coffee", "dessert", "study-spot", "fancy", "budget",
})

SYSTEM_PROMPT = """You are PickRight, an AI guide that summarizes a SINGLE local business. You never make things up that contradict the data you are given. You write in a friendly, concise tone. Do not personalize to any specific user; describe the place objectively.

You are given structured data about the business (name, category, rating, price, address, and a few review snippets). Your task is to produce a single JSON object with exactly these three top-level keys:

1. "notes": One or two short paragraphs of natural-language insight about this place (what people like, vibe, best situations to come here, stand-out items, dietary notes if present). Keep it concise.

2. "context": An object with exactly these keys (use empty strings or empty arrays if you have no info):
   - "summary": string — 1–3 sentence overview of the place.
   - "vibe": string — Ambiance / atmosphere (e.g. casual, date night, family-friendly).
   - "best_for": array of strings — e.g. ["studying", "catching up with friends", "quick lunch"].
   - "pros": array of strings — 3–7 positive points (what people like, standout items).
   - "cons": array of strings — 0–5 drawbacks or caveats (e.g. wait times, price).
   - "reliability_notes": string — How reliable the info is (e.g. "Based on Google reviews and place details").
   - "source_notes": string — Brief note on what sources were used (e.g. "Google Place details and reviews").

3. "tags": An array of 1–4 tags from this exact vocabulary only (use the string values as-is):
   date-night | groups | solo | quick-bite | healthy | coffee | dessert | study-spot | fancy | budget
   Only include tags that clearly fit the business based on reviews, rating, price level, and description. No other values.

Output ONLY valid JSON in this exact shape (no markdown, no code fence, no explanation):
{"notes": "...", "context": {"summary": "...", "vibe": "...", "best_for": [], "pros": [], "cons": [], "reliability_notes": "...", "source_notes": "..."}, "tags": ["tag1", "tag2"]}"""


def _format_review_snippets(place_data: dict, max_reviews: int = 3, max_chars_per_review: int = 300) -> str:
    """Extract at most 2–3 review snippets, heavily truncated."""
    reviews = place_data.get("reviews") or []
    snippets = []
    for r in reviews[:max_reviews]:
        text = (r or {}).get("text") or (r or {}).get("review")
        if text:
            snippets.append(text.strip()[:max_chars_per_review])
    return "\n\n".join(snippets) if snippets else "(No review snippets available)"


def _extract_city(place_data: dict) -> str:
    """Extract city/locality from Google Place address_components."""
    for comp in place_data.get("address_components") or []:
        if "locality" in (comp.get("types") or []):
            return comp.get("long_name") or comp.get("short_name") or ""
    return ""


def _build_prompt(business: Business, place_details: dict) -> str:
    """Build a concise prompt for the unified insights call."""
    name = business.name or "Unknown"
    category = (
        business.category
        or (place_details.get("types") or [""])[0]
        if place_details.get("types")
        else "Not specified"
    )
    address = business.address or business.address_full or ""
    city = _extract_city(place_details)
    state = getattr(business, "state", None) or ""
    rating = place_details.get("rating")
    review_count = place_details.get("user_ratings_total") or 0
    price_level = place_details.get("price_level")
    price_str = str(price_level) if price_level is not None else "Not specified"
    types = place_details.get("types") or []
    tags = ", ".join(types) if types else "None"
    review_snippets = _format_review_snippets(place_details)

    return f"""Business name: {name}
Category: {category}
Address: {address}, {city}, {state}
Rating: {rating} from {review_count} reviews
Price level: {price_str}
Tags: {tags}

Sample review snippets (truncated):
{review_snippets}

Respond with a single JSON object only: {{"notes": "...", "context": {{...}}, "tags": [...]}}."""


def _parse_json_from_response(text: str) -> dict[str, Any]:
    """Extract JSON from model response; may be wrapped in markdown code block."""
    if not text or not text.strip():
        return {}
    raw = text.strip()
    match = re.search(r"```(?:json)?\s*([\s\S]*?)\s*```", raw)
    if match:
        raw = match.group(1).strip()
    try:
        return json.loads(raw)
    except json.JSONDecodeError as e:
        logger.warning("Unified AI insights JSON parse failed: %s; raw snippet: %s", e, raw[:200])
        return {}


def _normalize_context_for_store(context: dict[str, Any]) -> dict[str, Any]:
    """Map Gemini context shape to BusinessAIContext (summary, pros, cons, best_for_user_profile, vibe, etc.)."""
    best_for = context.get("best_for")
    if isinstance(best_for, list):
        best_for_user_profile = ", ".join(str(x) for x in best_for) if best_for else ""
    else:
        best_for_user_profile = str(best_for) if best_for else ""

    raw = {
        "summary": context.get("summary") or "",
        "pros": context.get("pros") if isinstance(context.get("pros"), list) else [],
        "cons": context.get("cons") if isinstance(context.get("cons"), list) else [],
        "best_for_user_profile": best_for_user_profile,
        "vibe": context.get("vibe") or "",
        "reliability_notes": context.get("reliability_notes") or "",
        "source_notes": context.get("source_notes") or "",
    }
    try:
        ctx = BusinessAIContext.model_validate(raw)
        return ctx.to_store_dict() if hasattr(ctx, "to_store_dict") else ctx.model_dump(exclude_none=True)
    except Exception as e:
        logger.warning("BusinessAIContext validation failed, using raw: %s", e)
        return {k: v for k, v in raw.items() if k in BusinessAIContext.model_fields}


def _normalize_tags(raw_tags: Any) -> list[str]:
    """Extract and validate tags: must be from vocabulary, max 4. Invalid entries are skipped."""
    if not isinstance(raw_tags, list):
        return []
    out: list[str] = []
    for item in raw_tags[:4]:
        if isinstance(item, str) and item.strip() in AI_TAG_VOCABULARY:
            out.append(item.strip())
    return out


def generate_business_ai_insights(business: Business, place_details: dict) -> tuple[str, dict, list[str]]:
    """
    Call Gemini once and return ai_notes, ai_context, and ai_tags.

    Args:
        business: SQLAlchemy Business model (name, address, category, etc.).
        place_details: Raw Google Place Details API result (rating, reviews, types, etc.).

    Returns:
        (ai_notes_string, ai_context_dict, ai_tags_list). ai_context_dict is JSON-serializable
        and suitable for Business.ai_context (BusinessAIContext shape). ai_tags_list is
        1–4 tags from the fixed vocabulary; defaults to [] if missing or invalid.

    Raises:
        RuntimeError: If the LLM returns nothing or JSON parsing fails and we have no fallback.
    """
    fallback_notes = "AI notes could not be generated for this place."
    fallback_context = {
        "summary": "AI context could not be generated.",
        "source_notes": "Generation failed.",
    }
    fallback_tags: list[str] = []

    prompt = _build_prompt(business, place_details)
    try:
        response_text = generate_text_with_system(prompt, SYSTEM_PROMPT)
    except Exception as e:
        logger.exception("generate_business_ai_insights LLM failed for business %s: %s", business.id, e)
        raise RuntimeError("AI insights generation failed") from e

    if not response_text or not response_text.strip():
        logger.warning("Empty Gemini response for business %s; returning fallback", business.id)
        return (fallback_notes, fallback_context, fallback_tags)

    data = _parse_json_from_response(response_text)
    if not data:
        logger.warning("Could not parse AI insights JSON for business %s; returning fallback", business.id)
        return (fallback_notes, fallback_context, fallback_tags)

    notes = (data.get("notes") or "").strip() or fallback_notes
    context_raw = data.get("context")
    ai_context = _normalize_context_for_store(context_raw) if isinstance(context_raw, dict) else fallback_context
    raw_tags = data.get("tags")
    tags = _normalize_tags(raw_tags) if raw_tags is not None else fallback_tags
    if raw_tags is not None and not isinstance(raw_tags, list):
        logger.debug("AI insights tags not a list for business %s; using empty list", business.id)
    return (notes, ai_context, tags)


def generate_and_save_business_ai_insights(business_id: UUID, place_details: dict) -> None:
    """
    Load business, generate AI insights in one LLM call, and persist to DB.

    Intended to be run in a FastAPI BackgroundTask. Re-checks needs_ai to avoid
    duplicate work. Uses a new DB session; catches and logs errors so failures
    do not crash the background worker.

    Args:
        business_id: Business UUID (from Business.id).
        place_details: Raw Google Place Details API result (the "result" dict).
    """
    from datetime import datetime, timedelta, timezone

    from app.db.session import SessionLocal
    from app.models.business import Business

    db = SessionLocal()
    try:
        business = db.query(Business).filter(Business.id == business_id).first()
        if not business:
            logger.warning("generate_and_save_business_ai_insights: business %s not found", business_id)
            return

        now = datetime.now(timezone.utc)
        last_updated = business.ai_context_last_updated
        if last_updated is not None and last_updated.tzinfo is None:
            last_updated = last_updated.replace(tzinfo=timezone.utc)
        if (
            business.ai_notes
            and business.ai_context
            and last_updated is not None
            and (now - last_updated) <= timedelta(hours=24)
        ):
            logger.debug("generate_and_save_business_ai_insights: business %s already has fresh AI insights", business_id)
            return

        ai_notes, ai_context, ai_tags = generate_business_ai_insights(business, place_details)
        business.ai_notes = ai_notes
        business.ai_context = ai_context
        business.ai_tags = ai_tags
        business.ai_context_last_updated = now
        db.commit()
        logger.info("Saved AI insights for business %s", business_id)
    except Exception as e:
        logger.exception("generate_and_save_business_ai_insights failed for business %s: %s", business_id, e)
        db.rollback()
    finally:
        db.close()
