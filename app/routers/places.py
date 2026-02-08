"""Google Places API proxy endpoints."""

import logging
import re
import traceback
from datetime import datetime, timedelta, timezone

from fastapi import APIRouter, Depends, HTTPException, Query
from fastapi.responses import JSONResponse
import httpx
from sqlalchemy.orm import Session

from app.core.config import settings
from app.core.auth import get_current_user, require_onboarding
from app.db.session import get_db
from app.models.user import User
from app.models.business import Business
from app.services.ai_notes_service import generate_ai_notes_for_business
from app.ai.business_context import generate_business_ai_context
import math

from app.schemas.places import (
    NearbySearchResponse,
    PlaceResult,
    PlaceDetailsResponse,
    PlaceDetails,
    OpeningHours,
    OpeningHoursPeriod,
    PlaceSearchResult,
    TextSearchResponse,
)

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/places", tags=["places"])

GOOGLE_PLACES_BASE = "https://maps.googleapis.com/maps/api/place"
REQUEST_TIMEOUT = 10.0  # seconds


def _redact_api_key(url: str) -> str:
    """Remove API key from URL for safe logging."""
    return re.sub(r'key=[^&]+', 'key=REDACTED', str(url))


def _get_api_key() -> str:
    """Get API key or raise error if not configured."""
    if not settings.google_maps_api_key:
        logger.error("GOOGLE_MAPS_API_KEY is missing or empty in environment")
        raise HTTPException(
            status_code=500,
            detail={"error": "GOOGLE_MAPS_API_KEY missing"}
        )
    return settings.google_maps_api_key


def _build_photo_url(photo_reference: str | None, max_width: int = 1200) -> str | None:
    """Build Google Places photo URL from photo reference."""
    if not photo_reference:
        return None
    api_key = settings.google_maps_api_key
    return (
        f"{GOOGLE_PLACES_BASE}/photo"
        f"?maxwidth={max_width}"
        f"&photo_reference={photo_reference}"
        f"&key={api_key}"
    )


def _extract_state_from_address_components(place: dict) -> str | None:
    """Extract state/region from Google Place address_components (administrative_area_level_1)."""
    for comp in place.get("address_components") or []:
        if "administrative_area_level_1" in (comp.get("types") or []):
            return comp.get("long_name") or comp.get("short_name")
    return None


def _extract_primary_type(place: dict) -> str | None:
    """Extract best-effort primary type/category from place data."""
    # Prefer primary_type if available (newer API)
    if primary_type := place.get("primary_type"):
        return primary_type
    # Fall back to first type that's not generic
    types = place.get("types", [])
    generic_types = {"point_of_interest", "establishment"}
    for t in types:
        if t not in generic_types:
            return t
    return types[0] if types else None


def _haversine_distance(lat1: float, lng1: float, lat2: float, lng2: float) -> int:
    """Calculate distance between two points in meters using Haversine formula."""
    R = 6371000  # Earth's radius in meters
    phi1 = math.radians(lat1)
    phi2 = math.radians(lat2)
    delta_phi = math.radians(lat2 - lat1)
    delta_lambda = math.radians(lng2 - lng1)
    
    a = math.sin(delta_phi / 2) ** 2 + math.cos(phi1) * math.cos(phi2) * math.sin(delta_lambda / 2) ** 2
    c = 2 * math.atan2(math.sqrt(a), math.sqrt(1 - a))
    
    return int(R * c)


def _normalize_search_place(
    place: dict,
    origin_lat: float | None = None,
    origin_lng: float | None = None
) -> PlaceSearchResult:
    """Normalize a Google text search result to our schema."""
    location = place.get("geometry", {}).get("location", {})
    photos = place.get("photos", [])
    photo_ref = photos[0].get("photo_reference") if photos else None
    
    place_lat = location.get("lat", 0.0)
    place_lng = location.get("lng", 0.0)
    
    # Calculate distance if origin provided
    distance_m = None
    if origin_lat is not None and origin_lng is not None:
        distance_m = _haversine_distance(origin_lat, origin_lng, place_lat, place_lng)
    
    # Text search uses formatted_address instead of vicinity
    address = place.get("formatted_address") or place.get("vicinity")
    
    return PlaceSearchResult(
        provider="google",
        provider_place_id=place.get("place_id", ""),
        name=place.get("name", ""),
        category=_extract_primary_type(place),
        rating=place.get("rating"),
        review_count=place.get("user_ratings_total"),
        address_short=address,
        lat=place_lat,
        lng=place_lng,
        photo_url=_build_photo_url(photo_ref),
        types=place.get("types", []),
        price_level=place.get("price_level"),
        distance_m=distance_m,
    )


