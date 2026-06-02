"""
Telegram bot response message builders.

Formats confirmation and error messages per SRS Section 6.1 and Section 7.
"""

from __future__ import annotations

from telegram.helpers import escape_markdown

from src.sheets.writer import WriteResult, DuplicateBillError


def build_confirmation_message(result: WriteResult) -> str:
    """Build a success confirmation message per SRS Section 6.1.

    Args:
        result: WriteResult from a successful sheet write.

    Returns:
        Formatted confirmation string for Telegram.
    """
    return (
        f"✅ *Bill Processed Successfully*\n\n"
        f"📋 *Entry Type:* {result.entry_type_display}\n"
        f"📊 *Status:* Saved to Google Sheet\n"
        f"📄 *Sheet:* `{result.sheet_name}`\n"
        f"📍 *Row:* {result.row_number}\n"
        f"🎯 *Confidence:* {result.confidence}"
    )


def build_duplicate_message(exc: DuplicateBillError) -> str:
    """Build a duplicate bill rejection message.

    Tells the user where the original record lives.

    Args:
        exc: DuplicateBillError with location details.

    Returns:
        Formatted duplicate warning string for Telegram.
    """
    return (
        f"⚠️ *Duplicate Bill Detected*\n\n"
        f"This bill has already been processed:\n"
        f"📄 *Bill No:* `{exc.bill_number}`\n"
        f"🏢 *Supplier:* {exc.supplier_name}\n"
        f"📊 *Sheet:* `{exc.sheet_name}`\n"
        f"📍 *Row:* {exc.row_number}\n\n"
        f"_The bill was NOT added again._"
    )


def build_rejection_message() -> str:
    """Build a non-bill image rejection message."""
    return (
        "❌ *This doesn't appear to be a bill*\n\n"
        "I couldn't extract any meaningful data from this image.\n\n"
        "Please send a clear image of:\n"
        "• A tax invoice or bill\n"
        "• A delivery challan\n"
        "• A handwritten register entry\n"
        "• A WhatsApp order screenshot"
    )


def build_error_message(error_detail: str = "") -> str:
    """Build an error message per SRS Section 7 (FR-GS-8).

    Args:
        error_detail: Optional technical detail (shown in debug mode only).

    Returns:
        User-friendly error string for Telegram.
    """
    message = (
        "⚠️ *Data extracted but not saved.*\n\n"
        "Please try again or contact admin."
    )
    if error_detail:
        escaped = escape_markdown(error_detail, version=1)
        message += f"\n\n_Debug: {escaped}_"
    return message


def build_welcome_message() -> str:
    """Build the /start welcome message."""
    return (
        "👋 *Welcome to the Bill Processor Bot!*\n\n"
        "I extract data from bill and invoice images and save them "
        "to Google Sheets automatically.\n\n"
        "*How to use:*\n"
        "1️⃣ Send me a photo of a bill or invoice\n"
        "2️⃣ I'll extract the data and classify the entry type\n"
        "3️⃣ The data is saved to the correct Google Sheet\n"
        "4️⃣ I'll confirm what was saved\n\n"
        "📌 *Supported entry types:*\n"
        "• Grey Purchase\n"
        "• Yarn Purchase\n"
        "• Finish Purchase\n"
        "• GRN Entry (Job / Process / Sewing)\n"
        "• Ledger & Outstanding\n"
        "• General Entry\n\n"
        "Just send a bill image to get started! 📸"
    )


def build_help_message() -> str:
    """Build the /help message."""
    return (
        "ℹ️ *Bill Processor — Help*\n\n"
        "*Commands:*\n"
        "/start — Welcome message\n"
        "/help — This help message\n\n"
        "*Usage:*\n"
        "Simply send a photo of a bill or invoice. "
        "The bot will automatically:\n"
        "• Extract all relevant fields\n"
        "• Classify the entry type\n"
        "• Save to the correct Google Sheet\n"
        "• Send you a confirmation\n\n"
        "*Tips:*\n"
        "• Ensure the image is clear and well-lit\n"
        "• Avoid cropping important information\n"
        "• One bill per image works best"
    )
