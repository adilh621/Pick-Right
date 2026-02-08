"""Tests for POST /api/v1/chat/business/{business_id} endpoint.

Uses mocked Gemini chat client (generate_business_chat_with_search) to avoid
real external calls. Verifies 200 with assistant_message and metadata,
503 on quota, 404 on missing business, 401 without auth. Endpoint is stateless;
no server-side chat storage.
"""

import pytest
from datetime import datetime, timezone
from uuid import UUID
from unittest.mock import patch

from app.models.business import Business
from app.models.user import User
from app.routers.chat import CHAT_BUSINESS_SYSTEM_PROMPT
from tests.conftest import TEST_SUPABASE_UID_1, create_test_token


def test_chat_business_200_returns_assistant_message(
    client, db_session, mock_jwks, create_test_token
):
    """
    Authenticated user, valid business_id; mock Gemini chat returns dummy string.
    Assert 200 and assistant_message equals dummy; metadata present.
    """
    token = create_test_token(sub=TEST_SUPABASE_UID_1)
    r_me = client.get("/api/v1/me", headers={"Authorization": f"Bearer {token}"})
    r_me.raise_for_status()
    user_id = r_me.json()["id"]
    user = db_session.query(User).filter(User.id == UUID(user_id)).first()
    user.onboarding_preferences = {"budget": "mid"}
    user.onboarding_completed_at = datetime.now(timezone.utc)
    db_session.commit()

    business = Business(
        name="Test Restaurant",
        provider="google",
        provider_place_id="ChIJ-chat-123",
        ai_context={"summary": "Great spot", "vibe": "Casual"},
        ai_notes="Popular for brunch.",
    )
    db_session.add(business)
    db_session.commit()
    db_session.refresh(business)

    with patch("app.routers.chat.generate_business_chat_with_search") as mock_gen:
        mock_gen.return_value = "This place is a great fit for you."
        resp = client.post(
            f"/api/v1/chat/business/{business.id}",
            headers={"Authorization": f"Bearer {token}"},
            json={"user_message": "Is this place good for brunch?"},
        )

    assert resp.status_code == 200
    data = resp.json()
    assert data["assistant_message"] == "This place is a great fit for you."
    assert data.get("chat_session_id") == str(business.id)
    assert data["metadata"]["model"]
    assert data["metadata"]["business_id"] == str(business.id)
    assert "created_at" in data["metadata"]


def test_chat_business_context_includes_business_and_user_profile(
    client, db_session, mock_jwks, create_test_token
):
    """
    Chat endpoint builds context with both business and user_profile;
    user_content passed to Gemini contains JSON with these keys and user_profile has onboarding prefs.
    """
    token = create_test_token(sub=TEST_SUPABASE_UID_1)
    r_me = client.get("/api/v1/me", headers={"Authorization": f"Bearer {token}"})
    r_me.raise_for_status()
    user_id = r_me.json()["id"]
    user = db_session.query(User).filter(User.id == UUID(user_id)).first()
    user.onboarding_preferences = {"budget": "mid", "vibe": "casual"}
    user.onboarding_completed_at = datetime.now(timezone.utc)
    db_session.commit()

    business = Business(
        name="Test Restaurant",
        provider="google",
        provider_place_id="ChIJ-ctx-123",
        ai_context={"summary": "Great spot", "vibe": "Casual"},
        ai_notes="Popular for brunch.",
    )
    db_session.add(business)
    db_session.commit()
    db_session.refresh(business)

    with patch("app.routers.chat.generate_business_chat_with_search") as mock_gen:
        mock_gen.return_value = "Sure."
        resp = client.post(
            f"/api/v1/chat/business/{business.id}",
            headers={"Authorization": f"Bearer {token}"},
            json={"user_message": "Is this good for me?"},
        )

    assert resp.status_code == 200
    mock_gen.assert_called_once()
    call_kwargs = mock_gen.call_args[1]
    user_content = call_kwargs["messages"][0]["content"]
    assert "Context (JSON):" in user_content
    assert '"business"' in user_content
    assert '"user_profile"' in user_content
    assert "budget" in user_content and "mid" in user_content
    assert "vibe" in user_content and "casual" in user_content
    assert "Test Restaurant" in user_content
    assert "Great spot" in user_content


