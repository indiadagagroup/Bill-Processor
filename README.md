# 📄 Bill Processor Bot

A Telegram bot that extracts structured data from bill and invoice images using **Google Gemini Vision AI**, classifies them by entry type, and saves the results to **Google Sheets** — one dedicated worksheet per bill type.

Built for the textile industry, handling grey purchase, yarn purchase, finish purchase, GRN, and ledger documents.

---

## Architecture

```
Telegram (Photo)
    ↓
Gemini Vision API → Classification + Extraction
    ↓
Entry-Type Router (config-driven)
    ↓
Google Sheets (one worksheet per entry type)
    ↓
Telegram Confirmation Message
```

All entry types, fields, keywords, and sheet mappings are defined in `config/schemas.yaml`. Adding a new entry type requires **zero code changes** — just add a YAML block.

---

## Supported Entry Types

| Entry Type | Sheet Name | Description |
|---|---|---|
| Grey Purchase | `Grey_Purchase_Bills` | Raw grey fabric purchase invoices |
| Yarn Purchase | `Yarn_Purchase_Bills` | Yarn purchase invoices |
| Finish Purchase | `Finish_Purchase_Bills` | Finished fabric / processed goods invoices |
| GRN – Job | `GRN_Job_Entries` | Goods received back from job workers |
| GRN – Process | `GRN_Process_Entries` | Goods received from processing units |
| GRN – Process RF | `GRN_Process_RF_Entries` | Goods received from process (RF variant) |
| GRN – Sewing | `GRN_Sewing_Entries` | Goods received from sewing units |
| Ledger & Outstanding | `Ledger_Outstanding` | Party ledger and outstanding entries |
| General Entry | `General_Entries` | Fallback for unrecognized documents |

---

## Supported Document Types

- ✅ Printed tax invoices and bills
- ✅ Delivery challans
- ✅ Handwritten registers and ledger pages
- ✅ WhatsApp / chat screenshots with order details
- ✅ Photographs or scans of any commercial document

---

## Prerequisites

- **Python 3.11+**
- **Telegram Bot Token** — Create via [@BotFather](https://t.me/BotFather) on Telegram
- **Google Gemini API Key** — Get from [Google AI Studio](https://aistudio.google.com/apikey)
- **Google Service Account JSON** — For Sheets API access
- **Google Spreadsheet** — Shared with the service account email

---

## Setup

### 1. Clone and install dependencies

```bash
cd "d:\SRS Update\bill-processor"
python -m venv venv
venv\Scripts\activate       # Windows
pip install -r requirements.txt
```

### 2. Configure environment variables

Copy the example and fill in your values:

```bash
copy .env.example .env
```

Edit `.env`:

```env
# Telegram Bot
TELEGRAM_BOT_TOKEN=your-telegram-bot-token

# Google Gemini API
GEMINI_API_KEY=your-gemini-api-key
GEMINI_MODEL=gemini-2.0-flash

# Google Sheets
GOOGLE_SERVICE_ACCOUNT_FILE=path/to/service_account.json
GOOGLE_SPREADSHEET_ID=your-spreadsheet-id

# Logging
LOG_LEVEL=INFO
```

### 3. Set up Google Sheets

1. Create a new Google Spreadsheet
2. Copy the spreadsheet ID from the URL:
   ```
   https://docs.google.com/spreadsheets/d/THIS_IS_THE_ID/edit
   ```
3. Share the spreadsheet with your service account email (found in the JSON file under `client_email`)
4. Set the ID in `.env` as `GOOGLE_SPREADSHEET_ID`

The bot will automatically create worksheets as needed when bills are processed.

### 4. Run the bot

```bash
python main.py
```

The bot starts in **polling mode**. Send a bill image to your bot via Telegram.

---

## Environment Variables Reference

| Variable | Required | Default | Description |
|---|---|---|---|
| `TELEGRAM_BOT_TOKEN` | ✅ | — | Bot token from @BotFather |
| `GEMINI_API_KEY` | ✅ | — | Google Gemini API key |
| `GEMINI_MODEL` | ❌ | `gemini-2.0-flash` | Gemini model to use |
| `GOOGLE_SERVICE_ACCOUNT_FILE` | ✅ | — | Path to service account JSON |
| `GOOGLE_SPREADSHEET_ID` | ✅ | — | Target Google Spreadsheet ID |
| `LOG_LEVEL` | ❌ | `INFO` | Logging level (DEBUG, INFO, WARNING, ERROR) |

---

## How It Works

1. **User sends a photo** to the Telegram bot
2. **Bot downloads** the image and sends it to Gemini Vision API
3. **Gemini classifies** the document type and extracts all visible fields
4. **Bot validates** the extraction (non-bill images are rejected)
5. **Duplicate check** — if the same bill number + supplier already exists, it's rejected with the location of the original
6. **Data is written** to the correct worksheet in Google Sheets
7. **Bot confirms** with entry type, sheet name, row number, and confidence level

### Confidence Scoring

| Level | Threshold | Meaning |
|---|---|---|
| High | ≥ 80% of required fields filled | Most data extracted successfully |
| Medium | ≥ 50% of required fields filled | Some fields may need manual review |
| Low | < 50% of required fields filled | Significant data may be missing |

---

## Edge Case Handling

| Scenario | Bot Behavior |
|---|---|
| Multiple images sent at once | Rejected — "Please send only ONE image at a time" |
| Non-bill image (selfie, meme) | Rejected — "This doesn't appear to be a bill" |
| Duplicate bill submitted | Rejected — shows original sheet + row location |
| WhatsApp screenshot | Extracts only order info, ignores chat UI elements |
| Multi-page bill | Guidance to send the page with main totals |
| Handwritten document | Best-effort extraction with confidence score |

---

## Project Structure

```
bill-processor/
├── config/
│   ├── settings.py          # Environment-based configuration
│   └── schemas.yaml         # Entry type definitions (the core config)
├── src/
│   ├── models/
│   │   ├── bill.py          # Pydantic BillData model
│   │   └── schema_loader.py # YAML schema parser
│   ├── extraction/
│   │   ├── client.py        # Gemini API wrapper with retry logic
│   │   ├── prompts.py       # Dynamic prompt builder from schemas
│   │   └── extractor.py     # Extraction orchestrator
│   ├── sheets/
│   │   ├── client.py        # Google Sheets API wrapper + duplicate check
│   │   ├── router.py        # Entry-type → worksheet routing
│   │   └── writer.py        # Row writer with validation
│   ├── bot/
│   │   ├── handlers.py      # Telegram message handlers + edge cases
│   │   └── responses.py     # Response message templates
│   └── utils/
│       ├── logger.py        # Structured logging
│       └── validators.py    # Data quality validation (FR-GS-6, FR-GS-7)
├── main.py                  # Application entry point
├── requirements.txt
├── .env.example
└── .gitignore
```

---

## Adding a New Entry Type

1. Open `config/schemas.yaml`
2. Add a new block under `entry_types`:

```yaml
  new_type:
    display_name: "New Type"
    description: "Description of what this document type is"
    sheet_name: "New_Type_Sheet"
    keywords:
      - "keyword1"
      - "keyword2"
    specific_columns:
      - name: "Field Name"
        description: "What this field captures"
        required: true
```

3. Restart the bot. The new type is automatically:
   - Included in the Gemini extraction prompt
   - Routed to its own worksheet
   - Displayed in confirmation messages

**No code changes required.**

---

## License

Private project — not for public distribution.
