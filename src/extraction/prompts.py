"""
Extraction prompt builder.

Dynamically generates the Gemini prompt from schemas.yaml.
When a new entry type is added to the YAML config, the prompt
automatically includes it — zero code changes needed.
"""

from __future__ import annotations

import json

from src.models.schema_loader import (
    get_all_entry_types_with_details,
    build_extraction_field_list,
)


def build_extraction_prompt() -> str:
    """Build the complete Gemini extraction prompt.

    The prompt:
    1. Lists all known entry types with their keywords
    2. Lists all extractable fields per entry type
    3. Instructs Gemini to classify AND extract in one pass
    4. Enforces a strict JSON output schema
    5. Tells Gemini NOT to infer values (FR-GS-7)

    Returns:
        The full prompt string ready to send to Gemini.
    """
    entry_types = get_all_entry_types_with_details()

    # Build the entry type reference section
    entry_type_descriptions: list[str] = []
    for key, config in entry_types.items():
        keywords = ", ".join(config.get("keywords", []))
        description = config.get("description", "")
        fields_info = build_extraction_field_list(key)
        field_names = [f["name"] for f in fields_info]

        desc_line = f"    Description: {description}\n" if description else ""
        entry_type_descriptions.append(
            f"  - Key: \"{key}\"\n"
            f"    Display Name: \"{config['display_name']}\"\n"
            f"{desc_line}"
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
- "supplier_name": Name of the supplier/vendor/party on the bill
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
