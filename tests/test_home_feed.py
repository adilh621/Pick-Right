"""Tests for GET /api/v1/home-feed."""

from datetime import datetime, timezone
from unittest.mock import AsyncMock, MagicMock, patch

import pytest
from fastapi import status

from app.core.auth import get_current_user
from app.main import app
from app.models.business import Business
from app.models.user import User
from app.schemas.places import PlaceResult


def _complete_onboarding(client, token):
    """Ensure user exists and has completed onboarding."""
    client.get("/api/v1/me", headers={"Authorization": f"Bearer {token}"})
    client.put(
        "/api/v1/me/onboarding",
        headers={"Authorization": f"Bearer {token}"},
        json={"answers": {"diet": "vegetarian", "step": 1}},
    )


def test_home_feed_returns_200_and_sections_shape(client, mock_jwks, create_test_token):
    """GET /api/v1/home-feed with valid lat/lng returns 200 and HomeFeedResponse with sections list."""
    token = create_test_token(sub="550e8400-e29b-41d4-a716-4466554400d1", email="homefeed@example.com")
    _complete_onboarding(client, token)

    # Mock nearby to return empty so we don't hit Google; AI-tag sections may be empty
    with patch(
        "app.routers.home._fetch_nearby_places_async",
        new_callable=AsyncMock,
        return_value=([], []),
    ):
        response = client.get(
            "/api/v1/home-feed",
            params={"lat": 40.7128, "lng": -74.0060},
            headers={"Authorization": f"Bearer {token}"},
        )

    assert response.status_code == status.HTTP_200_OK
    data = response.json()
    assert "sections" in data
    assert isinstance(data["sections"], list)


def test_home_feed_includes_ai_tag_sections_when_businesses_have_tags(client, db_session, mock_jwks, create_test_token):
    """When DB has businesses with ai_tags, response includes AI-based sections with those businesses."""
    # Create businesses with ai_tags
    b1 = Business(
        name="Date Spot",
        provider="google",
        provider_place_id="ChIJ-date-1",
        lat=40.71,
        lng=-74.00,
        address="123 Main St",
        ai_tags=["date-night"],
    )
    b2 = Business(
        name="Study Cafe",
        provider="google",
        provider_place_id="ChIJ-study-1",
        lat=40.72,
        lng=-74.01,
        address="456 Oak St",
        ai_tags=["study-spot", "coffee"],
    )
    db_session.add(b1)
    db_session.add(b2)
    db_session.commit()

    token = create_test_token(sub="550e8400-e29b-41d4-a716-4466554400d2", email="homefeed2@example.com")
    _complete_onboarding(client, token)

    with patch(
        "app.routers.home._fetch_nearby_places_async",
        new_callable=AsyncMock,
        return_value=([], []),
    ):
        response = client.get(
            "/api/v1/home-feed",
            params={"lat": 40.71, "lng": -74.00, "radius": 5000},
            headers={"Authorization": f"Bearer {token}"},
        )

    assert response.status_code == status.HTTP_200_OK
    data = response.json()
    sections = {s["id"]: s for s in data["sections"]}
    # AI-tag sections that have results should appear
    assert "date_night" in sections or "study_spots" in sections or "healthy_options" in sections
    # At least one section has businesses
    section_with_businesses = next((s for s in data["sections"] if s.get("businesses")), None)
    assert section_with_businesses is not None
    assert len(section_with_businesses["businesses"]) >= 1
    biz = section_with_businesses["businesses"][0]
    assert "provider_place_id" in biz and "name" in biz and "lat" in biz and "lng" in biz


