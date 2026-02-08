"""Schemas for Google Places API proxy responses."""

from uuid import UUID
from typing import Literal, Optional, Any

from pydantic import BaseModel, ConfigDict


class PlaceResult(BaseModel):
    """Normalized place result from Google Places API."""
    provider: str = "google"
    provider_place_id: str
    name: str
    category: Optional[str] = None
    rating: Optional[float] = None
    review_count: Optional[int] = None
    address_short: Optional[str] = None
    lat: float
    lng: float
    photo_url: Optional[str] = None
    price_level: Optional[int] = None


class NearbySearchResponse(BaseModel):
    """Response for nearby search endpoint."""
    results: list[PlaceResult]


class OpeningHoursPeriod(BaseModel):
    """Opening hours period."""
    open_day: int
    open_time: str
    close_day: Optional[int] = None
    close_time: Optional[str] = None


class OpeningHours(BaseModel):
    """Opening hours information."""
    open_now: Optional[bool] = None
    weekday_text: list[str] = []
    periods: list[OpeningHoursPeriod] = []


class PlaceDetails(BaseModel):
    """
    Normalized place details from Google Places API.
    
    Photo fields:
    - photo_url: Single URL for backwards compatibility (first photo)
    - photo_urls: Array of up to 10 photo URLs for carousel support
    
    Example curl:
    ```bash
    curl "http://localhost:8000/api/v1/places/details?place_id=ChIJN1t_tDeuEmsRUsoyG83frY4"
    ```
    
    Response includes:
    ```json
    {
      "result": {
        "photo_url": "https://maps.googleapis.com/...",
        "photo_urls": [
          "https://maps.googleapis.com/...",
          "https://maps.googleapis.com/...",
          ...
        ]
      }
    }
    ```
    """
    provider: str = "google"
    provider_place_id: str
    name: str
    category: Optional[str] = None
    types: list[str] = []
    rating: Optional[float] = None
    review_count: Optional[int] = None
    formatted_address: Optional[str] = None
    phone: Optional[str] = None
    website: Optional[str] = None
    opening_hours: Optional[OpeningHours] = None
    # Single photo URL for backwards compatibility
    photo_url: Optional[str] = None
    # Multiple photo URLs for carousel support (up to 10)
    photo_urls: list[str] = []
    lat: Optional[float] = None
    lng: Optional[float] = None
    # AI-generated summary for chat context (cached per business)
    ai_notes: Optional[str] = None
    # Business UUID for chat and future calls (same identifier as chat endpoint)
    business_id: Optional[UUID] = None
    # Structured AI context (summary, pros, cons, vibe, best_for_user_profile, etc.)
    ai_context: Optional[dict[str, Any]] = None
    price_level: Optional[int] = None


class PlaceDetailsResponse(BaseModel):
    """Response for place details endpoint. Top-level business_id, ai_context, and ai_status for client decoding."""
    result: PlaceDetails
    business_id: Optional[UUID] = None
    ai_context: Optional[dict[str, Any]] = None
    ai_status: Literal["ready", "pending", "unavailable"] = "ready"

    model_config = ConfigDict(serialization_exclude_none=True)


class PlaceSearchResult(BaseModel):
    """
    Place result for text search - extends PlaceResult with additional fields.
    Compatible with /nearby results for iOS card reuse.
    """
    provider: str = "google"
    provider_place_id: str
    name: str
    category: Optional[str] = None
    rating: Optional[float] = None
    review_count: Optional[int] = None
    address_short: Optional[str] = None
    lat: float
    lng: float
    photo_url: Optional[str] = None
    # Additional fields for search results
    types: list[str] = []
    price_level: Optional[int] = None
    distance_m: Optional[int] = None


class TextSearchResponse(BaseModel):
    """Response for text search endpoint."""
    results: list[PlaceSearchResult]

