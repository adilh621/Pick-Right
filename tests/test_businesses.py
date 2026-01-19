import pytest
from fastapi import status


def test_create_business(client):
    """Test creating a business."""
    response = client.post(
        "/api/v1/businesses",
        json={
            "name": "Test Restaurant",
            "category": "restaurant",
            "address_full": "123 Test St"
        }
    )
    assert response.status_code == status.HTTP_201_CREATED
    data = response.json()
    assert data["name"] == "Test Restaurant"
    assert data["category"] == "restaurant"
    assert "id" in data


def test_list_businesses(seeded_client):
    """Test listing businesses."""
    response = seeded_client.get("/api/v1/businesses")
    assert response.status_code == status.HTTP_200_OK
    data = response.json()
    assert isinstance(data, list)
    assert len(data) >= 2  # At least 2 from seed data


def test_list_businesses_with_filter(seeded_client):
    """Test listing businesses with name filter."""
    response = seeded_client.get("/api/v1/businesses?name=Pizza")
    assert response.status_code == status.HTTP_200_OK
    data = response.json()
    assert isinstance(data, list)
    # Should find "Tony's Pizza"
    assert any("Pizza" in business["name"] for business in data)


def test_get_business(seeded_client):
    """Test getting a business by ID."""
    # Create a business first
    create_response = seeded_client.post(
        "/api/v1/businesses",
        json={"name": "Test Business"}
    )
    business_id = create_response.json()["id"]
    
    response = seeded_client.get(f"/api/v1/businesses/{business_id}")
    assert response.status_code == status.HTTP_200_OK
    data = response.json()
    assert data["id"] == business_id
    assert data["name"] == "Test Business"

