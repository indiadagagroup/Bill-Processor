"""
Main extraction orchestrator.

Coordinates the full two-pass extraction pipeline:
  Pass 1: Image bytes → Classification prompt → Gemini → entry_type + supplier + reasoning
  Pass 2: Image bytes → Type-specific prompt  → Gemini → specific fields
  Merge:  Combine results → Pydantic model → Validated BillData

The two-pass approach dramatically improves accuracy because:
  - Pass 1 focuses solely on classification with chain-of-thought reasoning
  - Pass 2 uses a type-specific prompt that only asks for relevant fields
  - Supplier vs buyer identification uses spatial/visual analysis
"""

from __future__ import annotations

from src.extraction.client import GeminiClient, GeminiClientError
from src.extraction.prompts import (
    build_classification_prompt,
    build_extraction_prompt,
)
from src.models.bill import BillData
from src.models.schema_loader import (
    get_all_entry_type_keys,
    get_display_name,
)
from src.models.schemas_pydantic import (
    build_classification_schema,
    build_extraction_schema,
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
    """Orchestrates bill image extraction using Gemini Vision.

    Uses a two-pass approach:
    1. Classification pass — identifies document type with chain-of-thought
    2. Extraction pass — extracts type-specific fields
    """

    def __init__(self, gemini_client: GeminiClient) -> None:
        """Initialize the extractor.

        Args:
            gemini_client: Configured GeminiClient instance.
        """
        self._client = gemini_client
        # Build prompts and schemas (classification prompt is static)
        self._classification_prompt = build_classification_prompt()
        self._classification_schema = build_classification_schema()
        logger.info("BillExtractor initialized (two-pass mode)")

    def extract(
        self,
        image_bytes: bytes,
        telegram_file_id: str = "",
        mime_type: str = "image/jpeg",
    ) -> BillData:
        """Extract structured data from a bill image using two-pass pipeline.

        Pass 1: Classify the document and identify supplier/buyer.
        Pass 2: Extract type-specific fields.

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
            logger.info("Starting two-pass extraction for image (file_id=%s)", telegram_file_id)

            # ============================================================
            # PASS 1: Classification + supplier/buyer identification
            # ============================================================
            classification = self._classify(image_bytes, mime_type)

            entry_type = classification.get("entry_type", "general_entry")
            supplier_name = str(classification.get("supplier_name", ""))
            buyer_name = str(classification.get("buyer_name", ""))
            reasoning = str(classification.get("reasoning", ""))

            # Log the classification reasoning for debugging
            logger.info(
                "Pass 1 — Classification: type=%s, supplier='%s', buyer='%s'",
                entry_type,
                supplier_name,
                buyer_name,
            )
            if reasoning:
                logger.info("Pass 1 — Reasoning: %s", reasoning[:500])

            # Validate entry type
            valid_types = get_all_entry_type_keys()
            if entry_type not in valid_types:
                logger.warning(
                    "Gemini returned unknown entry type '%s', falling back to 'general_entry'",
                    entry_type,
                )
                entry_type = "general_entry"

            # Sanity check: warn if supplier looks like it might be the buyer
            if supplier_name and buyer_name:
                if supplier_name.strip().lower() == buyer_name.strip().lower():
                    logger.warning(
                        "Supplier and buyer names are identical ('%s') — this may be an error",
                        supplier_name,
                    )

            # ============================================================
            # PASS 2: Type-specific field extraction
            # ============================================================
            specific_fields = self._extract_fields(
                image_bytes=image_bytes,
                mime_type=mime_type,
                entry_type=entry_type,
                supplier_name=supplier_name,
            )

            # Clean specific fields (FR-GS-7)
            specific_fields = validate_no_inferred_values(specific_fields)

            # ============================================================
            # MERGE: Combine results into BillData
            # ============================================================
            required_fields = get_required_field_names(entry_type)
            bill_data = BillData(
                entry_type=entry_type,
                entry_type_display=get_display_name(entry_type),
                supplier_name=supplier_name,
                supplier_gstin=str(classification.get("supplier_gstin", "")),
                bill_number=str(classification.get("bill_number", "")),
                bill_date=str(classification.get("bill_date", "")),
                total_amount=str(classification.get("total_amount", "")),
                currency=str(classification.get("currency", "INR")),
                source="Telegram",
                image_reference=telegram_file_id,
                specific_fields=specific_fields,
            )

            filled, total = bill_data.count_filled_required_fields(required_fields)
            bill_data.confidence = compute_confidence(filled, total)

            logger.info(
                "Extraction complete: type=%s, supplier='%s', confidence=%s, filled=%d/%d required fields",
                entry_type,
                supplier_name,
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

    def _classify(
        self,
        image_bytes: bytes,
        mime_type: str,
    ) -> dict:
        """Pass 1: Classify the document and identify supplier/buyer.

        Uses chain-of-thought reasoning and response_schema enforcement
        to ensure accurate classification.

        Args:
            image_bytes: Raw image bytes.
            mime_type: Image MIME type.

        Returns:
            Dict with keys: reasoning, entry_type, supplier_name, buyer_name,
            supplier_gstin, bill_number, bill_date, total_amount, currency.
        """
        logger.info("Pass 1 — Classifying document...")

        result = self._client.extract_from_image(
            image_bytes=image_bytes,
            prompt=self._classification_prompt,
            mime_type=mime_type,
            response_schema=self._classification_schema,
        )

        return result

    def _extract_fields(
        self,
        image_bytes: bytes,
        mime_type: str,
        entry_type: str,
        supplier_name: str = "",
    ) -> dict:
        """Pass 2: Extract type-specific fields.

        Uses a prompt tailored to the classified entry type and a
        response_schema that only includes the relevant fields.

        Args:
            image_bytes: Raw image bytes.
            mime_type: Image MIME type.
            entry_type: The classified entry type key.
            supplier_name: Supplier name from Pass 1 (for context).

        Returns:
            Dict of specific field name → extracted value.
        """
        logger.info("Pass 2 — Extracting fields for type '%s'...", entry_type)

        extraction_prompt = build_extraction_prompt(
            entry_type=entry_type,
            supplier_name=supplier_name,
        )
        extraction_schema = build_extraction_schema(entry_type)

        result = self._client.extract_from_image(
            image_bytes=image_bytes,
            prompt=extraction_prompt,
            mime_type=mime_type,
            response_schema=extraction_schema,
        )

        # Extract specific_fields from the response
        raw_specific_fields = result.get("specific_fields", {})

        # If result came back flat (no specific_fields wrapper), use the whole dict
        if not raw_specific_fields and result:
            # Filter out any metadata keys
            raw_specific_fields = {
                k: v for k, v in result.items()
                if k != "specific_fields"
            }

        # Map safe keys back to original sheet column names
        from src.models.schema_loader import build_specific_field_list
        fields = build_specific_field_list(entry_type)
        key_map = {f["safe_name"]: f["name"] for f in fields}

        specific_fields = {}
        for safe_key, value in raw_specific_fields.items():
            original_name = key_map.get(safe_key, safe_key)
            specific_fields[original_name] = value

        logger.info(
            "Pass 2 — Extracted %d specific fields for type '%s'",
            len(specific_fields),
            entry_type,
        )

        return specific_fields
