"""
Sheets client.

Uses gspread with service account authentication.
Provides worksheet access and row operations.

Supports two auth methods (in order of precedence):
1.  GOOGLE_SERVICE_ACCOUNT_JSON — raw JSON string from env var (cloud-friendly)
2.  GOOGLE_SERVICE_ACCOUNT_FILE — path to a local JSON file (backward-compatible)
"""

from __future__ import annotations

from pathlib import Path
from typing import Any

import gspread
from google.oauth2.service_account import Credentials

from src.utils.logger import get_logger

logger = get_logger(__name__)

_SCOPES = [
    "https://www.googleapis.com/auth/spreadsheets",
    "https://www.googleapis.com/auth/drive",
]


class SheetsClientError(Exception):
    """Raised when Google Sheets operations fail."""


class SheetsClient:
    """Wrapper around gspread for Google Sheets operations."""

    def __init__(
        self,
        service_account_path: Path | None = None,
        service_account_info: dict[str, Any] | None = None,
        spreadsheet_id: str = "",
    ) -> None:
        """Initialize the Sheets client.

        Args:
            service_account_path: Path to the service account JSON (optional).
            service_account_info: Parsed service account JSON dict (optional).
            spreadsheet_id: Google Spreadsheet ID.
        """
        try:
            if service_account_info is not None:
                credentials = Credentials.from_service_account_info(
                    service_account_info,
                    scopes=_SCOPES,
                )
            elif service_account_path is not None:
                credentials = Credentials.from_service_account_file(
                    str(service_account_path),
                    scopes=_SCOPES,
                )
            else:
                raise SheetsClientError(
                    "No service account provided. "
                    "Set either GOOGLE_SERVICE_ACCOUNT_JSON or "
                    "GOOGLE_SERVICE_ACCOUNT_FILE."
                )
            self._gc = gspread.authorize(credentials)
            self._spreadsheet_id = spreadsheet_id
            self._spreadsheet: gspread.Spreadsheet | None = None
            logger.info(
                "SheetsClient initialized (spreadsheet_id=%s)",
                spreadsheet_id,
            )
        except SheetsClientError:
            raise
        except Exception as exc:
            raise SheetsClientError(
                f"Failed to initialize Sheets client: {exc}"
            ) from exc

    @property
    def spreadsheet(self) -> gspread.Spreadsheet:
        """Lazy-load and cache the spreadsheet instance."""
        if self._spreadsheet is None:
            try:
                self._spreadsheet = self._gc.open_by_key(self._spreadsheet_id)
                logger.info("Opened spreadsheet: %s", self._spreadsheet.title)
            except gspread.SpreadsheetNotFound as exc:
                raise SheetsClientError(
                    f"Spreadsheet not found: {self._spreadsheet_id}. "
                    "Ensure it is shared with the service account email."
                ) from exc
            except Exception as exc:
                raise SheetsClientError(
                    f"Failed to open spreadsheet: {exc}"
                ) from exc
        return self._spreadsheet

    def get_or_create_worksheet(
        self,
        sheet_name: str,
        headers: list[str] | None = None,
    ) -> gspread.Worksheet:
        """Get a worksheet by name, creating it if it doesn't exist.

        If the worksheet is newly created and headers are provided,
        the header row is written first.

        If the worksheet already exists, any columns present in `headers`
        but missing from the sheet's current header row are appended to
        the right — existing data and column positions are never disturbed
        (backward-compatible schema migration).

        Args:
            sheet_name: Name of the worksheet.
            headers: Full ordered list of column headers from the schema.

        Returns:
            The gspread Worksheet instance.
        """
        try:
            worksheet = self.spreadsheet.worksheet(sheet_name)
            logger.debug("Found existing worksheet: %s", sheet_name)
            # Backward-compat: append any new schema columns to the header row.
            if headers:
                self._ensure_headers(worksheet, headers)
            return worksheet
        except gspread.WorksheetNotFound:
            logger.info("Creating new worksheet: %s", sheet_name)
            worksheet = self.spreadsheet.add_worksheet(
                title=sheet_name,
                rows=1000,
                cols=max(len(headers) if headers else 20, 20),
            )
            if headers:
                worksheet.update("A1", [headers])
                logger.info(
                    "Wrote %d headers to '%s'",
                    len(headers),
                    sheet_name,
                )
            return worksheet

    def _ensure_headers(
        self,
        worksheet: gspread.Worksheet,
        expected_headers: list[str],
    ) -> None:
        """Append any schema-new columns to an existing worksheet's header row.

        Called every time an existing sheet is opened. If the current schema
        has columns that are not yet in the sheet (e.g. because the schema
        was updated after the sheet was first created), those column names are
        written to the right of the last existing header.

        Rules:
        - Existing columns are NEVER moved, renamed, or deleted.
        - Existing data rows are NEVER touched.
        - Only truly missing headers are added, in the order they appear in
          the schema, so new rows will align correctly with new columns.

        Args:
            worksheet: The open gspread Worksheet instance.
            expected_headers: Full ordered header list from the current schema.
        """
        try:
            existing = worksheet.row_values(1)  # Current header row (row 1)
            missing = [h for h in expected_headers if h not in existing]
            if not missing:
                return  # Sheet is already up-to-date — nothing to do.

            # Append missing headers starting immediately after the last
            # existing column so no existing cell is overwritten.
            start_col = len(existing) + 1  # 1-indexed
            range_start = gspread.utils.rowcol_to_a1(1, start_col)
            range_end = gspread.utils.rowcol_to_a1(1, start_col + len(missing) - 1)
            worksheet.update(f"{range_start}:{range_end}", [missing])
            logger.info(
                "Schema migration: added %d new column(s) to '%s': %s",
                len(missing),
                worksheet.title,
                missing,
            )
        except Exception as exc:
            # Non-fatal: log the warning but don't block the write.
            logger.warning(
                "Could not sync headers for worksheet '%s': %s",
                worksheet.title,
                str(exc),
            )

    def append_row(
        self,
        sheet_name: str,
        row_data: list[str],
        headers: list[str] | None = None,
    ) -> int:
        """Append a single row to the specified worksheet.

        This is an append-only operation (FR-GS-3: shall not overwrite).

        Args:
            sheet_name: Target worksheet name.
            row_data: Ordered list of cell values to append.
            headers: Column headers (used if sheet needs to be created).

        Returns:
            The 1-indexed row number where data was written.

        Raises:
            SheetsClientError: If the write operation fails (FR-GS-9: no partial writes).
        """
        try:
            worksheet = self.get_or_create_worksheet(sheet_name, headers)
            worksheet.append_row(
                row_data,
                value_input_option="USER_ENTERED",
            )
            # Get the row number (total rows = current last row)
            row_number = len(worksheet.get_all_values())
            logger.info(
                "Appended row %d to '%s'",
                row_number,
                sheet_name,
            )
            return row_number

        except SheetsClientError:
            raise
        except Exception as exc:
            # FR-GS-9: No partial writes — if anything fails, raise error
            logger.error(
                "Failed to write to sheet '%s': %s",
                sheet_name,
                str(exc),
            )
            raise SheetsClientError(
                f"Failed to save data to Google Sheets: {exc}"
            ) from exc

    def find_duplicate(
        self,
        sheet_name: str,
        bill_number: str,
        supplier_name: str,
    ) -> int | None:
        """Check if a bill already exists in a worksheet.

        Searches for a row where both Bill Number and Supplier Name match.
        Skips check if bill_number is empty (e.g. handwritten docs).

        Args:
            sheet_name: Worksheet name to search.
            bill_number: Bill number to look for.
            supplier_name: Supplier name to match.

        Returns:
            Row number (1-indexed) if duplicate found, None otherwise.
        """
        if not bill_number.strip():
            return None  # Can't check duplicates without a bill number

        try:
            worksheet = self.spreadsheet.worksheet(sheet_name)
        except gspread.WorksheetNotFound:
            return None  # Sheet doesn't exist yet, no duplicates possible

        try:
            all_values = worksheet.get_all_values()
            if not all_values:
                return None

            headers = all_values[0]

            # Find column indices
            bill_col = None
            supplier_col = None
            for i, h in enumerate(headers):
                if h == "Bill Number":
                    bill_col = i
                elif h == "Supplier Name":
                    supplier_col = i

            if bill_col is None:
                return None  # No Bill Number column

            # Search rows (skip header)
            for row_idx, row in enumerate(all_values[1:], start=2):
                if row_idx <= 1:
                    continue
                bill_match = (
                    len(row) > bill_col
                    and row[bill_col].strip().lower() == bill_number.strip().lower()
                )
                supplier_match = True  # Default if no supplier column
                if supplier_col is not None and supplier_name.strip():
                    supplier_match = (
                        len(row) > supplier_col
                        and row[supplier_col].strip().lower()
                        == supplier_name.strip().lower()
                    )

                if bill_match and supplier_match:
                    logger.info(
                        "Duplicate found: bill '%s' in '%s' at row %d",
                        bill_number,
                        sheet_name,
                        row_idx,
                    )
                    return row_idx

            return None

        except Exception as exc:
            logger.warning("Duplicate check failed: %s", str(exc))
            return None  # Don't block writes if duplicate check fails
