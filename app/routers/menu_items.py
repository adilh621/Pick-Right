from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.orm import Session
from uuid import UUID

from app.db.session import get_db
from app.models.menu_item import MenuItem
from app.models.business import Business
from app.schemas.menu_item import MenuItemCreate, MenuItemRead

router = APIRouter(tags=["menu-items"])


@router.post("/businesses/{business_id}/menu-items", response_model=MenuItemRead, status_code=201)
def create_menu_item(
    business_id: UUID,
    menu_item: MenuItemCreate,
    db: Session = Depends(get_db)
):
    """Create a menu item under a business."""
    # Verify business exists
    business = db.query(Business).filter(Business.id == business_id).first()
    if not business:
        raise HTTPException(status_code=404, detail="Business not found")
    
    # Override business_id from path
    menu_item_data = menu_item.model_dump()
    menu_item_data["business_id"] = business_id
    
    db_menu_item = MenuItem(**menu_item_data)
    db.add(db_menu_item)
    db.commit()
    db.refresh(db_menu_item)
    return db_menu_item


@router.get("/businesses/{business_id}/menu-items", response_model=list[MenuItemRead])
def list_menu_items(business_id: UUID, db: Session = Depends(get_db)):
    """List menu items for a business."""
    # Verify business exists
    business = db.query(Business).filter(Business.id == business_id).first()
    if not business:
        raise HTTPException(status_code=404, detail="Business not found")
    
    menu_items = db.query(MenuItem).filter(MenuItem.business_id == business_id).all()
    return menu_items


@router.get("/menu-items/{menu_item_id}", response_model=MenuItemRead)
def get_menu_item(menu_item_id: UUID, db: Session = Depends(get_db)):
    """Get menu item by ID."""
    menu_item = db.query(MenuItem).filter(MenuItem.id == menu_item_id).first()
    if not menu_item:
        raise HTTPException(status_code=404, detail="Menu item not found")
    return menu_item

