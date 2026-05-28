"""
Main extraction orchestrator.

Coordinates the full extraction pipeline:
  Image bytes → Gemini client → JSON → Pydantic model → Validated BillData
"""

from __future__ import annotations

from src.extraction.client import GeminiClient, GeminiClientError
from src.extraction.prompts import build_extraction_prompt
from src.models.bill import BillData
from src.models.schema_loader import (
    get_all_entry_type_keys,
    get_display_name,
)
from src.utils.validators import (
    compute_confidence,
    get_required_field_names,
    validate_no_inferred_values,
)
from src.utils.logger import get_logger

logger = get_logger(__name__)


class ExtractionError(Exception):
    """Raised when extraction fails."""


class BillExtractor:
    """Orchestrates bill image extraction using Gemini Vision."""

    def __init__(self, gemini_client: GeminiClient) -> None:
        """Initialize the extractor.

        Args:
            gemini_client: Configured GeminiClient instance.
        """
        self._client = gemini_client
        self._prompt = build_extraction_prompt()
        logger.info("BillExtractor initialized")

    def extract(
        self,
        image_bytes: bytes,
        telegram_file_id: str = "",
        mime_type: str = "image/jpeg",
    ) -> BillData:
        """Extract structured data from a bill image.

        Args:
            image_bytes: Raw image bytes.
            telegram_file_id: Telegram file ID for reference tracking.
            mime_type: Image MIME type.

        Returns:
            Validated BillData instance.

        Raises:
            ExtractionError: If extraction or parsing fails.
        """
        try:
            logger.info("Starting extraction for image (file_id=%s)", telegram_file_id)

            # Step 1: Call Gemini
            raw_result = self._client.extract_from_image(
                image_bytes=image_bytes,
                prompt=self._prompt,
                mime_type=mime_type,
            )

            # Step 2: Validate entry type
            entry_type = raw_result.get("entry_type", "general_entry")
            valid_types = get_all_entry_type_keys()

            if entry_type not in valid_types:
                logger.warning(
                    "Gemini returned unknown entry type '%s', falling back to 'general_entry'",
                    entry_type,
                )
                entry_type = "general_entry"

            # Step 3: Clean specific fields (FR-GS-7)
            specific_fields = raw_result.get("specific_fields", {})
            specific_fields = validate_no_inferred_values(specific_fields)

            # Step 4: Compute confidence
            required_fields = get_required_field_names(entry_type)
            bill_data = BillData(
                entry_type=entry_type,
                entry_type_display=get_display_name(entry_type),
                supplier_name=str(raw_result.get("supplier_name", "")),
                supplier_gstin=str(raw_result.get("supplier_gstin", "")),
                bill_number=str(raw_result.get("bill_number", "")),
                bill_date=str(raw_result.get("bill_date", "")),
                total_amount=str(raw_result.get("total_amount", "")),
                currency=str(raw_result.get("currency", "INR")),
                source="Telegram",
                image_reference=telegram_file_id,
                specific_fields=specific_fields,
            )

            filled, total = bill_data.count_filled_required_fields(required_fields)
            bill_data.confidence = compute_confidence(filled, total)

            logger.info(
                "Extraction complete: type=%s, confidence=%s, filled=%d/%d required fields",
                entry_type,
                bill_data.confidence,
                filled,
                total,
            )

            return bill_data

        except GeminiClientError as exc:
            logger.error("Gemini extraction failed: %s", str(exc))
            raise ExtractionError(f"Failed to extract data from image: {exc}") from exc
        except Exception as exc:
            logger.error("Unexpected extraction error: %s", str(exc))
            raise ExtractionError(f"Extraction error: {exc}") from exc