def test_home_feed_nearby_sections_when_mocked(client, mock_jwks, create_test_token):
    """When nearby is mocked to return fake places, cafes_nearby (or similar) section appears with those places."""
    token = create_test_token(sub="550e8400-e29b-41d4-a716-4466554400d3", email="homefeed3@example.com")
    _complete_onboarding(client, token)

    fake_place = PlaceResult(
        provider="google",
        provider_place_id="place_cafe_1",
        name="Test Cafe",
        category="cafe",
        rating=4.5,
        review_count=100,
        address_short="123 Coffee St",
        lat=40.7128,
        lng=-74.0060,
        photo_url=None,
        price_level=1,
    )

    async def mock_nearby(lat, lng, radius, type_):
        if type_ == "cafe":
            return ([fake_place], ["place_cafe_1"])
        return ([], [])

    with patch(
        "app.routers.home._fetch_nearby_places_async",
        new_callable=AsyncMock,
        side_effect=mock_nearby,
    ):
        response = client.get(
            "/api/v1/home-feed",
            params={"lat": 40.7128, "lng": -74.0060},
            headers={"Authorization": f"Bearer {token}"},
        )

    assert response.status_code == status.HTTP_200_OK
    data = response.json()
    # At least one nearby section when mock returns non-empty
    nearby_sections = [s for s in data["sections"] if s["id"] == "cafes_nearby"]
    assert len(nearby_sections) == 1
    cafes = nearby_sections[0]
    assert cafes["title"] == "Cafes Nearby"
    assert cafes.get("subtitle") is not None
    assert len(cafes["businesses"]) == 1
    assert cafes["businesses"][0]["name"] == "Test Cafe"
    assert cafes["businesses"][0]["provider_place_id"] == "place_cafe_1"


def test_home_feed_schedules_prewarm_when_nearby_returns_places(client, mock_jwks, create_test_token):
    """When home-feed gets nearby results, prewarm_insights_for_places is called with those results."""
    token = create_test_token(sub="550e8400-e29b-41d4-a716-4466554400d4", email="homeprewarm@example.com")
    _complete_onboarding(client, token)

    fake_place = PlaceResult(
        provider="google",
        provider_place_id="place_gym_1",
        name="Test Gym",
        category="gym",
        rating=4.0,
        review_count=50,
        address_short="456 Gym St",
        lat=40.71,
        lng=-74.01,
        photo_url=None,
        price_level=None,
    )

    async def mock_nearby(lat, lng, radius, type_):
        if type_ == "gym":
            return ([fake_place], ["place_gym_1"])
        return ([], [])

    with (
        patch(
            "app.routers.home._fetch_nearby_places_async",
            new_callable=AsyncMock,
            side_effect=mock_nearby,
        ),
        patch("app.routers.home.prewarm_insights_for_places") as mock_prewarm,
    ):
        response = client.get(
            "/api/v1/home-feed",
            params={"lat": 40.7128, "lng": -74.0060},
            headers={"Authorization": f"Bearer {token}"},
        )
    assert response.status_code == status.HTTP_200_OK
    mock_prewarm.assert_called_once()
    places_arg = mock_prewarm.call_args[0][1]
    assert len(places_arg) == 1
    assert places_arg[0].provider_place_id == "place_gym_1"


def test_home_feed_business_to_place_result_includes_photo_url(client, db_session, mock_jwks, create_test_token):
    """When a business has photo_url or photo_reference, AI-tag section cards include photo_url."""
    from app.routers.home import _business_to_place_result

    biz_with_url = Business(
        name="Cafe With Photo",
        provider="google",
        provider_place_id="ChIJ-with-url",
        lat=40.71,
        lng=-74.00,
        address="123 Main",
        ai_tags=["coffee"],
        photo_url="https://maps.googleapis.com/maps/api/place/photo?maxwidth=1200&photo_reference=ref1&key=test",
    )
    db_session.add(biz_with_url)

    biz_with_ref = Business(
        name="Cafe With Ref",
        provider="google",
        provider_place_id="ChIJ-with-ref",
        lat=40.72,
        lng=-74.01,
        address="456 Oak",
        ai_tags=["coffee"],
        photo_reference="ref_xyz",
    )
    db_session.add(biz_with_ref)

    biz_no_photo = Business(
        name="Cafe No Photo",
        provider="google",
        provider_place_id="ChIJ-no-photo",
        lat=40.73,
        lng=-74.02,
        address="789 Elm",
        ai_tags=["coffee"],
    )
    db_session.add(biz_no_photo)
    db_session.commit()

    out_url = _business_to_place_result(biz_with_url)
    assert out_url.photo_url == "https://maps.googleapis.com/maps/api/place/photo?maxwidth=1200&photo_reference=ref1&key=test"

    with patch("app.routers.home._build_photo_url", return_value="https://built/from/ref"):
        out_ref = _business_to_place_result(biz_with_ref)
    assert out_ref.photo_url == "https://built/from/ref"

    out_none = _business_to_place_result(biz_no_photo)
    assert out_none.photo_url is None


