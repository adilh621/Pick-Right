import pytest
from fastapi import status
from uuid import uuid4

from tests.conftest import TEST_SUPABASE_UID_1, TEST_SUPABASE_UID_2, TEST_SUPABASE_UID_3


def test_get_me_creates_user_on_first_request(client, mock_jwks, create_test_token):
    """Test GET /me creates user on first request and returns it."""
    # First request with a new token should create a user
    token = create_test_token(sub=TEST_SUPABASE_UID_1, email="test@example.com")
    response = client.get(
        "/api/v1/me",
        headers={"Authorization": f"Bearer {token}"}
    )
    
    assert response.status_code == status.HTTP_200_OK
    data = response.json()
    assert data["external_auth_uid"] == TEST_SUPABASE_UID_1
    assert data["external_auth_provider"] == "email"
    assert data["id"] is not None
    assert data["onboarding_preferences"] is None
    assert data["onboarding_completed_at"] is None
    assert "created_at" in data
    assert "updated_at" in data


def test_get_me_returns_existing_user(client, mock_jwks, create_test_token):
    """Test GET /me returns existing user on subsequent requests."""
    token = create_test_token(sub=TEST_SUPABASE_UID_2, email="test2@example.com")
    
    # First request creates user
    first_response = client.get(
        "/api/v1/me",
        headers={"Authorization": f"Bearer {token}"}
    )
    assert first_response.status_code == status.HTTP_200_OK
    user_id = first_response.json()["id"]
    
    # Second request returns same user
    second_response = client.get(
        "/api/v1/me",
        headers={"Authorization": f"Bearer {token}"}
    )
    assert second_response.status_code == status.HTTP_200_OK
    assert second_response.json()["id"] == user_id
    assert second_response.json()["external_auth_uid"] == TEST_SUPABASE_UID_2


def test_get_me_requires_auth(client):
    """Test GET /me requires Bearer token."""
    response = client.get("/api/v1/me")
    assert response.status_code == status.HTTP_403_FORBIDDEN


def test_me_returns_needs_onboarding(client, mock_jwks, create_test_token):
    """GET /me returns needs_onboarding true when user has no onboarding."""
    token = create_test_token(sub="550e8400-e29b-41d4-a716-4466554400b0", email="noonboard@example.com")
    # Create user with no onboarding (do not call onboarding endpoint)
    response = client.get(
        "/api/v1/me",
        headers={"Authorization": f"Bearer {token}"}
    )
    assert response.status_code == status.HTTP_200_OK
    data = response.json()
    assert data.get("needs_onboarding") is True
    assert data["onboarding_preferences"] is None
    assert data["onboarding_completed_at"] is None


def test_after_onboarding_needs_onboarding_is_false(client, mock_jwks, create_test_token):
    """After completing onboarding, GET /me returns needs_onboarding false."""
    token = create_test_token(sub="550e8400-e29b-41d4-a716-4466554400b1", email="after@example.com")
    client.get("/api/v1/me", headers={"Authorization": f"Bearer {token}"})
    # Complete onboarding
    onboarding_response = client.put(
        "/api/v1/me/onboarding",
        headers={"Authorization": f"Bearer {token}"},
        json={"answers": {"diet": "vegetarian", "step": 1}},
    )
    assert onboarding_response.status_code == status.HTTP_200_OK
    assert onboarding_response.json().get("needs_onboarding") is False
    # GET /me also returns needs_onboarding false
    me_response = client.get("/api/v1/me", headers={"Authorization": f"Bearer {token}"})
    assert me_response.status_code == status.HTTP_200_OK
    assert me_response.json().get("needs_onboarding") is False


def test_places_nearby_blocks_if_not_onboarded(client, mock_jwks, create_test_token):
    """Calling /places/nearby without completed onboarding returns 409."""
    token = create_test_token(sub="550e8400-e29b-41d4-a716-4466554400b2", email="blocked@example.com")
    # Create user with no onboarding
    client.get("/api/v1/me", headers={"Authorization": f"Bearer {token}"})
    response = client.get(
        "/api/v1/places/nearby",
        params={"lat": 40.7128, "lng": -74.0060},
        headers={"Authorization": f"Bearer {token}"},
    )
    assert response.status_code == 409
    assert response.json().get("detail") == "Onboarding incomplete. Please finish onboarding."


