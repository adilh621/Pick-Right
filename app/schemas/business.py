from pydantic import BaseModel, ConfigDict
from uuid import UUID
from datetime import datetime
from typing import Optional, TYPE_CHECKING

if TYPE_CHECKING:
    from app.schemas.menu_item import MenuItemRead
    from app.schemas.scan_session import ScanSessionRead


class BusinessBase(BaseModel):
    name: str
    external_id_yelp: Optional[str] = None
    external_id_google: Optional[str] = None
    address_full: Optional[str] = None
    lat: Optional[float] = None
    lng: Optional[float] = None
    category: Optional[str] = None


class BusinessCreate(BusinessBase):
    pass


class BusinessUpdate(BaseModel):
    name: Optional[str] = None
    external_id_yelp: Optional[str] = None
    external_id_google: Optional[str] = None
    address_full: Optional[str] = None
    lat: Optional[float] = None
    lng: Optional[float] = None
    category: Optional[str] = None


class BusinessRead(BusinessBase):
    id: UUID
    created_at: datetime

    model_config = ConfigDict(from_attributes=True)


class BusinessReadWithItems(BusinessRead):
    menu_items: list["MenuItemRead"] = []
    scan_sessions: list["ScanSessionRead"] = []

    model_config = ConfigDict(from_attributes=True)