def _normalize_nearby_place(place: dict) -> PlaceResult:
    """Normalize a Google place result to our schema."""
    location = place.get("geometry", {}).get("location", {})
    photos = place.get("photos", [])
    photo_ref = photos[0].get("photo_reference") if photos else None
    
    return PlaceResult(
        provider="google",
        provider_place_id=place.get("place_id", ""),
        name=place.get("name", ""),
        category=_extract_primary_type(place),
        rating=place.get("rating"),
        review_count=place.get("user_ratings_total"),
        address_short=place.get("vicinity"),
        lat=location.get("lat", 0.0),
        lng=location.get("lng", 0.0),
        photo_url=_build_photo_url(photo_ref),
        price_level=place.get("price_level"),
    )


def _normalize_opening_hours(hours_data: dict | None) -> OpeningHours | None:
    """Normalize opening hours from Google response."""
    if not hours_data:
        return None
    
    periods = []
    for p in hours_data.get("periods", []):
        open_info = p.get("open", {})
        close_info = p.get("close", {})
        periods.append(OpeningHoursPeriod(
            open_day=open_info.get("day", 0),
            open_time=open_info.get("time", "0000"),
            close_day=close_info.get("day") if close_info else None,
            close_time=close_info.get("time") if close_info else None,
        ))
    
    return OpeningHours(
        open_now=hours_data.get("open_now"),
        weekday_text=hours_data.get("weekday_text", []),
        periods=periods,
    )


def _normalize_place_details(
    place: dict,
    ai_notes: str | None = None,
    business_id: Business | None = None,
    ai_context: dict | None = None,
) -> PlaceDetails:
    """Normalize Google place details to our schema. Optionally attach cached ai_notes, business_id, ai_context."""
    location = place.get("geometry", {}).get("location", {})
    photos = place.get("photos", [])
    
    # Extract up to 10 photo URLs for carousel support
    photo_urls = [
        url for url in (
            _build_photo_url(p.get("photo_reference"))
            for p in photos[:10]  # Limit to 10 photos for carousel
            if p.get("photo_reference")
        )
        if url is not None
    ]
    
    # Set single photo_url for backwards compatibility
    photo_url = photo_urls[0] if photo_urls else None
    
    return PlaceDetails(
        provider="google",
        provider_place_id=place.get("place_id", ""),
        name=place.get("name", ""),
        category=_extract_primary_type(place),
        types=place.get("types", []),
        rating=place.get("rating"),
        review_count=place.get("user_ratings_total"),
        formatted_address=place.get("formatted_address"),
        phone=place.get("formatted_phone_number"),
        website=place.get("website"),
        opening_hours=_normalize_opening_hours(place.get("opening_hours")),
        photo_url=photo_url,
        photo_urls=photo_urls,
        lat=location.get("lat"),
        lng=location.get("lng"),
        ai_notes=ai_notes,
        business_id=business_id.id if business_id else None,
        ai_context=ai_context,
        price_level=place.get("price_level"),
    )


async def _call_google_api(url: str, params: dict) -> dict:
    """
    Call Google Places API with logging and error handling.
    
    Returns parsed JSON on success.
    Raises HTTPException with detailed error info on failure.
    """
    # Build the full URL for logging (will redact key)
    full_url = httpx.URL(url, params=params)
    safe_url = _redact_api_key(str(full_url))
    
    logger.info(f"Calling Google Places API: {safe_url}")
    
    try:
        async with httpx.AsyncClient(timeout=REQUEST_TIMEOUT) as client:
            response = await client.get(url, params=params)
            response_text = response.text
            truncated_body = response_text[:500] if response_text else "(empty)"
            
            logger.info(
                f"Google API response: status={response.status_code}, "
                f"body_preview={truncated_body}"
            )
            
            # Check HTTP status first
            if response.status_code != 200:
                logger.error(
                    f"Google API HTTP error: url={safe_url}, "
                    f"status={response.status_code}, body={truncated_body}"
                )
                raise HTTPException(
                    status_code=502,
                    detail={
                        "error": "google_error",
                        "status": response.status_code,
                        "body": truncated_body
                    }
                )
            
            return response.json()
            
    except httpx.TimeoutException as e:
        logger.error(
            f"Google API timeout: url={safe_url}\n"
            f"Traceback:\n{traceback.format_exc()}"
        )
        raise HTTPException(
            status_code=504,
            detail={
                "error": "google_timeout",
                "message": "Google Places API request timed out"
            }
        )
    except httpx.RequestError as e:
        logger.error(
            f"Google API request error: url={safe_url}, error={str(e)}\n"
            f"Traceback:\n{traceback.format_exc()}"
        )
        raise HTTPException(
            status_code=502,
            detail={
                "error": "google_request_error",
                "message": str(e)
            }
        )


# Coordinate bounds for validation (same behavior for any location worldwide)
LAT_MIN, LAT_MAX = -90.0, 90.0
LNG_MIN, LNG_MAX = -180.0, 180.0


