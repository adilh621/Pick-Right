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
    When generate_text_with_system returns None (quota/cooldown),
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

    with patch("app.ai.business_context.generate_text_with_system", return_value=None):
        result = generate_business_ai_context(business, _minimal_place_data())

    assert result is None


def test_generate_business_ai_context_prompt_is_generic_no_user_preferences(db_session):
    """
    The prompt passed to the LLM must not contain user preferences or personalization.
    AI context is generic (same for all users).
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

    with patch("app.ai.business_context.generate_text_with_system") as mock_llm:
        mock_llm.return_value = '{"summary": "A place.", "pros": [], "cons": [], "best_for_user_profile": "Anyone.", "vibe": "Casual", "reliability_notes": "", "source_notes": ""}'
        generate_business_ai_context(business, place_data, None)
        generate_business_ai_context(business, place_data, {"diet": "vegetarian", "budget": "low"})

    assert mock_llm.call_count >= 1
    for call in mock_llm.call_args_list:
        user_prompt = call.args[0]
        assert isinstance(user_prompt, str)
        # Must not include user preferences or their values (AI context is generic)
        assert "User onboarding preferences" not in user_prompt
        assert "vegetarian" not in user_prompt
        assert "low" not in user_prompt
        assert "generic" in user_prompt.lower()
        assert "best_for_user_profile" in user_prompt
