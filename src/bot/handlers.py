"""
Telegram bot message and image handlers.

Implements the main processing pipeline:
  Photo received -> Download -> Extract -> Route -> Write -> Confirm

Edge case handling:
  - Single image enforcement
  - Non-bill image rejection
  - Duplicate bill detection with location
  - Multi-page guidance
"""

from __future__ import annotations

from telegram import Update
from telegram.ext import (
    Application,
    CommandHandler,
    ContextTypes,
    MessageHandler,
    filters,
)

from src.extraction.extractor import BillExtractor, ExtractionError
from src.sheets.writer import SheetWriter, DuplicateBillError
from src.sheets.client import SheetsClientError
from src.bot.responses import (
    build_confirmation_message,
    build_duplicate_message,
    build_rejection_message,
    build_error_message,
    build_welcome_message,
    build_help_message,
)
from src.utils.logger import get_logger

logger = get_logger(__name__)


class BotHandlers:
    """Registers and manages Telegram bot handlers."""

    def __init__(
        self,
        extractor: BillExtractor,
        writer: SheetWriter,
    ) -> None:
        """Initialize handlers with required dependencies.

        Args:
            extractor: BillExtractor for image processing.
            writer: SheetWriter for Google Sheets output.
        """
        self._extractor = extractor
        self._writer = writer

    def register(self, app: Application) -> None:
        """Register all handlers with the Telegram Application.

        Args:
            app: The python-telegram-bot Application instance.
        """
        app.add_handler(CommandHandler("start", self._handle_start))
        app.add_handler(CommandHandler("help", self._handle_help))
        app.add_handler(
            MessageHandler(filters.PHOTO, self._handle_photo)
        )
        app.add_handler(
            MessageHandler(
                filters.Document.IMAGE, self._handle_document_image
            )
        )
        # Catch-all for non-image messages
        app.add_handler(
            MessageHandler(
                filters.ALL & ~filters.PHOTO & ~filters.Document.IMAGE & ~filters.COMMAND,
                self._handle_unknown,
            )
        )
        app.add_error_handler(self._handle_error)

        logger.info("Bot handlers registered")

    async def _handle_start(
        self,
        update: Update,
        context: ContextTypes.DEFAULT_TYPE,
    ) -> None:
        """Handle the /start command."""
        logger.info("Received /start from user %s", update.effective_user.id)
        await update.message.reply_text(
            build_welcome_message(),
            parse_mode="Markdown",
        )

    async def _handle_help(
        self,
        update: Update,
        context: ContextTypes.DEFAULT_TYPE,
    ) -> None:
        """Handle the /help command."""
        logger.info("Received /help from user %s", update.effective_user.id)
        await update.message.reply_text(
            build_help_message(),
            parse_mode="Markdown",
        )

    async def _handle_photo(
        self,
        update: Update,
        context: ContextTypes.DEFAULT_TYPE,
    ) -> None:
        """Handle incoming photo messages — the main processing pipeline."""
        user_id = update.effective_user.id
        logger.info("Received photo from user %s", user_id)

        # Edge Case: Check for media group (multiple photos sent together)
        if update.message.media_group_id:
            await update.message.reply_text(
                "📸 *Please send only ONE image at a time.*\n\n"
                "For multi-page bills, send the page with the main totals.",
                parse_mode="Markdown",
            )
            return

        # Send a "processing" indicator
        processing_msg = await update.message.reply_text(
            "🔄 Processing your bill image... Please wait."
        )

        await self._process_image(
            update=update,
            context=context,
            processing_msg=processing_msg,
            file_id=update.message.photo[-1].file_id,
            mime_type="image/jpeg",
            user_id=user_id,
        )

    async def _handle_document_image(
        self,
        update: Update,
        context: ContextTypes.DEFAULT_TYPE,
    ) -> None:
        """Handle images sent as documents (uncompressed)."""
        user_id = update.effective_user.id
        logger.info("Received document image from user %s", user_id)

        processing_msg = await update.message.reply_text(
            "🔄 Processing your bill image... Please wait."
        )

        document = update.message.document
        filename = document.file_name or ""

        # Determine MIME type from filename
        mime_type = "image/jpeg"
        if filename.lower().endswith(".png"):
            mime_type = "image/png"
        elif filename.lower().endswith(".webp"):
            mime_type = "image/webp"

        await self._process_image(
            update=update,
            context=context,
            processing_msg=processing_msg,
            file_id=document.file_id,
            mime_type=mime_type,
            user_id=user_id,
        )

    async def _process_image(
        self,
        update: Update,
        context: ContextTypes.DEFAULT_TYPE,
        processing_msg,
        file_id: str,
        mime_type: str,
        user_id: int,
    ) -> None:
        """Core processing pipeline shared by photo and document handlers.

        Steps:
        1. Download image
        2. Extract data via Gemini
        3. Reject non-bill images (zero useful fields)
        4. Write to Google Sheets (with duplicate check)
        5. Send confirmation
        """
        try:
            # Step 1: Download the image
            file = await context.bot.get_file(file_id)
            image_bytes = await file.download_as_bytearray()

            logger.info(
                "Downloaded image: file_id=%s, size=%d bytes",
                file_id,
                len(image_bytes),
            )

            # Step 2: Extract data
            bill_data = self._extractor.extract(
                image_bytes=bytes(image_bytes),
                telegram_file_id=file_id,
                mime_type=mime_type,
            )

            # Step 3: Reject non-bill images
            # If it fell back to general_entry AND has no supplier/bill info,
            # it's likely not a bill at all
            is_non_bill = (
                bill_data.entry_type == "general_entry"
                and not bill_data.supplier_name.strip()
                and not bill_data.bill_number.strip()
                and not bill_data.total_amount.strip()
            )
            if is_non_bill:
                logger.info("Rejecting non-bill image from user %s", user_id)
                await processing_msg.edit_text(
                    build_rejection_message(),
                    parse_mode="Markdown",
                )
                return

            # Step 4: Write to Google Sheets (includes duplicate check)
            result = self._writer.write(bill_data)

            # Step 5: Send confirmation
            await processing_msg.edit_text(
                build_confirmation_message(result),
                parse_mode="Markdown",
            )

            logger.info(
                "Pipeline complete for user %s: type=%s, sheet=%s, row=%d",
                user_id,
                result.entry_type_display,
                result.sheet_name,
                result.row_number,
            )

        except DuplicateBillError as exc:
            logger.info("Duplicate bill from user %s: %s", user_id, str(exc))
            await processing_msg.edit_text(
                build_duplicate_message(exc),
                parse_mode="Markdown",
            )

        except ExtractionError as exc:
            logger.error("Extraction failed for user %s: %s", user_id, str(exc))
            await processing_msg.edit_text(
                build_error_message(str(exc)),
                parse_mode="Markdown",
            )

        except SheetsClientError as exc:
            logger.error("Sheets write failed for user %s: %s", user_id, str(exc))
            await processing_msg.edit_text(
                build_error_message(str(exc)),
                parse_mode="Markdown",
            )

        except Exception as exc:
            logger.error(
                "Unexpected error for user %s: %s",
                user_id,
                str(exc),
                exc_info=True,
            )
            await processing_msg.edit_text(
                build_error_message("An unexpected error occurred."),
                parse_mode="Markdown",
            )

    async def _handle_unknown(
        self,
        update: Update,
        context: ContextTypes.DEFAULT_TYPE,
    ) -> None:
        """Handle non-image messages."""
        await update.message.reply_text(
            "📸 Please send me a *photo* of a bill or invoice.\n"
            "Type /help for usage instructions.",
            parse_mode="Markdown",
        )

    async def _handle_error(
        self,
        update: object,
        context: ContextTypes.DEFAULT_TYPE,
    ) -> None:
        """Global error handler for unhandled exceptions."""
        logger.error(
            "Unhandled exception: %s",
            context.error,
            exc_info=context.error,
        )
