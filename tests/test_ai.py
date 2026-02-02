"""Tests for AI chat endpoint: context loading and prompt construction."""

import pytest
from datetime import datetime, timezone
from uuid import UUID
from unittest.mock import patch

from app.models.user import User
from app.models.business import Business
from tests.conftest import TEST_SUPABASE_UID_1, create_test_token


def test_chat_loads_business_ai_context_and_user_prefs(client, db_session, mock_jwks, create_test_token):
    """
    Chat endpoint loads Business, Business.ai_context, and User.onboarding_preferences,
    and builds a system prompt that references the correct business and AI context.
    Uses mocked LLM to avoid network calls.
    """
    token = create_test_token(sub=TEST_SUPABASE_UID_1)
    # Create user via GET /me
    r_me = client.get("/api/v1/me", headers={"Authorization": f"Bearer {token}"})
    r_me.raise_for_status()
    user_id = r_me.json()["id"]
    # Set onboarding_preferences and onboarding_completed_at
    user = db_session.query(User).filter(User.id == UUID(user_id)).first()
    user.onboarding_preferences = {"budget": "mid", "vibe": "casual"}
    user.onboarding_completed_at = datetime.now(timezone.utc)
    db_session.commit()
    # Create business with ai_context
    business = Business(
        name="Test Restaurant",
        provider="google",
        provider_place_id="ChIJ-test-chat-123",
        ai_context={
            "summary": "A great spot for dinner",
            "pros": ["Good food", "Friendly staff"],
            "vibe": "Casual and cozy",
        },
    )
    db_session.add(business)
    db_session.commit()
    db_session.refresh(business)

    with patch("app.routers.ai.generate_text_with_system") as mock_gen:
        mock_gen.return_value = "Yes, it is great."
        resp = client.post(
            "/api/v1/ai/chat",
            headers={"Authorization": f"Bearer {token}"},
            json={"message": "Is this place good?", "business_id": str(business.id)},
        )

    assert resp.status_code == 200
    data = resp.json()
    assert data["reply"] == "Yes, it is great."
    assert mock_gen.called
    # First arg: user content (message + optional history), second: system instruction
    call_args = mock_gen.call_args
    user_content = call_args[0][0]
    system_instruction = call_args[0][1]
    assert "Test Restaurant" in system_instruction
    assert "A great spot for dinner" in system_instruction or "ai_context_summary" in system_instruction or "summary" in system_instruction
    assert "Is this place good?" in user_content
    # User preferences should be in system context
    assert "budget" in system_instruction or "mid" in system_instruction or "UserPreferences" in system_instruction


def test_chat_returns_ai_context_when_business_has_it(client, db_session, mock_jwks, create_test_token):
    """Chat response includes ai_context when business has ai_context stored."""
    token = create_test_token(sub=TEST_SUPABASE_UID_1)
    client.get("/api/v1/me", headers={"Authorization": f"Bearer {token}"})
    business = Business(
        name="Place With Context",
        provider="google",
        provider_place_id="ChIJ-ctx-456",
        ai_context={"summary": "Summary here", "vibe": "Chill"},
    )
    db_session.add(business)
    db_session.commit()
    db_session.refresh(business)

    with patch("app.routers.ai.generate_text_with_system") as mock_gen:
        mock_gen.return_value = "Sure."
        resp = client.post(
            "/api/v1/ai/chat",
            headers={"Authorization": f"Bearer {token}"},
            json={"message": "Tell me more", "business_id": str(business.id)},
        )

    assert resp.status_code == 200
    data = resp.json()
    assert data.get("ai_context") is not None
    assert data["ai_context"].get("summary") == "Summary here"
    assert data["ai_context"].get("vibe") == "Chill"


def test_chat_404_when_business_id_not_found(client, mock_jwks, create_test_token):
    """Chat returns 404 when business_id does not exist."""
    token = create_test_token()
    client.get("/api/v1/me", headers={"Authorization": f"Bearer {token}"})
    fake_uuid = "550e8400-e29b-41d4-a716-446655440099"
    resp = client.post(
        "/api/v1/ai/chat",
        headers={"Authorization": f"Bearer {token}"},
        json={"message": "Hi", "business_id": fake_uuid},
    )
    assert resp.status_code == 404


def test_chat_rejects_invalid_latitude(client, mock_jwks, create_test_token, db_session):
    """POST /ai/chat with latitude outside [-90, 90] returns 422."""
    token = create_test_token()
    client.get("/api/v1/me", headers={"Authorization": f"Bearer {token}"})
    business = Business(
        name="Test Place",
        provider="google",
        provider_place_id="ChIJ-invalid-lat",
    )
    db_session.add(business)
    db_session.commit()
    db_session.refresh(business)
    resp = client.post(
        "/api/v1/ai/chat",
        headers={"Authorization": f"Bearer {token}"},
        json={
            "message": "How far?",
            "business_id": str(business.id),
            "latitude": 91.0,
            "longitude": 0.0,
        },
    )
    assert resp.status_code == 422
    detail = resp.json().get("detail", [])
    assert any("latitude" in str(d).lower() for d in (detail if isinstance(detail, list) else [detail]))


def test_chat_rejects_invalid_longitude(client, mock_jwks, create_test_token, db_session):
    """POST /ai/chat with longitude outside [-180, 180] returns 422."""
    token = create_test_token()
    client.get("/api/v1/me", headers={"Authorization": f"Bearer {token}"})
    business = Business(
        name="Test Place",
        provider="google",
        provider_place_id="ChIJ-invalid-lng",
    )
    db_session.add(business)
    db_session.commit()
    db_session.refresh(business)
    resp = client.post(
        "/api/v1/ai/chat",
        headers={"Authorization": f"Bearer {token}"},
        json={
            "message": "How far?",
            "business_id": str(business.id),
            "latitude": 0.0,
            "longitude": 181.0,
        },
    )
    assert resp.status_code == 422
    detail = resp.json().get("detail", [])
    assert any("longitude" in str(d).lower() for d in (detail if isinstance(detail, list) else [detail]))
