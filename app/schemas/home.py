"""Schemas for home feed endpoint."""

from pydantic import BaseModel

from app.schemas.places import PlaceResult


class HomeFeedSection(BaseModel):
    """A single section in the home feed (e.g. Cafes Nearby or Best for Date Night)."""
    id: str
    title: str
    subtitle: str | None = None
    businesses: list[PlaceResult]


class HomeFeedResponse(BaseModel):
    """Response for GET /api/v1/home-feed."""
    sections: list[HomeFeedSection]
