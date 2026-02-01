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
