"""Home feed endpoint: nearby sections + AI-tag sections."""

import logging
import math
from fastapi import APIRouter, BackgroundTasks, Depends, Query
from sqlalchemy.orm import Session

from app.core.auth import get_current_user, require_onboarding
from app.db.session import get_db
from app.models.business import Business
from app.models.user import User
from app.schemas.home import HomeFeedSection, HomeFeedResponse
from app.schemas.places import PlaceResult
from app.routers.places import (
    _build_photo_url,
    _fetch_nearby_places_async,
    prewarm_insights_for_places,
    LAT_MIN,
    LAT_MAX,
    LNG_MIN,
    LNG_MAX,
)

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/home-feed", tags=["home-feed"])

# Default radius for home feed (meters)
HOME_FEED_DEFAULT_RADIUS = 2000
# Radius for AI-tag sections (meters)
AI_TAG_RADIUS_M = 3000
# Max businesses per AI-tag section
AI_TAG_SECTION_LIMIT = 10

# Nearby section config: (section_id, title, subtitle, Google type, radius_m)
NEARBY_SECTION_SPECS = [
    ("cafes_nearby", "Cafes Nearby", "Coffee and cafes nearby", "cafe", 1500),
    ("gyms_nearby", "Gyms Nearby", "Fitness and gyms nearby", "gym", 2000),
    ("hotels_nearby", "Hotels Nearby", "Hotels within driving distance", "lodging", 3000),
    ("restaurants_nearby", "Popular Eats Nearby", "Restaurants within about a mile", "restaurant", 1500),
    ("bars_nearby", "Bars & Nightlife", "Bars and lounges nearby", "bar", 2000),
    ("parks_nearby", "Parks & Outdoors", "Parks and outdoor spots nearby", "park", 2500),
]

# AI-tag section config: (section_id, title, subtitle, tag value in ai_tags)
TAG_SECTION_SPECS = [
    ("date_night", "Best for Date Night", "AI-picked date night spots", "date-night"),
    ("groups", "Great for Groups", "Good for group hangs", "groups"),
    ("study_spots", "Study Spots & Cafes", "Quiet spots and cafes to study", "study-spot"),
    ("healthy_options", "Healthy Options", "Spots with healthier options", "healthy"),
    ("quick_bites", "Quick Bites", "Good for a fast bite", "quick-bite"),
    ("dessert_and_sweets", "Dessert & Sweets", "Spots for dessert lovers", "dessert"),
    ("budget_friendly", "Budget-Friendly Bites", "Good options on a budget", "budget"),
]


def _haversine_m(lat1: float, lng1: float, lat2: float, lng2: float) -> float:
    """Distance between two points in meters."""
    R = 6371000
    phi1 = math.radians(lat1)
    phi2 = math.radians(lat2)
    dphi = math.radians(lat2 - lat1)
    dlam = math.radians(lng2 - lng1)
    a = math.sin(dphi / 2) ** 2 + math.cos(phi1) * math.cos(phi2) * math.sin(dlam / 2) ** 2
    c = 2 * math.atan2(math.sqrt(a), math.sqrt(1 - a))
    return R * c


def _business_to_place_result(business: Business) -> PlaceResult:
    """Convert a DB Business to PlaceResult (same shape as /places/nearby) for iOS. Uses persisted photo when available."""
    lat = business.lat if business.lat is not None else business.latitude
    lng = business.lng if business.lng is not None else business.longitude
    photo_url = None
    if business.photo_url:
        photo_url = business.photo_url
    elif business.photo_reference:
        photo_url = _build_photo_url(business.photo_reference)
    return PlaceResult(
        provider=business.provider or "google",
        provider_place_id=business.provider_place_id or "",
        name=business.name or "",
        category=business.category,
        rating=None,
        review_count=None,
        address_short=business.address,
        lat=lat if lat is not None else 0.0,
        lng=lng if lng is not None else 0.0,
        photo_url=photo_url,
        price_level=None,
    )


