"""
Pydantic-compatible response schemas for Gemini API calls.

Builds response schema definitions (as dicts) that are passed to Gemini's
``response_schema`` parameter to enforce structured output at the
token-generation level.

Uses dict format (not Pydantic classes) because the entry type enum values
are loaded dynamically from schemas.yaml — we can't use typing.Literal with
runtime values.  The dict format is natively supported by the
google-generativeai library.
"""

from __future__ import annotations

from typing import Any

from src.models.schema_loader import (
    get_all_entry_type_keys,
    get_entry_type_config,
)


def build_classification_schema() -> dict[str, Any]:
    """Build the JSON response schema for the classification pass (Pass 1).

    This schema:
    - Constrains ``entry_type`` to valid enum values from schemas.yaml
    - Includes ``reasoning`` for chain-of-thought classification
    - Extracts both ``supplier_name`` and ``buyer_name`` so we can verify
      the supplier is the issuer, not the buyer

    Returns:
        A dict in the format expected by ``genai.GenerationConfig(response_schema=...)``.
    """
    entry_type_keys = get_all_entry_type_keys()

    return {
        "type": "OBJECT",
        "properties": {
            "reasoning": {
                "type": "STRING",
                "description": (
                    "Step-by-step analysis of the document. First identify the "
                    "seller/issuer (letterhead/logo) and buyer ('To:' section). "
                    "Then analyze the document title, HSN codes, and structure to "
                    "determine the entry type. Explain your reasoning."
                ),
            },
            "entry_type": {
                "type": "STRING",
                "enum": entry_type_keys,
                "description": (
                    "The classified document type. Must be one of the allowed values."
                ),
            },
            "supplier_name": {
                "type": "STRING",
                "description": (
                    "Name of the SELLER/ISSUER — the company in the letterhead/logo "
                    "that ISSUED this bill. NEVER the buyer."
                ),
            },
            "buyer_name": {
                "type": "STRING",
                "description": (
                    "Name of the BUYER — the company in the 'To:', 'M/s', "
                    "'Bill To:', or 'Consignee:' section."
                ),
            },
            "supplier_gstin": {
                "type": "STRING",
                "description": "GSTIN of the supplier/seller if visible.",
            },
            "bill_number": {
                "type": "STRING",
                "description": "Invoice or bill number.",
            },
            "bill_date": {
                "type": "STRING",
                "description": "Date on the bill exactly as printed.",
            },
            "total_amount": {
                "type": "STRING",
                "description": "The final / grand total amount including taxes.",
            },
            "currency": {
                "type": "STRING",
                "description": "Currency code. Default 'INR' for Indian bills.",
            },
        },
        "required": [
            "reasoning",
            "entry_type",
            "supplier_name",
            "buyer_name",
        ],
    }


def build_extraction_schema(entry_type_key: str) -> dict[str, Any]:
    """Build the JSON response schema for the extraction pass (Pass 2).

    This schema is type-specific — it only includes the fields relevant
    to the classified entry type, reducing hallucination and ensuring
    accurate field extraction.

    Args:
        entry_type_key: The classified entry type key (e.g., 'grn_job').

    Returns:
        A dict in the format expected by ``genai.GenerationConfig(response_schema=...)``.
    """
    config = get_entry_type_config(entry_type_key)
    specific_columns = config.get("specific_columns", [])

    # Build properties for each specific field
    specific_properties: dict[str, Any] = {}
    for col in specific_columns:
        specific_properties[col["name"]] = {
            "type": "STRING",
            "description": col.get("description", ""),
        }

    return {
        "type": "OBJECT",
        "properties": {
            "specific_fields": {
                "type": "OBJECT",
                "properties": specific_properties,
                "description": (
                    "Entry-type-specific fields. Use the exact field names listed."
                ),
            },
        },
        "required": ["specific_fields"],
    }
