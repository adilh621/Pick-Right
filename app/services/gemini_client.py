"""Gemini AI client service."""

import logging
from google import genai

from app.core.config import settings

logger = logging.getLogger(__name__)

# System instruction for PickRight AI (original, used by /ai/hello)
SYSTEM_INSTRUCTION = "You are PickRight, helpful and concise. Return markdown."

# Stricter system instruction for /ai/chat (non-hours queries)
STRICT_SYSTEM_INSTRUCTION = """You are PickRight, a helpful and concise assistant. Return markdown.

IMPORTANT RULES:
- Do NOT invent or guess facts like business hours, addresses, or phone numbers.
- Do NOT say "visit the website" or "check their website".
- If you are uncertain about specific details, ask a clarifying question instead.
- Be helpful but honest about what you don't know."""


def _get_client() -> genai.Client:
    """Get Gemini client, raising error if API key not configured."""
    if not settings.gemini_api_key:
        raise ValueError("GEMINI_API_KEY missing")
    return genai.Client(api_key=settings.gemini_api_key)


def generate_text(prompt: str) -> str:
    """
    Generate text using Gemini model (original system instruction).
    
    Args:
        prompt: The user prompt to send to the model.
        
    Returns:
        The generated text response.
        
    Raises:
        ValueError: If GEMINI_API_KEY is not configured.
        Exception: If the API call fails.
    """
    return generate_text_with_system(prompt, SYSTEM_INSTRUCTION)


def generate_text_with_system(prompt: str, system_instruction: str) -> str:
    """
    Generate text using Gemini model with custom system instruction.
    
    Args:
        prompt: The user prompt to send to the model.
        system_instruction: Custom system instruction for the model.
        
    Returns:
        The generated text response.
        
    Raises:
        ValueError: If GEMINI_API_KEY is not configured.
        Exception: If the API call fails.
    """
    client = _get_client()
    model = settings.gemini_model
    
    logger.info(f"Calling Gemini model={model}, prompt_length={len(prompt)}")
    
    response = client.models.generate_content(
        model=model,
        contents=prompt,
        config=genai.types.GenerateContentConfig(
            system_instruction=system_instruction,
        ),
    )
    
    result = response.text
    logger.info(f"Gemini response_length={len(result) if result else 0}")
    
    return result