def _businesses_for_tag(
    db: Session,
    tag: str,
    lat: float,
    lng: float,
    radius_m: int = AI_TAG_RADIUS_M,
    limit: int = AI_TAG_SECTION_LIMIT,
) -> list[PlaceResult]:
    """Return businesses that have this ai_tag, within radius, ordered by freshness. Portable (no JSONB ops in SQL)."""
    all_with_tags = (
        db.query(Business)
        .filter(Business.ai_tags.isnot(None))
        .all()
    )
    matching: list[tuple[Business, float | None]] = []
    for b in all_with_tags:
        tags = b.ai_tags
        if not isinstance(tags, list):
            continue
        if tag not in tags:
            continue
        blat = b.lat if b.lat is not None else b.latitude
        blng = b.lng if b.lng is not None else b.longitude
        if blat is None or blng is None:
            matching.append((b, None))
            continue
        dist = _haversine_m(lat, lng, blat, blng)
        if dist <= radius_m:
            matching.append((b, dist))
    # Order by ai_context_last_updated desc (fresh first), then by distance asc
    def _sort_key(x: tuple[Business, float | None]) -> tuple[float, float]:
        ts = x[0].ai_context_last_updated.timestamp() if x[0].ai_context_last_updated else 0.0
        dist = x[1] if x[1] is not None else float("inf")
        return (-ts, dist)

    matching.sort(key=_sort_key)
    businesses = [b for b, _ in matching[:limit]]
    return [_business_to_place_result(b) for b in businesses]


@router.get("", response_model=HomeFeedResponse)
async def get_home_feed(
    lat: float = Query(..., ge=LAT_MIN, le=LAT_MAX, description="Latitude"),
    lng: float = Query(..., ge=LNG_MIN, le=LNG_MAX, description="Longitude"),
    radius: int | None = Query(
        HOME_FEED_DEFAULT_RADIUS,
        ge=1,
        le=50000,
        description="Search radius in meters for nearby sections",
    ),
    background_tasks: BackgroundTasks = None,
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
) -> HomeFeedResponse:
    """
    Get the home feed: premade nearby sections (cafes, gyms, hotels) and AI-tag sections.
    Requires authentication and completed onboarding.
    """
    require_onboarding(current_user)
    sections: list[HomeFeedSection] = []
    all_nearby_results: list[PlaceResult] = []

    # Nearby sections (per-spec radius; use request radius as fallback only for backward compat)
    for section_id, title, subtitle, place_type, radius_m in NEARBY_SECTION_SPECS:
        try:
            effective_radius = radius if radius is not None else radius_m
            results, _ = await _fetch_nearby_places_async(
                lat, lng, effective_radius, place_type
            )
            if results:
                all_nearby_results.extend(results)
                sections.append(
                    HomeFeedSection(
                        id=section_id,
                        title=title,
                        subtitle=subtitle,
                        businesses=results,
                    )
                )
        except Exception as e:
            logger.warning("Home feed section %s failed: %s", section_id, e, exc_info=True)

    # AI-tag sections (only include if we have at least one business)
    for section_id, title, subtitle, tag in TAG_SECTION_SPECS:
        try:
            businesses = _businesses_for_tag(db, tag, lat, lng, radius_m=AI_TAG_RADIUS_M)
            if businesses:
                sections.append(
                    HomeFeedSection(
                        id=section_id,
                        title=title,
                        subtitle=subtitle,
                        businesses=businesses,
                    )
                )
        except Exception as e:
            logger.warning("Home feed AI section %s failed: %s", section_id, e, exc_info=True)

    # Proactive prewarm for nearby places (capped, same as /places/nearby)
    if background_tasks and all_nearby_results:
        prewarm_insights_for_places(background_tasks, all_nearby_results)

    return HomeFeedResponse(sections=sections)
