"""
Sheet row writer.

Orchestrates the final step: takes BillData, routes it to the correct sheet,
formats the row, validates it, and appends it.
"""

from __future__ import annotations

from src.models.bill import BillData
from src.sheets.client import SheetsClient, SheetsClientError
from src.sheets.router import SheetRouter
from src.utils.validators import annotate_missing_fields
from src.utils.logger import get_logger

logger = get_logger(__name__)


class DuplicateBillError(Exception):
    """Raised when a duplicate bill is detected."""

    def __init__(self, sheet_name: str, row_number: int, bill_number: str, supplier_name: str):
        self.sheet_name = sheet_name
        self.row_number = row_number
        self.bill_number = bill_number
        self.supplier_name = supplier_name
        super().__init__(
            f"Duplicate bill '{bill_number}' from '{supplier_name}' "
            f"already exists in '{sheet_name}' at row {row_number}"
        )


class WriteResult:
    """Encapsulates the result of a successful sheet write."""

    def __init__(self, sheet_name: str, row_number: int, entry_type_display: str, confidence: str):
        self.sheet_name = sheet_name
        self.row_number = row_number
        self.entry_type_display = entry_type_display
        self.confidence = confidence


class SheetWriter:
    """Writes extracted bill data to the appropriate Google Sheet."""

    def __init__(self, sheets_client: SheetsClient) -> None:
        """Initialize the writer.

        Args:
            sheets_client: Configured SheetsClient instance.
        """
        self._client = sheets_client
        self._router = SheetRouter()
        logger.info("SheetWriter initialized")

    def write(self, bill_data: BillData) -> WriteResult:
        """Write bill data to the correct Google Sheet.

        Pipeline:
        1. Route entry type -> worksheet name
        2. Check for duplicates (by bill_number + supplier_name)
        3. Get column order from config
        4. Convert BillData -> ordered row
        5. Annotate missing required fields (FR-GS-6)
        6. Append row to sheet (FR-GS-3: append only, FR-GS-9: no partial writes)
        7. Return result for confirmation message

        Args:
            bill_data: Validated BillData instance.

        Returns:
            WriteResult with sheet name, row number, etc.

        Raises:
            DuplicateBillError: If a duplicate bill is found.
            SheetsClientError: If the write fails.
        """
        entry_type = bill_data.entry_type

        # Step 1: Route
        sheet_name = self._router.get_target_sheet(entry_type)
        columns = self._router.get_column_headers(entry_type)

        # Step 2: Duplicate check
        existing_row = self._client.find_duplicate(
            sheet_name=sheet_name,
            bill_number=bill_data.bill_number,
            supplier_name=bill_data.supplier_name,
        )
        if existing_row is not None:
            raise DuplicateBillError(
                sheet_name=sheet_name,
                row_number=existing_row,
                bill_number=bill_data.bill_number,
                supplier_name=bill_data.supplier_name,
            )

        logger.info(
            "Writing to sheet '%s' with %d columns",
            sheet_name,
            len(columns),
        )

        # Step 3: Convert to row
        row = bill_data.to_sheet_row(columns)

        # Step 4: Annotate missing fields
        row = annotate_missing_fields(row, columns, entry_type)

        # Step 5: Append
        row_number = self._client.append_row(
            sheet_name=sheet_name,
            row_data=row,
            headers=columns,
        )

        logger.info(
            "Successfully wrote row %d to '%s' (type=%s, confidence=%s)",
            row_number,
            sheet_name,
            entry_type,
            bill_data.confidence,
        )

        # Step 6: Return result
        return WriteResult(
            sheet_name=sheet_name,
            row_number=row_number,
            entry_type_display=bill_data.entry_type_display,
            confidence=bill_data.confidence,
        )
