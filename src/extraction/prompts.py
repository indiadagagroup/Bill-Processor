"""
Extraction prompt builder.

Provides two prompts for the two-pass extraction pipeline:
  1. ``build_classification_prompt()``  — classifies the document type
     with chain-of-thought reasoning and identifies supplier vs buyer.
  2. ``build_extraction_prompt()``      — extracts type-specific fields
     for a classified entry type.

Both prompts are dynamically generated from schemas.yaml. When a new
entry type is added to the YAML config, both prompts automatically
include it — zero code changes needed.

Backward compatibility:
  ``build_full_extraction_prompt()`` is kept as a single-pass fallback
  that mirrors the original ``build_extraction_prompt()`` behavior.
"""

from __future__ import annotations

import json

from src.models.schema_loader import (
    get_all_entry_types_with_details,
    build_extraction_field_list,
    build_specific_field_list,
    get_glossary,
)


# ---------------------------------------------------------------------------
# Textile industry glossary — built once from schemas.yaml
# ---------------------------------------------------------------------------

def _build_glossary_block() -> str:
    """Build the textile glossary section from schemas.yaml."""
    glossary = get_glossary()
    if not glossary:
        return ""

    lines = [
        "## TEXTILE INDUSTRY GLOSSARY — words that have SPECIFIC meanings",
        "",
        "In the textile industry, many common English words have specific "
        "technical meanings that differ from everyday usage:",
        "",
    ]
    for entry in glossary:
        lines.append(f"- \"{entry['term']}\" = {entry['meaning']}")

    lines.append("")
    return "\n".join(lines)


# ---------------------------------------------------------------------------
# Entry type reference block — shared by both prompts
# ---------------------------------------------------------------------------

def _build_entry_types_block() -> str:
    """Build the entry type reference section for the classification prompt.

    Includes keywords, description, disambiguation rules, and document purpose
    for each entry type defined in schemas.yaml.
    """
    entry_types = get_all_entry_types_with_details()
    sections: list[str] = []

    for key, config in entry_types.items():
        keywords = ", ".join(config.get("keywords", []))
        description = config.get("description", "")
        disambiguation = config.get("disambiguation", "").strip()
        purpose = config.get("document_purpose", "")

        lines = [f'  - Key: "{key}"']
        lines.append(f'    Display Name: "{config["display_name"]}"')

        if description:
            lines.append(f"    Description: {description}")
        if purpose:
            lines.append(f"    Document Purpose: {purpose}")
        lines.append(f"    Keywords/Indicators: {keywords}")
        if disambiguation:
            lines.append(f"    Disambiguation: {disambiguation}")

        sections.append("\n".join(lines))

    return "\n\n".join(sections)


# ===================================================================
# PASS 1: Classification Prompt
# ===================================================================

