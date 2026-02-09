"""Tests for places router, including _upsert_business_from_place, GET /details, and GET /nearby."""

from datetime import datetime, timezone
from unittest.mock import AsyncMock, MagicMock, patch

import pytest
from fastapi import status

from app.core.auth import get_current_user
from app.main import app
from app.models.business import Business
from app.models.user import User
from app.routers.places import (
    _upsert_business_from_place,
    PREWARM_CAP,
)


def _minimal_place_result(place_id: str, name: str = "Test Place", with_photos: bool = False) -> dict:
    """Minimal Google Place Details-style result for testing."""
    out = {
        "place_id": place_id,
        "name": name,
        "formatted_address": "123 Test St, City",
        "geometry": {"location": {"lat": 40.7, "lng": -73.9}},
        "address_components": [],
        "types": ["restaurant"],
    }
    if with_photos:
        out["photos"] = [{"photo_reference": "ref_abc123"}]
    return out


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


def test_place_details_when_ai_fresh_returns_ready_and_includes_ai(client, db_session):
    """
    When business already has fresh ai_notes and ai_context (TTL < 24h),
    GET /places/details returns ai_status="ready" and includes ai_notes and ai_context;
    no background task is scheduled.
    """
    place_id = "ChIJtest123"
    minimal_result = _minimal_place_result(place_id, name="Papa Johns Pizza")
    fixed_ai_context = {
        "summary": "Test summary for Papa Johns.",
        "pros": ["Good for groups", "Fast delivery"],
        "cons": [],
        "best_for_user_profile": "Great for casual groups.",
        "vibe": "Casual",
        "reliability_notes": "Based on Google reviews.",
        "source_notes": "Google Place details and reviews.",
    }

    # Pre-seed business with fresh AI data
    business = _upsert_business_from_place(db_session, place_id, minimal_result)
    business.ai_notes = "Test ai notes"
    business.ai_context = fixed_ai_context
    business.ai_context_last_updated = datetime.now(timezone.utc)
    db_session.commit()
    db_session.refresh(business)

    mock_user = MagicMock(spec=User)
    mock_user.id = None
    mock_user.onboarding_completed_at = datetime.now(timezone.utc)
    mock_user.onboarding_preferences = {"diet": "vegetarian"}
    app.dependency_overrides[get_current_user] = lambda: mock_user

    try:
        with (
            patch(
                "app.routers.places._call_google_api",
                new_callable=AsyncMock,
                return_value={"status": "OK", "result": minimal_result},
            ),
            patch(
                "app.routers.places.generate_and_save_business_ai_insights",
            ) as mock_save_insights,
        ):
            response = client.get(f"/api/v1/places/details?place_id={place_id}")
        mock_save_insights.assert_not_called()
    finally:
        app.dependency_overrides.pop(get_current_user, None)

    assert response.status_code == status.HTTP_200_OK
    data = response.json()
    assert data.get("ai_status") == "ready"
    assert data["result"]["provider_place_id"] == place_id
    assert data["business_id"] is not None
    assert data["ai_context"] == fixed_ai_context
    assert data["result"]["ai_notes"] == "Test ai notes"
    assert data["result"]["ai_context"] == fixed_ai_context


