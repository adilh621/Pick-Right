import logging
from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy.orm import Session
from datetime import datetime, timezone

from app.db.session import get_db
from app.core.auth import get_current_user
from app.models.user import User
from app.models.scan_session import ScanSession
from app.schemas.user import (
    MeRead,
    OnboardingPreferences,
    UserPreferencesUpdate,
    GuestUpgradeRequest,
    OnboardingRead,
    OnboardingUpdate,
)

logger = logging.getLogger(__name__)
router = APIRouter(prefix="/me", tags=["me"])


@router.get("", response_model=MeRead)
def get_me(
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db)
):
    """
    Get the authenticated user's profile.
    User is resolved by auth (get_current_user); this route only reads,
    never creates users.
    """
    return MeRead.model_validate(current_user)


@router.put("/preferences", response_model=MeRead)
def update_preferences(
    preferences: UserPreferencesUpdate,
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db)
):
    """
    Update the authenticated user's onboarding preferences (supports partial updates).
    Always operates on the User returned by get_current_user; never creates new users.
    
    Supports partial updates:
    - Both `onboarding_preferences` and `onboarding_completed_at` are optional
    - If `onboarding_completed_at` is provided, `onboarding_preferences` must also be provided
    - If `onboarding_preferences` is provided but `onboarding_completed_at` is omitted, 
      `onboarding_completed_at` will be automatically set to the current time
    - Only updates fields that are provided in the request
    - Updates `updated_at` timestamp when changes are made
    - Returns fresh user data from database after update
    
    Supports flattened payload format for backward compatibility:
    ```json
    {
        "place_interests": ["restaurants"],
        "intent_selections": ["dining"]
    }
    ```
    
    Or nested format:
    ```json
    {
        "onboarding_preferences": {"dietary_restrictions": ["vegetarian"]},
        "onboarding_completed_at": "2024-01-15T10:30:00Z"
    }
    ```
    
    Example curl:
    ```bash
    curl -X PUT http://localhost:8000/api/v1/me/preferences \\
      -H "Authorization: Bearer <token>" \\
      -H "Content-Type: application/json" \\
      -d '{
        "onboarding_preferences": {"dietary_restrictions": ["vegetarian"]},
        "onboarding_completed_at": "2024-01-15T10:30:00Z"
      }'
    ```
    """
    logger.info(f"Updating preferences for user id={current_user.id}, external_auth_uid={current_user.external_auth_uid}, email={current_user.email}")
    
    # Track if any changes were made
    has_changes = False
    now = datetime.now(timezone.utc)
    
    # Handle onboarding_preferences (partial update support): normalize to canonical shape
    if preferences.onboarding_preferences is not None:
        existing = current_user.onboarding_preferences or {}
        if isinstance(existing, dict):
            merged = {**existing, **preferences.onboarding_preferences}
        else:
            merged = preferences.onboarding_preferences
        canonical = OnboardingPreferences.model_validate(merged)
        current_user.onboarding_preferences = canonical.model_dump(exclude_none=True)
        has_changes = True
        prefs_keys = list(current_user.onboarding_preferences.keys())
        logger.info(f"Updating onboarding_preferences (canonical): keys={prefs_keys}")
    
    # Handle onboarding_completed_at (partial update support)
    if preferences.onboarding_completed_at is not None:
        try:
            # Parse ISO datetime string into timezone-aware datetime
            parsed_dt = datetime.fromisoformat(preferences.onboarding_completed_at.replace('Z', '+00:00'))
            # Ensure it's timezone-aware (if not, assume UTC)
            if parsed_dt.tzinfo is None:
                parsed_dt = parsed_dt.replace(tzinfo=timezone.utc)
            # Convert to UTC if needed
            completed_at = parsed_dt.astimezone(timezone.utc)
            current_user.onboarding_completed_at = completed_at
            has_changes = True
            logger.info(f"Updating onboarding_completed_at to: {completed_at.isoformat()}")
        except (ValueError, TypeError, AttributeError) as e:
            logger.error(f"Invalid datetime format for onboarding_completed_at: {e}")
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail=f"Invalid datetime format for onboarding_completed_at. Expected ISO 8601 format (e.g., '2024-01-15T10:30:00Z'): {str(e)}"
            )
    elif preferences.onboarding_preferences is not None:
        # If onboarding_completed_at omitted but onboarding_preferences provided, set to now
        current_user.onboarding_completed_at = now
        has_changes = True
        logger.info(f"Setting onboarding_completed_at to now (omitted in request but onboarding_preferences provided)")
    
    # Only update updated_at if there were actual changes
    if has_changes:
        current_user.updated_at = now
        
        # Commit the update
        db.commit()
        
        # Log the update summary
        logger.info(
            f"Committed update for user id={current_user.id}, external_auth_uid={current_user.external_auth_uid}: "
            f"onboarding_preferences={'updated' if preferences.onboarding_preferences is not None else 'unchanged'}, "
            f"onboarding_completed_at={'updated' if preferences.onboarding_completed_at is not None or (preferences.onboarding_preferences is not None and preferences.onboarding_completed_at is None) else 'unchanged'}"
        )
        
        # Fresh read from database to ensure consistency (DB-level confirmation)
        db.refresh(current_user)
        
        # Verify the update was persisted (DB-level confirmation)
        updated_user = db.query(User).filter(User.id == current_user.id).first()
        if not updated_user:
            logger.error(f"User not found after update, id={current_user.id}")
            raise HTTPException(
                status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
                detail="User not found after update"
            )
        
        logger.info(
            f"Successfully updated user id={updated_user.id}: "
            f"onboarding_preferences={'set' if updated_user.onboarding_preferences else 'null'}, "
            f"onboarding_completed_at={'set' if updated_user.onboarding_completed_at else 'null'}, "
            f"updated_at={updated_user.updated_at.isoformat() if updated_user.updated_at else 'null'}"
        )
        
        return updated_user
    else:
        # No changes made, return current user as-is
        logger.info(f"No changes to apply for user id={current_user.id}")
        return current_user


