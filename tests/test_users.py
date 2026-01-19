import pytest
from fastapi import status


def test_create_user(client):
    """Test creating a user."""
    response = client.post(
        "/api/v1/users",
        json={
            "auth_provider_id": "test_provider_123",
            "email": "test@example.com"
        }
    )
    assert response.status_code == status.HTTP_201_CREATED
    data = response.json()
    assert data["email"] == "test@example.com"
    assert data["auth_provider_id"] == "test_provider_123"
    assert "id" in data
    assert "created_at" in data


def test_get_user(seeded_client):
    """Test getting a user by ID."""
    # First, create a user to get its ID
    create_response = seeded_client.post(
        "/api/v1/users",
        json={
            "auth_provider_id": "test_get_user",
            "email": "gettest@example.com"
        }
    )
    user_id = create_response.json()["id"]
    
    # Now get the user
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