def test_chat_business_uses_search_enabled_client_with_correct_args(
    client, db_session, mock_jwks, create_test_token
):
    """
    Chat endpoint calls generate_business_chat_with_search with CHAT_BUSINESS_SYSTEM_PROMPT
    and messages containing context JSON with business and user_profile.
    """
    token = create_test_token(sub=TEST_SUPABASE_UID_1)
    r_me = client.get("/api/v1/me", headers={"Authorization": f"Bearer {token}"})
    r_me.raise_for_status()
    user_id = r_me.json()["id"]
    user = db_session.query(User).filter(User.id == UUID(user_id)).first()
    user.onboarding_preferences = {"budget": "mid"}
    user.onboarding_completed_at = datetime.now(timezone.utc)
    db_session.commit()

    business = Business(
        name="Search Test Cafe",
        provider="google",
        provider_place_id="ChIJ-search-123",
        ai_context={"summary": "Cozy cafe"},
        ai_notes="Good coffee.",
    )
    db_session.add(business)
    db_session.commit()
    db_session.refresh(business)

    with patch("app.routers.chat.generate_business_chat_with_search") as mock_gen:
        mock_gen.return_value = "Based on web search results, it appears that this location opened in 2020."
        resp = client.post(
            f"/api/v1/chat/business/{business.id}",
            headers={"Authorization": f"Bearer {token}"},
            json={"user_message": "When was this location established?"},
        )

    assert resp.status_code == 200
    assert (
        resp.json()["assistant_message"]
        == "Based on web search results, it appears that this location opened in 2020."
    )
    mock_gen.assert_called_once()
    call_kwargs = mock_gen.call_args[1]
    assert call_kwargs["system_prompt"] == CHAT_BUSINESS_SYSTEM_PROMPT.strip()
    messages = call_kwargs["messages"]
    assert len(messages) == 1
    assert messages[0]["role"] == "user"
    user_content = messages[0]["content"]
    assert "Context (JSON):" in user_content
    assert '"business"' in user_content
    assert '"user_profile"' in user_content
    assert "Search Test Cafe" in user_content
    assert "When was this location established?" in user_content


def test_chat_business_503_when_gemini_returns_none(client, db_session, mock_jwks, create_test_token):
    """When generate_business_chat_with_search returns None (quota), return 503 with model_overloaded."""
    token = create_test_token(sub=TEST_SUPABASE_UID_1)
    client.get("/api/v1/me", headers={"Authorization": f"Bearer {token}"})
    business = Business(
        name="Test Place",
        provider="google",
        provider_place_id="ChIJ-503",
        ai_context={"summary": "Nice"},
    )
    db_session.add(business)
    db_session.commit()
    db_session.refresh(business)

    with patch("app.routers.chat.generate_business_chat_with_search", return_value=None):
        resp = client.post(
            f"/api/v1/chat/business/{business.id}",
            headers={"Authorization": f"Bearer {token}"},
            json={"user_message": "Tell me more"},
        )

    assert resp.status_code == 503
    data = resp.json()
    assert data.get("detail") is not None
    detail = data["detail"]
    if isinstance(detail, dict):
        assert detail.get("error") == "model_overloaded"
        assert "temporarily busy" in (detail.get("message") or "").lower()
    else:
        assert "model_overloaded" in str(detail) or "temporarily" in str(detail).lower()


def test_chat_business_404_when_business_not_found(client, mock_jwks, create_test_token):
    """Chat returns 404 when business_id does not exist."""
    token = create_test_token(sub=TEST_SUPABASE_UID_1)
    client.get("/api/v1/me", headers={"Authorization": f"Bearer {token}"})
    fake_uuid = "550e8400-e29b-41d4-a716-446655440099"
    resp = client.post(
        f"/api/v1/chat/business/{fake_uuid}",
        headers={"Authorization": f"Bearer {token}"},
        json={"user_message": "Hi"},
    )
    assert resp.status_code == 404


