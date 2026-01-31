import pytest
from fastapi import status


def test_create_user(client):
    """Test creating a user (programmatic; requires external_auth_uid)."""
    response = client.post(
        "/api/v1/users",
        json={
            "external_auth_uid": "73af4eb5-1d0f-4391-9ae4-9319fb2bb944",
            "auth_provider_id": "test_provider_123",
            "email": "test@example.com",
        },
    )
    assert response.status_code == status.HTTP_201_CREATED
    data = response.json()
    assert data["email"] == "test@example.com"
    assert data["auth_provider_id"] == "test_provider_123"
    assert data["external_auth_uid"] == "73af4eb5-1d0f-4391-9ae4-9319fb2bb944"
    assert "id" in data
    assert "created_at" in data


def test_get_user(seeded_client):
    """Test getting a user by ID."""
    create_response = seeded_client.post(
        "/api/v1/users",
        json={
            "external_auth_uid": "a1b2c3d4-e5f6-7890-abcd-ef1234567890",
            "auth_provider_id": "test_get_user",
            "email": "gettest@example.com",
        },
    )
    user_id = create_response.json()["id"]
    response = seeded_client.get(f"/api/v1/users/{user_id}")
    assert response.status_code == status.HTTP_200_OK
    data = response.json()
    assert data["id"] == user_id
    assert data["email"] == "gettest@example.com"


def test_get_user_not_found(seeded_client):
    """Test getting a non-existent user."""
    import uuid
    fake_id = uuid.uuid4()
    response = seeded_client.get(f"/api/v1/users/{fake_id}")
    assert response.status_code == status.HTTP_404_NOT_FOUND

