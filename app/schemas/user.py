from pydantic import BaseModel, ConfigDict, model_validator
from uuid import UUID
from datetime import datetime
from typing import Optional, Dict, Any, TYPE_CHECKING

if TYPE_CHECKING:
    from app.schemas.scan_session import ScanSessionRead


class UserBase(BaseModel):
    auth_provider_id: Optional[str] = None
    email: Optional[str] = None


class UserCreate(UserBase):
    pass


class UserUpdate(BaseModel):
    auth_provider_id: Optional[str] = None
    email: Optional[str] = None


class UserRead(BaseModel):
    id: UUID
    external_auth_provider: Optional[str] = None
    external_auth_uid: Optional[str] = None
    onboarding_preferences: Optional[Dict[str, Any]] = None
    onboarding_completed_at: Optional[datetime] = None
    created_at: Optional[datetime] = None
    updated_at: Optional[datetime] = None
    # Legacy fields (for backward compatibility)
    auth_provider_id: Optional[str] = None
    email: Optional[str] = None

    model_config = ConfigDict(from_attributes=True)


class UserReadWithSessions(UserRead):
    scan_sessions: list["ScanSessionRead"] = []

    model_config = ConfigDict(from_attributes=True)


# New schemas for /me endpoints
class MeRead(UserRead):
    """Response model for GET /me endpoint."""
    pass


class UserPreferencesUpdate(BaseModel):
    """Request model for updating user preferences (supports partial updates).
    
    Accepts:
    - onboarding_preferences: Optional JSONB dict with user preferences
    - onboarding_completed_at: Optional ISO datetime string to set specific completion time
    
    Both fields are optional to support partial updates. However, if onboarding_completed_at
    is provided, onboarding_preferences must also be provided.
    
    If onboarding_preferences is missing but other fields (like place_interests, intent_selections, etc.)
    are present, they will be automatically wrapped into onboarding_preferences.
    
    If onboarding_completed_at is omitted and onboarding_preferences is provided,
    it will be set to the current time.
    
    Example with both fields:
    ```json
    {
        "onboarding_preferences": {"dietary_restrictions": ["vegetarian"]},
        "onboarding_completed_at": "2024-01-15T10:30:00Z"
    }
    ```
    
    Example with only onboarding_preferences (onboarding_completed_at will be set to now):
    ```json
    {
        "onboarding_preferences": {"dietary_restrictions": ["vegetarian"]}
    }
    ```
    
    Example with flattened fields (backward compatibility):
    ```json
    {
        "place_interests": ["restaurants", "cafes"],
        "intent_selections": ["dining"]
    }
    ```
    """
    onboarding_preferences: Optional[Dict[str, Any]] = None
    onboarding_completed_at: Optional[str] = None  # ISO datetime string
    
    # Allow extra fields for flattened payload support
    model_config = ConfigDict(extra="allow")
    
    @model_validator(mode="before")
    @classmethod
    def wrap_flattened_fields(cls, data: Any) -> Any:
        """Wrap flattened fields into onboarding_preferences if needed."""
        if isinstance(data, dict):
            # If onboarding_preferences is already present, return as-is
            if "onboarding_preferences" in data and data["onboarding_preferences"] is not None:
                return data
            
            # Check if there are any fields that look like flattened preferences
            # (i.e., fields other than onboarding_completed_at)
            excluded_fields = {"onboarding_completed_at", "onboarding_completed"}
            flattened_fields = {
                k: v for k, v in data.items()
                if k not in excluded_fields and v is not None
            }
            
            # If we have flattened fields, wrap them into onboarding_preferences
            if flattened_fields:
                wrapped_data = {
                    "onboarding_preferences": flattened_fields,
                    "onboarding_completed_at": data.get("onboarding_completed_at")
                }
                return wrapped_data
        
        return data
    
    @model_validator(mode="after")
    def validate_consistency(self) -> "UserPreferencesUpdate":
        """Validate that if onboarding_completed_at is provided, onboarding_preferences must also be provided."""
        if self.onboarding_completed_at is not None and self.onboarding_preferences is None:
            raise ValueError("onboarding_preferences is required when onboarding_completed_at is provided")
        return self


class GuestUpgradeRequest(BaseModel):
    """Request model for upgrading guest sessions to user."""
    device_id: str


class OnboardingUpdate(BaseModel):
    """Request model for saving onboarding answers."""
    answers: Dict[str, Any]


class OnboardingRead(BaseModel):
    """Response model for getting onboarding answers."""
    answers: Optional[Dict[str, Any]] = None
    completed: bool = False
    completed_at: Optional[str] = None

