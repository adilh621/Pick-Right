from datetime import datetime, timedelta, timezone

from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy.orm import Session
from sqlalchemy import or_
from uuid import UUID
from typing import Optional

from app.core.auth import get_current_user
from app.db.session import get_db
from app.models.business import Business
from app.models.user import User
from app.schemas.business import (
    BusinessCreate,
    BusinessRead,
    BusinessAiNotesUpdate,
    BusinessAIInsightsResponse,
)

router = APIRouter(prefix="/businesses", tags=["businesses"])


@router.post("", response_model=BusinessRead, status_code=201)
def create_business(business: BusinessCreate, db: Session = Depends(get_db)):
    """Create a new business."""
    db_business = Business(**business.model_dump())
    db.add(db_business)
    db.commit()
    db.refresh(db_business)
    return db_business


@router.get("", response_model=list[BusinessRead])
def list_businesses(
    name: Optional[str] = Query(None, description="Search by business name"),
    db: Session = Depends(get_db)
):
    """List businesses with optional name filter."""
    query = db.query(Business)
    if name:
        query = query.filter(Business.name.ilike(f"%{name}%"))
    return query.all()


@router.get("/{business_id}", response_model=BusinessRead)
def get_business(business_id: UUID, db: Session = Depends(get_db)):
    """
    Get business by ID.
    Response includes address, state, latitude, longitude, and ai_notes when set.
    ai_notes are AI-generated summaries intended for injection into the AI chat context
    (e.g. top-mentioned items, halal/vegetarian notes, atmosphere).
    """
    business = db.query(Business).filter(Business.id == business_id).first()
    if not business:
        raise HTTPException(status_code=404, detail="Business not found")
    return business


@router.get("/{business_id}/ai-insights", response_model=BusinessAIInsightsResponse)
def get_business_ai_insights(
    business_id: UUID,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
) -> BusinessAIInsightsResponse:
    """
    Get AI insights status and data for a business. Lightweight; frontend polls
    after GET /places/details returns ai_status="pending" to know when AI is ready.
    """
    business = db.query(Business).filter(Business.id == business_id).first()
    if not business:
        raise HTTPException(status_code=404, detail="Business not found")

    now = datetime.now(timezone.utc)
    last_updated = business.ai_context_last_updated
    if last_updated is not None and last_updated.tzinfo is None:
        last_updated = last_updated.replace(tzinfo=timezone.utc)
    ai_ttl_hours = 24
    has_fresh_ai = (
        business.ai_notes
        and business.ai_notes.strip()
        and business.ai_context is not None
        and last_updated is not None
        and (now - last_updated) <= timedelta(hours=ai_ttl_hours)
    )

    if has_fresh_ai:
        return BusinessAIInsightsResponse(
            business_id=business.id,
            ai_status="ready",
            ai_notes=business.ai_notes,
            ai_context=business.ai_context,
        )
    # Missing or stale; no error tracking yet, so we use "pending"
    return BusinessAIInsightsResponse(
        business_id=business.id,
        ai_status="pending",
        ai_notes=None,
        ai_context=None,
    )


@router.patch("/{business_id}/ai-notes", response_model=BusinessRead)
def update_business_ai_notes(
    business_id: UUID,
    body: BusinessAiNotesUpdate,
    db: Session = Depends(get_db),
):
    """
    Update the ai_notes field for a business.
    ai_notes are meant to be injected into the AI chat context (e.g. top-mentioned items,
    special notes about halal, atmosphere, etc.). Used by the app or internal admin tools.
    Returns the full updated business row including id and ai_notes.
    """
    business = db.query(Business).filter(Business.id == business_id).first()
    if not business:
        raise HTTPException(status_code=404, detail="Business not found")
    business.ai_notes = body.ai_notes
    db.commit()
    db.refresh(business)
    return business

