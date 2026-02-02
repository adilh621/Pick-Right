"""Gemini AI client service.

Primary key (GEMINI_API_KEY) is used for ai_context and ai_notes generation.
GEMINI_API_KEY2 is used only for the conversational chat endpoint.
"""

import logging
import re
from datetime import datetime, timedelta, timezone
from typing import Optional

from google import genai
from google.genai import errors as genai_errors

from app.core.config import settings

logger = logging.getLogger(__name__)

# Cooldown after 429 RESOURCE_EXHAUSTED; skip all Gemini calls until this time
_quota_cooldown_until: Optional[datetime] = None
# Separate cooldown for chat (GEMINI_API_KEY2) so key1 and key2 do not block each other
_quota_cooldown_until_chat: Optional[datetime] = None

# System instruction for PickRight AI (original, used by /ai/hello)
SYSTEM_INSTRUCTION = "You are PickRight, helpful and concise. Return markdown."

# Stricter system instruction for /ai/chat (non-hours queries)
STRICT_SYSTEM_INSTRUCTION = """You are PickRight, a helpful and concise assistant. Return markdown.

IMPORTANT RULES:
- Do NOT invent or guess facts like business hours, addresses, or phone numbers.
- Do NOT say "visit the website" or "check their website".
- If you are uncertain about specific details, ask a clarifying question instead.
- Be helpful but honest about what you don't know."""


def _is_quota_error(exc: BaseException) -> bool:
    """True if the exception is a 429 / RESOURCE_EXHAUSTED from the Gemini API."""
    if not isinstance(exc, genai_errors.ClientError):
        return False
    if getattr(exc, "code", None) == 429:
        return True
    status = getattr(exc, "status", None)
    if status and "RESOURCE_EXHAUSTED" in str(status).upper():
        return True
    return False


def _extract_retry_delay_seconds(exc: BaseException) -> Optional[int]:
    """
    Parse RetryInfo from error details if present.
    Returns delay in seconds, or None if not found.
    """
    details = getattr(exc, "details", None)
    if not details or not isinstance(details, dict):
        return None
    # details might be the full error object with nested "error" or a "details" list
    err = details.get("error", details)
    if not isinstance(err, dict):
        return None
    raw_list = err.get("details") if isinstance(err.get("details"), list) else None
    if not raw_list:
        return None
    for item in raw_list:
        if not isinstance(item, dict):
            continue
        if item.get("@type") == "type.googleapis.com/google.rpc.RetryInfo":
            delay_str = item.get("retryDelay")
            if delay_str is None:
                continue
            # Format is often "34s" or "60.123s"
            match = re.match(r"^(\d+(?:\.\d+)?)\s*s", str(delay_str).strip())
            if match:
                return int(float(match.group(1)))
    return None


def _should_skip_due_to_quota() -> bool:
    """True if we are still in the quota cooldown window."""
    global _quota_cooldown_until
    if _quota_cooldown_until is None:
        return False
    if datetime.now(timezone.utc) >= _quota_cooldown_until:
        _quota_cooldown_until = None
        return False
    return True


def _get_client() -> genai.Client:
    """Get Gemini client (GEMINI_API_KEY), raising error if API key not configured."""
    if not settings.gemini_api_key:
        raise ValueError("GEMINI_API_KEY missing")
    return genai.Client(api_key=settings.gemini_api_key)


def _should_skip_due_to_quota_chat() -> bool:
    """True if we are still in the chat quota cooldown window (GEMINI_API_KEY2)."""
    global _quota_cooldown_until_chat
    if _quota_cooldown_until_chat is None:
        return False
    if datetime.now(timezone.utc) >= _quota_cooldown_until_chat:
        _quota_cooldown_until_chat = None
        return False
    return True


def _get_client_chat() -> genai.Client:
    """Get Gemini client for chat (GEMINI_API_KEY2), raising error if API key not configured."""
    if not settings.gemini_api_key2:
        raise ValueError("GEMINI_API_KEY2 missing")
    return genai.Client(api_key=settings.gemini_api_key2)