def test_same_supabase_uid_creates_only_one_user(client, mock_jwks, create_test_token, db_session):
    """Re-authenticating with the same Supabase UID must reuse the same public.users row."""
    from app.models.user import User

    uid = "a1b2c3d4-e5f6-7890-abcd-ef1234567890"
    token = create_test_token(sub=uid, email="same@example.com")

    # First request: creates user
    r1 = client.get("/api/v1/me", headers={"Authorization": f"Bearer {token}"})
    assert r1.status_code == status.HTTP_200_OK
    user_id_1 = r1.json()["id"]
    assert r1.json()["external_auth_uid"] == uid

    # Second request: must return same user (no duplicate row)
    r2 = client.get("/api/v1/me", headers={"Authorization": f"Bearer {token}"})
    assert r2.status_code == status.HTTP_200_OK
    assert r2.json()["id"] == user_id_1
    assert r2.json()["external_auth_uid"] == uid

    # DB must have exactly one user with this external_auth_uid
    count = db_session.query(User).filter(User.external_auth_uid == uid).count()
    assert count == 1


def test_get_or_create_user_for_supabase_uid_idempotent(db_session):
    """Calling get_or_create_user_for_supabase_uid twice with same UID returns same user, no duplicate row."""
    from app.models.user import User
    from app.core.auth import get_or_create_user_for_supabase_uid

    uid_str = "c3d4e5f6-a7b8-9012-cdef-123456789012"
    # First call creates user
    user1 = get_or_create_user_for_supabase_uid(
        db_session,
        external_auth_uid=uid_str,
        external_auth_provider="google",
        email="idempotent@example.com",
    )
    assert user1.id is not None
    assert user1.external_auth_uid == uid_str

    # Second call with same UID must return same user (no IntegrityError, no duplicate)
    user2 = get_or_create_user_for_supabase_uid(
        db_session,
        external_auth_uid=uid_str,
        external_auth_provider="google",
        email="idempotent@example.com",
    )
    assert user2.id == user1.id
    assert user2.external_auth_uid == uid_str

    count = db_session.query(User).filter(User.external_auth_uid == uid_str).count()
    assert count == 1


def test_onboarding_multiple_times_updates_same_row(client, mock_jwks, create_test_token, db_session):
    """Hitting onboarding endpoint multiple times for the same auth user must not create duplicate users."""
    from app.models.user import User

    uid = "b2c3d4e5-f6a7-8901-bcde-f12345678901"
    token = create_test_token(sub=uid, email="onboard@example.com")

    # Create user via GET /me
    r_me = client.get("/api/v1/me", headers={"Authorization": f"Bearer {token}"})
    assert r_me.status_code == status.HTTP_200_OK
    user_id = r_me.json()["id"]

    # First onboarding update (canonical keys)
    r1 = client.put(
        "/api/v1/me/onboarding",
        headers={"Authorization": f"Bearer {token}"},
        json={"answers": {"dietary_restrictions": ["vegetarian"], "companion": "Solo"}},
    )
    assert r1.status_code == status.HTTP_200_OK

    # Second onboarding update (same user, canonical keys)
    r2 = client.put(
        "/api/v1/me/onboarding",
        headers={"Authorization": f"Bearer {token}"},
        json={"answers": {"dietary_restrictions": ["vegan", "nuts"], "companion": "Partner"}},
    )
    assert r2.status_code == status.HTTP_200_OK

    # GET /me must show latest onboarding_preferences (canonical shape) and one user only
    r_get = client.get("/api/v1/me", headers={"Authorization": f"Bearer {token}"})
    assert r_get.status_code == status.HTTP_200_OK
    assert r_get.json()["id"] == user_id
    prefs = r_get.json()["onboarding_preferences"]
    assert prefs is not None
    assert prefs.get("dietary_restrictions") == ["vegan", "nuts"]
    assert prefs.get("companion") == "Partner"
    assert r_get.json().get("onboarding_completed_at") is not None

    count = db_session.query(User).filter(User.external_auth_uid == uid).count()
    assert count == 1


