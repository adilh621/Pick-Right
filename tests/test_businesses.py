from datetime import datetime, timezone
from unittest.mock import MagicMock

import pytest
from fastapi import status

from app.core.auth import get_current_user
from app.main import app
from app.models.business import Business
from app.models.user import User


def test_create_business(client):
    """Test creating a business."""
    response = client.post(
        "/api/v1/businesses",
        json={
            "name": "Test Restaurant",
            "provider": "google",
            "provider_place_id": "ChIJ-test-create",
            "category": "restaurant",
            "address_full": "123 Test St"
        }
    )
    assert response.status_code == status.HTTP_201_CREATED
    data = response.json()
    assert data["name"] == "Test Restaurant"
    assert data["category"] == "restaurant"
    assert "id" in data


def test_list_businesses(seeded_client):
    """Test listing businesses."""
    response = seeded_client.get("/api/v1/businesses")
    assert response.status_code == status.HTTP_200_OK
    data = response.json()
    assert isinstance(data, list)
    assert len(data) >= 2  # At least 2 from seed data


def test_list_businesses_with_filter(seeded_client):
    """Test listing businesses with name filter."""
    response = seeded_client.get("/api/v1/businesses?name=Pizza")
    assert response.status_code == status.HTTP_200_OK
    data = response.json()
    assert isinstance(data, list)
    # Should find "Tony's Pizza"
    assert any("Pizza" in business["name"] for business in data)


def test_get_business(seeded_client):
    """Test getting a business by ID."""
    # Create a business first
    create_response = seeded_client.post(
        "/api/v1/businesses",
        json={
            "name": "Test Business",
            "provider": "google",
            "provider_place_id": "ChIJ-test-get",
        }
    )
    business_id = create_response.json()["id"]
    
    response = seeded_client.get(f"/api/v1/businesses/{business_id}")
    assert response.status_code == status.HTTP_200_OK
    data = response.json()
    assert data["id"] == business_id
    assert data["name"] == "Test Business"


# --- GET /businesses/{id}/ai-insights ---


def test_ai_insights_returns_404_for_invalid_business_id(client, mock_jwks, create_test_token):
    """GET /businesses/{id}/ai-insights returns 404 when business id is invalid."""
    token = create_test_token(sub="550e8400-e29b-41d4-a716-4466554400a1", email="ai_insights@example.com")
    fake_uuid = "550e8400-e29b-41d4-a716-446655440099"  # no such business
    app.dependency_overrides[get_current_user] = lambda: MagicMock(
        spec=User,
        id=None,
        onboarding_completed_at=datetime.now(timezone.utc),
    )
    try:
        response = client.get(
            f"/api/v1/businesses/{fake_uuid}/ai-insights",
            headers={"Authorization": f"Bearer {token}"},
        )
    finally:
        app.dependency_overrides.pop(get_current_user, None)
    assert response.status_code == status.HTTP_404_NOT_FOUND


def test_ai_insights_returns_ready_when_fresh(client, db_session, mock_jwks, create_test_token):
    """GET /businesses/{id}/ai-insights returns ai_status=ready with data when present and fresh."""
    from app.routers.places import _upsert_business_from_place

    place_id = "ChIJai-ready-test"
    result = {
        "place_id": place_id,
        "name": "AI Ready Place",
        "formatted_address": "456 Ready St",
        "geometry": {"location": {"lat": 40.8, "lng": -74.0}},
        "address_components": [],
        "types": ["cafe"],
    }
    business = _upsert_business_from_place(db_session, place_id, result)
    business.ai_notes = "Cozy spot for coffee."
    business.ai_context = {
        "summary": "A nice cafe.",
        "vibe": "Cozy",
        "pros": ["Good coffee"],
    }
    business.ai_context_last_updated = datetime.now(timezone.utc)
    db_session.commit()
    db_session.refresh(business)

    token = create_test_token(sub="550e8400-e29b-41d4-a716-4466554400a2", email="ready@example.com")
    app.dependency_overrides[get_current_user] = lambda: MagicMock(
        spec=User,
        id=None,
        onboarding_completed_at=datetime.now(timezone.utc),
    )
    try:
        response = client.get(
            f"/api/v1/businesses/{business.id}/ai-insights",
            headers={"Authorization": f"Bearer {token}"},
        )
    finally:
        app.dependency_overrides.pop(get_current_user, None)

    assert response.status_code == status.HTTP_200_OK
    data = response.json()
    assert data["business_id"] == str(business.id)
    assert data["ai_status"] == "ready"
    assert data["ai_notes"] == "Cozy spot for coffee."
    assert data["ai_context"]["summary"] == "A nice cafe."


def test_ai_insights_returns_pending_when_missing(client, db_session, mock_jwks, create_test_token):
    """GET /businesses/{id}/ai-insights returns ai_status=pending when AI data missing but business exists."""
    from app.routers.places import _upsert_business_from_place

    place_id = "ChIJai-pending-test"
    result = {
        "place_id": place_id,
        "name": "AI Pending Place",
        "formatted_address": "789 Pending St",
        "geometry": {"location": {"lat": 40.9, "lng": -74.1}},
        "address_components": [],
        "types": ["restaurant"],
    }
    business = _upsert_business_from_place(db_session, place_id, result)
    assert business.ai_notes is None
    assert business.ai_context is None
    db_session.commit()

    token = create_test_token(sub="550e8400-e29b-41d4-a716-4466554400a3", email="pending@example.com")
    app.dependency_overrides[get_current_user] = lambda: MagicMock(
        spec=User,
        id=None,
        onboarding_completed_at=datetime.now(timezone.utc),
    )
    try:
        response = client.get(
            f"/api/v1/businesses/{business.id}/ai-insights",
            headers={"Authorization": f"Bearer {token}"},
        )
    finally:
        app.dependency_overrides.pop(get_current_user, None)

    assert response.status_code == status.HTTP_200_OK
    data = response.json()
    assert data["business_id"] == str(business.id)
    assert data["ai_status"] == "pending"
    assert data["ai_notes"] is None
    assert data["ai_context"] is None

