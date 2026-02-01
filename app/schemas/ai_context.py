"""
Structured AI context schema for a single business.

Stored in Business.ai_context (JSONB). Generated on business detail load
and used by the chat endpoint so the user never has to re-explain the business.
"""

from typing import TypedDict

from pydantic import BaseModel, Field


class BusinessAIContextDict(TypedDict, total=False):
    """TypedDict for the raw JSON shape stored in Business.ai_context."""

    summary: str
    pros: list[str]
    cons: list[str]
    best_for_user_profile: str
    vibe: str
    reliability_notes: str
    source_notes: str


class BusinessAIContext(BaseModel):
    """
    Structured AI context for a business detail / chat.

    - summary: Short overview of the place.
    - pros: List of positive points.
    - cons: List of drawbacks or caveats.
    - best_for_user_profile: Who this place is best for (personalized when user prefs available).
    - vibe: Ambiance / atmosphere description.
    - reliability_notes: How reliable the info is (e.g. based on reviews vs live data).
    - source_notes: High-level explanation of what sources were used (e.g. Google, web search).
    """

    summary: str = Field(default="", description="Short overview of the place")
    pros: list[str] = Field(default_factory=list, description="Positive points")
    cons: list[str] = Field(default_factory=list, description="Drawbacks or caveats")
    best_for_user_profile: str = Field(
        default="",
        description="Who this place is best for (personalized when user prefs available)",
    )
    vibe: str = Field(default="", description="Ambiance / atmosphere")
    reliability_notes: str = Field(
        default="",
        description="How reliable the info is (e.g. based on reviews vs live data)",
    )
    source_notes: str = Field(
        default="",
        description="High-level explanation of what sources were used",
    )

    model_config = {"extra": "ignore"}

    def to_store_dict(self) -> dict:
        """Return a dict suitable for JSONB storage (only non-empty fields)."""
        d = self.model_dump()
        return {k: v for k, v in d.items() if v is not None and v != "" and v != []}
