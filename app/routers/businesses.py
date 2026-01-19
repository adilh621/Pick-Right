from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy.orm import Session
from sqlalchemy import or_
from uuid import UUID
from typing import Optional

from app.db.session import get_db
from app.models.business import Business
from app.schemas.business import BusinessCreate, BusinessRead

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
    """Get business by ID."""
    business = db.query(Business).filter(Business.id == business_id).first()
    if not business:
        raise HTTPException(status_code=404, detail="Business not found")
    return business