def build_classification_prompt() -> str:
    """Build the classification prompt for Pass 1 of the extraction pipeline.

    This prompt asks Gemini to:
    1. Analyze the document's visual layout (letterhead, logo, "To:" block)
    2. Identify who is the SELLER vs BUYER
    3. Classify the document into an entry type with chain-of-thought reasoning
    4. Extract header-level fields (bill number, date, amount)

    The prompt does NOT ask for type-specific field extraction — that's Pass 2.

    Returns:
        The classification prompt string.
    """
    glossary_block = _build_glossary_block()
    entry_types_block = _build_entry_types_block()

    prompt = f"""Analyze this document image and classify it.

{glossary_block}

## HOW TO IDENTIFY THE SUPPLIER (SELLER) vs BUYER — USE VISUAL LAYOUT

On Indian invoices and bills, use SPATIAL POSITION and VISUAL CUES:

**SUPPLIER/SELLER (the company that ISSUED this bill):**
- Their name/logo appears in the LETTERHEAD — usually the largest text at the very top
- Their PAN, GSTIN, CIN, address are in the header area of the document
- Their name appears in "FOR: [Company Name]" near the signature at the bottom
- Their bank details are printed for payment

**BUYER (the company the bill is addressed TO):**
- Their name appears after "To:", "M/s", "Bill To:", "Ship To:", "Buyer:", or "Consignee:"
- Usually positioned BELOW the seller's header section
- Their GSTIN may appear with a different state code

CRITICAL RULES:
- The SUPPLIER is ALWAYS the entity in the LETTERHEAD/LOGO — never the "Bill To" entity
- If two company names appear, the one with the logo/letterhead at the TOP is the supplier
- Extract the SELLER/ISSUER as supplier_name — NEVER the buyer

## HOW TO CLASSIFY THE DOCUMENT TYPE — ANALYZE PURPOSE, NOT KEYWORDS

Do NOT classify based on individual words. Analyze the document's BUSINESS PURPOSE:

1. **Read the TITLE of the document** (e.g., "TAX INVOICE", "JOB WORK", "DELIVERY CHALLAN")
2. **Check HSN codes — they reveal the transaction type:**
   - HSN 998821 / 9988xx = Job work services → this is a grn_job bill
   - HSN 5007-5516 / 6001-6006 = Fabric goods → this is a Purchase bill
3. **Analyze document structure:**
   - Has both "Grey Kgs" AND "Fin Kgs" columns? → Processing/Job work bill (grn_job), NOT a purchase
   - Has "Grey Value" + "Job Value" breakdown? → Job work bill (grn_job)
   - Simple quantity × rate for fabric/yarn? → Purchase bill
4. **Determine the business transaction:**
   - Are we BUYING raw material or goods? → Purchase type (grey_purchase / yarn_purchase / finish_purchase)
   - Is a processor/mill CHARGING us for WORK done on OUR material? → grn_job
   - Is someone RETURNING processed goods with a delivery note? → grn_process

CRITICAL DISAMBIGUATION:
- "Bill On: FINISH" means billing method (finished weight) — it does NOT mean finish_purchase
- "Fin Kgs" means finished weight — it does NOT mean finish_purchase
- A bill titled "JOB WORK" from a dyeing/printing mill is ALWAYS grn_job, even if "finish" appears
- finish_purchase is ONLY for invoices where we are BUYING finished fabric as a product

## KNOWN ENTRY TYPES

{entry_types_block}

## INSTRUCTIONS

1. First, identify the SUPPLIER (letterhead/logo) and the BUYER ("To:" section)
2. Then, analyze the document title, HSN codes, and overall structure
3. Provide your step-by-step reasoning in the "reasoning" field
4. Classify into one of the entry type keys listed above
5. If truly unsure, use "general_entry" as a last resort
6. Extract the bill number, date, and total amount
7. For amounts: extract exactly as printed, do NOT recalculate
8. For dates: extract exactly as they appear on the document
9. If a field is not visible, return an empty string ""
"""

    return prompt


# ===================================================================
# PASS 2: Type-Specific Extraction Prompt
# ===================================================================

def build_extraction_prompt(entry_type: str, supplier_name: str = "") -> str:
    """Build the type-specific extraction prompt for Pass 2.

    Now that we know the entry type from Pass 1, this prompt focuses
    exclusively on extracting the specific fields for that type.

    Args:
        entry_type: The classified entry type key (e.g., 'grn_job').
        supplier_name: The supplier name from Pass 1, for context.

    Returns:
        The extraction prompt string.
    """
    fields = build_specific_field_list(entry_type)

    # Build field descriptions
    field_lines: list[str] = []
    for f in fields:
        required_tag = " (REQUIRED)" if f.get("required", "False") == "True" else ""
        field_lines.append(f'  - "{f["name"]}": {f["description"]}{required_tag}')

    fields_block = "\n".join(field_lines)

    supplier_context = ""
    if supplier_name:
        supplier_context = (
            f"\nNote: This document has been classified and the supplier/issuer "
            f"is '{supplier_name}'. Use this for context.\n"
        )

    prompt = f"""Extract the specific fields from this document image.

This document has been classified as: **{entry_type}**
{supplier_context}
## FIELDS TO EXTRACT

{fields_block}

## RULES

1. Extract ONLY values that are clearly visible in the document
2. DO NOT INFER or calculate values that are not explicitly printed
3. If a field is not visible, return an empty string ""
4. For amounts: extract exactly as printed, do not recalculate
5. For quantities: extract the exact value shown
6. For handwritten documents: do your best to read the handwriting
7. If a field appears multiple times across line items, extract it ONCE only — do NOT concatenate duplicates or list multiple values
8. Return the values in the "specific_fields" object using the exact field names above
"""

    return prompt


# ===================================================================
# BACKWARD COMPATIBILITY: Single-pass prompt (original behavior)
# ===================================================================