@router.get("/nearby", response_model=NearbySearchResponse)
async def nearby_search(
    lat: float = Query(..., ge=LAT_MIN, le=LAT_MAX, description="Latitude (-90 to 90)"),
    lng: float = Query(..., ge=LNG_MIN, le=LNG_MAX, description="Longitude (-180 to 180)"),
    radius: int = Query(1500, ge=1, le=50000, description="Search radius in meters"),
    type: str = Query("restaurant", description="Place type to search for"),
    current_user: User = Depends(get_current_user),
) -> NearbySearchResponse:
    """
    Search for nearby places using Google Places API.
    Requires completed onboarding.

    Accepts any valid coordinates (lat in [-90, 90], lng in [-180, 180]).
    Use the same lat/lng when the user has chosen a custom location (e.g. "Change location").
    The server does not geocode; the client must pass coordinates from device or geocoding.
    Returns a normalized list of places with basic info.
    """
    require_onboarding(current_user)
    api_key = _get_api_key()
    
    url = f"{GOOGLE_PLACES_BASE}/nearbysearch/json"
    params = {
        "location": f"{lat},{lng}",
        "radius": radius,
        "type": type,
        "key": api_key,
    }
    
    data = await _call_google_api(url, params)
    
    # Check Google API status field
    status = data.get("status", "UNKNOWN_ERROR")
    if status not in ("OK", "ZERO_RESULTS"):
        error_msg = data.get("error_message", status)
        body_preview = str(data)[:500]
        logger.error(
            f"Google API logical error: status={status}, "
            f"error_message={error_msg}, body={body_preview}"
        )
        raise HTTPException(
            status_code=502,
            detail={
                "error": "google_error",
                "status": status,
                "body": body_preview
            }
        )
    
    results = [
        _normalize_nearby_place(place)
        for place in data.get("results", [])
    ]
    
    return NearbySearchResponse(results=results)


def _upsert_business_from_place(db: Session, place_id: str, result: dict) -> Business:
    """
    Upsert a Business row from Google Place Details result.
    Looks up by (provider, provider_place_id) to match the unique constraint.
    Updates existing row with fresh place data; does not overwrite ai_notes.
    Returns the business (existing or newly created).
    """
    location = result.get("geometry", {}).get("location", {})
    lat = location.get("lat")
    lng = location.get("lng")
    name = result.get("name") or ""
    formatted_address = result.get("formatted_address")
    state = _extract_state_from_address_components(result)
    category = _extract_primary_type(result)

    # Look up by (provider, provider_place_id) to match DB unique constraint
    business = (
        db.query(Business)
        .filter(
            Business.provider == "google",
            Business.provider_place_id == place_id,
        )
        .first()
    )
    if business:
        # Update with fresh place data; do not touch ai_notes or other curated fields
        business.name = name
        business.address = formatted_address
        business.state = state
        business.latitude = lat
        business.longitude = lng
        business.lat = lat
        business.lng = lng
        business.category = category
        business.external_id_google = place_id
        db.commit()
        db.refresh(business)
        return business

    business = Business(
        name=name,
        provider="google",
        provider_place_id=place_id,
        external_id_google=place_id,
        address=formatted_address,
        state=state,
        latitude=lat,
        longitude=lng,
        lat=lat,
        lng=lng,
        category=category,
    )
    db.add(business)
    db.commit()
    db.refresh(business)
    return business


# TTL for AI context: regenerate if older than this
AI_CONTEXT_TTL_HOURS = 24


