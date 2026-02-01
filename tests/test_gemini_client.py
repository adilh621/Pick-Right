"""Tests for Gemini client: 429 handling and cooldown."""

from datetime import datetime, timezone, timedelta
from unittest.mock import MagicMock, patch

import pytest
from google.genai import errors as genai_errors

from app.services import gemini_client


class _MockResponse429:
    """Minimal mock response that produces 429 RESOURCE_EXHAUSTED in ClientError."""
    body_segments = [{"error": {"code": 429, "status": "RESOURCE_EXHAUSTED", "message": "quota exceeded"}}]


def test_429_sets_cooldown_and_returns_none():
    """
    When the SDK raises ClientError 429 RESOURCE_EXHAUSTED,
    generate_text_with_system sets the module cooldown and returns None.
    """
    # Reset cooldown so we are not already in cooldown
    gemini_client._quota_cooldown_until = None

    def raise_429(*args, **kwargs):
        raise genai_errors.ClientError(429, _MockResponse429())

    with patch.object(gemini_client, "_get_client") as mock_get_client:
        mock_client = MagicMock()
        mock_client.models.generate_content = raise_429
        mock_get_client.return_value = mock_client

        result = gemini_client.generate_text_with_system("test prompt", "system")

    assert result is None
    assert gemini_client._quota_cooldown_until is not None
    assert gemini_client._quota_cooldown_until > datetime.now(timezone.utc)


def test_cooldown_skips_call_and_returns_none():
    """
    When in cooldown, generate_text_with_system does not call the SDK
    and returns None.
    """
    gemini_client._quota_cooldown_until = datetime.now(timezone.utc) + timedelta(seconds=60)

    try:
        with patch.object(gemini_client, "_get_client") as mock_get_client:
            result = gemini_client.generate_text_with_system("test prompt", "system")

        assert result is None
        mock_get_client.assert_not_called()
    finally:
        gemini_client._quota_cooldown_until = None


def test_success_returns_text():
    """When the SDK returns text, generate_text_with_system returns it."""
    gemini_client._quota_cooldown_until = None

    mock_response = MagicMock()
    mock_response.text = "Hello from Gemini"

    with patch.object(gemini_client, "_get_client") as mock_get_client:
        mock_client = MagicMock()
        mock_client.models.generate_content = MagicMock(return_value=mock_response)
        mock_get_client.return_value = mock_client

        result = gemini_client.generate_text_with_system("test prompt", "system")

    assert result == "Hello from Gemini"
