"""
Tests for Supabase JWT authentication verification.
"""
import pytest
from unittest.mock import patch, MagicMock, Mock
from fastapi import status
from datetime import datetime, timedelta, timezone
import jwt as pyjwt
from cryptography.hazmat.primitives import serialization
from cryptography.hazmat.primitives.asymmetric import rsa
from cryptography.hazmat.backends import default_backend

from app.core.auth import verify_supabase_token, get_current_identity, get_jwks_client
from app.core.config import settings


# Generate RSA key pair for testing
def generate_test_keypair():
    """Generate a test RSA key pair."""
    private_key = rsa.generate_private_key(
        public_exponent=65537,
        key_size=2048,
        backend=default_backend()
    )
    public_key = private_key.public_key()
    
    # Serialize keys
    private_pem = private_key.private_bytes(
        encoding=serialization.Encoding.PEM,
        format=serialization.PrivateFormat.PKCS8,
        encryption_algorithm=serialization.NoEncryption()
    )
    
    public_pem = public_key.public_bytes(
        encoding=serialization.Encoding.PEM,
        format=serialization.PublicFormat.SubjectPublicKeyInfo
    )
    
    return private_key, public_key, private_pem, public_pem


# Generate keys once for all tests
_test_private_key, _test_public_key, _test_private_pem, _test_public_pem = generate_test_keypair()


def create_test_jwks(public_key, kid="test-key-id"):
    """Create a test JWKS structure from a public key."""
    # Extract modulus and exponent from public key
    public_numbers = public_key.public_numbers()
    
    # Convert integers to base64url-encoded strings
    def int_to_base64url(n):
        """Convert integer to base64url-encoded string."""
        import base64
        # Convert to bytes (big-endian)
        byte_length = (n.bit_length() + 7) // 8
        n_bytes = n.to_bytes(byte_length, 'big')
        # Base64 encode and convert to base64url
        b64 = base64.urlsafe_b64encode(n_bytes).decode('utf-8')
        # Remove padding
        return b64.rstrip('=')
    
    n = int_to_base64url(public_numbers.n)
    e = int_to_base64url(public_numbers.e)
    
    return {
        "keys": [
            {
                "kty": "RSA",
                "kid": kid,
                "use": "sig",
                "alg": "RS256",
                "n": n,
                "e": e
            }
        ]
    }


def create_test_token(
    private_key,
    sub="test-user-123",
    email="test@example.com",
    exp=None,
    aud=None,
    iss=None,
    kid="test-key-id"
):
    """
    Create a test JWT token with the given claims.
    
    Args:
        private_key: RSA private key for signing
        sub: Subject (user ID)
        email: Email address
        exp: Expiration time (default: 1 hour from now)
        aud: Audience (default: settings.supabase_jwt_audience)
        iss: Issuer (default: settings.supabase_issuer)
        kid: Key ID for header
    """
    if exp is None:
        exp = int((datetime.now(timezone.utc) + timedelta(hours=1)).timestamp())
    
    if aud is None:
        aud = settings.supabase_jwt_audience
    
    if iss is None:
        iss = settings.supabase_issuer
    
    claims = {
        "sub": sub,
        "email": email,
        "aud": aud,
        "iss": iss,
        "exp": exp,
        "iat": int(datetime.now(timezone.utc).timestamp()),
    }
    
    # Serialize private key to PEM for jwt.encode
    private_pem = private_key.private_bytes(
        encoding=serialization.Encoding.PEM,
        format=serialization.PrivateFormat.PKCS8,
        encryption_algorithm=serialization.NoEncryption()
    ).decode('utf-8')
    
    headers = {"kid": kid, "alg": "RS256", "typ": "JWT"}
    
    return pyjwt.encode(claims, private_pem, algorithm="RS256", headers=headers)


@pytest.fixture(autouse=True)
def reset_jwks_client():
    """Reset JWKS client before each test."""
    from app.core.auth import _jwks_client
    # Reset the global client
    import app.core.auth
    app.core.auth._jwks_client = None
    yield
    app.core.auth._jwks_client = None


@pytest.fixture
def mock_jwks_response():
    """Create a mock JWKS response."""
    jwks = create_test_jwks(_test_public_key)
    return jwks


def test_verify_valid_token(mock_jwks_response):
    """Test verification of a valid token."""
    from unittest.mock import Mock
    
    token = create_test_token(_test_private_key)
    
    # Create a mock signing key object
    mock_signing_key = Mock()
    mock_signing_key.key = _test_public_pem.decode('utf-8') if isinstance(_test_public_pem, bytes) else _test_public_pem
    
    # Mock PyJWKClient
    mock_jwks_client = Mock()
    mock_jwks_client.get_signing_key_from_jwt.return_value = mock_signing_key
    
    with patch('app.core.auth.get_jwks_client', return_value=mock_jwks_client):
        claims = verify_supabase_token(token)
        
        assert claims["sub"] == "test-user-123"
        assert claims["email"] == "test@example.com"