@router.get("/details", response_model=PlaceDetailsResponse)
async def place_details(
    place_id: str = Query(..., description="Google Place ID"),
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
) -> PlaceDetailsResponse:
    """
    Get detailed information about a place using Google Places API.

    Requires authentication and completed onboarding.

    - Upserts a business row (by place_id).
    - Generates and caches ai_notes if missing.
    - Generates and caches structured AI context (ai_context) if missing or older than 24h;
      ai_context is generic (no per-user personalization).
    - Returns business_id so the client can use it for the chat endpoint.

    Returns normalized place details including hours, contact info, photos, ai_notes,
    business_id, and ai_context.
    """
    require_onboarding(current_user)
    api_key = _get_api_key()

    url = f"{GOOGLE_PLACES_BASE}/details/json"
    params = {
        "place_id": place_id,
        "fields": ",".join([
            "place_id",
            "name",
            "types",
            "rating",
            "user_ratings_total",
            "formatted_address",
            "formatted_phone_number",
            "website",
            "opening_hours",
            "photos",
            "geometry",
            "address_components",
            "reviews",
            "price_level",
        ]),
        "key": api_key,
    }

    data = await _call_google_api(url, params)

    # Check Google API status field
    status = data.get("status", "UNKNOWN_ERROR")
    if status != "OK":
        error_msg = data.get("error_message", status)
        body_preview = str(data)[:500]

        if status == "NOT_FOUND":
            logger.warning(f"Place not found: place_id={place_id}")
            raise HTTPException(status_code=404, detail="Place not found")

        logger.error(
            f"Google API logical error: status={status}, "
            f"error_message={error_msg}, body={body_preview}"
        )
        raise HTTPException(
            status_code=502,
            detail={
                "error": "google_error",
                "status": status,
                "body": body_preview
            }
        )

    result = data.get("result")
    if not result:
        logger.warning(f"Place details empty: place_id={place_id}")
        raise HTTPException(status_code=404, detail="Place not found")

    # Upsert business so we can cache ai_notes and ai_context
    business = _upsert_business_from_place(db, place_id, result)

    # Generate and cache ai_notes if missing
    ai_notes = business.ai_notes
    if not (ai_notes and ai_notes.strip()):
        try:
            generated = generate_ai_notes_for_business(business, result)
            if generated and generated.strip():
                business.ai_notes = generated
                db.commit()
                db.refresh(business)
                ai_notes = business.ai_notes
        except Exception as e:
            logger.exception("Failed to generate ai_notes for business %s: %s", business.id, e)
            ai_notes = None

    # Decide whether to regenerate AI context (Option B: null or older than TTL)
    now_utc = datetime.now(timezone.utc)
    need_ai_context = (
        business.ai_context is None
        or business.ai_context_last_updated is None
        or (now_utc - business.ai_context_last_updated) > timedelta(hours=AI_CONTEXT_TTL_HOURS)
    )
    if need_ai_context:
        ai_context_dict = generate_business_ai_context(business, result, None)
        if ai_context_dict is not None:
            business.ai_context = ai_context_dict
            business.ai_context_last_updated = now_utc
            db.commit()
            db.refresh(business)

    ai_context = business.ai_context

    return PlaceDetailsResponse(
        result=_normalize_place_details(
            result,
            ai_notes=ai_notes,
            business_id=business,
            ai_context=ai_context,
        ),
        business_id=business.id,
        ai_context=ai_context,
    )


@router.get("/search", response_model=TextSearchResponse)
async def text_search(
    q: str = Query(..., description="Search query (e.g., 'pizza bronx', 'papa johns')"),
    lat: float | None = Query(None, ge=LAT_MIN, le=LAT_MAX, description="Latitude for location bias (-90 to 90)"),
    lng: float | None = Query(None, ge=LNG_MIN, le=LNG_MAX, description="Longitude for location bias (-180 to 180)"),
    radius_m: int = Query(5000, ge=1, le=50000, description="Search radius in meters (used with lat/lng)"),
    limit: int = Query(20, ge=1, le=60, description="Maximum number of results"),
) -> TextSearchResponse:
    """
    Search for places by text query using Google Places Text Search API.
    
    Place text search. Returns results compatible with /nearby cards.
    
    - If lat/lng provided: biases results near that location (any valid coordinates accepted).
    - If lat/lng omitted: searches without location bias.
    
    Example curl:
    ```bash
    # Search with location bias
    curl "http://localhost:8000/api/v1/places/search?q=papa+johns+bronx&lat=40.8448&lng=-73.8648"
    
    # Search without location bias
    curl "http://localhost:8000/api/v1/places/search?q=papa+johns+castle+hill+bronx"
    ```
    
    Returns a list of place cards with: place_id, name, address, rating,
    review_count, types, price_level, photo_url, lat, lng, distance_m (if location provided).
    """
    api_key = _get_api_key()
    
    url = f"{GOOGLE_PLACES_BASE}/textsearch/json"
    params: dict = {
        "query": q,
        "key": api_key,
    }
    
    # Add location bias if coordinates provided
    if lat is not None and lng is not None:
        params["location"] = f"{lat},{lng}"
        params["radius"] = radius_m
    
    data = await _call_google_api(url, params)
    
    # Check Google API status field
    status = data.get("status", "UNKNOWN_ERROR")
    if status not in ("OK", "ZERO_RESULTS"):
        error_msg = data.get("error_message", status)
        body_preview = str(data)[:500]
        logger.error(
            f"Google API logical error: status={status}, "
            f"error_message={error_msg}, body={body_preview}"
        )
        raise HTTPException(
            status_code=502,
            detail={
                "error": "google_error",
                "status": status,
                "body": body_preview
            }
        )
    
    # Normalize results (limit to requested count)
    raw_results = data.get("results", [])[:limit]
    results = [
        _normalize_search_place(place, origin_lat=lat, origin_lng=lng)
        for place in raw_results
    ]
    
    # Sort by distance if we have location
    if lat is not None and lng is not None:
        results.sort(key=lambda r: r.distance_m or float('inf'))
    
    return TextSearchResponse(results=results)