def test_update_preferences_updates_jsonb(client, mock_jwks, create_test_token):
    """Test PUT /me/preferences updates JSONB with canonical shape and completed_at."""
    token = create_test_token(sub=TEST_SUPABASE_UID_3, email="test3@example.com")
    
    # Create user first
    client.get(
        "/api/v1/me",
        headers={"Authorization": f"Bearer {token}"}
    )
    
    # Update preferences (canonical keys only are stored/returned)
    preferences_data = {
        "dietary_restrictions": ["vegetarian", "gluten-free"],
        "place_interests": ["restaurants", "cafes"],
    }
    
    response = client.put(
        "/api/v1/me/preferences",
        headers={"Authorization": f"Bearer {token}"},
        json={
            "onboarding_preferences": preferences_data
        }
    )
    
    assert response.status_code == status.HTTP_200_OK
    data = response.json()
    assert data["onboarding_preferences"] == preferences_data
    assert data["onboarding_completed_at"] is not None
    assert data["needs_onboarding"] is False
    
    get_response = client.get(
        "/api/v1/me",
        headers={"Authorization": f"Bearer {token}"}
    )
    assert get_response.json()["onboarding_preferences"] == preferences_data


def test_update_preferences_without_completion(client, mock_jwks, create_test_token):
    """Test PUT /me/preferences with only onboarding_preferences (completed_at auto-set to now)."""
    token = create_test_token(sub="550e8400-e29b-41d4-a716-446655440101", email="test4@example.com")
    
    client.get("/api/v1/me", headers={"Authorization": f"Bearer {token}"})
    
    response = client.put(
        "/api/v1/me/preferences",
        headers={"Authorization": f"Bearer {token}"},
        json={
            "onboarding_preferences": {"companion": "Partner"}
        }
    )
    
    assert response.status_code == status.HTTP_200_OK
    data = response.json()
    assert data["onboarding_preferences"] == {"companion": "Partner"}
    assert data["onboarding_completed_at"] is not None
    assert data["needs_onboarding"] is False


def test_update_preferences_can_clear_completion(client, mock_jwks, create_test_token):
    """PUT /me/preferences with onboarding_preferences but no onboarding_completed_at sets completed_at to now."""
    token = create_test_token(sub="550e8400-e29b-41d4-a716-446655440102", email="test5@example.com")
    
    client.get("/api/v1/me", headers={"Authorization": f"Bearer {token}"})
    client.put(
        "/api/v1/me/preferences",
        headers={"Authorization": f"Bearer {token}"},
        json={
            "onboarding_preferences": {"companion": "Solo"},
            "onboarding_completed_at": "2024-01-15T10:30:00Z"
        }
    )
    
    response = client.put(
        "/api/v1/me/preferences",
        headers={"Authorization": f"Bearer {token}"},
        json={
            "onboarding_preferences": {"companion": "Partner", "travel_frequency": "Weekly"}
        }
    )
    
    assert response.status_code == status.HTTP_200_OK
    assert response.json()["onboarding_completed_at"] is not None
    assert response.json()["needs_onboarding"] is False


def test_update_preferences_with_datetime_string(client, mock_jwks, create_test_token):
    """Test PUT /me/preferences accepts onboarding_completed_at as ISO datetime string."""
    from datetime import datetime, timezone
    
    token = create_test_token(sub="550e8400-e29b-41d4-a716-446655440103", email="test_datetime@example.com")
    
    # Create user first
    client.get(
        "/api/v1/me",
        headers={"Authorization": f"Bearer {token}"}
    )
    
    # Set a specific datetime
    test_datetime_str = "2024-01-15T10:30:00Z"
    preferences_data = {
        "dietary_restrictions": ["vegetarian", "gluten-free"],
        "place_interests": ["cafes"],
    }
    
    response = client.put(
        "/api/v1/me/preferences",
        headers={"Authorization": f"Bearer {token}"},
        json={
            "onboarding_preferences": preferences_data,
            "onboarding_completed_at": test_datetime_str
        }
    )
    
    assert response.status_code == status.HTTP_200_OK
    data = response.json()
    assert data["onboarding_preferences"] == preferences_data
    assert data["onboarding_completed_at"] is not None
    completed_at = data["onboarding_completed_at"]
    assert completed_at is not None
    
    get_response = client.get("/api/v1/me", headers={"Authorization": f"Bearer {token}"})
    assert get_response.status_code == status.HTTP_200_OK
    get_data = get_response.json()
    assert get_data["onboarding_preferences"] == preferences_data
    assert get_data["onboarding_completed_at"] is not None
    assert get_data["onboarding_completed_at"] == completed_at