def test_home_feed_includes_quick_bites_when_business_has_tag(client, db_session, mock_jwks, create_test_token):
    """When a business has ai_tags containing 'quick-bite', section quick_bites appears with that business."""
    b = Business(
        name="Quick Bite Spot",
        provider="google",
        provider_place_id="ChIJ-quick-1",
        lat=40.71,
        lng=-74.00,
        address="100 Quick St",
        ai_tags=["quick-bite"],
    )
    db_session.add(b)
    db_session.commit()

    token = create_test_token(sub="550e8400-e29b-41d4-a716-4466554400d5", email="quickbites@example.com")
    _complete_onboarding(client, token)

    with patch(
        "app.routers.home._fetch_nearby_places_async",
        new_callable=AsyncMock,
        return_value=([], []),
    ):
        response = client.get(
            "/api/v1/home-feed",
            params={"lat": 40.71, "lng": -74.00},
            headers={"Authorization": f"Bearer {token}"},
        )

    assert response.status_code == status.HTTP_200_OK
    data = response.json()
    sections_by_id = {s["id"]: s for s in data["sections"]}
    assert "quick_bites" in sections_by_id
    quick_bites = sections_by_id["quick_bites"]
    assert quick_bites["title"] == "Quick Bites"
    assert quick_bites.get("subtitle") == "Good for a fast bite"
    assert len(quick_bites["businesses"]) == 1
    assert quick_bites["businesses"][0]["name"] == "Quick Bite Spot"
    assert quick_bites["businesses"][0]["provider_place_id"] == "ChIJ-quick-1"


def test_home_feed_includes_restaurants_nearby_when_mocked(client, mock_jwks, create_test_token):
    """When nearby mock returns restaurant results, section restaurants_nearby appears."""
    token = create_test_token(sub="550e8400-e29b-41d4-a716-4466554400d6", email="restaurants@example.com")
    _complete_onboarding(client, token)

    fake_restaurant = PlaceResult(
        provider="google",
        provider_place_id="place_rest_1",
        name="Test Restaurant",
        category="restaurant",
        rating=4.2,
        review_count=80,
        address_short="789 Food Ave",
        lat=40.7128,
        lng=-74.0060,
        photo_url=None,
        price_level=2,
    )

    async def mock_nearby(lat, lng, radius, type_):
        if type_ == "restaurant":
            return ([fake_restaurant], ["place_rest_1"])
        return ([], [])

    with patch(
        "app.routers.home._fetch_nearby_places_async",
        new_callable=AsyncMock,
        side_effect=mock_nearby,
    ):
        response = client.get(
            "/api/v1/home-feed",
            params={"lat": 40.7128, "lng": -74.0060},
            headers={"Authorization": f"Bearer {token}"},
        )

    assert response.status_code == status.HTTP_200_OK
    data = response.json()
    sections_by_id = {s["id"]: s for s in data["sections"]}
    assert "restaurants_nearby" in sections_by_id
    rest = sections_by_id["restaurants_nearby"]
    assert rest["title"] == "Popular Eats Nearby"
    assert rest.get("subtitle") == "Restaurants within about a mile"
    assert len(rest["businesses"]) == 1
    assert rest["businesses"][0]["name"] == "Test Restaurant"