def generate_text(prompt: str) -> Optional[str]:
    """
    Generate text using Gemini model (original system instruction).

    Args:
        prompt: The user prompt to send to the model.

    Returns:
        The generated text response, or None on quota/cooldown or transient failure.
    """
    return generate_text_with_system(prompt, SYSTEM_INSTRUCTION)


def generate_text_with_system(prompt: str, system_instruction: str) -> Optional[str]:
    """
    Generate text using Gemini model with custom system instruction.

    On 429 RESOURCE_EXHAUSTED, sets a module-level cooldown and returns None.
    During cooldown, skips the SDK call and returns None.

    Args:
        prompt: The user prompt to send to the model.
        system_instruction: Custom system instruction for the model.

    Returns:
        The generated text response, or None on quota exceeded, during cooldown,
        or if the API returns empty.
    """
    global _quota_cooldown_until

    if _should_skip_due_to_quota():
        logger.debug(
            "Skipping Gemini call due to recent quota exceeded; still in cooldown"
        )
        return None

    try:
        client = _get_client()
        model = settings.gemini_model

        logger.info("Calling Gemini model=%s, prompt_length=%s", model, len(prompt))

        response = client.models.generate_content(
            model=model,
            contents=prompt,
            config=genai.types.GenerateContentConfig(
                system_instruction=system_instruction,
            ),
        )

        result = response.text
        logger.info(
            "Gemini response_length=%s",
            len(result) if result else 0,
        )
        return result

    except genai_errors.ClientError as e:
        if _is_quota_error(e):
            retry_sec = _extract_retry_delay_seconds(e)
            cooldown_sec = retry_sec if retry_sec is not None else settings.gemini_quota_cooldown_seconds
            _quota_cooldown_until = datetime.now(timezone.utc) + timedelta(seconds=cooldown_sec)
            logger.warning(
                "Gemini quota exceeded (429 RESOURCE_EXHAUSTED); cooldown %s s. retryDelay=%s",
                cooldown_sec,
                retry_sec,
            )
            return None
        raise


def generate_text_with_system_chat(prompt: str, system_instruction: str) -> Optional[str]:
    """
    Generate text using Gemini model (GEMINI_API_KEY2) with custom system instruction.
    Used only for the conversational chat endpoint.

    On 429 RESOURCE_EXHAUSTED, sets the chat cooldown and returns None.
    During cooldown, skips the SDK call and returns None.

    Args:
        prompt: The user prompt (may include conversation history) to send to the model.
        system_instruction: Custom system instruction for the model.

    Returns:
        The generated text response, or None on quota exceeded, during cooldown,
        or if the API returns empty.
    """
    global _quota_cooldown_until_chat

    if _should_skip_due_to_quota_chat():
        logger.debug(
            "Skipping Gemini chat call due to recent quota exceeded; still in cooldown"
        )
        return None

    try:
        client = _get_client_chat()
        model = settings.gemini_model

        logger.info(
            "Calling Gemini chat model=%s, prompt_length=%s",
            model,
            len(prompt),
        )

        response = client.models.generate_content(
            model=model,
            contents=prompt,
            config=genai.types.GenerateContentConfig(
                system_instruction=system_instruction,
            ),
        )

        result = response.text
        logger.info(
            "Gemini chat response_length=%s",
            len(result) if result else 0,
        )
        return result

    except genai_errors.ClientError as e:
        if _is_quota_error(e):
            retry_sec = _extract_retry_delay_seconds(e)
            cooldown_sec = retry_sec if retry_sec is not None else settings.gemini_quota_cooldown_seconds
            _quota_cooldown_until_chat = datetime.now(timezone.utc) + timedelta(seconds=cooldown_sec)
            logger.warning(
                "Gemini chat quota exceeded (429 RESOURCE_EXHAUSTED); model=%s cooldown=%s s retryDelay=%s",
                settings.gemini_model,
                cooldown_sec,
                retry_sec,
            )
            return None
        raise