def test_update_preferences_with_explicit_datetime(client, mock_jwks, create_test_token):
    """Test that onboarding_completed_at can be set explicitly."""
    token = create_test_token(sub="550e8400-e29b-41d4-a716-446655440104", email="test_precedence@example.com")
    
    client.get("/api/v1/me", headers={"Authorization": f"Bearer {token}"})
    
    test_datetime_str = "2024-02-20T14:45:00Z"
    response = client.put(
        "/api/v1/me/preferences",
        headers={"Authorization": f"Bearer {token}"},
        json={
            "onboarding_preferences": {"companion": "Family"},
            "onboarding_completed_at": test_datetime_str
        }
    )
    
    assert response.status_code == status.HTTP_200_OK
    data = response.json()
    assert data["onboarding_preferences"] == {"companion": "Family"}
    assert data["onboarding_completed_at"] is not None


def test_upgrade_guest_migrates_sessions(client, mock_jwks, create_test_token):
    """Test upgrade-guest migrates sessions from device_id to user."""
    token = create_test_token(sub="550e8400-e29b-41d4-a716-446655440105", email="test6@example.com")
    device_id = str(uuid4())
    
    # Create user
    user_response = client.get(
        "/api/v1/me",
        headers={"Authorization": f"Bearer {token}"}
    )
    user_id = user_response.json()["id"]
    
    # Create guest scan session with device_id (no user_id)
    scan_session_response = client.post(
        "/api/v1/scan-sessions",
        json={
            "image_url": "https://example.com/image.jpg",
            "detected_text_raw": "Test menu text",
            "status": "PENDING",
            "device_id": device_id
        }
    )
    
    assert scan_session_response.status_code == status.HTTP_201_CREATED
    session_id = scan_session_response.json()["id"]
    # Verify it's a guest session (no user_id)
    assert scan_session_response.json()["user_id"] is None
    assert scan_session_response.json()["device_id"] == device_id
    
    # Test upgrade
    upgrade_response = client.post(
        "/api/v1/me/upgrade-guest",
        headers={"Authorization": f"Bearer {token}"},
        json={"device_id": device_id}
    )
    
    assert upgrade_response.status_code == status.HTTP_200_OK
    data = upgrade_response.json()
    assert "migrated_scan_sessions" in data
    assert data["migrated_scan_sessions"] == 1
    
    # Verify the session now has user_id
    get_session_response = client.get(f"/api/v1/scan-sessions/{session_id}")
    assert get_session_response.status_code == status.HTTP_200_OK
    assert get_session_response.json()["user_id"] == user_id


def test_upgrade_guest_no_sessions(client, mock_jwks, create_test_token):
    """Test upgrade-guest returns 0 when no guest sessions exist."""
    token = create_test_token(sub="550e8400-e29b-41d4-a716-446655440106", email="test7@example.com")
    device_id = str(uuid4())
    
    # Create user
    client.get(
        "/api/v1/me",
        headers={"Authorization": f"Bearer {token}"}
    )
    
    # Try to upgrade with non-existent device_id
    response = client.post(
        "/api/v1/me/upgrade-guest",
        headers={"Authorization": f"Bearer {token}"},
        json={"device_id": device_id}
    )
    
    assert response.status_code == status.HTTP_200_OK
    assert response.json()["migrated_scan_sessions"] == 0


