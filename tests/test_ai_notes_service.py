"""Tests for AI notes service."""

from unittest.mock import patch

import pytest

from app.models.business import Business
from app.services.ai_notes_service import generate_ai_notes_for_business


def _minimal_place_data() -> dict:
    """Minimal Google Place Details-style data for testing."""
    return {
        "place_id": "ChIJtest",
        "name": "Test Place",
        "types": ["restaurant"],
        "address_components": [],
    }


def test_generate_ai_notes_returns_none_when_llm_returns_none(db_session):
    """
    When unified generate_business_ai_insights raises or returns empty,
    generate_ai_notes_for_business returns None and does not raise.
    """
    business = Business(
        name="Test Restaurant",
        provider="google",
        provider_place_id="ChIJ-test-notes",
    )
    db_session.add(business)
    db_session.commit()
    db_session.refresh(business)

    with patch(
        "app.services.ai_notes_service.generate_business_ai_insights",
        return_value=(None, {}),
    ):
        result = generate_ai_notes_for_business(business, _minimal_place_data())

    assert result is None
