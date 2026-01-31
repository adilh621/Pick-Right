from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.orm import Session
from uuid import UUID

from app.db.session import get_db
from app.models.user import User
from app.models.scan_session import ScanSession
from app.schemas.user import UserCreate, UserRead
from app.schemas.scan_session import ScanSessionRead

router = APIRouter(prefix="/users", tags=["users"])


def _normalize_uid(uid: UUID | str) -> str:
    if isinstance(uid, UUID):
        return str(uid)
    return str(UUID(str(uid)))


@router.post("", response_model=UserRead, status_code=201)
def create_user(user: UserCreate, db: Session = Depends(get_db)):
    """Create a new user (programmatic only). Prefer auth flow for real users."""
    uid_str = _normalize_uid(user.external_auth_uid)
    existing = db.query(User).filter(
        (User.external_auth_uid == uid_str)
        | (User.email == user.email)
        | (User.auth_provider_id == user.auth_provider_id)
    ).first()
    if existing:
        raise HTTPException(status_code=400, detail="User with this external_auth_uid, email or auth_provider_id already exists")
    data = user.model_dump()
    data["external_auth_uid"] = uid_str
    db_user = User(**data)
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