def test_place_details_when_ai_missing_returns_pending_and_schedules_background_task(client, db_session):
    """
    When ai_notes/context are missing, GET /places/details returns quickly with ai_status="pending",
    includes all non-AI business details, and schedules generate_and_save_business_ai_insights.
    (TestClient runs background tasks after response, so we assert the mock was called.)
    """
    place_id = "ChIJpending123"
    minimal_result = _minimal_place_result(place_id, name="Place Pending AI")

    mock_user = MagicMock(spec=User)
    mock_user.id = None
    mock_user.onboarding_completed_at = datetime.now(timezone.utc)
    mock_user.onboarding_preferences = None
    app.dependency_overrides[get_current_user] = lambda: mock_user

    try:
        with (
            patch(
                "app.routers.places._call_google_api",
                new_callable=AsyncMock,
                return_value={"status": "OK", "result": minimal_result},
            ),
            patch(
                "app.routers.places.generate_and_save_business_ai_insights",
            ) as mock_save_insights,
        ):
            response = client.get(f"/api/v1/places/details?place_id={place_id}")
        # Background tasks run synchronously in TestClient
        mock_save_insights.assert_called_once()
        call_args = mock_save_insights.call_args[0]
        assert call_args[1] == minimal_result
    finally:
        app.dependency_overrides.pop(get_current_user, None)

    assert response.status_code == status.HTTP_200_OK
    data = response.json()
    assert data.get("ai_status") == "pending"
    assert data["result"]["provider_place_id"] == place_id
    assert data["result"]["name"] == "Place Pending AI"
    assert data["business_id"] is not None


def test_place_details_returns_200_with_pending_when_no_ai_data(client, db_session):
    """
    GET /places/details when business has no AI data returns 200 with place details
    and ai_status="pending"; background task is scheduled (mock prevents real LLM call).
    """
    place_id = "ChIJnone123"
    minimal_result = _minimal_place_result(place_id, name="Place No AI")

    mock_user = MagicMock(spec=User)
    mock_user.id = None
    mock_user.onboarding_completed_at = datetime.now(timezone.utc)
    mock_user.onboarding_preferences = None
    app.dependency_overrides[get_current_user] = lambda: mock_user

    try:
        with (
            patch(
                "app.routers.places._call_google_api",
                new_callable=AsyncMock,
                return_value={"status": "OK", "result": minimal_result},
            ),
            patch("app.routers.places.generate_and_save_business_ai_insights"),
        ):
            response = client.get(f"/api/v1/places/details?place_id={place_id}")
    finally:
        app.dependency_overrides.pop(get_current_user, None)

    assert response.status_code == status.HTTP_200_OK
    data = response.json()
    assert data["result"]["provider_place_id"] == place_id
    assert data["result"]["name"] == "Place No AI"
    assert data.get("ai_status") == "pending"
    assert data.get("ai_context") is None


# --- GET /places/nearby: arbitrary coordinates and validation ---


def _complete_onboarding(client, token):
    """Ensure user exists and has completed onboarding so /places/nearby is allowed."""
    client.get("/api/v1/me", headers={"Authorization": f"Bearer {token}"})
    client.put(
        "/api/v1/me/onboarding",
        headers={"Authorization": f"Bearer {token}"},
        json={"answers": {"diet": "vegetarian", "step": 1}},
    )


def test_places_nearby_rejects_invalid_lat(client, mock_jwks, create_test_token):
    """GET /places/nearby with lat outside [-90, 90] returns 422."""
    token = create_test_token(sub="550e8400-e29b-41d4-a716-4466554400c1", email="invalid_lat@example.com")
    _complete_onboarding(client, token)
    response = client.get(
        "/api/v1/places/nearby",
        params={"lat": 91.0, "lng": 0.0},
        headers={"Authorization": f"Bearer {token}"},
    )
    assert response.status_code == status.HTTP_422_UNPROCESSABLE_ENTITY
    detail = response.json().get("detail", [])
    assert any(
        "latitude" in str(d).lower() or "lat" in str(d).lower()
        for d in (detail if isinstance(detail, list) else [detail])
    )


def test_places_nearby_rejects_invalid_lng(client, mock_jwks, create_test_token):
    """GET /places/nearby with lng outside [-180, 180] returns 422."""
    token = create_test_token(sub="550e8400-e29b-41d4-a716-4466554400c2", email="invalid_lng@example.com")
    _complete_onboarding(client, token)
    response = client.get(
        "/api/v1/places/nearby",
        params={"lat": 0.0, "lng": 181.0},
        headers={"Authorization": f"Bearer {token}"},
    )
    assert response.status_code == status.HTTP_422_UNPROCESSABLE_ENTITY
    detail = response.json().get("detail", [])
    assert any(
        "longitude" in str(d).lower() or "lng" in str(d).lower()
        for d in (detail if isinstance(detail, list) else [detail])
    )


