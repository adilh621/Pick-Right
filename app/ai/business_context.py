"""
Generate and store structured AI context for a single business.

Deprecated: Prefer app.services.business_ai_insights.generate_business_ai_insights
for a single LLM call that returns both ai_notes and ai_context. This module keeps
a thin wrapper for backward compatibility.
"""

import logging
from typing import Any

from app.models.business import Business
from app.services.business_ai_insights import generate_business_ai_insights

logger = logging.getLogger(__name__)


def generate_business_ai_context(
    business: Business,
    place_data: dict,
    user_preferences: dict | None = None,
) -> dict[str, Any] | None:
    """
    Generate structured AI context for a business (thin wrapper around unified generate_business_ai_insights).

    Args:
        business: SQLAlchemy Business model (name, address, category, etc.).
        place_data: Raw Google Place Details API result (rating, reviews, types, etc.).
        user_preferences: Unused; kept for backward compatibility.

    Returns:
        Dict suitable for Business.ai_context (JSONB), or None on LLM failure.
    """
    try:
        _, context, _ = generate_business_ai_insights(business, place_data)
        return context if context else None
    except Exception as e:
        logger.exception("generate_business_ai_context failed for business %s: %s", business.id, e)
        return None
