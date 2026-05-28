"""
Bill Processor — Application entry point.

Bootstraps all services and starts the Telegram bot.

Usage:
    python main.py
"""

from __future__ import annotations

import sys
from pathlib import Path

from telegram.ext import Application

from config.settings import get_settings
from src.extraction.client import GeminiClient
from src.extraction.extractor import BillExtractor
from src.sheets.client import SheetsClient
from src.sheets.writer import SheetWriter
from src.bot.handlers import BotHandlers
from src.utils.logger import setup_logger, get_logger


def main() -> None:
    """Initialize all services and start the Telegram bot."""

    # --- Load config ---
    settings = get_settings()

    # --- Setup logging ---
    setup_logger(level=settings.log_level)
    logger = get_logger("main")
    logger.info("=" * 60)
    logger.info("Bill Processor starting up...")
    logger.info("=" * 60)

    # --- Validate required config ---
    if not settings.telegram_bot_token:
        logger.error("TELEGRAM_BOT_TOKEN is not set")
        sys.exit(1)

    if not settings.gemini_api_key:
        logger.error("GEMINI_API_KEY is not set")
        sys.exit(1)

    if not settings.google_spreadsheet_id:
        logger.error(
            "GOOGLE_SPREADSHEET_ID is not set. "
            "Create a Google Spreadsheet, share it with '%s', "
            "and set the spreadsheet ID in .env",
            "bill-processor@bill-processor-487413.iam.gserviceaccount.com",
        )
        sys.exit(1)

    service_account_path = settings.service_account_path
    if not service_account_path.exists():
        logger.error(
            "Service account file not found: %s",
            service_account_path,
        )
        sys.exit(1)

    # --- Initialize services ---
    logger.info("Initializing Gemini client (model=%s)...", settings.gemini_model)
    gemini_client = GeminiClient(
        api_key=settings.gemini_api_key,
        model_name=settings.gemini_model,
    )

    logger.info("Initializing bill extractor...")
    extractor = BillExtractor(gemini_client)

    logger.info("Initializing Google Sheets client...")
    sheets_client = SheetsClient(
        service_account_path=service_account_path,
        spreadsheet_id=settings.google_spreadsheet_id,
    )

    logger.info("Initializing sheet writer...")
    writer = SheetWriter(sheets_client)

    # --- Build Telegram bot ---
    logger.info("Building Telegram bot application...")
    app = Application.builder().token(settings.telegram_bot_token).build()

    # Register handlers
    handlers = BotHandlers(extractor=extractor, writer=writer)
    handlers.register(app)

    # --- Start the bot ---
    logger.info("Bot is starting in polling mode...")
    logger.info("Press Ctrl+C to stop.")
    app.run_polling(
        drop_pending_updates=True,  # Ignore messages sent while bot was offline
    )


if __name__ == "__main__":
    main()
