from pydantic import BaseModel, ConfigDict, model_validator, model_serializer
from uuid import UUID
from datetime import datetime
from typing import Optional, Dict, Any, Union, List, TYPE_CHECKING

if TYPE_CHECKING:
    from app.schemas.scan_session import ScanSessionRead


class OnboardingPreferences(BaseModel):
    """
    Canonical schema for onboarding_preferences.
    Used for GET /me response, PUT /me/preferences payload, and PUT /me/onboarding.
    Accepts legacy keys on input (intent_selections → intents, priority_selections → priorities);
    output always uses canonical keys only (intents, priorities).
    """
    companion: Optional[str] = None
    intents: Optional[List[str]] = None
    priorities: Optional[List[str]] = None
    place_interests: Optional[List[str]] = None
    travel_frequency: Optional[str] = None
    exploration_level: Optional[float] = None
    dietary_restrictions: Optional[List[str]] = None

    model_config = ConfigDict(extra="allow")

    @model_validator(mode="before")
    @classmethod
    def map_legacy_keys(cls, data: Any) -> Any:
        """Map legacy keys to canonical: intent_selections → intents, priority_selections → priorities."""
        if not isinstance(data, dict):
            return data
        data = dict(data)
        if data.get("intents") is None and data.get("intent_selections") is not None:
            data["intents"] = data["intent_selections"]
        if data.get("priorities") is None and data.get("priority_selections") is not None:
            data["priorities"] = data["priority_selections"]
        return data

    @model_serializer
    def _serialize_exclude_none(self):
        """Emit only set fields; never include legacy keys (they are not model fields)."""
        return {k: getattr(self, k) for k in self.model_fields if getattr(self, k) is not None}


class UserBase(BaseModel):
    auth_provider_id: Optional[str] = None
    email: Optional[str] = None


class UserCreate(UserBase):
    """For programmatic/create-user API only. Auth flow uses get_or_create_user_for_supabase_uid."""
    external_auth_uid: Union[str, UUID]  # Required; 1:1 with Supabase JWT sub


class UserUpdate(BaseModel):
    auth_provider_id: Optional[str] = None
    email: Optional[str] = None


class UserRead(BaseModel):
    id: UUID
    external_auth_provider: Optional[str] = None
    external_auth_uid: Optional[Union[str, UUID]] = None  # JWT sub; UUID in DB, str in API
    onboarding_preferences: Optional[OnboardingPreferences] = None
    onboarding_completed_at: Optional[datetime] = None
    created_at: Optional[datetime] = None
    updated_at: Optional[datetime] = None
    # Legacy fields (for backward compatibility)
    auth_provider_id: Optional[str] = None
    email: Optional[str] = None
    needs_onboarding: bool = False

    model_config = ConfigDict(from_attributes=True)

    @model_validator(mode="after")
    def set_needs_onboarding(self) -> "UserRead":
        """needs_onboarding is True iff onboarding_completed_at is NULL (source of truth for iOS)."""
        self.needs_onboarding = self.onboarding_completed_at is None
        return self


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