def test_verify_token_missing_kid(mock_jwks_response):
    """Test that token without kid in header is rejected."""
    # Create token without kid in header
    token = create_test_token(_test_private_key)
    
    # Manually create a token without kid
    import base64
    import json
    
    # Decode token parts
    parts = token.split('.')
    header = json.loads(base64.urlsafe_b64decode(parts[0] + '=='))
    header.pop('kid', None)
    
    # Re-encode header without kid
    header_b64 = base64.urlsafe_b64encode(
        json.dumps(header).encode('utf-8')
    ).decode('utf-8').rstrip('=')
    
    # Reconstruct token (this will have invalid signature, but we test kid first)
    invalid_token = f"{header_b64}.{parts[1]}.{parts[2]}"
    
    # Mock PyJWKClient to raise an error when kid is missing
    mock_jwks_client = Mock()
    mock_jwks_client.get_signing_key_from_jwt.side_effect = Exception("Key ID not found")
    
    with patch('app.core.auth.get_jwks_client', return_value=mock_jwks_client):
        with pytest.raises(Exception):  # Should fail when trying to get kid
            verify_supabase_token(invalid_token)


def test_verify_token_wrong_issuer(mock_jwks_response):
    """Test that token with wrong issuer is rejected."""
    from unittest.mock import Mock
    
    token = create_test_token(
        _test_private_key,
        iss="https://wrong-issuer.com/auth/v1"
    )
    
    # Create a mock signing key object
    mock_signing_key = Mock()
    mock_signing_key.key = _test_public_pem.decode('utf-8') if isinstance(_test_public_pem, bytes) else _test_public_pem
    
    # Mock PyJWKClient
    mock_jwks_client = Mock()
    mock_jwks_client.get_signing_key_from_jwt.return_value = mock_signing_key
    
    with patch('app.core.auth.get_jwks_client', return_value=mock_jwks_client):
        with pytest.raises(Exception):  # Should raise HTTPException
            verify_supabase_token(token)


def test_verify_token_wrong_audience(mock_jwks_response):
    """Test that token with wrong audience is rejected."""
    from unittest.mock import Mock
    
    token = create_test_token(
        _test_private_key,
        aud="wrong-audience"
    )
    
    # Create a mock signing key object
    mock_signing_key = Mock()
    mock_signing_key.key = _test_public_pem.decode('utf-8') if isinstance(_test_public_pem, bytes) else _test_public_pem
    
    # Mock PyJWKClient
    mock_jwks_client = Mock()
    mock_jwks_client.get_signing_key_from_jwt.return_value = mock_signing_key
    
    with patch('app.core.auth.get_jwks_client', return_value=mock_jwks_client):
        with pytest.raises(Exception):  # Should raise HTTPException
            verify_supabase_token(token)


def test_verify_token_expired(mock_jwks_response):
    """Test that expired token is rejected."""
    from unittest.mock import Mock
    
    # Create token that expired 1 hour ago
    exp = int((datetime.now(timezone.utc) - timedelta(hours=1)).timestamp())
    token = create_test_token(_test_private_key, exp=exp)
    
    # Create a mock signing key object
    mock_signing_key = Mock()
    mock_signing_key.key = _test_public_pem.decode('utf-8') if isinstance(_test_public_pem, bytes) else _test_public_pem
    
    # Mock PyJWKClient
    mock_jwks_client = Mock()
    mock_jwks_client.get_signing_key_from_jwt.return_value = mock_signing_key
    
    with patch('app.core.auth.get_jwks_client', return_value=mock_jwks_client):
        with pytest.raises(Exception):  # Should raise HTTPException
            verify_supabase_token(token)


def test_verify_token_key_not_in_jwks():
    """Test that token with key ID not in JWKS is rejected."""
    from unittest.mock import Mock
    
    token = create_test_token(_test_private_key, kid="non-existent-key-id")
    
    # Mock PyJWKClient to raise an error when key is not found
    mock_jwks_client = Mock()
    mock_jwks_client.get_signing_key_from_jwt.side_effect = Exception("Key not found")
    
    with patch('app.core.auth.get_jwks_client', return_value=mock_jwks_client):
        with pytest.raises(Exception):  # Should raise HTTPException
            verify_supabase_token(token)


def test_get_current_identity_extracts_claims(mock_jwks_response):
    """Test that get_current_identity extracts claims correctly."""
    from fastapi.security import HTTPAuthorizationCredentials
    from unittest.mock import Mock
    
    token = create_test_token(_test_private_key, sub="user-456", email="user@test.com")
    credentials = HTTPAuthorizationCredentials(scheme="Bearer", credentials=token)
    
    # Create a mock signing key object
    mock_signing_key = Mock()
    mock_signing_key.key = _test_public_pem.decode('utf-8') if isinstance(_test_public_pem, bytes) else _test_public_pem
    
    # Mock PyJWKClient
    mock_jwks_client = Mock()
    mock_jwks_client.get_signing_key_from_jwt.return_value = mock_signing_key
    
    with patch('app.core.auth.get_jwks_client', return_value=mock_jwks_client):
        identity = get_current_identity(credentials)
        
        assert identity.uid == "user-456"
        assert identity.email == "user@test.com"
        assert identity.provider == "supabase"  # Default provider


def test_get_current_identity_missing_token():
    """Test that missing token raises 401."""
    from fastapi.security import HTTPAuthorizationCredentials
    
    credentials = HTTPAuthorizationCredentials(scheme="Bearer", credentials="")
    
    with pytest.raises(Exception):  # Should raise HTTPException
        get_current_identity(credentials)

