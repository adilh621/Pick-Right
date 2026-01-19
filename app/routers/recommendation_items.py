from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.orm import Session
from uuid import UUID

from app.db.session import get_db
from app.models.recommendation_item import RecommendationItem
from app.models.scan_session import ScanSession
from app.models.menu_item import MenuItem
from app.schemas.recommendation_item import (
    RecommendationItemCreate,
    RecommendationItemRead,
    RecommendationItemBulkCreate,
)

router = APIRouter(tags=["recommendations"])


@router.post("/scan-sessions/{scan_session_id}/recommendations", response_model=list[RecommendationItemRead], status_code=201)
def create_recommendation_items(
    scan_session_id: UUID,
    bulk_create: RecommendationItemBulkCreate,
    db: Session = Depends(get_db)
):
    """Create recommendation items for a scan session (bulk)."""
    # Verify scan session exists
    scan_session = db.query(ScanSession).filter(ScanSession.id == scan_session_id).first()
    if not scan_session:
        raise HTTPException(status_code=404, detail="Scan session not found")
    
    # Verify all menu items exist
    menu_item_ids = {item.menu_item_id for item in bulk_create.items}
    existing_menu_items = db.query(MenuItem).filter(MenuItem.id.in_(menu_item_ids)).all()
    existing_ids = {item.id for item in existing_menu_items}
    missing_ids = menu_item_ids - existing_ids
    if missing_ids:
        raise HTTPException(
            status_code=404,
            detail=f"Menu items not found: {missing_ids}"
        )
    
    # Create recommendation items
    db_items = []
    for item_data in bulk_create.items:
        item_dict = item_data.model_dump()
        item_dict["scan_session_id"] = scan_session_id
        db_item = RecommendationItem(**item_dict)
        db.add(db_item)
        db_items.append(db_item)
    
    db.commit()
    for db_item in db_items:
        db.refresh(db_item)
    
    return db_items


@router.get("/scan-sessions/{scan_session_id}/recommendations", response_model=list[RecommendationItemRead])
def get_recommendation_items(scan_session_id: UUID, db: Session = Depends(get_db)):
    """Get recommendation items for a scan session."""
    # Verify scan session exists
    scan_session = db.query(ScanSession).filter(ScanSession.id == scan_session_id).first()
    if not scan_session:
        raise HTTPException(status_code=404, detail="Scan session not found")
    
    recommendation_items = (
        db.query(RecommendationItem)
        .filter(RecommendationItem.scan_session_id == scan_session_id)
        .order_by(RecommendationItem.rank)
        .all()
    )
    return recommendation_items