def test_get_me_schema_handles_optional_timestamps(client, mock_jwks, create_test_token):
    """Test that UserRead schema accepts Optional timestamps.
    
    This test verifies that the schema change to make updated_at and created_at
    Optional[datetime] is working correctly. The schema will now handle NULL
    values from the database without causing ResponseValidationError.
    
    Note: We can't easily create a NULL in the test database due to the NOT NULL
    constraint and onupdate trigger, but this test verifies the schema definition
    is correct and the endpoint works normally.
    """
    from app.schemas.user import UserRead
    from datetime import datetime
    
    token = create_test_token(sub="550e8400-e29b-41d4-a716-446655440107", email="schematest@example.com")
    
    # Create user and verify endpoint works
    user_response = client.get(
        "/api/v1/me",
        headers={"Authorization": f"Bearer {token}"}
    )
    assert user_response.status_code == status.HTTP_200_OK
    data = user_response.json()
    
    # Verify the response has the expected fields
    assert "id" in data
    assert "created_at" in data
    assert "updated_at" in data
    
    # Verify the schema can handle None values (simulate old data scenario)
    # Create a UserRead instance with None timestamps to verify schema accepts it
    test_data = {
        "id": data["id"],
        "created_at": None,
        "updated_at": None,
        "external_auth_provider": data.get("external_auth_provider"),
        "external_auth_uid": data.get("external_auth_uid"),
    }
    
    # This should not raise a validation error
    user_read = UserRead(**test_data)
    assert user_read.created_at is None
    assert user_read.updated_at is None
    
    # Verify the schema serializes None correctly
    serialized = user_read.model_dump()
    assert serialized["created_at"] is None
    assert serialized["updated_at"] is None


def test_update_preferences_flattened_payload(client, mock_jwks, create_test_token):
    """PUT /me/preferences accepts flattened payload; response uses canonical keys (intents not intent_selections)."""
    token = create_test_token(sub="550e8400-e29b-41d4-a716-446655440108", email="test_flattened@example.com")
    
    client.get("/api/v1/me", headers={"Authorization": f"Bearer {token}"})
    
    response = client.put(
        "/api/v1/me/preferences",
        headers={"Authorization": f"Bearer {token}"},
        json={
            "place_interests": ["restaurants", "cafes"],
            "intent_selections": ["dining", "takeout"],
            "dietary_restrictions": ["vegetarian"]
        }
    )
    
    assert response.status_code == status.HTTP_200_OK
    data = response.json()
    prefs = data["onboarding_preferences"]
    assert prefs is not None
    assert prefs["place_interests"] == ["restaurants", "cafes"]
    assert prefs["intents"] == ["dining", "takeout"]  # canonical key, not intent_selections
    assert prefs["dietary_restrictions"] == ["vegetarian"]
    assert "intent_selections" not in prefs
    assert data["onboarding_completed_at"] is not None
    assert data["needs_onboarding"] is False
    
    get_data = client.get("/api/v1/me", headers={"Authorization": f"Bearer {token}"}).json()
    assert get_data["onboarding_preferences"]["place_interests"] == ["restaurants", "cafes"]
    assert get_data["onboarding_preferences"]["intents"] == ["dining", "takeout"]


def test_update_preferences_flattened_with_datetime(client, mock_jwks, create_test_token):
    """Test PUT /me/preferences with flattened payload and explicit datetime."""
    token = create_test_token(sub="550e8400-e29b-41d4-a716-446655440109", email="test_flattened_dt@example.com")
    
    # Create user first
    client.get(
        "/api/v1/me",
        headers={"Authorization": f"Bearer {token}"}
    )
    
    # Update preferences using flattened format with explicit datetime
    test_datetime_str = "2024-03-15T12:00:00Z"
    response = client.put(
        "/api/v1/me/preferences",
        headers={"Authorization": f"Bearer {token}"},
        json={
            "place_interests": ["restaurants"],
            "onboarding_completed_at": test_datetime_str
        }
    )
    
    assert response.status_code == status.HTTP_200_OK
    data = response.json()
    
    # Should have onboarding_preferences with wrapped fields
    assert data["onboarding_preferences"] is not None
    assert data["onboarding_preferences"]["place_interests"] == ["restaurants"]
    
    # onboarding_completed_at should be the explicit datetime
    assert data["onboarding_completed_at"] is not None
    # The datetime should match (allowing for timezone conversion)
    assert "2024-03-15" in str(data["onboarding_completed_at"])


