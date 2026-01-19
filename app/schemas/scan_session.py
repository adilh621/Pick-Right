from pydantic import BaseModel, ConfigDict
from uuid import UUID
from datetime import datetime
from typing import Optional


class ScanSessionBase(BaseModel):
    image_url: str
    detected_text_raw: str
    status: str  # PENDING, PROCESSING, COMPLETED, FAILED


class ScanSessionCreate(ScanSessionBase):
    user_id: Optional[UUID] = None
    device_id: Optional[str] = None
    business_id: Optional[UUID] = None


class ScanSessionUpdate(BaseModel):
    user_id: Optional[UUID] = None
    business_id: Optional[UUID] = None
    image_url: Optional[str] = None
    detected_text_raw: Optional[str] = None
    status: Optional[str] = None
    completed_at: Optional[datetime] = None


class ScanSessionRead(ScanSessionBase):
    id: UUID
    user_id: Optional[UUID] = None
    device_id: Optional[str] = None
    business_id: Optional[UUID] = None
    created_at: datetime
    completed_at: Optional[datetime] = None

    model_config = ConfigDict(from_attributes=True)