def build_full_extraction_prompt() -> str:
    """Build the complete single-pass Gemini extraction prompt.

    This is the original prompt that classifies AND extracts in one pass.
    Kept for backward compatibility — the two-pass approach is preferred
    for better accuracy.

    Returns:
        The full prompt string ready to send to Gemini.
    """
    entry_types = get_all_entry_types_with_details()
    glossary_block = _build_glossary_block()

    # Build the entry type reference section
    entry_type_descriptions: list[str] = []
    for key, config in entry_types.items():
        keywords = ", ".join(config.get("keywords", []))
        description = config.get("description", "")
        disambiguation = config.get("disambiguation", "").strip()
        fields_info = build_extraction_field_list(key)
        field_names = [f["name"] for f in fields_info]

        desc_line = f"    Description: {description}\n" if description else ""
        disambig_line = f"    Disambiguation: {disambiguation}\n" if disambiguation else ""
        entry_type_descriptions.append(
            f'  - Key: "{key}"\n'
            f'    Display Name: "{config["display_name"]}"\n'
            f"{desc_line}"
            f"{disambig_line}"
            f"    Keywords/Indicators: {keywords}\n"
            f"    Fields to extract: {json.dumps(field_names)}"
        )

    entry_types_block = "\n\n".join(entry_type_descriptions)

    # Build the JSON schema example
    sample_output = {
        "entry_type": "grey_purchase",
        "supplier_name": "VIRAT FASHION FABRIC",
        "supplier_gstin": "24AAWFV1219L1ZP",
        "bill_number": "VF04012/25-26",
        "bill_date": "22/01/2026",
        "total_amount": "208937.00",
        "currency": "INR",
        "specific_fields": {
            "Fabric Type": "DOT KNIT MILANGE",
            "Quantity": "1473.980",
            "Rate": "135.0000",
            "Lot Number": "DKMO-2024",
            "No of Rolls (Taka)": "48",
            "HSN Code": "60063100",
            "CGST Amount": "4974.68",
            "SGST Amount": "4974.68",
            "IGST Amount": "",
        },
    }

    prompt = f"""You are an expert document extraction system for a textile industry ERP.

Your job is to analyze a document image and:
1. CLASSIFY it into one of the known entry types
2. EXTRACT all relevant fields from the document

The document may be:
- A printed tax invoice or bill
- A delivery challan
- A handwritten register or ledger page
- A WhatsApp/chat screenshot with order details
- A photograph or scan of any commercial document
- A PDF screenshot

Regardless of format (printed, handwritten, screenshot), do your best to extract all visible information.

{glossary_block}

## HOW TO IDENTIFY THE SUPPLIER (SELLER) vs BUYER

On Indian invoices, the SUPPLIER/SELLER is the company in the LETTERHEAD/LOGO at the
top. The BUYER is the company in the "To:" or "Bill To:" section below.
ALWAYS extract the SELLER as supplier_name, never the buyer.

## KNOWN ENTRY TYPES

{entry_types_block}

## CRITICAL RULES

1. **Classification**: Determine the entry type based on the document content, keywords, and structure. If unsure, use "general_entry".
2. **Extraction**: Extract ONLY values that are clearly visible in the document.
3. **DO NOT INFER**: Never guess or calculate values that are not explicitly printed on the document. If a field is not visible, return an empty string "".
4. **Amounts**: Extract amounts exactly as printed — do not recalculate totals or taxes.
5. **Dates**: Extract dates exactly as they appear on the document.
6. **Handwritten documents**: Try your best to read handwriting. If a value is unclear, still attempt to extract it.
7. **WhatsApp/chat screenshots**: If the image is a chat screenshot, extract ONLY the bill or order information from the message content. IGNORE chat UI elements like sender names, message timestamps, read receipts, and profile pictures.
8. **Non-bill images**: If the image does not contain any bill, invoice, challan, or order information, still return the JSON with empty fields and entry_type "general_entry".

## OUTPUT FORMAT

Return a single JSON object with exactly this structure:

```json
{json.dumps(sample_output, indent=2)}
```

### Field descriptions:
- "entry_type": One of the entry type keys listed above (e.g., "grey_purchase", "yarn_purchase", etc.)
- "supplier_name": Name of the supplier/vendor — the company that ISSUED this bill (letterhead/logo), NOT the buyer
- "supplier_gstin": GSTIN of the supplier if visible
- "bill_number": Invoice or bill number
- "bill_date": Date on the bill exactly as printed
- "total_amount": The final/net/grand total amount
- "currency": Currency (default "INR" for Indian bills)
- "specific_fields": A JSON object with the entry-type-specific fields. Use the exact field names listed for the classified entry type.

## IMPORTANT
- Return ONLY the JSON object, no other text.
- Use empty string "" for any field you cannot find in the document.
- Do NOT wrap the response in markdown code fences.
"""

    return prompt
