"""Tests for business AI context generation."""

from unittest.mock import patch

import pytest

from app.models.business import Business
from app.ai.business_context import generate_business_ai_context


def _minimal_place_data() -> dict:
    """Minimal Google Place Details-style data for testing."""
    return {
        "place_id": "ChIJtest",
        "name": "Test Place",
        "types": ["restaurant"],
        "address_components": [],
    }


def test_generate_business_ai_context_returns_none_when_llm_returns_none(db_session):
    """
    When unified generate_business_ai_insights raises or returns empty,
    generate_business_ai_context returns None.
    """
    business = Business(
        name="Test Restaurant",
        provider="google",
        provider_place_id="ChIJ-test-ctx",
    )
    db_session.add(business)
    db_session.commit()
    db_session.refresh(business)

    with patch(
        "app.ai.business_context.generate_business_ai_insights",
        return_value=("", None, []),
    ):
        result = generate_business_ai_context(business, _minimal_place_data())

    assert result is None


def test_generate_business_ai_context_prompt_is_generic_no_user_preferences(db_session):
    """
    The wrapper calls unified generate_business_ai_insights with (business, place_data) only;
    user_preferences are not passed (AI context is generic for all users).
    """
    business = Business(
        name="Test Restaurant",
        provider="google",
        provider_place_id="ChIJ-test-generic",
    )
    db_session.add(business)
    db_session.commit()
    db_session.refresh(business)
    place_data = _minimal_place_data()

    with patch("app.ai.business_context.generate_business_ai_insights") as mock_insights:
        mock_insights.return_value = (
            "Some notes",
            {"summary": "A place.", "vibe": "Casual", "pros": [], "cons": []},
            [],
        )
        generate_business_ai_context(business, place_data, None)
        generate_business_ai_context(business, place_data, {"diet": "vegetarian", "budget": "low"})

    assert mock_insights.call_count == 2
    for call in mock_insights.call_args_list:
        # Only (business, place_data) are passed; no user_preferences
        args = call[0]
        assert len(args) == 2
        assert args[0] is business
        assert args[1] == place_data
