"""Google Cloud Vision OCR service for ScanMatch.

Processes uploaded images/PDFs using Google Cloud Vision REST API (DOCUMENT_TEXT_DETECTION)
with language hints for Gujarati, Hindi, and English.
"""

import base64
import json
import logging
import os
import urllib.error
import urllib.request
from typing import NamedTuple, Optional

log = logging.getLogger("scanmatch.ocr")


class OCRResult(NamedTuple):
    """Standard OCR output structure returned by the OCR engine."""
    text: str
    confidence: float
    success: bool
    error: Optional[str] = None


class BaseOCR:
    """Abstract interface for OCR implementations."""
    name: str = "base"

    def extract_text(
        self,
        file_bytes: bytes,
        filename: Optional[str] = None,
        mock_override: Optional[str] = None,
        api_key: Optional[str] = None
    ) -> OCRResult:
        raise NotImplementedError


class GoogleCloudVisionOCR(BaseOCR):
    """Production Google Cloud Vision OCR integration.

    Uses Google Cloud Vision REST API (v1 images:annotate) with
    DOCUMENT_TEXT_DETECTION and language hints for Gujarati, Hindi, and English.
    Requires an API key passed via parameter or GOOGLE_VISION_API_KEY / GOOGLE_API_KEY environment variable.
    """
    name: str = "google_cloud_vision"

    def __init__(self, default_api_key: Optional[str] = None):
        self.default_api_key = (
            default_api_key
            or os.getenv("GOOGLE_VISION_API_KEY")
            or os.getenv("GOOGLE_API_KEY")
        )

    def extract_text(
        self,
        file_bytes: bytes,
        filename: Optional[str] = None,
        mock_override: Optional[str] = None,
        api_key: Optional[str] = None
    ) -> OCRResult:
        if not file_bytes:
            return OCRResult(text="", confidence=0.0, success=False, error="EMPTY_FILE_BYTES")

        # Allow explicit override (e.g. for testing)
        if mock_override is not None and mock_override.strip():
            return OCRResult(text=mock_override.strip(), confidence=0.98, success=True)

        key = api_key or self.default_api_key or os.getenv("GOOGLE_VISION_API_KEY") or os.getenv("GOOGLE_API_KEY")
        if not key or not key.strip():
            return OCRResult(
                text="",
                confidence=0.0,
                success=False,
                error=(
                    "Google Cloud Vision API key is not configured. "
                    "Please enter your API key in the web UI settings or set GOOGLE_VISION_API_KEY in your environment."
                )
            )

        # Call Google Cloud Vision REST API endpoint
        url = f"https://vision.googleapis.com/v1/images:annotate?key={key.strip()}"
        b64_content = base64.b64encode(file_bytes).decode("ascii")

        payload = {
            "requests": [
                {
                    "image": {"content": b64_content},
                    "features": [
                        {"type": "DOCUMENT_TEXT_DETECTION", "maxResults": 1}
                    ],
                    "imageContext": {
                        "languageHints": ["gu", "hi", "en"]
                    }
                }
            ]
        }

        try:
            req_data = json.dumps(payload).encode("utf-8")
            req = urllib.request.Request(
                url,
                data=req_data,
                headers={"Content-Type": "application/json"}
            )
            with urllib.request.urlopen(req, timeout=20) as resp:
                resp_json = json.loads(resp.read().decode("utf-8"))
        except urllib.error.HTTPError as e:
            err_body = e.read().decode("utf-8", errors="replace")
            try:
                err_dict = json.loads(err_body)
                msg = err_dict.get("error", {}).get("message", f"HTTP {e.code}: {e.reason}")
            except Exception:
                msg = f"HTTP {e.code}: {e.reason}"
            return OCRResult(text="", confidence=0.0, success=False, error=f"Google Cloud Vision Error: {msg}")
        except urllib.error.URLError as e:
            return OCRResult(text="", confidence=0.0, success=False, error=f"Network error connecting to Cloud Vision: {e.reason}")
        except Exception as e:
            return OCRResult(text="", confidence=0.0, success=False, error=f"Cloud Vision request failed: {str(e)}")

        responses = resp_json.get("responses", [])
        if not responses:
            return OCRResult(text="", confidence=0.0, success=False, error="No response received from Google Cloud Vision.")

        res0 = responses[0]
        if "error" in res0:
            err_msg = res0["error"].get("message", "Unknown error from Google Cloud Vision")
            return OCRResult(text="", confidence=0.0, success=False, error=f"Google Cloud Vision Error: {err_msg}")

        # Extract full document text annotation
        full_text = res0.get("fullTextAnnotation", {}).get("text", "")
        if not full_text:
            text_annotations = res0.get("textAnnotations", [])
            if text_annotations:
                full_text = text_annotations[0].get("description", "")

        if not full_text or not full_text.strip():
            return OCRResult(text="", confidence=0.0, success=True, error=None)

        # Compute average confidence from pages/blocks if present
        confidences = []
        for page in res0.get("fullTextAnnotation", {}).get("pages", []):
            if "confidence" in page:
                confidences.append(page["confidence"])
            for block in page.get("blocks", []):
                if "confidence" in block:
                    confidences.append(block["confidence"])

        avg_conf = sum(confidences) / len(confidences) if confidences else 0.95
        return OCRResult(text=full_text.strip(), confidence=round(avg_conf, 4), success=True)


def get_ocr_engine() -> GoogleCloudVisionOCR:
    """Factory returning the active Google Cloud Vision OCR engine."""
    return GoogleCloudVisionOCR()
