"""Tests for unified business AI insights (notes, context, tags)."""

from unittest.mock import patch

import pytest

from app.models.business import Business
from app.services.business_ai_insights import (
    generate_business_ai_insights,
    generate_and_save_business_ai_insights,
    _normalize_tags,
)


def _minimal_place_details() -> dict:
    """Minimal Google Place Details-style result for testing."""
    return {
        "place_id": "ChIJtest",
        "name": "Test Cafe",
        "types": ["cafe", "food"],
        "address_components": [],
        "rating": 4.5,
        "user_ratings_total": 100,
        "reviews": [{"text": "Great coffee and vibe."}],
    }


def test_generate_business_ai_insights_returns_tags_when_present(db_session):
    """When LLM returns valid notes, context, and tags, all three are parsed and returned."""
    business = Business(
        name="Test Cafe",
        provider="google",
        provider_place_id="ChIJ-tags-happy",
    )
    db_session.add(business)
    db_session.commit()
    db_session.refresh(business)

    response_json = (
        '{"notes": "Cozy spot for coffee.", '
        '"context": {"summary": "A cafe.", "vibe": "Casual", "best_for": [], "pros": [], "cons": [], '
        '"reliability_notes": "Based on Google.", "source_notes": "Google."}, '
        '"tags": ["coffee", "study-spot"]}'
    )

    with patch(
        "app.services.business_ai_insights.generate_text_with_system",
        return_value=response_json,
    ):
        notes, context, tags = generate_business_ai_insights(business, _minimal_place_details())

    assert notes == "Cozy spot for coffee."
    assert isinstance(context, dict)
    assert context.get("summary") == "A cafe."
    assert tags == ["coffee", "study-spot"]


def test_generate_business_ai_insights_tags_missing_defaults_to_empty_list(db_session):
    """When tags key is missing or invalid, tags default to [] but notes/context still returned."""
    business = Business(
        name="Test Place",
        provider="google",
        provider_place_id="ChIJ-tags-missing",
    )
    db_session.add(business)
    db_session.commit()
    db_session.refresh(business)

    # No "tags" key
    response_json = (
        '{"notes": "Some notes.", '
        '"context": {"summary": "Summary.", "vibe": "", "best_for": [], "pros": [], "cons": [], '
        '"reliability_notes": "", "source_notes": ""}}'
    )

    with patch(
        "app.services.business_ai_insights.generate_text_with_system",
        return_value=response_json,
    ):
        notes, context, tags = generate_business_ai_insights(business, _minimal_place_details())

    assert notes == "Some notes."
    assert isinstance(context, dict)
    assert tags == []


def test_normalize_tags_filters_vocabulary_and_limits_four():
    """Only tags in vocabulary are kept; max 4."""
    assert _normalize_tags(["coffee", "study-spot", "date-night"]) == ["coffee", "study-spot", "date-night"]
    assert _normalize_tags(["coffee", "invalid-tag", "study-spot"]) == ["coffee", "study-spot"]
    assert _normalize_tags(["coffee", "study-spot", "date-night", "groups", "solo"]) == [
        "coffee",
        "study-spot",
        "date-night",
        "groups",
    ]
    assert _normalize_tags("not-a-list") == []
    assert _normalize_tags(None) == []


def test_generate_and_save_business_ai_insights_persists_tags(db_session):
    """generate_and_save_business_ai_insights saves ai_notes, ai_context, and ai_tags."""
    business = Business(
        name="Test Place",
        provider="google",
        provider_place_id="ChIJ-save-tags",
    )
    db_session.add(business)
    db_session.commit()
    db_session.refresh(business)
    business_id = business.id

    response_json = (
        '{"notes": "Saved notes.", '
        '"context": {"summary": "Summary.", "vibe": "Cozy", "best_for": [], "pros": [], "cons": [], '
        '"reliability_notes": "", "source_notes": ""}, '
        '"tags": ["quick-bite", "budget"]}'
    )
    place_details = _minimal_place_details()

    with (
        patch("app.db.session.SessionLocal", return_value=db_session),
        patch.object(db_session, "close"),  # avoid closing test session
        patch(
            "app.services.business_ai_insights.generate_text_with_system",
            return_value=response_json,
        ),
    ):
        generate_and_save_business_ai_insights(business_id, place_details)

    db_session.refresh(business)
    assert business.ai_notes == "Saved notes."
    assert business.ai_context is not None
    assert business.ai_tags == ["quick-bite", "budget"]
