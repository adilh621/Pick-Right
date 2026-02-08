"""
Generate and cache AI notes for businesses.

Deprecated: Prefer app.services.business_ai_insights.generate_business_ai_insights
for a single LLM call that returns both ai_notes and ai_context. This module keeps
a thin wrapper for backward compatibility.
"""

import logging
from typing import Optional

from app.models.business import Business
from app.services.business_ai_insights import generate_business_ai_insights

logger = logging.getLogger(__name__)


def generate_ai_notes_for_business(business: Business, place_data: dict) -> Optional[str]:
    """
    Generate AI notes for a business (thin wrapper around unified generate_business_ai_insights).

    Args:
        business: SQLAlchemy Business model (name, address, state, category, etc.).
        place_data: Raw Google Place Details API result (rating, review_count, types, reviews, price_level).

    Returns:
        Concise summary string, or None on LLM failure.
    """
    try:
        notes, _ = generate_business_ai_insights(business, place_data)
        return notes if notes else None
    except Exception as e:
        logger.exception("generate_ai_notes_for_business failed for business %s: %s", business.id, e)
        return None