def test_places_nearby_accepts_valid_coordinates_and_passes_to_google(client, mock_jwks, create_test_token):
    """
    GET /places/nearby with valid lat/lng returns 200 and passes the same coordinates
    to the Google API (generic behavior for any location, e.g. Discover or Change location).
    """
    token = create_test_token(sub="550e8400-e29b-41d4-a716-4466554400c3", email="nearby_ok@example.com")
    _complete_onboarding(client, token)

    with patch(
        "app.routers.places._call_google_api",
        new_callable=AsyncMock,
        return_value={"status": "OK", "results": []},
    ) as mock_api:
        response = client.get(
            "/api/v1/places/nearby",
            params={"lat": 40.7128, "lng": -74.0060, "radius": 2000},
            headers={"Authorization": f"Bearer {token}"},
        )
    assert response.status_code == status.HTTP_200_OK
    assert response.json().get("results") == []
    mock_api.assert_called_once()
    call_args = mock_api.call_args[0]
    params = call_args[1]
    assert params.get("location") == "40.7128,-74.006"  # float may drop trailing zero
    assert params.get("radius") == 2000


def test_places_nearby_different_coordinates_produce_different_results(client, mock_jwks, create_test_token):
    """
    Different lat/lng values result in different location params passed to Google,
    so the Discover feed can be refreshed for a new location (e.g. Change location).
    """
    token = create_test_token(sub="550e8400-e29b-41d4-a716-4466554400c4", email="diff_coords@example.com")
    _complete_onboarding(client, token)

    def make_mock_results(lat: float, lng: float):
        """Return one fake result with name indicating the requested location."""
        return {
            "status": "OK",
            "results": [
                {
                    "place_id": f"place_{lat}_{lng}",
                    "name": f"Place at {lat},{lng}",
                    "vicinity": "123 Test St",
                    "geometry": {"location": {"lat": lat, "lng": lng}},
                    "types": ["restaurant"],
                }
            ],
        }

    with patch("app.routers.places._call_google_api", new_callable=AsyncMock) as mock_api:
        mock_api.side_effect = [
            make_mock_results(40.7128, -74.0060),   # NYC
            make_mock_results(51.5074, -0.1278),   # London
        ]
        nyc = client.get(
            "/api/v1/places/nearby",
            params={"lat": 40.7128, "lng": -74.0060},
            headers={"Authorization": f"Bearer {token}"},
        )
        london = client.get(
            "/api/v1/places/nearby",
            params={"lat": 51.5074, "lng": -0.1278},
            headers={"Authorization": f"Bearer {token}"},
        )
    assert nyc.status_code == status.HTTP_200_OK
    assert london.status_code == status.HTTP_200_OK
    assert nyc.json()["results"][0]["name"] == "Place at 40.7128,-74.006"  # float may drop trailing zero
    assert london.json()["results"][0]["name"] == "Place at 51.5074,-0.1278"
    assert mock_api.call_count == 2
    locations_called = [
        mock_api.call_args_list[i][0][1]["location"]
        for i in range(2)
    ]
    assert "40.7128,-74.006" in locations_called[0]
    assert "51.5074,-0.1278" in locations_called[1]


