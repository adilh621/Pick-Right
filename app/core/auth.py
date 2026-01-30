import logging
import time
from typing import Optional, Dict, Any
from fastapi import Depends, HTTPException, status
from fastapi.security import HTTPBearer, HTTPAuthorizationCredentials
from sqlalchemy.orm import Session
from pydantic import BaseModel
import httpx
from jose import jwt, jwk
from jose.exceptions import JWTError, JWKError, ExpiredSignatureError, JWTClaimsError

from app.db.session import get_db
from app.models.user import User
from app.core.config import settings

logger = logging.getLogger(__name__)

# Security scheme for Bearer token
security = HTTPBearer()

# JWKS cache with TTL
_jwks_cache: Optional[Dict[str, Any]] = None
_jwks_cache_time: float = 0
JWKS_CACHE_TTL = 600  # 10 minutes in seconds


def fetch_jwks() -> Dict[str, Any]:
    """
    Fetch JWKS from Supabase endpoint.
    
    Returns:
        JWKS dictionary with 'keys' list
        
    Raises:
        HTTPException: If JWKS fetch fails
    """
    global _jwks_cache, _jwks_cache_time
    
    # Check cache
    current_time = time.time()
    if _jwks_cache is not None and (current_time - _jwks_cache_time) < JWKS_CACHE_TTL:
        logger.debug("Using cached JWKS")
        return _jwks_cache
    
    # Fetch fresh JWKS
    try:
        logger.info(f"Fetching JWKS from {settings.supabase_jwks_url}")
        response = httpx.get(settings.supabase_jwks_url, timeout=10.0)
        response.raise_for_status()
        jwks_data = response.json()
        
        # Validate JWKS structure
        if not isinstance(jwks_data, dict) or "keys" not in jwks_data:
            raise ValueError("Invalid JWKS structure: missing 'keys' field")
        
        # Update cache
        _jwks_cache = jwks_data
        _jwks_cache_time = current_time
        logger.info(f"JWKS fetched successfully, {len(jwks_data.get('keys', []))} keys found")
        
        return jwks_data
        
    except httpx.HTTPError as e:
        logger.error(f"Failed to fetch JWKS: {e}")
        # If we have cached data, use it even if expired
        if _jwks_cache is not None:
            logger.warning("Using expired JWKS cache due to fetch failure")
            return _jwks_cache
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail="Unable to verify token: JWKS endpoint unavailable"
        )
    except Exception as e:
        logger.error(f"Unexpected error fetching JWKS: {e}")
        if _jwks_cache is not None:
            logger.warning("Using expired JWKS cache due to unexpected error")
            return _jwks_cache
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail="Unable to verify token: JWKS fetch failed"
        )


def get_signing_key(token: str, jwks: Dict[str, Any]) -> Dict[str, Any]:
    """
    Extract kid from token header and find matching key in JWKS.
    
    Args:
        token: JWT token string
        jwks: JWKS dictionary
        
    Returns:
        JWK dictionary for the signing key
        
    Raises:
        HTTPException: If kid not found or key not in JWKS
    """
    try:
        # Decode header without verification to get kid
        unverified_header = jwt.get_unverified_header(token)
        kid = unverified_header.get("kid")
        alg = unverified_header.get("alg", "ES256")
        
        if not kid:
            logger.warning("Token missing 'kid' in header")
            raise HTTPException(
                status_code=status.HTTP_401_UNAUTHORIZED,
                detail="Token verification failed"
            )
        
        # Find key with matching kid
        for key in jwks.get("keys", []):
            if key.get("kid") == kid:
                logger.debug(f"Found matching key for kid: {kid}, alg: {alg}")
                return key
        
        logger.warning(f"Key ID '{kid}' not found in JWKS")
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Token verification failed"
        )
        
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Error extracting key ID from token: {e}")
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Token verification failed"
        )


class Identity(BaseModel):
    """Represents the authenticated identity from the token."""
    provider: str
    uid: str
    email: Optional[str] = None


def verify_supabase_token(token: str) -> dict:
    """
    Verify Supabase JWT token and extract claims.
    
    Args:
        token: JWT token string
        
    Returns:
        Dict containing verified token claims
        
    Raises:
        HTTPException: If token verification fails
    """
    try:
        # Fetch JWKS (with caching)
        jwks = fetch_jwks()
        
        # Get signing key from token header (kid)
        jwk_key = get_signing_key(token, jwks)
        
        # Convert JWK to key object for verification
        try:
            # jose.jwk.construct() creates a key object from JWK
            key = jwk.construct(jwk_key)
        except JWKError as e:
            logger.error(f"Failed to construct key from JWK: {e}")
            raise HTTPException(
                status_code=status.HTTP_401_UNAUTHORIZED,
                detail="Token verification failed"
            )
        
        # Get algorithm from header or JWK
        unverified_header = jwt.get_unverified_header(token)
        header_alg = unverified_header.get("alg")
        jwk_alg = jwk_key.get("alg")
        
        # Use algorithm from header, fallback to JWK, default to ES256
        algorithm = header_alg or jwk_alg or "ES256"
        
        # Validate algorithm matches between header and JWK (if both present)
        if header_alg and jwk_alg and header_alg != jwk_alg:
            logger.warning(f"Algorithm mismatch: header={header_alg}, JWK={jwk_alg}")
            raise HTTPException(
                status_code=status.HTTP_401_UNAUTHORIZED,
                detail="Token verification failed"
            )
        
        # Supported algorithms (Supabase uses ES256, but support RS256 for compatibility)
        supported_algorithms = ["ES256", "RS256"]
        if algorithm not in supported_algorithms:
            logger.warning(f"Unsupported algorithm: {algorithm}")
            raise HTTPException(
                status_code=status.HTTP_401_UNAUTHORIZED,
                detail="Token verification failed"
            )
        
        # Verify and decode the token
        try:
            payload = jwt.decode(
                token,
                key,
                algorithms=supported_algorithms,
                audience=settings.supabase_jwt_audience,
                issuer=settings.supabase_issuer,
                options={
                    "verify_signature": True,
                    "verify_aud": True,
                    "verify_iss": True,
                    "verify_exp": True,
                }
            )
            
            logger.debug(f"Token verified successfully for sub: {payload.get('sub')}")
            return payload
            
        except ExpiredSignatureError:
            logger.warning("Token has expired")
            raise HTTPException(
                status_code=status.HTTP_401_UNAUTHORIZED,
                detail="Token verification failed"
            )
        except JWTClaimsError as e:
            logger.warning(f"Token claims validation failed: {e}")
            raise HTTPException(
                status_code=status.HTTP_401_UNAUTHORIZED,
                detail="Token verification failed"
            )
        except JWTError as e:
            logger.warning(f"JWT verification error: {e}")
            raise HTTPException(
                status_code=status.HTTP_401_UNAUTHORIZED,
                detail="Token verification failed"
            )
        
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Unexpected error during token verification: {e}", exc_info=True)
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Token verification failed"
        )


