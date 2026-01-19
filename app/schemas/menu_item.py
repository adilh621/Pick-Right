from pydantic import BaseModel, ConfigDict
from uuid import UUID
from datetime import datetime
from typing import Optional, TYPE_CHECKING

if TYPE_CHECKING:
    from app.schemas.business import BusinessRead


class MenuItemBase(BaseModel):
    name: str
    item_type: str  # FOOD, DRINK, SERVICE, PERSON, OTHER
    total_mentions: int = 0
    positive_mentions: int = 0
    negative_mentions: int = 0
    avg_rating: Optional[float] = None
    top_positive_snippet: Optional[str] = None
    top_negative_snippet: Optional[str] = None


class MenuItemCreate(MenuItemBase):
    business_id: UUID


class MenuItemUpdate(BaseModel):
    name: Optional[str] = None
    item_type: Optional[str] = None
    total_mentions: Optional[int] = None
    positive_mentions: Optional[int] = None
    negative_mentions: Optional[int] = None
    avg_rating: Optional[float] = None
    top_positive_snippet: Optional[str] = None
    top_negative_snippet: Optional[str] = None


class MenuItemRead(MenuItemBase):
    id: UUID
    business_id: UUID
    created_at: datetime
    updated_at: datetime

    model_config = ConfigDict(from_attributes=True)


class MenuItemReadWithBusiness(MenuItemRead):
    business: Optional["BusinessRead"] = None

    model_config = ConfigDict(from_attributes=True)

