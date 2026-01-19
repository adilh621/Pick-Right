from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.orm import Session
from uuid import UUID

from app.db.session import get_db
from app.models.user import User
from app.models.scan_session import ScanSession
from app.schemas.user import UserCreate, UserRead
from app.schemas.scan_session import ScanSessionRead

router = APIRouter(prefix="/users", tags=["users"])


@router.post("", response_model=UserRead, status_code=201)
def create_user(user: UserCreate, db: Session = Depends(get_db)):
    """Create a new user."""
    # Check if user with email or auth_provider_id already exists
    existing_user = db.query(User).filter(
        (User.email == user.email) | (User.auth_provider_id == user.auth_provider_id)
    ).first()
    if existing_user:
        raise HTTPException(status_code=400, detail="User with this email or auth_provider_id already exists")
    
    db_user = User(**user.model_dump())
    db.add(db_user)
    db.commit()
    db.refresh(db_user)
    return db_user


@router.get("/{user_id}", response_model=UserRead)
def get_user(user_id: UUID, db: Session = Depends(get_db)):
    """Get user by ID."""
    user = db.query(User).filter(User.id == user_id).first()
    if not user:
        raise HTTPException(status_code=404, detail="User not found")
    return user


@router.get("/{user_id}/scan-sessions", response_model=list[ScanSessionRead])
def list_user_scan_sessions(user_id: UUID, db: Session = Depends(get_db)):
    """List scan sessions for a user."""
    # Verify user exists
    user = db.query(User).filter(User.id == user_id).first()
    if not user:
        raise HTTPException(status_code=404, detail="User not found")
    
    scan_sessions = db.query(ScanSession).filter(ScanSession.user_id == user_id).all()
    return scan_sessions

