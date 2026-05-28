"""
Entry-type to Google Sheet routing.

Reads schemas.yaml to determine which worksheet receives data
for each entry type. Config-driven — no if-else chains.
"""

from __future__ import annotations

from src.models.schema_loader import (
    get_sheet_name,
    get_full_column_names,
    get_all_entry_type_keys,
)
from src.utils.logger import get_logger

logger = get_logger(__name__)


class RoutingError(Exception):
    """Raised when routing fails for an entry type."""


class SheetRouter:
    """Routes bill data to the correct Google Sheet worksheet based on entry type."""

    def __init__(self) -> None:
        """Initialize the router and pre-load the routing table from config."""
        self._valid_types = set(get_all_entry_type_keys())
        logger.info(
            "SheetRouter initialized with %d entry types: %s",
            len(self._valid_types),
            sorted(self._valid_types),
        )

    def get_target_sheet(self, entry_type_key: str) -> str:
        """Return the worksheet name for the given entry type.

        Args:
            entry_type_key: Entry type key (e.g., 'grey_purchase').

        Returns:
            Google Sheet worksheet name (e.g., 'Grey_Purchase_Bills').

        Raises:
            RoutingError: If the entry type is not configured.
        """
        if entry_type_key not in self._valid_types:
            raise RoutingError(
                f"Cannot route entry type '{entry_type_key}'. "
                f"Valid types: {sorted(self._valid_types)}"
            )

        sheet_name = get_sheet_name(entry_type_key)
        logger.debug("Routed '%s' → '%s'", entry_type_key, sheet_name)
        return sheet_name

    def get_column_headers(self, entry_type_key: str) -> list[str]:
        """Return the ordered column headers for the given entry type.

        Args:
            entry_type_key: Entry type key.

        Returns:
            Ordered list of column header names.
        """
        return get_full_column_names(entry_type_key)