def get_current_identity(
    credentials: HTTPAuthorizationCredentials = Depends(security)
) -> Identity:
    """
    Extract and verify identity from Supabase Bearer token.
    
    Verifies JWT signature using Supabase JWKS, validates issuer, audience,
    and expiration, then extracts user identity from claims.
    
    Args:
        credentials: HTTP Bearer token credentials
        
    Returns:
        Identity object with provider, uid, and optional email
        
    Raises:
        HTTPException: If token is missing, invalid, or verification fails
    """
    token = credentials.credentials
    
    if not token:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Missing token"
        )
    
    # Verify token and get claims
    claims = verify_supabase_token(token)
    
    # Extract user ID (sub claim)
    uid = claims.get("sub")
    if not uid:
        logger.warning("Token missing subject (sub) claim")
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Token missing subject (sub) claim"
        )
    
    # Extract email if present
    email = claims.get("email")
    
    # Extract provider from app_metadata (Supabase stores provider here for OAuth)
    app_metadata = claims.get("app_metadata", {})
    provider = app_metadata.get("provider")
    
    # Fallback: check user_metadata or default to "email" for email/password, "oauth" for others
    if not provider:
        user_metadata = claims.get("user_metadata", {})
        if "provider" in user_metadata:
            provider = user_metadata["provider"]
        else:
            # Default based on auth method - if no provider info, default to "email" or "oauth"
            # For Google OAuth, app_metadata.provider should be "google"
            provider = "email"  # Default fallback for email/password auth
    
    logger.info(f"Authenticated user: sub={uid}, email={email}, provider={provider}")
    
    return Identity(
        provider=provider,
        uid=uid,
        email=email
    )


def get_current_user_optional(
    credentials: HTTPAuthorizationCredentials | None = Depends(HTTPBearer(auto_error=False)),
    db: Session = Depends(get_db)
) -> User | None:
    """
    Get current user if authenticated, otherwise return None.
    
    Use this for endpoints that work for both guests and authenticated users.
    """
    if not credentials or not credentials.credentials:
        return None
    
    try:
        # Verify token and get claims
        claims = verify_supabase_token(credentials.credentials)
        uid = claims.get("sub")
        if not uid:
            return None
        
        # Look up user
        user = db.query(User).filter(User.external_auth_uid == uid).first()
        return user
    except HTTPException:
        # Invalid token - treat as guest
        return None
    except Exception as e:
        logger.warning(f"Error in optional auth: {e}")
        return None


def get_current_user(
    identity: Identity = Depends(get_current_identity),
    db: Session = Depends(get_db)
) -> User:
    """
    Get or create user based on external auth identity (idempotent).
    
    Looks up user by external_auth_uid. If not found, creates a new user
    with email and provider information. Ensures all required fields are set.
    
    Args:
        identity: Identity from token
        db: Database session
        
    Returns:
        User model instance
    """
    # Look up user by external_auth_uid (should match Supabase "sub")
    user = db.query(User).filter(
        User.external_auth_uid == identity.uid
    ).first()
    
    if not user:
        # Create new user with external auth info
        logger.info(f"Creating new user for external_auth_uid={identity.uid}, provider={identity.provider}, email={identity.email}")
        user = User(
            external_auth_provider=identity.provider or "email",
            external_auth_uid=identity.uid,
            email=identity.email  # Set email from JWT
        )
        db.add(user)
        db.commit()
        db.refresh(user)
        logger.info(f"Created user: id={user.id}, external_auth_uid={user.external_auth_uid}")
    else:
        # User exists - update email if we have it and user doesn't
        was_updated = False
        if identity.email and not user.email:
            logger.info(f"Updating email for existing user id={user.id}, external_auth_uid={identity.uid}")
            user.email = identity.email
            was_updated = True
        
        # Update provider if missing
        if not user.external_auth_provider and identity.provider:
            logger.info(f"Updating provider for existing user id={user.id}, provider={identity.provider}")
            user.external_auth_provider = identity.provider
            was_updated = True
        
        if was_updated:
            db.commit()
            db.refresh(user)
    
    return user

