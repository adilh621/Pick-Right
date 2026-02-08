"""Tests for AI chat endpoint: context loading and prompt construction."""

import pytest
from datetime import datetime, timezone
from uuid import UUID
from unittest.mock import patch, AsyncMock

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


# --- Main chat (no business_id): location_hint and recommended_places ---


def test_main_chat_with_location_hint_includes_area_in_prompt(client, mock_jwks, create_test_token):
    """Main chat (no business_id) with location_hint passes area to Gemini and returns reply."""
    token = create_test_token()
    client.get("/api/v1/me", headers={"Authorization": f"Bearer {token}"})

    with patch("app.routers.ai.generate_text_with_system") as mock_gen:
        mock_gen.return_value = "Here are some gyms around Queens, NY."
        resp = client.post(
            "/api/v1/ai/chat",
            headers={"Authorization": f"Bearer {token}"},
            json={
                "message": "Find me good gyms near me",
                "location_hint": "Queens, NY",
            },
        )

    assert resp.status_code == 200
    data = resp.json()
    assert data["reply"] == "Here are some gyms around Queens, NY."
    assert mock_gen.called
    call_args = mock_gen.call_args
    system_instruction = call_args[0][1]
    assert "Queens, NY" in system_instruction
    assert "area_hint" in system_instruction or "user_location_context" in system_instruction
    assert data.get("recommended_places") is None


def test_main_chat_without_location_hint_returns_fixed_message_without_calling_gemini(client, mock_jwks, create_test_token):
    """Main chat (no business_id) without location_hint returns no-location message and does not call Gemini."""
    token = create_test_token()
    client.get("/api/v1/me", headers={"Authorization": f"Bearer {token}"})

    with patch("app.routers.ai.generate_text_with_system") as mock_gen:
        resp = client.post(
            "/api/v1/ai/chat",
            headers={"Authorization": f"Bearer {token}"},
            json={"message": "Find me good gyms"},
        )

    assert resp.status_code == 200
    data = resp.json()
    assert "location" in data["reply"].lower()
    assert "don't have your location" in data["reply"] or "setting or changing your location" in data["reply"]
    assert not mock_gen.called


def test_main_chat_empty_location_hint_treated_as_missing(client, mock_jwks, create_test_token):
    """Main chat with location_hint empty string is treated as missing; returns no-location message."""
    token = create_test_token()
    client.get("/api/v1/me", headers={"Authorization": f"Bearer {token}"})

    with patch("app.routers.ai.generate_text_with_system") as mock_gen:
        resp = client.post(
            "/api/v1/ai/chat",
            headers={"Authorization": f"Bearer {token}"},
            json={"message": "Find gyms", "location_hint": ""},
        )

    assert resp.status_code == 200
    assert "location" in resp.json()["reply"].lower()
    assert not mock_gen.called


def test_main_chat_places_query_includes_recommended_places(client, mock_jwks, create_test_token):
    """Place-like query with lat/lng calls Google Places with same radius as /places/nearby and returns recommended_places."""
    from app.services.places_client import DEFAULT_NEARBY_RADIUS_M

    token = create_test_token()
    client.get("/api/v1/me", headers={"Authorization": f"Bearer {token}"})

    lat, lng = 40.7282, -73.7949
    fake_places = [
        {"place_id": "ChIJ-bjj-1", "name": "Queens BJJ"},
        {"place_id": "ChIJ-bjj-2", "name": "Brooklyn Grappling"},
        {"place_id": "ChIJ-bjj-3", "name": "NYC Combat"},
    ]

    with patch("app.routers.ai.generate_text_with_system") as mock_gen:
        mock_gen.return_value = "Here are some BJJ gyms near you. Check the options below."
        with patch("app.routers.ai.search_places_text", new_callable=AsyncMock) as mock_places:
            mock_places.return_value = fake_places
            resp = client.post(
                "/api/v1/ai/chat",
                headers={"Authorization": f"Bearer {token}"},
                json={
                    "message": "What are the best bjj gyms around me?",
                    "location_hint": "Queens, NY",
                    "latitude": lat,
                    "longitude": lng,
                },
            )

    assert resp.status_code == 200
    data = resp.json()
    assert mock_gen.called
    # Places call uses request coords and same default radius as GET /places/nearby
    assert mock_places.called
    call_kw = mock_places.call_args.kwargs
    assert call_kw["query"] == "Brazilian Jiu-Jitsu gym"
    assert call_kw["lat"] == lat
    assert call_kw["lng"] == lng
    assert call_kw["radius_m"] == DEFAULT_NEARBY_RADIUS_M
    assert data["recommended_places"] is not None
    assert len(data["recommended_places"]) == 3
    assert data["recommended_places"][0]["name"] == "Queens BJJ" and data["recommended_places"][0]["place_id"] == "ChIJ-bjj-1"
    assert data["recommended_places"][1]["name"] == "Brooklyn Grappling"
    assert data["recommended_places"][2]["name"] == "NYC Combat"


def test_main_chat_non_place_query_has_no_recommended_places(client, mock_jwks, create_test_token):
    """Non-place question returns no recommended_places even with location."""
    token = create_test_token()
    client.get("/api/v1/me", headers={"Authorization": f"Bearer {token}"})

    with patch("app.routers.ai.generate_text_with_system") as mock_gen:
        mock_gen.return_value = "Sorry, I can only help with places near you."
        resp = client.post(
            "/api/v1/ai/chat",
            headers={"Authorization": f"Bearer {token}"},
            json={
                "message": "What is 2+2?",
                "location_hint": "Queens, NY",
                "latitude": 40.7282,
                "longitude": -73.7949,
            },
        )

    assert resp.status_code == 200
    data = resp.json()
    assert data.get("recommended_places") is None or data.get("recommended_places") == []


def test_main_chat_place_query_without_coords_skips_places_call(client, mock_jwks, create_test_token):
    """When latitude or longitude is missing, we do not call search_places_text."""
    token = create_test_token()
    client.get("/api/v1/me", headers={"Authorization": f"Bearer {token}"})

    with patch("app.routers.ai.generate_text_with_system") as mock_gen:
        mock_gen.return_value = "Here are some cafes to work from."
        with patch("app.routers.ai.search_places_text", new_callable=AsyncMock) as mock_places:
            resp = client.post(
                "/api/v1/ai/chat",
                headers={"Authorization": f"Bearer {token}"},
                json={
                    "message": "Cafes to work from",
                    "location_hint": "Queens, NY",
                    # no latitude / longitude
                },
            )

    assert resp.status_code == 200
    data = resp.json()
    assert mock_gen.called
    assert not mock_places.called
    assert data.get("recommended_places") is None