@router.post("/upgrade-guest", status_code=200)
def upgrade_guest(
    request: GuestUpgradeRequest,
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db)
):
    """
    Upgrade guest scan sessions to the authenticated user.
    
    Requires Bearer token in Authorization header.
    
    Finds all ScanSessions with the given device_id and null user_id,
    and assigns them to the current user.
    
    Returns the number of migrated scan sessions.
    """
    # Find all guest sessions with this device_id and no user_id
    guest_sessions = db.query(ScanSession).filter(
        ScanSession.device_id == request.device_id,
        ScanSession.user_id.is_(None)
    ).all()
    
    if not guest_sessions:
        return {"migrated_scan_sessions": 0}
    
    # Assign all sessions to current user
    for session in guest_sessions:
        session.user_id = current_user.id
        # Optionally clear device_id after migration
        # session.device_id = None
    
    db.commit()
    
    return {"migrated_scan_sessions": len(guest_sessions)}


@router.get("/onboarding", response_model=OnboardingRead)
def get_onboarding(
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db)
):
    """
    Get the authenticated user's onboarding answers.
    Reads from the User instance returned by auth; no user creation here.
    """
    return OnboardingRead(
        answers=current_user.onboarding_preferences,
        completed=current_user.onboarding_completed_at is not None,
        completed_at=current_user.onboarding_completed_at.isoformat() if current_user.onboarding_completed_at else None
    )


@router.put("/onboarding", response_model=MeRead)
def update_onboarding(
    request: OnboardingUpdate,
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db)
):
    """
    Save onboarding answers for the authenticated user.
    Works even if preferences are currently NULL. Overwrites onboarding_preferences
    with the request payload and always sets onboarding_completed_at to now.
    """
    now = datetime.now(timezone.utc)

    logger.info(f"Updating onboarding for user id={current_user.id}, answers_keys={list(request.answers.keys()) if request.answers else []}")

    canonical = OnboardingPreferences.model_validate(request.answers)
    current_user.onboarding_preferences = canonical.model_dump(exclude_none=True)
    current_user.onboarding_completed_at = now
    current_user.updated_at = now

    db.add(current_user)
    db.commit()
    db.refresh(current_user)

    logger.info(f"Onboarding saved for user id={current_user.id}")

    return MeRead.model_validate(current_user)

