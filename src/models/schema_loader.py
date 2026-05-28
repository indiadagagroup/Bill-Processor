"""
Schema loader utility.

Reads config/schemas.yaml and provides typed access to entry-type definitions,
column lists, and sheet names. This is the single source of truth for all
schema-related operations in the system.
"""

from __future__ import annotations

from pathlib import Path
from functools import lru_cache
from typing import Any

import yaml


_SCHEMA_PATH = Path(__file__).resolve().parent.parent.parent / "config" / "schemas.yaml"


def _load_raw_yaml(path: Path | None = None) -> dict[str, Any]:
    """Load and return the raw YAML content."""
    target = path or _SCHEMA_PATH
    with open(target, "r", encoding="utf-8") as fh:
        return yaml.safe_load(fh)


@lru_cache
def get_schema_config(path: str | None = None) -> dict[str, Any]:
    """Return the full parsed schema config (cached)."""
    return _load_raw_yaml(Path(path) if path else None)


def get_common_columns() -> list[dict[str, Any]]:
    """Return the list of common column definitions shared by all sheets."""
    return get_schema_config()["common_columns"]


def get_entry_type_config(entry_type_key: str) -> dict[str, Any]:
    """Return the config for a specific entry type by its key.

    Raises:
        KeyError: If the entry type key is not found in schemas.yaml.
    """
    entry_types = get_schema_config()["entry_types"]
    if entry_type_key not in entry_types:
        raise KeyError(
            f"Unknown entry type '{entry_type_key}'. "
            f"Valid types: {list(entry_types.keys())}"
        )
    return entry_types[entry_type_key]


def get_all_entry_type_keys() -> list[str]:
    """Return all valid entry type keys."""
    return list(get_schema_config()["entry_types"].keys())


def get_all_entry_types_with_details() -> dict[str, dict[str, Any]]:
    """Return the complete entry_types mapping."""
    return get_schema_config()["entry_types"]


def get_sheet_name(entry_type_key: str) -> str:
    """Return the Google Sheet worksheet name for the given entry type."""
    return get_entry_type_config(entry_type_key)["sheet_name"]


def get_display_name(entry_type_key: str) -> str:
    """Return the human-readable display name for the entry type."""
    return get_entry_type_config(entry_type_key)["display_name"]


def get_full_column_names(entry_type_key: str) -> list[str]:
    """Return the ordered list of ALL column names (common + specific) for an entry type.

    This defines the exact column order for the Google Sheet.
    """
    common = [col["name"] for col in get_common_columns()]
    specific = [
        col["name"]
        for col in get_entry_type_config(entry_type_key)["specific_columns"]
    ]
    return common + specific


def get_confidence_thresholds() -> dict[str, int]:
    """Return confidence scoring thresholds."""
    return get_schema_config()["confidence"]


def build_extraction_field_list(entry_type_key: str) -> list[dict[str, str]]:
    """Build a combined field list for the Gemini extraction prompt.

    Returns common + specific fields with name and description.
    """
    fields: list[dict[str, str]] = []

    for col in get_common_columns():
        # Skip auto-generated fields that Gemini shouldn't extract
        if col["name"] in ("Timestamp", "Source", "Image Reference", "Raw Text", "Confidence"):
            continue
        fields.append({"name": col["name"], "description": col["description"]})

    for col in get_entry_type_config(entry_type_key)["specific_columns"]:
        fields.append({"name": col["name"], "description": col["description"]})

    return fields