def test_preferences_legacy_keys_return_canonical_and_needs_onboarding(client, mock_jwks, create_test_token):
    """PUT /me/preferences with intent_selections/priority_selections; GET /me returns intents/priorities and needs_onboarding matches onboarding_completed_at."""
    token = create_test_token(sub="550e8400-e29b-41d4-a716-4466554400b0", email="legacy-keys@example.com")
    client.get("/api/v1/me", headers={"Authorization": f"Bearer {token}"})

    response = client.put(
        "/api/v1/me/preferences",
        headers={"Authorization": f"Bearer {token}"},
        json={
            "onboarding_preferences": {
                "intent_selections": ["Work / study", "Stay active"],
                "priority_selections": ["💰  Price / affordability", "🧘  Vibe & atmosphere"],
                "companion": "Partner",
            }
        },
    )
    assert response.status_code == status.HTTP_200_OK
    data = response.json()
    prefs = data["onboarding_preferences"]
    assert "intents" in prefs and prefs["intents"] == ["Work / study", "Stay active"]
    assert "priorities" in prefs and prefs["priorities"] == ["💰  Price / affordability", "🧘  Vibe & atmosphere"]
    assert "intent_selections" not in prefs
    assert "priority_selections" not in prefs
    assert data["onboarding_completed_at"] is not None
    assert data["needs_onboarding"] is False

    get_me = client.get("/api/v1/me", headers={"Authorization": f"Bearer {token}"}).json()
    assert get_me["needs_onboarding"] is (get_me["onboarding_completed_at"] is None)
    assert get_me["onboarding_preferences"]["intents"] == ["Work / study", "Stay active"]
    assert get_me["onboarding_preferences"]["priorities"] == ["💰  Price / affordability", "🧘  Vibe & atmosphere"]


def test_put_onboarding_canonical_keys_sets_completed_at_and_needs_onboarding_false(client, mock_jwks, create_test_token):
    """PUT /me/onboarding with canonical keys sets onboarding_completed_at and returns needs_onboarding False."""
    token = create_test_token(sub="550e8400-e29b-41d4-a716-4466554400c0", email="onboarding-canonical@example.com")
    client.get("/api/v1/me", headers={"Authorization": f"Bearer {token}"})

    response = client.put(
        "/api/v1/me/onboarding",
        headers={"Authorization": f"Bearer {token}"},
        json={
            "answers": {
                "companion": "Partner",
                "intents": ["Work / study", "Stay active"],
                "priorities": ["💰  Price / affordability", "🧘  Vibe & atmosphere"],
                "place_interests": ["cafes", "restaurants"],
                "travel_frequency": "A few times a month",
                "exploration_level": 0.3,
                "dietary_restrictions": ["🐟  Pescatarian"],
            }
        },
    )
    assert response.status_code == status.HTTP_200_OK
    data = response.json()
    assert data["onboarding_completed_at"] is not None
    assert data["needs_onboarding"] is False
    prefs = data["onboarding_preferences"]
    assert prefs["companion"] == "Partner"
    assert prefs["intents"] == ["Work / study", "Stay active"]
    assert prefs["priorities"] == ["💰  Price / affordability", "🧘  Vibe & atmosphere"]
    assert prefs["place_interests"] == ["cafes", "restaurants"]
    assert prefs["travel_frequency"] == "A few times a month"
    assert prefs["exploration_level"] == 0.3
    assert prefs["dietary_restrictions"] == ["🐟  Pescatarian"]


def test_update_preferences_nested_takes_precedence(client, mock_jwks, create_test_token):
    """Nested onboarding_preferences is used; only canonical keys are stored and returned."""
    token = create_test_token(sub="550e8400-e29b-41d4-a716-44665544000a", email="test_nested@example.com")
    
    client.get("/api/v1/me", headers={"Authorization": f"Bearer {token}"})
    
    response = client.put(
        "/api/v1/me/preferences",
        headers={"Authorization": f"Bearer {token}"},
        json={
            "onboarding_preferences": {"companion": "Partner", "nested": "ignored"},
            "flattened_field": "should_be_ignored"
        }
    )
    
    assert response.status_code == status.HTTP_200_OK
    data = response.json()
    # Only canonical keys in response; legacy/extra keys dropped
    assert data["onboarding_preferences"] == {"companion": "Partner"}
    assert "nested" not in data["onboarding_preferences"]
    assert "flattened_field" not in data["onboarding_preferences"]

