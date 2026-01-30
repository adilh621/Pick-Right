"""Google Places API client service for AI grounding."""

import logging
import re
import traceback

import httpx

from app.core.config import settings

logger = logging.getLogger(__name__)

GOOGLE_PLACES_BASE = "https://maps.googleapis.com/maps/api/place"
REQUEST_TIMEOUT = 10.0


def _redact_api_key(url: str) -> str:
    """Remove API key from URL for safe logging."""
    return re.sub(r'key=[^&]+', 'key=REDACTED', str(url))


def _get_api_key() -> str:
    """Get API key or raise error if not configured."""
    if not settings.google_maps_api_key:
        raise ValueError("GOOGLE_MAPS_API_KEY missing")
    return settings.google_maps_api_key


async def _call_google_api(url: str, params: dict) -> dict:
    """Call Google Places API with logging. Returns parsed JSON or raises."""
    full_url = httpx.URL(url, params=params)
    safe_url = _redact_api_key(str(full_url))
    
    logger.info(f"Places service calling: {safe_url}")
    
    async with httpx.AsyncClient(timeout=REQUEST_TIMEOUT) as client:
        response = await client.get(url, params=params)
        response_text = response.text
        truncated_body = response_text[:500] if response_text else "(empty)"
        
        logger.info(f"Places response: status={response.status_code}, body_preview={truncated_body}")
        
        if response.status_code != 200:
            raise Exception(f"Google API HTTP {response.status_code}: {truncated_body}")
        
        return response.json()


async def text_search(query: str, location_hint: str | None = None) -> dict | None:
    """
    Search for a place using Google Places Text Search.
    
    Args:
        query: The search query (e.g., "Papa John's Castle Hill")
        location_hint: Optional location context (e.g., "Bronx, NY")
    
    Returns:
        The top result dict from Google, or None if no results.
    """
    api_key = _get_api_key()
    
    # Combine query with location hint for better results
    search_query = query
    if location_hint:
        search_query = f"{query} {location_hint}"
    
    url = f"{GOOGLE_PLACES_BASE}/textsearch/json"
    params = {
        "query": search_query,
        "key": api_key,
    }
    
    try:
        data = await _call_google_api(url, params)
        
        status = data.get("status", "UNKNOWN_ERROR")
        if status == "ZERO_RESULTS":
            logger.info(f"Text search returned no results for: {search_query}")
            return None
        if status != "OK":
            logger.error(f"Text search error: status={status}, query={search_query}")
            return None
        
        results = data.get("results", [])
        if not results:
            return None
        
        # Return top result
        top = results[0]
        logger.info(f"Text search top result: name={top.get('name')}, place_id={top.get('place_id')}")
        return top
        
    except Exception as e:
        logger.error(f"Text search failed: {e}\n{traceback.format_exc()}")
        return None


async def get_place_details(place_id: str) -> dict | None:
    """
    Get place details including opening hours.
    
    Args:
        place_id: Google Place ID
    
    Returns:
        Place details dict with name, formatted_address, opening_hours, etc.
        Returns None on error.
    """
    api_key = _get_api_key()
    
    url = f"{GOOGLE_PLACES_BASE}/details/json"
    params = {
        "place_id": place_id,
        "fields": "place_id,name,formatted_address,opening_hours",
        "key": api_key,
    }
    
    try:
        data = await _call_google_api(url, params)
        
        status = data.get("status", "UNKNOWN_ERROR")
        if status != "OK":
            logger.error(f"Place details error: status={status}, place_id={place_id}")
            return None
        
        result = data.get("result")
        if result:
            logger.info(f"Place details: name={result.get('name')}, has_hours={bool(result.get('opening_hours'))}")
        return result
        
    except Exception as e:
        logger.error(f"Place details failed: {e}\n{traceback.format_exc()}")
        return None


async def find_place_with_hours(query: str, location_hint: str | None = None) -> dict | None:
    """
    Find a place and get its details including hours.
    
    Combines text search + details in one call.
    
    Returns:
        Dict with: name, formatted_address, opening_hours (weekday_text list), place_id
        Returns None if place not found.
    """
    # First, search for the place
    place = await text_search(query, location_hint)
    if not place:
        return None
    
    place_id = place.get("place_id")
    if not place_id:
        return None
    
    # Get details with hours
    details = await get_place_details(place_id)
    if not details:
        # Return basic info from search if details fail
        return {
            "name": place.get("name"),
            "formatted_address": place.get("formatted_address"),
            "opening_hours": None,
            "place_id": place_id,
        }
    
    # Extract weekday_text from opening_hours
    opening_hours = details.get("opening_hours", {})
    weekday_text = opening_hours.get("weekday_text", []) if opening_hours else []
    
    return {
        "name": details.get("name"),
        "formatted_address": details.get("formatted_address"),
        "opening_hours": weekday_text if weekday_text else None,
        "place_id": place_id,
    }

