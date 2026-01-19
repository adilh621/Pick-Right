from pydantic import BaseModel, ConfigDict
from uuid import UUID
from datetime import datetime
from typing import Optional, TYPE_CHECKING

if TYPE_CHECKING:
    from app.schemas.scan_session import ScanSessionRead
    from app.schemas.menu_item import MenuItemRead


class RecommendationItemBase(BaseModel):
    rank: int
    is_recommended: bool
    recommendation_label: str  # HIGHLY_RECOMMENDED, RECOMMENDED, NOT_RECOMMENDED
    display_mention_count: int
    display_avg_rating: Optional[float] = None
    display_positive_snippet: Optional[str] = None
    display_negative_snippet: Optional[str] = None


class RecommendationItemCreate(RecommendationItemBase):
    menu_item_id: UUID


class RecommendationItemBulkCreate(BaseModel):
    items: list[RecommendationItemCreate]


class RecommendationItemUpdate(BaseModel):
    rank: Optional[int] = None
    is_recommended: Optional[bool] = None
    recommendation_label: Optional[str] = None
    display_mention_count: Optional[int] = None
    display_avg_rating: Optional[float] = None
    display_positive_snippet: Optional[str] = None
    display_negative_snippet: Optional[str] = None


class RecommendationItemRead(RecommendationItemBase):
    id: UUID
    scan_session_id: UUID
    menu_item_id: UUID
    created_at: datetime

    model_config = ConfigDict(from_attributes=True)


class RecommendationItemReadWithRelations(RecommendationItemRead):
    scan_session: Optional["ScanSessionRead"] = None
    menu_item: Optional["MenuItemRead"] = None

    model_config = ConfigDict(from_attributes=True)

