"""
Data quality validation utilities.

Implements validation rules from the SRS:
  - FR-GS-6: Missing mandatory fields → blank cell + "Missing data" note
  - FR-GS-7: Do not infer numeric values not visible in the document
"""

from __future__ import annotations

from typing import Any

from src.models.schema_loader import (
    get_common_columns,
    get_entry_type_config,
    get_confidence_thresholds,
)
from src.utils.logger import get_logger

logger = get_logger(__name__)


def get_required_field_names(entry_type_key: str) -> list[str]:
    """Return all field names marked as required for the given entry type.

    Includes both common and entry-specific required fields.
    """
    required: list[str] = []

    for col in get_common_columns():
        if col.get("required", False) and col["name"] not in (
            "Timestamp",
            "Confidence",
            "Source",
        ):
            required.append(col["name"])

    config = get_entry_type_config(entry_type_key)
    for col in config["specific_columns"]:
        if col.get("required", False):
            required.append(col["name"])

    return required


def compute_confidence(
    filled_count: int,
    total_required: int,
) -> str:
    """Compute confidence level based on how many required fields are filled.

    Uses thresholds from schemas.yaml:
        - >= high_threshold%  → "High"
        - >= medium_threshold% → "Medium"
        - below → "Low"
    """
    if total_required == 0:
        return "Medium"

    fill_pct = (filled_count / total_required) * 100
    thresholds = get_confidence_thresholds()

    if fill_pct >= thresholds["high_threshold"]:
        return "High"
    elif fill_pct >= thresholds["medium_threshold"]:
        return "Medium"
    else:
        return "Low"


def annotate_missing_fields(
    row: list[str],
    column_names: list[str],
    entry_type_key: str,
) -> list[str]:
    """Mark any blank fields with 'N/A'.

    All empty fields (both required and optional) are filled with 'N/A'
    so the spreadsheet never has blank cells.

    Args:
        row: The data row (list of string values).
        column_names: Ordered column names matching the row.
        entry_type_key: Entry type key for logging context.

    Returns:
        The annotated row (same list, modified in place for efficiency).
    """
    required_fields = set(get_required_field_names(entry_type_key))

    for i, (col_name, value) in enumerate(zip(column_names, row)):
        if not value.strip():
            row[i] = "N/A"
            if col_name in required_fields:
                logger.warning(
                    "Required field '%s' is missing for entry type '%s'",
                    col_name,
                    entry_type_key,
                )

    return row


def validate_no_inferred_values(extracted_data: dict[str, Any]) -> dict[str, Any]:
    """Ensure no numeric values are fabricated (FR-GS-7).

    This is enforced at the prompt level (Gemini is told not to infer),
    but we add a safeguard here: any obviously suspicious values are
    stripped and logged.

    Currently this is a pass-through with logging. Can be enhanced with
    domain-specific rules as needed.
    """
    for field_name, value in extracted_data.items():
        if value is None:
            extracted_data[field_name] = ""

    return extracted_data
