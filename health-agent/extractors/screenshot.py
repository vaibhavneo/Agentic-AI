from __future__ import annotations
"""
Screenshot extractor: uses Claude vision to read vitals from monitor/device screenshots.
Works with: hospital monitor screenshots, smartwatch screenshots, phone health apps.
"""
import base64
import json
import re
from pathlib import Path
import anthropic

_client = anthropic.Anthropic()

EXTRACTION_PROMPT = """You are a medical data extractor. Analyze this health/medical screenshot and extract ALL vital signs.

Return ONLY valid JSON (no markdown, no extra text):
{"heart_rate": <bpm or null>, "systolic_bp": <mmHg or null>, "diastolic_bp": <mmHg or null>, "spo2": <percentage or null>, "temperature": <Celsius or null>, "respiratory_rate": <per min or null>, "glucose": <mg/dL or null>, "weight": <kg or null>, "patient_id": "<string or UNKNOWN>", "timestamp": "<ISO string or null>", "notes": "<visible warnings or null>"}

Be precise with numbers. Convert units if needed (F to C, mmol/L glucose to mg/dL)."""


def extract_from_screenshot(image_path: str) -> dict:
    """
    Extract vitals from a screenshot using Claude vision.
    Accepts: PNG, JPG, JPEG, WebP, GIF.
    """
    path = Path(image_path)
    if not path.exists():
        raise FileNotFoundError("Image not found: " + image_path)

    ext = path.suffix.lower().lstrip(".")
    media_type_map = {
        "jpg": "image/jpeg", "jpeg": "image/jpeg",
        "png": "image/png", "gif": "image/gif", "webp": "image/webp",
    }
    media_type = media_type_map.get(ext, "image/png")
    image_data = base64.standard_b64encode(path.read_bytes()).decode("utf-8")

    response = _client.messages.create(
        model="claude-opus-4-8",
        max_tokens=1024,
        messages=[{
            "role": "user",
            "content": [
                {"type": "image", "source": {"type": "base64", "media_type": media_type, "data": image_data}},
                {"type": "text", "text": EXTRACTION_PROMPT},
            ],
        }],
    )

    text = response.content[0].text.strip()
    if text.startswith("```"):
        text = re.sub(r"^```[a-z]*\s*", "", text)
        text = re.sub(r"\s*```$", "", text)
    return json.loads(text)


def capture_and_extract(save_path: str = "/tmp/health_capture.png") -> dict:
    """
    Capture a screenshot of the current screen and extract vitals.
    Useful for hospital monitors displayed on a computer.
    """
    import subprocess
    subprocess.run(["screencapture", "-x", save_path], check=True)
    return extract_from_screenshot(save_path)
