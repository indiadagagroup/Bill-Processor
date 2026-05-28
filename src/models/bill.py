"""
Pydantic models for extracted bill data.

Provides a single flexible BillData model rather than one subclass per entry type.
The schema is driven by config/schemas.yaml — field validation adapts automatically
when new entry types are added.
"""

from __future__ import annotations

from datetime import datetime
from typing import Any

from pydantic import BaseModel, Field, field_validator


class BillData(BaseModel):
    """Represents the extracted data from a single bill image.

    Common fields are typed explicitly. Entry-specific fields live in
    `specific_fields` as a flexible dict keyed by column name.
    This avoids needing a Pydantic subclass per entry type while still
    providing structure and validation.
    """

    # --- Common fields (SRS Section 4.1) ---
    timestamp: datetime = Field(default_factory=datetime.now)
    entry_type: str = Field(
        ..., description="ERP entry classification key (e.g. 'grey_purchase')"
    )
    entry_type_display: str = Field(
        default="", description="Human-readable entry type name"
    )
    confidence: str = Field(
        default="Low", description="Extraction confidence: High / Medium / Low"
    )
    supplier_name: str = Field(default="", description="Extracted supplier name")
    supplier_gstin: str = Field(default="", description="Supplier GSTIN")
    bill_number: str = Field(default="", description="Bill or invoice number")
    bill_date: str = Field(default="", description="Bill date as it appears")
    total_amount: str = Field(default="", description="Net or gross total amount")
    currency: str = Field(default="INR", description="Currency code")
    source: str = Field(default="Telegram", description="Source channel")
    image_reference: str = Field(default="", description="Telegram file ID")

    # --- Entry-specific fields ---
    specific_fields: dict[str, Any] = Field(
        default_factory=dict,
        description="Entry-type-specific fields keyed by column name",
    )

    @field_validator("confidence")
    @classmethod
    def normalize_confidence(cls, value: str) -> str:
        """Ensure confidence is one of the three valid values."""
        normalized = value.strip().capitalize()
        if normalized not in ("High", "Medium", "Low"):
            return "Low"
        return normalized

    def to_sheet_row(self, column_order: list[str]) -> list[str]:
        """Convert this bill data into an ordered list of cell values.

        The order matches the column_order list which comes from schemas.yaml.
        Missing fields are returned as empty strings with a 'Missing data' note
        where applicable (FR-GS-6).

        Args:
            column_order: Ordered list of column names from schema config.

        Returns:
            List of string values aligned with column_order.
        """
        # Map our fields to column names
        common_mapping: dict[str, str] = {
            "Timestamp": self.timestamp.strftime("%Y-%m-%d %H:%M:%S"),
            "Entry Type": self.entry_type_display or self.entry_type,
            "Confidence": self.confidence,
            "Supplier Name": self.supplier_name,
            "Supplier GSTIN": self.supplier_gstin,
            "Bill Number": self.bill_number,
            "Bill Date": self.bill_date,
            "Total Amount": str(self.total_amount),
            "Currency": self.currency,
            "Source": self.source,
            "Image Reference": self.image_reference,

        }

        row: list[str] = []
        for col_name in column_order:
            # Check common fields first
            if col_name in common_mapping:
                row.append(common_mapping[col_name])
            # Then check specific fields
            elif col_name in self.specific_fields:
                value = self.specific_fields[col_name]
                row.append(str(value) if value is not None else "")
            else:
                row.append("")

        return row

    def count_filled_required_fields(self, required_fields: list[str]) -> tuple[int, int]:
        """Count how many required fields have non-empty values.

        Returns:
            Tuple of (filled_count, total_required_count).
        """
        all_values = {
            "Supplier Name": self.supplier_name,
            "Supplier GSTIN": self.supplier_gstin,
            "Bill Number": self.bill_number,
            "Bill Date": self.bill_date,
            "Total Amount": self.total_amount,
            "Entry Type": self.entry_type,
        }
        all_values.update(self.specific_fields)

        total = len(required_fields)
        filled = sum(
            1
            for field_name in required_fields
            if all_values.get(field_name) not in (None, "", "0", 0)
        )
        return filled, total
