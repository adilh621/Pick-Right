from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.orm import Session
from uuid import UUID

from app.db.session import get_db
from app.models.scan_session import ScanSession
from app.models.user import User
from app.models.business import Business
from app.schemas.scan_session import ScanSessionCreate, ScanSessionRead

router = APIRouter(prefix="/scan-sessions", tags=["scan-sessions"])


@router.post("", response_model=ScanSessionRead, status_code=201)
def create_scan_session(scan_session: ScanSessionCreate, db: Session = Depends(get_db)):
    """Create a new scan session."""
    # Enforce: at least one of user_id or device_id must be set
    if not scan_session.user_id and not scan_session.device_id:
        raise HTTPException(
            status_code=400,
            detail="Either user_id or device_id must be provided"
        )
    
    # Verify user exists if provided
    if scan_session.user_id:
        user = db.query(User).filter(User.id == scan_session.user_id).first()
        if not user:
            raise HTTPException(status_code=404, detail="User not found")
    
    # Verify business exists if provided
    if scan_session.business_id:
        business = db.query(Business).filter(Business.id == scan_session.business_id).first()
        if not business:
            raise HTTPException(status_code=404, detail="Business not found")
    
    db_scan_session = ScanSession(**scan_session.model_dump())
    db.add(db_scan_session)
    db.commit()
    db.refresh(db_scan_session)
    return db_scan_session


@router.get("/{scan_session_id}", response_model=ScanSessionRead)
def get_scan_session(scan_session_id: UUID, db: Session = Depends(get_db)):
    """Get scan session by ID."""
    scan_session = db.query(ScanSession).filter(ScanSession.id == scan_session_id).first()
    if not scan_session:
        raise HTTPException(status_code=404, detail="Scan session not found")
    return scan_session