def test_chat_business_401_without_auth(client, db_session):
    """Chat returns 401 or 403 when no Bearer token is provided (auth required)."""
    business = Business(
        name="Test",
        provider="google",
        provider_place_id="ChIJ-401",
    )
    db_session.add(business)
    db_session.commit()
    db_session.refresh(business)

    resp = client.post(
        f"/api/v1/chat/business/{business.id}",
        json={"user_message": "Hi"},
    )
    assert resp.status_code in (401, 403)


def test_chat_business_with_distance_miles_injects_into_prompt(
    client, db_session, mock_jwks, create_test_token
):
    """
    When request includes distance_miles, the user content passed to Gemini
    contains the context JSON with distance_miles and user_distance_note in business.
    """
    token = create_test_token(sub=TEST_SUPABASE_UID_1)
    r_me = client.get("/api/v1/me", headers={"Authorization": f"Bearer {token}"})
    r_me.raise_for_status()
    user_id = r_me.json()["id"]
    user = db_session.query(User).filter(User.id == UUID(user_id)).first()
    user.onboarding_preferences = {"budget": "mid"}
    user.onboarding_completed_at = datetime.now(timezone.utc)
    db_session.commit()

    business = Business(
        name="Test Restaurant",
        provider="google",
        provider_place_id="ChIJ-dist-123",
        ai_context={"summary": "Great spot"},
        ai_notes="Popular for brunch.",
    )
    db_session.add(business)
    db_session.commit()
    db_session.refresh(business)

    with patch("app.routers.chat.generate_business_chat_with_search") as mock_gen:
        mock_gen.return_value = "About 1.3 miles from you."
        resp = client.post(
            f"/api/v1/chat/business/{business.id}",
            headers={"Authorization": f"Bearer {token}"},
            json={"user_message": "How far away is this place?", "distance_miles": 1.3},
        )

    assert resp.status_code == 200
    assert resp.json()["assistant_message"] == "About 1.3 miles from you."

    mock_gen.assert_called_once()
    call_kwargs = mock_gen.call_args[1]
    user_content = call_kwargs["messages"][0]["content"]
    # Context is in user content (messages[0].content), not system instruction
    assert "Context (JSON):" in user_content
    assert '"distance_miles": 1.3' in user_content
    assert "user_distance_note" in user_content
    assert "approximately 1.3 miles" in user_content


def test_chat_business_without_distance_miles_works_and_omits_distance(
    client, db_session, mock_jwks, create_test_token
):
    """
    When request omits distance_miles, endpoint returns 200 and the context
    in user content does not include distance_miles in the business object.
    """
    token = create_test_token(sub=TEST_SUPABASE_UID_1)
    r_me = client.get("/api/v1/me", headers={"Authorization": f"Bearer {token}"})
    r_me.raise_for_status()
    user_id = r_me.json()["id"]
    user = db_session.query(User).filter(User.id == UUID(user_id)).first()
    user.onboarding_preferences = {}
    user.onboarding_completed_at = datetime.now(timezone.utc)
    db_session.commit()

    business = Business(
        name="Test Place",
        provider="google",
        provider_place_id="ChIJ-nodist",
        ai_context={"summary": "Nice"},
    )
    db_session.add(business)
    db_session.commit()
    db_session.refresh(business)

    with patch("app.routers.chat.generate_business_chat_with_search") as mock_gen:
        mock_gen.return_value = "I don't have information about your distance."
        resp = client.post(
            f"/api/v1/chat/business/{business.id}",
            headers={"Authorization": f"Bearer {token}"},
            json={"user_message": "How far is it?"},
        )

    assert resp.status_code == 200
    mock_gen.assert_called_once()
    call_kwargs = mock_gen.call_args[1]
    user_content = call_kwargs["messages"][0]["content"]
    # Context is in user content; business object should not have distance_miles when not requested
    assert "Context (JSON):" in user_content
    # When distance_miles is omitted, build_business_chat_context does not add distance_miles to business
    assert '"distance_miles"' not in user_content
