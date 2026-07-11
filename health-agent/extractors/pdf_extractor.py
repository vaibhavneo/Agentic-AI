from __future__ import annotations
"""
PDF extractor: reads health reports, lab results, discharge summaries.
Uses pypdf for text extraction + Claude for structured parsing.
"""
import json
import re
import pypdf
import anthropic

_client = anthropic.Anthropic()

EXTRACTION_PROMPT = """You are a medical data extractor. Parse this health document and extract ALL vital signs.

Document text:
{text}

Return ONLY valid JSON (no markdown, no extra text):
{{"patient_id": "<string or UNKNOWN>", "timestamp": "<ISO string or null>", "heart_rate": <bpm or null>, "systolic_bp": <mmHg or null>, "diastolic_bp": <mmHg or null>, "spo2": <percentage or null>, "temperature": <Celsius or null>, "respiratory_rate": <per min or null>, "glucose": <mg/dL or null>, "weight": <kg or null>, "notes": "<clinical notes or null>"}}

Convert units if needed (F to C, mmol/L to mg/dL). Extract only measured values."""


def extract_from_pdf(pdf_path: str, page_range: tuple = None) -> dict:
    """
    Extract vitals from a PDF health document.
    page_range: (start, end) page indices, defaults to all pages.
    """
    reader = pypdf.PdfReader(pdf_path)
    total_pages = len(reader.pages)

    if page_range:
        start, end = page_range
    else:
        start, end = 0, total_pages
    end = min(end, total_pages)

    text_parts = []
    for i in range(start, end):
        page_text = reader.pages[i].extract_text()
        if page_text:
            text_parts.append(page_text)

    full_text = "\n".join(text_parts)
    if not full_text.strip():
        raise ValueError("No extractable text found in PDF: " + pdf_path)

    if len(full_text) > 12000:
        full_text = full_text[:12000] + "\n[... truncated ...]"

    response = _client.messages.create(
        model="claude-haiku-4-5-20251001",
        max_tokens=1024,
        messages=[{"role": "user", "content": EXTRACTION_PROMPT.format(text=full_text)}],
    )

    text = response.content[0].text.strip()
    if text.startswith("```"):
        text = re.sub(r"^```[a-z]*\s*", "", text)
        text = re.sub(r"\s*```$", "", text)
    return json.loads(text)
