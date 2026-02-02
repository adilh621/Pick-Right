from pydantic import Field
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    database_url: str
    project_name: str = "PickRight API"
    api_v1_prefix: str = "/api/v1"
    
    # Supabase authentication configuration
    # SUPABASE_URL: Full Supabase project URL (e.g., https://xxx.supabase.co)
    #   Used to derive JWKS URL and issuer for JWT verification
    supabase_url: str
    
    # SUPABASE_JWT_AUDIENCE: JWT audience claim to validate (default: "authenticated")
    #   Supabase access tokens typically have aud="authenticated"
    supabase_jwt_audience: str = "authenticated"
    
    # Debug flag for debug endpoint gating
    debug: bool = Field(default=False, alias="DEBUG")
    
    # Google Maps API key for Places API proxy endpoints (optional)
    google_maps_api_key: str | None = None
    
    # Gemini AI configuration (optional)
    # gemini_api_key: used for ai_context and ai_notes generation (places, business_context, ai_notes_service)
    gemini_api_key: str | None = None
    # gemini_api_key2: used only for the conversational chat endpoint (POST /api/v1/chat/business/{id})
    gemini_api_key2: str | None = None
    gemini_model: str = "gemini-2.5-flash"
    # Cooldown in seconds after 429 RESOURCE_EXHAUSTED; used when RetryInfo not present
    gemini_quota_cooldown_seconds: int = 60
    
    @property
    def supabase_jwks_url(self) -> str:
        """Derive JWKS URL from Supabase URL."""
        return f"{self.supabase_url.rstrip('/')}/auth/v1/.well-known/jwks.json"
    
    @property
    def supabase_issuer(self) -> str:
        """Derive issuer from Supabase URL."""
        return f"{self.supabase_url.rstrip('/')}/auth/v1"
    
    model_config = SettingsConfigDict(
        env_file=".env",
        env_file_encoding="utf-8",
        case_sensitive=False,
        extra="forbid"
    )


settings = Settings()

