from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy.orm import Session
from sqlalchemy import or_
from uuid import UUID
from typing import Optional

from app.db.session import get_db
from app.models.business import Business
from app.schemas.business import BusinessCreate, BusinessRead, BusinessAiNotesUpdate

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