def test_places_nearby_schedules_prewarm_when_results_returned(client, mock_jwks, create_test_token):
    """When nearby returns places, prewarm_insights_for_places is called with those results (non-blocking)."""
    token = create_test_token(sub="550e8400-e29b-41d4-a716-4466554400c5", email="prewarm@example.com")
    _complete_onboarding(client, token)

    raw = {
        "status": "OK",
        "results": [
            {"place_id": "pid_1", "name": "Place 1", "vicinity": "Addr 1", "geometry": {"location": {"lat": 40.7, "lng": -74.0}}, "types": ["cafe"]},
            {"place_id": "pid_2", "name": "Place 2", "vicinity": "Addr 2", "geometry": {"location": {"lat": 40.71, "lng": -74.01}}, "types": ["cafe"]},
        ],
    }

    with (
        patch("app.routers.places._call_google_api", new_callable=AsyncMock, return_value=raw),
        patch("app.routers.places.prewarm_insights_for_places") as mock_prewarm,
    ):
        response = client.get(
            "/api/v1/places/nearby",
            params={"lat": 40.7128, "lng": -74.0060},
            headers={"Authorization": f"Bearer {token}"},
        )
    assert response.status_code == status.HTTP_200_OK
    mock_prewarm.assert_called_once()
    call_args = mock_prewarm.call_args[0]
    assert call_args[1]  # places list
    assert len(call_args[1]) == 2
    assert call_args[1][0].provider_place_id == "pid_1"
    assert call_args[1][1].provider_place_id == "pid_2"


def test_places_nearby_prewarm_capped(client, mock_jwks, create_test_token):
    """When nearby returns more than PREWARM_CAP places, _prewarm_ai_insights_for_place_ids receives only PREWARM_CAP."""
    token = create_test_token(sub="550e8400-e29b-41d4-a716-4466554400c6", email="cap@example.com")
    _complete_onboarding(client, token)

    n = PREWARM_CAP + 5
    raw = {
        "status": "OK",
        "results": [
            {
                "place_id": f"pid_{i}",
                "name": f"Place {i}",
                "vicinity": "Addr",
                "geometry": {"location": {"lat": 40.7, "lng": -74.0}},
                "types": ["cafe"],
            }
            for i in range(n)
        ],
    }

    with (
        patch("app.routers.places._call_google_api", new_callable=AsyncMock, return_value=raw),
        patch("app.routers.places._prewarm_ai_insights_for_place_ids") as mock_task,
    ):
        response = client.get(
            "/api/v1/places/nearby",
            params={"lat": 40.7128, "lng": -74.0060},
            headers={"Authorization": f"Bearer {token}"},
        )
    assert response.status_code == status.HTTP_200_OK
    mock_task.assert_called_once()
    place_ids = mock_task.call_args[0][0]
    assert len(place_ids) == PREWARM_CAP
    assert place_ids[0] == "pid_0"


def test_upsert_business_from_place_persists_photo(db_session):
    """When place result has photos, upsert persists photo_reference and photo_url."""
    place_id = "ChIJ-photo-test"
    result = _minimal_place_result(place_id, name="Photo Place", with_photos=True)
    business = _upsert_business_from_place(db_session, place_id, result)
    assert business.photo_reference == "ref_abc123"
    assert business.photo_url is not None
    assert "photo_reference=ref_abc123" in business.photo_url or "ref_abc123" in business.photo_url


def test_prewarm_skips_business_with_fresh_ai(db_session):
    """When a business already has fresh ai_context, _prewarm_ai_insights_for_place_ids does not call generate_and_save."""
    from app.routers.places import _prewarm_ai_insights_for_place_ids

    place_id = "ChIJ-fresh-ai"
    result = _minimal_place_result(place_id, name="Fresh AI Place")
    business = _upsert_business_from_place(db_session, place_id, result)
    business.ai_notes = "Cached notes"
    business.ai_context = {"summary": "Cached"}
    business.ai_context_last_updated = datetime.now(timezone.utc)
    db_session.commit()
    db_session.refresh(business)

    with (
        patch("app.db.session.SessionLocal", return_value=db_session),
        patch.object(db_session, "close"),
        patch("app.routers.places._fetch_place_details_sync", return_value={"status": "OK", "result": result}),
        patch("app.routers.places.generate_and_save_business_ai_insights") as mock_save,
    ):
        _prewarm_ai_insights_for_place_ids([place_id])

    mock_save.assert_not_called()
