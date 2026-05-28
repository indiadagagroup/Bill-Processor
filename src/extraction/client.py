"""
Gemini API client wrapper.

Thin abstraction over the google-generativeai SDK.
Handles authentication, image upload, structured JSON output,
and retry logic with exponential backoff.
"""

from __future__ import annotations

import time
from typing import Any

import google.generativeai as genai
from google.api_core import exceptions as google_exceptions

from src.utils.logger import get_logger

logger = get_logger(__name__)

# Retryable error types
_RETRYABLE_ERRORS = (
    google_exceptions.ResourceExhausted,
    google_exceptions.ServiceUnavailable,
    google_exceptions.DeadlineExceeded,
    ConnectionError,
    TimeoutError,
)


class GeminiClientError(Exception):
    """Raised when Gemini API calls fail after all retries."""


class GeminiClient:
    """Wrapper around Google's Generative AI SDK for vision tasks."""

    def __init__(
        self,
        api_key: str,
        model_name: str = "gemini-flash-latest",
        max_retries: int = 3,
        base_delay: float = 1.0,
    ) -> None:
        """Initialize the Gemini client.

        Args:
            api_key: Google AI API key.
            model_name: Model identifier to use.
            max_retries: Maximum number of retry attempts on transient errors.
            base_delay: Base delay in seconds for exponential backoff.
        """
        genai.configure(api_key=api_key)
        self._model = genai.GenerativeModel(model_name)
        self._max_retries = max_retries
        self._base_delay = base_delay
        logger.info("GeminiClient initialized with model '%s'", model_name)

    def extract_from_image(
        self,
        image_bytes: bytes,
        prompt: str,
        mime_type: str = "image/jpeg",
    ) -> dict[str, Any]:
        """Send an image + prompt to Gemini and return the structured JSON response.

        Args:
            image_bytes: Raw bytes of the bill image.
            prompt: The extraction prompt (built by prompts.py).
            mime_type: MIME type of the image.

        Returns:
            Parsed JSON dict from Gemini's response.

        Raises:
            GeminiClientError: If all retries are exhausted.
        """
        image_part = {
            "mime_type": mime_type,
            "data": image_bytes,
        }

        last_error: Exception | None = None

        for attempt in range(1, self._max_retries + 1):
            try:
                logger.info("Gemini API call attempt %d/%d", attempt, self._max_retries)

                response = self._model.generate_content(
                    [prompt, image_part],
                    generation_config=genai.GenerationConfig(
                        response_mime_type="application/json",
                        temperature=0.1,  # Low temperature for factual extraction
                    ),
                )

                # Parse the JSON response
                raw_text = response.text.strip()
                logger.debug("Raw Gemini response: %s", raw_text[:500])

                parsed = self._parse_json_response(raw_text)
                logger.info("Gemini extraction successful on attempt %d", attempt)
                return parsed

            except _RETRYABLE_ERRORS as exc:
                last_error = exc
                delay = self._base_delay * (2 ** (attempt - 1))
                logger.warning(
                    "Retryable error on attempt %d: %s. Retrying in %.1fs...",
                    attempt,
                    str(exc),
                    delay,
                )
                time.sleep(delay)

            except Exception as exc:
                # Non-retryable errors — fail immediately
                logger.error("Non-retryable Gemini error: %s", str(exc))
                raise GeminiClientError(f"Gemini API error: {exc}") from exc

        raise GeminiClientError(
            f"Gemini API failed after {self._max_retries} attempts. "
            f"Last error: {last_error}"
        )

    @staticmethod
    def _parse_json_response(raw_text: str) -> dict[str, Any]:
        """Parse JSON from Gemini's response, handling common formatting issues."""
        import json

        # Strip markdown code fences if present
        text = raw_text
        if text.startswith("```"):
            lines = text.split("\n")
            # Remove first and last lines (```json and ```)
            lines = [ln for ln in lines if not ln.strip().startswith("```")]
            text = "\n".join(lines)

        try:
            return json.loads(text)
        except json.JSONDecodeError as exc:
            logger.error("Failed to parse Gemini JSON response: %s", text[:200])
            raise GeminiClientError(
                f"Invalid JSON in Gemini response: {exc}"
            ) from exc
