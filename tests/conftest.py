import pytest
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from fastapi.testclient import TestClient
from unittest.mock import patch, Mock
from datetime import datetime, timedelta, timezone
import jwt as pyjwt
from cryptography.hazmat.primitives import serialization
from cryptography.hazmat.primitives.asymmetric import rsa
from cryptography.hazmat.backends import default_backend
import base64
import json

from app.db.base import Base
from app.db.session import get_db
from app.main import app
from app.seed.seed_data import seed_db
from app.core.config import settings
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.dialects.sqlite import JSON as SQLiteJSON
from sqlalchemy import event


# Use SQLite in-memory database for testing
SQLALCHEMY_DATABASE_URL = "sqlite:///./test.db"

engine = create_engine(
    SQLALCHEMY_DATABASE_URL, connect_args={"check_same_thread": False}
)

# Override JSONB type compilation for SQLite
@event.listens_for(engine, "connect")
def set_sqlite_pragma(dbapi_conn, connection_record):
    """Set SQLite pragmas and override JSONB handling."""
    # Enable JSON support in SQLite
    dbapi_conn.execute("PRAGMA foreign_keys=ON")

# Monkey-patch JSONB to work with SQLite
import sqlalchemy.dialects.sqlite.base as sqlite_base
original_visit_JSONB = getattr(sqlite_base.SQLiteTypeCompiler, 'visit_JSONB', None)
if not original_visit_JSONB:
    def visit_JSONB(self, type_, **kw):
        return "JSON"
    sqlite_base.SQLiteTypeCompiler.visit_JSONB = visit_JSONB

# Monkey-patch postgresql.UUID to work with SQLite (store as CHAR(36))
if not getattr(sqlite_base.SQLiteTypeCompiler, 'visit_UUID', None):
    def visit_UUID(self, type_, **kw):
        return "CHAR(36)"
    sqlite_base.SQLiteTypeCompiler.visit_UUID = visit_UUID

TestingSessionLocal = sessionmaker(autocommit=False, autoflush=False, bind=engine)


@pytest.fixture(scope="function")
def db_session():
    """Create a fresh database for each test."""
    Base.metadata.create_all(bind=engine)
    db = TestingSessionLocal()
    try:
        yield db
    finally:
        db.close()
        Base.metadata.drop_all(bind=engine)


@pytest.fixture(scope="function")
def client(db_session):
    """Create a test client with database dependency override."""
    def override_get_db():
        try:
            yield db_session
        finally:
            pass
    
    app.dependency_overrides[get_db] = override_get_db
    client = TestClient(app)
    yield client
    app.dependency_overrides.clear()


@pytest.fixture(scope="function")
def seeded_db(db_session):
    """Create a database session with seeded data."""
    seed_db(db_session)
    return db_session


@pytest.fixture(scope="function")
def seeded_client(seeded_db):
    """Create a test client with seeded database."""
    def override_get_db():
        try:
            yield seeded_db
        finally:
            pass
    
    app.dependency_overrides[get_db] = override_get_db
    client = TestClient(app)
    yield client
    app.dependency_overrides.clear()


# Test JWT key pair (generated once)
_test_private_key = rsa.generate_private_key(
    public_exponent=65537,
    key_size=2048,
    backend=default_backend()
)
_test_public_key = _test_private_key.public_key()


def _create_test_jwks(public_key, kid="test-key-id"):
    """Create a test JWKS structure from a public key."""
    public_numbers = public_key.public_numbers()
    
    def int_to_base64url(n):
        byte_length = (n.bit_length() + 7) // 8
        n_bytes = n.to_bytes(byte_length, 'big')
        b64 = base64.urlsafe_b64encode(n_bytes).decode('utf-8')
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


def _create_test_token(
    private_key,
    sub="test-user-123",
    email="test@example.com",
    exp=None,
    aud=None,
    iss=None,
    kid="test-key-id"
):
    """Create a test JWT token with the given claims."""
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
    
    private_pem = private_key.private_bytes(
        encoding=serialization.Encoding.PEM,
        format=serialization.PrivateFormat.PKCS8,
        encryption_algorithm=serialization.NoEncryption()
    ).decode('utf-8')
    
    headers = {"kid": kid, "alg": "RS256", "typ": "JWT"}
    
    return pyjwt.encode(claims, private_pem, algorithm="RS256", headers=headers)


# Default test Supabase UIDs (valid UUIDs for external_auth_uid)
TEST_SUPABASE_UID_1 = "550e8400-e29b-41d4-a716-446655440000"
TEST_SUPABASE_UID_2 = "550e8400-e29b-41d4-a716-446655440001"
TEST_SUPABASE_UID_3 = "550e8400-e29b-41d4-a716-446655440002"


@pytest.fixture
def mock_jwks():
    """Fixture that mocks JWKS so JWT verification uses the test key."""
    test_jwks = _create_test_jwks(_test_public_key)
    with patch("app.core.auth.fetch_jwks", return_value=test_jwks):
        yield test_jwks


@pytest.fixture
def create_test_token():
    """Fixture that provides a function to create test JWT tokens. sub must be a valid UUID."""
    def _create(sub=TEST_SUPABASE_UID_1, email="test@example.com", **kwargs):
        return _create_test_token(_test_private_key, sub=sub, email=email, **kwargs)
    return _create

