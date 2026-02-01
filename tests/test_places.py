"""Tests for places router, including _upsert_business_from_place and GET /details."""

from datetime import datetime, timezone
from unittest.mock import AsyncMock, MagicMock, patch

import pytest
from fastapi import status

from app.core.auth import get_current_user
from app.main import app
from app.models.business import Business
from app.models.user import User
from app.routers.places import _upsert_business_from_place


def _minimal_place_result(place_id: str, name: str = "Test Place") -> dict:
    """Minimal Google Place Details-style result for testing."""
    return {
        "place_id": place_id,
        "name": name,
        "formatted_address": "123 Test St, City",
        "geometry": {"location": {"lat": 40.7, "lng": -73.9}},
        "address_components": [],
        "types": ["restaurant"],
    }


def test_upsert_business_from_place_twice_same_place_id_no_integrity_error(db_session):
    """
    Calling _upsert_business_from_place twice with the same (provider, provider_place_id)
    must not raise IntegrityError and must leave exactly one row.
    """
    place_id = "ChIJcXx-hXlhwokRxu8raEC7zus"
    result = _minimal_place_result(place_id)

    # First call: insert
    b1 = _upsert_business_from_place(db_session, place_id, result)
    assert b1.id is not None
    assert b1.provider == "google"
    assert b1.provider_place_id == place_id
    assert b1.name == "Test Place"

    # Second call: update (must not insert duplicate, must not raise)
    b2 = _upsert_business_from_place(db_session, place_id, result)
    assert b2.id == b1.id
    assert b2.provider == "google"
    assert b2.provider_place_id == place_id

    # Exactly one row with this (provider, provider_place_id)
    count = (
        db_session.query(Business)
        .filter(
            Business.provider == "google",
            Business.provider_place_id == place_id,
        )
        .count()
    )
    assert count == 1


def test_upsert_business_from_place_updates_existing_row(db_session):
    """Upsert with same place_id updates existing row; ai_notes preserved."""
    place_id = "ChIJ-update-test-place-id"
    result1 = _minimal_place_result(place_id, name="Original Name")
    b1 = _upsert_business_from_place(db_session, place_id, result1)
    b1.ai_notes = "curated user notes"
    db_session.commit()

    result2 = _minimal_place_result(place_id, name="Updated Name")
    b2 = _upsert_business_from_place(db_session, place_id, result2)

    assert b2.id == b1.id
    assert b2.name == "Updated Name"
    db_session.refresh(b2)
    assert b2.ai_notes == "curated user notes"


def test_place_details_returns_top_level_business_id_and_ai_context(client, db_session):
    """
    GET /places/details with mocked Google API and LLM returns 200 with top-level
    business_id and ai_context; DB business row has ai_context and ai_context_last_updated set.
    """
    place_id = "ChIJtest123"
    minimal_result = _minimal_place_result(place_id, name="Papa Johns Pizza")

    mock_user = MagicMock(spec=User)
    mock_user.id = None  # not used for this test
    mock_user.onboarding_completed_at = datetime.now(timezone.utc)
    mock_user.onboarding_preferences = {"diet": "vegetarian"}

    fixed_ai_context = {
        "summary": "Test summary for Papa Johns.",
        "pros": ["Good for groups", "Fast delivery"],
        "cons": [],
        "best_for_user_profile": "Great for your vegetarian preferences.",
        "vibe": "Casual",
        "reliability_notes": "Based on Google reviews.",
        "source_notes": "Google Place details and reviews.",
    }

    def override_get_current_user():
        return mock_user

    app.dependency_overrides[get_current_user] = override_get_current_user

    try:
        with (
            patch(
                "app.routers.places._call_google_api",
                new_callable=AsyncMock,
                return_value={"status": "OK", "result": minimal_result},
            ),
            patch(
                "app.routers.places.generate_ai_notes_for_business",
                return_value="Test ai notes",
            ),
            patch(
                "app.routers.places.generate_business_ai_context",
                return_value=fixed_ai_context,
            ),
        ):
            response = client.get(
                f"/api/v1/places/details?place_id={place_id}",
            )
    finally:
        app.dependency_overrides.pop(get_current_user, None)

    assert response.status_code == status.HTTP_200_OK
    data = response.json()
    assert "result" in data
    assert data["result"]["provider_place_id"] == place_id
    assert "business_id" in data
    assert data["business_id"] is not None
    assert "ai_context" in data
    assert data["ai_context"] == fixed_ai_context
    assert data["ai_context"]["summary"] == "Test summary for Papa Johns."

    business = (
        db_session.query(Business)
        .filter(
            Business.provider == "google",
            Business.provider_place_id == place_id,
        )
        .first()
    )
    assert business is not None
    assert business.ai_context == fixed_ai_context
    assert business.ai_context_last_updated is not None


def test_place_details_returns_200_when_ai_helpers_return_none(client, db_session):
    """
    GET /places/details when AI helpers return None returns 200 with place details;
    business.ai_notes and business.ai_context are not updated (remain null).
    """
    place_id = "ChIJnone123"
    minimal_result = _minimal_place_result(place_id, name="Place No AI")

    mock_user = MagicMock(spec=User)
    mock_user.id = None
    mock_user.onboarding_completed_at = datetime.now(timezone.utc)
    mock_user.onboarding_preferences = None

    def override_get_current_user():
        return mock_user

    app.dependency_overrides[get_current_user] = override_get_current_user

    try:
        with (
            patch(
                "app.routers.places._call_google_api",
                new_callable=AsyncMock,
                return_value={"status": "OK", "result": minimal_result},
            ),
            patch(
                "app.routers.places.generate_ai_notes_for_business",
                return_value=None,
            ),
            patch(
                "app.routers.places.generate_business_ai_context",
                return_value=None,
            ),
        ):
            response = client.get(
                f"/api/v1/places/details?place_id={place_id}",
            )
    finally:
        app.dependency_overrides.pop(get_current_user, None)

    assert response.status_code == status.HTTP_200_OK
    data = response.json()
    assert "result" in data
    assert data["result"]["provider_place_id"] == place_id
    assert data["result"]["name"] == "Place No AI"
    assert data.get("ai_context") is None

    business = (
        db_session.query(Business)
        .filter(
            Business.provider == "google",
            Business.provider_place_id == place_id,
        )
        .first()
    )
    assert business is not None
    assert business.ai_notes is None
    assert business.ai_context is None
