"""ScanMatch Local Mini Application - FastAPI Service.

Provides:
- Web UI serving (GET /)
- Health check (GET /health)
- Document scan endpoint (POST /api/scan)

Pipeline:
Upload (Image / PDF)
  ↓
FastAPI validation & safe temporary storage
  ↓
Deterministic local MockOCR (server/ocr_service.py)
  ↓
OCR text & confidence
  ↓
Python ctypes FFI (python/scanmatch_ctypes.py)
  ↓
Authoritative C engine (build/libscanmatch.so)
  ↓
Structured JSON response & status mapping
  ↓
Browser result table & summary cards
"""

import csv
import logging
import os
import re
import tempfile
import threading
import time
from pathlib import Path
from typing import Optional

from fastapi import FastAPI, File, Form, HTTPException, Request, UploadFile
from fastapi.responses import FileResponse, JSONResponse

from python.scanmatch_ctypes import ScanMatch, ScanMatchError
from server.ocr_service import get_ocr_engine

# Setup logger for production-style logging
logging.basicConfig(level=logging.INFO, format="%(asctime)s [%(levelname)s] %(name)s: %(message)s")
log = logging.getLogger("scanmatch.app")

# Project directories resolved without hard-coded machine paths
ROOT_DIR = Path(__file__).resolve().parents[1]
BUILD_DIR = ROOT_DIR / "build"
DATA_DIR = ROOT_DIR / "data"
CATALOG_PATH = DATA_DIR / "products.csv"
WEB_DIR = ROOT_DIR / "web"

# Constants
MAX_FILE_BYTES = 10 * 1024 * 1024  # 10 MB upload ceiling
ALLOWED_EXTENSIONS = {".jpg", ".jpeg", ".png", ".webp", ".pdf"}

app = FastAPI(
    title="ScanMatch Local Mini App",
    version="1.0.0",
    description="Local offline Gujarati/Hindi/English shopping list matcher powered by libscanmatch.so"
)

# Persistent singleton C engine state
_engine: Optional[ScanMatch] = None
_engine_lock = threading.Lock()
_ocr_engine = get_ocr_engine()


def get_engine() -> ScanMatch:
    """Initializes and returns the singleton ScanMatch C engine.

    The library and catalog are loaded once so subsequent requests
    can reuse the compiled C matching engine with zero overhead.
    """
    global _engine
    if _engine is None:
        with _engine_lock:
            if _engine is None:
                engine = ScanMatch()
                engine.load_catalog(CATALOG_PATH)
                _engine = engine
                log.info("Initialized ScanMatch C engine and loaded product catalog.")
    return _engine


@app.exception_handler(Exception)
async def generic_exception_handler(request: Request, exc: Exception):
    """Catches unhandled errors and ensures the client never sees raw stack traces."""
    log.exception(f"Unhandled error processing request: {exc}")
    return JSONResponse(
        status_code=500,
        content={
            "success": False,
            "error": {
                "code": "INTERNAL_SERVER_ERROR",
                "message": "An unexpected error occurred during processing."
            }
        }
    )


@app.get("/")
def serve_index():
    """Serves the main application web interface."""
    index_file = WEB_DIR / "index.html"
    if not index_file.exists():
        raise HTTPException(status_code=404, detail="Web interface files not found.")
    return FileResponse(index_file)


@app.get("/style.css")
def serve_css():
    """Serves application styling."""
    css_file = WEB_DIR / "style.css"
    return FileResponse(css_file, media_type="text/css")


@app.get("/app.js")
def serve_js():
    """Serves client-side frontend script."""
    js_file = WEB_DIR / "app.js"
    return FileResponse(js_file, media_type="application/javascript")


@app.get("/health")
def health_check():
    """Returns application health and configuration status."""
    try:
        engine = get_engine()
        catalog_status = "loaded" if engine else "not_loaded"
    except Exception as e:
        log.warning(f"Engine health probe issue: {e}")
        catalog_status = "error"

    has_cloud_vision_key = bool(
        os.getenv("GOOGLE_VISION_API_KEY") or os.getenv("GOOGLE_API_KEY")
    )

    return {
        "success": True,
        "ok": True,
        "status": "healthy",
        "version": "1.0.0",
        "mode": "cloud_vision",
        "catalog": catalog_status,
        "ocr_engine": "google_cloud_vision",
        "cloud_vision_configured": has_cloud_vision_key
    }


@app.get("/api/catalog")
def get_catalog():
    """Returns the list of loaded products in the catalog for client display."""
    items = []
    if CATALOG_PATH.exists():
        try:
            with open(CATALOG_PATH, "r", encoding="utf-8") as f:
                reader = csv.DictReader(f)
                for row in reader:
                    items.append({
                        "product_id": row.get("product_id"),
                        "canonical_name": row.get("canonical_name"),
                        "category": row.get("category", ""),
                        "aliases_en": row.get("aliases_en", ""),
                        "aliases_gu": row.get("aliases_gu", ""),
                        "aliases_hi": row.get("aliases_hi", ""),
                        "units": row.get("units", ""),
                        "pack_sizes": row.get("pack_sizes", "")
                    })
        except Exception as e:
            log.warning(f"Error reading catalog: {e}")
    return {"success": True, "count": len(items), "products": items}


# In-memory cache for catalog metadata (canonical name, category, brand)
_catalog_meta: dict[str, dict] = {}


def get_catalog_meta() -> dict[str, dict]:
    """Loads and caches product metadata from products.csv for quick category and detail lookup."""
    global _catalog_meta
    if not _catalog_meta and CATALOG_PATH.exists():
        try:
            with open(CATALOG_PATH, "r", encoding="utf-8") as f:
                reader = csv.DictReader(f)
                for row in reader:
                    pid = row.get("product_id")
                    if pid:
                        _catalog_meta[pid] = {
                            "canonical_name": row.get("canonical_name", ""),
                            "category": row.get("category", ""),
                            "brand": row.get("brand", ""),
                            "units": row.get("units", ""),
                            "pack_sizes": row.get("pack_sizes", "")
                        }
        except Exception as e:
            log.warning(f"Error reading catalog metadata: {e}")
    return _catalog_meta


# Comprehensive Indic digit map
INDIC_DIGITS = {
    '૦': '0', '૧': '1', '૨': '2', '૩': '3', '૪': '4',
    '૫': '5', '૬': '6', '૭': '7', '૮': '8', '૯': '9',
    '०': '0', '१': '1', '२': '2', '३': '3', '४': '4',
    '५': '5', '६': '6', '७': '7', '८': '8', '९': '9'
}


def normalize_indic_digits(text: str) -> str:
    """Converts Gujarati and Devanagari numerals into standard ASCII digits."""
    for k, v in INDIC_DIGITS.items():
        text = text.replace(k, v)
    return text


def parse_line_meta(raw_line: str) -> dict:
    """Parses a shopping list line into structured components:
    - quantity (int/float or None)
    - unit, unit_category, unit_display
    - clean_item (clean product name without currency, unit, or quantity prefixes)
    - c_query (optimized query string for the libscanmatch C matching engine)
    """
    raw_str = raw_line.strip()
    norm = normalize_indic_digits(raw_str)
    # Strip list numbering ('1.', '1)', '૧)') and bullets ('•', '-', '*', '▪')
    cleaned = re.sub(
        r"^\s*(?:[0-9\u0AE6-\u0AEF\u0966-\u096F]+[\.\)\:\-]\s*|[•\-\*▪\u2022\u2023\u25E6\u2043\u2219]\s*)",
        "",
        norm
    ).strip()

    # 1. Currency & Value-Pack patterns (e.g. 10₹, ₹10, 10 nu, 20 rupiya na, 20 rs, 20 રૂપિયા)
    currency_patterns = [
        r"^\s*₹\s*(\d+(?:\.\d+)?)\s*(?:નું|નો|ની|ના|nu|na)?\s*(.*)$",
        r"^\s*(\d+(?:\.\d+)?)\s*₹\s*(?:નું|નો|ની|ના|nu|na)?\s*(.*)$",
        r"^\s*(\d+(?:\.\d+)?)\s+(?:નું|નો|ની|ના|nu|na)\s+(.*)$",
        r"^\s*(?:rs\.?|inr|રૂ\.?|રૂપિયા|rupiya)\s*(\d+(?:\.\d+)?)\s*(?:નું|નો|ની|ના|nu|na)?\s*(.*)$",
        r"^\s*(\d+(?:\.\d+)?)\s*(?:rs\.?|inr|રૂ\.?|રૂપિયા|rupiya)\s*(?:નું|નો|ની|ના|nu|na)?\s*(.*)$",
    ]
    for pat in currency_patterns:
        m = re.match(pat, cleaned, re.IGNORECASE)
        if m:
            qty = float(m.group(1))
            item = m.group(2).strip()
            item = re.sub(r"^[₹\s\.\,\-]+", "", item).strip()
            item = re.sub(r"^(?:નું|નો|ની|ના|nu|na)\s+", "", item).strip()
            item = re.sub(r"^(?:rs\.?|inr|રૂ\.?|રૂપિયા|rupiya)\s+", "", item, flags=re.IGNORECASE).strip()
            clean_item = item or raw_str
            q_val = int(qty) if qty.is_integer() else round(qty, 2)
            return {
                "raw_text": raw_str,
                "qty": q_val,
                "unit": "₹",
                "unit_category": "value_pack",
                "unit_display": "₹ (Value Pack)",
                "clean_item": clean_item,
                "c_query": f"{q_val} g {clean_item}"
            }

    sep = r"(?:\s+|$)"

    # 2. Grams (250 g, 250 gm, 250 gms, 250 gram, 250 ગ્રાm, 250 ગ્રા., 250 ગ્રામ, 250 ग्रा, 250 ग्राम)
    m = re.match(rf"^\s*(\d+(?:\.\d+)?)\s*(?:grams|gram|gms|gm|g|ગ્રામ|ગ્રાm|ગ્રા\.|ગ્રા|ग्राम|ग्रा){sep}(.*)$", cleaned, re.IGNORECASE)
    if m:
        qty = float(m.group(1))
        item = m.group(2).strip()
        q_val = int(qty) if qty.is_integer() else round(qty, 2)
        return {
            "raw_text": raw_str,
            "qty": q_val,
            "unit": "g",
            "unit_category": "weight",
            "unit_display": "g",
            "clean_item": item or raw_str,
            "c_query": f"{q_val} g {item}" if item else cleaned
        }

    # 3. Kilograms (2 kg, 2 kilo, 2 કિલો, 2 કીલો, 2 કિગ્રા, 2 કિ.ગ્રા., 2 किलो, 2 किग्रा)
    m = re.match(rf"^\s*(\d+(?:\.\d+)?)\s*(?:kilograms|kilogram|kilos|kilo|kgs|kg|કિલોગ્રામ|કિલો|કીલો|કિ\.ગ્રા\.|કિગ્રા|किलोग्राम|किलो|किग्रा){sep}(.*)$", cleaned, re.IGNORECASE)
    if m:
        qty = float(m.group(1))
        item = m.group(2).strip()
        q_val = int(qty) if qty.is_integer() else round(qty, 2)
        return {
            "raw_text": raw_str,
            "qty": q_val,
            "unit": "kg",
            "unit_category": "weight",
            "unit_display": "kg",
            "clean_item": item or raw_str,
            "c_query": f"{q_val} kg {item}" if item else cleaned
        }

    # 4. Liters (1 l, 1 ltr, 1 liter, 1 litre, 1 લીટર, 1 લિટર, 1 લિ, 1 लीटर)
    m = re.match(rf"^\s*(\d+(?:\.\d+)?)\s*(?:litres|liters|litre|liter|ltr|l|લીટર|લિટર|લિ|लीटर){sep}(.*)$", cleaned, re.IGNORECASE)
    if m:
        qty = float(m.group(1))
        item = m.group(2).strip()
        q_val = int(qty) if qty.is_integer() else round(qty, 2)
        return {
            "raw_text": raw_str,
            "qty": q_val,
            "unit": "L",
            "unit_category": "volume",
            "unit_display": "L",
            "clean_item": item or raw_str,
            "c_query": f"{q_val} l {item}" if item else cleaned
        }

    # 5. Milliliters (500 ml, 500 મિલી, 500 મિલિ, 500 मिली)
    m = re.match(rf"^\s*(\d+(?:\.\d+)?)\s*(?:ml|મિલી|મિલિ|मिली){sep}(.*)$", cleaned, re.IGNORECASE)
    if m:
        qty = float(m.group(1))
        item = m.group(2).strip()
        q_val = int(qty) if qty.is_integer() else round(qty, 2)
        return {
            "raw_text": raw_str,
            "qty": q_val,
            "unit": "ml",
            "unit_category": "volume",
            "unit_display": "ml",
            "clean_item": item or raw_str,
            "c_query": f"{q_val} ml {item}" if item else cleaned
        }

    # 6. Packets (1 packet, 2 pkt, 2 પેકેટ, 2 પૅકેટ, 2 પેક, 2 पैकेट)
    m = re.match(rf"^\s*(\d+(?:\.\d+)?)\s*(?:packets|packet|pkts|pkt|packs|pack|પેકેટ|પૅકેટ|પેક|पैकेट){sep}(.*)$", cleaned, re.IGNORECASE)
    if m:
        qty = float(m.group(1))
        item = m.group(2).strip()
        q_val = int(qty) if qty.is_integer() else round(qty, 2)
        return {
            "raw_text": raw_str,
            "qty": q_val,
            "unit": "packet",
            "unit_category": "packaging",
            "unit_display": "packet",
            "clean_item": item or raw_str,
            "c_query": f"{q_val} packet {item}" if item else cleaned
        }

    # 7. Pouches (1 pouch, 1 પાઉચ, 1 पाउच)
    m = re.match(rf"^\s*(\d+(?:\.\d+)?)\s*(?:pouches|pouch|પાઉચ|पाउच){sep}(.*)$", cleaned, re.IGNORECASE)
    if m:
        qty = float(m.group(1))
        item = m.group(2).strip()
        q_val = int(qty) if qty.is_integer() else round(qty, 2)
        return {
            "raw_text": raw_str,
            "qty": q_val,
            "unit": "pouch",
            "unit_category": "packaging",
            "unit_display": "pouch",
            "clean_item": item or raw_str,
            "c_query": f"{q_val} pouch {item}" if item else cleaned
        }

    # 8. Bottles (1 bottle, 1 બોટલ, 1 بوتل)
    m = re.match(rf"^\s*(\d+(?:\.\d+)?)\s*(?:bottles|bottle|બોટલ|બોટલ્સ|बोतल){sep}(.*)$", cleaned, re.IGNORECASE)
    if m:
        qty = float(m.group(1))
        item = m.group(2).strip()
        q_val = int(qty) if qty.is_integer() else round(qty, 2)
        return {
            "raw_text": raw_str,
            "qty": q_val,
            "unit": "bottle",
            "unit_category": "packaging",
            "unit_display": "bottle",
            "clean_item": item or raw_str,
            "c_query": f"{q_val} bottle {item}" if item else cleaned
        }

    # 9. Boxes (1 box, 1 બોક્સ, 1 બૉક્સ, 1 बॉक्स)
    m = re.match(rf"^\s*(\d+(?:\.\d+)?)\s*(?:boxes|box|બોક્સ|બૉક્સ|बॉक्स){sep}(.*)$", cleaned, re.IGNORECASE)
    if m:
        qty = float(m.group(1))
        item = m.group(2).strip()
        q_val = int(qty) if qty.is_integer() else round(qty, 2)
        return {
            "raw_text": raw_str,
            "qty": q_val,
            "unit": "box",
            "unit_category": "packaging",
            "unit_display": "box",
            "clean_item": item or raw_str,
            "c_query": f"{q_val} box {item}" if item else cleaned
        }

    # 10. Pieces / Count (2 piece, 2 pcs, 2 નંગ, 2 नग)
    m = re.match(rf"^\s*(\d+(?:\.\d+)?)\s*(?:pieces|piece|pcs|pc|items|item|નંગ|ટુકડા|પીસ|नग){sep}(.*)$", cleaned, re.IGNORECASE)
    if m:
        qty = float(m.group(1))
        item = m.group(2).strip()
        q_val = int(qty) if qty.is_integer() else round(qty, 2)
        return {
            "raw_text": raw_str,
            "qty": q_val,
            "unit": "piece",
            "unit_category": "count",
            "unit_display": "piece",
            "clean_item": item or raw_str,
            "c_query": f"{q_val} piece {item}" if item else cleaned
        }

    # 11. Dozen (1 dozen, 1 ડઝન, 1 दर्जन)
    m = re.match(rf"^\s*(\d+(?:\.\d+)?)\s*(?:dozens|dozen|ડઝન|દર્જન){sep}(.*)$", cleaned, re.IGNORECASE)
    if m:
        qty = float(m.group(1))
        item = m.group(2).strip()
        q_val = int(qty) if qty.is_integer() else round(qty, 2)
        return {
            "raw_text": raw_str,
            "qty": q_val,
            "unit": "dozen",
            "unit_category": "count",
            "unit_display": "dozen",
            "clean_item": item or raw_str,
            "c_query": f"{q_val} dozen {item}" if item else cleaned
        }

    # 12. Plain number with item: e.g. '5 safarjan', '2 dabeli'
    m = re.match(rf"^\s*(\d+(?:\.\d+)?)\s+(.*)$", cleaned)
    if m:
        qty = float(m.group(1))
        item = m.group(2).strip()
        q_val = int(qty) if qty.is_integer() else round(qty, 2)
        return {
            "raw_text": raw_str,
            "qty": q_val,
            "unit": None,
            "unit_category": "none",
            "unit_display": "-",
            "clean_item": item or raw_str,
            "c_query": f"{q_val} {item}" if item else cleaned
        }

    # 13. Default line format (e.g., 'Rice 2kg', 'Sugar 1kg', 'ચોખા ૫ કિલો', 'ધાણા')
    return {
        "raw_text": raw_str,
        "qty": None,
        "unit": None,
        "unit_category": "none",
        "unit_display": "-",
        "clean_item": cleaned,
        "c_query": cleaned
    }


def split_shopping_lines(raw_text: str) -> list[str]:
    """Splits raw shopping text on newlines, semicolons, and commas into distinct items."""
    if not raw_text:
        return []
    lines = []
    raw_lines = raw_text.replace(";", "\n").split("\n")
    for raw_line in raw_lines:
        line_str = raw_line.strip()
        if not line_str:
            continue
        subparts = [p.strip() for p in line_str.split(",") if p.strip()]
        for part in subparts:
            lines.append(part)
    return lines


def preprocess_shopping_text(raw_text: str) -> str:
    """Preprocesses user input into clean line-by-line format for the C engine.
    Maintains backward compatibility while leveraging parse_line_meta optimizations.
    """
    subparts = split_shopping_lines(raw_text)
    if not subparts:
        return ""
    parsed = [parse_line_meta(p) for p in subparts]
    return "\n".join(p["c_query"] for p in parsed)


def categorize_unit(unit: str) -> tuple[str, str]:
    """Maps a raw unit string to (unit_category, unit_display)."""
    if not unit or unit == "-":
        return "none", "-"
    u_lower = unit.strip().lower()
    if u_lower in {"g", "gm", "gms", "gram", "grams", "kg", "kgs", "kilo", "kilogram"}:
        return "weight", unit
    if u_lower in {"l", "liter", "litre", "liters", "litres", "ml"}:
        return "volume", unit
    if u_lower in {"packet", "packets", "pack", "packs", "pkt", "pkts", "pouch", "pouches", "bottle", "bottles", "box", "boxes", "can", "tin"}:
        return "packaging", unit
    if u_lower in {"piece", "pieces", "pc", "pcs", "item", "items", "dozen", "dozens"}:
        return "count", unit
    if u_lower in {"₹", "rs", "rupee", "rupees", "rupiya"}:
        return "value_pack", "₹ (Value Pack)"
    return "general", unit


def _map_display_status(score: float, is_catalog_match: bool) -> tuple[str, str, str]:
    """Maps matching score to (display_status, status_category, confidence_tier).
    Tiers:
    - High (>= 0.80): 'Matched successfully', 'matched', 'high'
    - Medium (0.60 <= score < 0.80): 'Likely match — please review', 'review', 'medium'
    - Low (0.40 <= score < 0.60): 'Suggested match — please review', 'review', 'low'
    - Uncataloged / Custom (< 0.40 or not catalog match): 'New / Uncataloged Item', 'uncataloged', 'custom'
    """
    if not is_catalog_match or score < 0.50:
        return "New / Uncataloged Item", "uncataloged", "custom"
    if score >= 0.80:
        return "Matched successfully", "matched", "high"
    if score >= 0.60:
        return "Likely match — please review", "review", "medium"
    return "Suggested match — please review", "review", "low"


def _format_c_results(c_result: dict, parsed_metas: list = None) -> tuple[list, int, int, int]:
    """Helper to transform C library results into UI items with clean naming, categorized units, and tiered confidence."""
    cat_meta = get_catalog_meta()
    raw_items = c_result.get("items", [])
    formatted_items = []
    confirmed_count = 0
    review_count = 0
    unidentified_count = 0

    for i, it in enumerate(raw_items):
        meta = parsed_metas[i] if (parsed_metas and i < len(parsed_metas)) else {}
        raw_text = meta.get("raw_text") or it.get("raw_text", "")
        product_id = it.get("product_id")
        conf = float(it.get("confidence", 0.0))
        product_text = it.get("product_text") or raw_text

        # Determine if this matched an authoritative SKU with sufficient confidence (>= 0.50)
        is_catalog_match = bool(product_id and it.get("name") and conf >= 0.50)

        # 1. Product Name Resolution
        if is_catalog_match:
            product_name = it.get("name")
            active_pid = product_id
            product_category = cat_meta.get(product_id, {}).get("category", "")
        else:
            active_pid = None
            product_category = ""
            # Clean custom item name by removing unit/currency prefixes and particles
            clean_name = meta.get("clean_item") or product_text or raw_text or "Custom Item"
            clean_name = re.sub(r"^[₹\s\.\,\-]+", "", clean_name).strip()
            clean_name = re.sub(r"^(?:નું|નો|ની|ના|nu|na)\s+", "", clean_name).strip()
            clean_name = re.sub(r"^(?:rs\.?|inr|રૂ\.?|રૂપિયા|rupiya)\s+", "", clean_name, flags=re.IGNORECASE).strip()
            clean_name = re.sub(r"^(?:grams|gram|gms|gm|g|ગ્રામ|ગ્રાm|ગ્રા\.|ગ્રા|kg|kgs|kilo|કિલો)\s+", "", clean_name, flags=re.IGNORECASE).strip()
            product_name = clean_name or "Custom Item"

        # 2. Confidence Tier & Display Status Resolution
        disp_status, status_category, conf_tier = _map_display_status(conf, is_catalog_match)

        if status_category == "matched":
            confirmed_count += 1
        elif status_category in {"review", "verify"}:
            review_count += 1
        else:
            unidentified_count += 1

        # 3. Quantity Resolution: parsed meta takes priority
        if meta.get("qty") is not None:
            display_qty = meta["qty"]
        else:
            raw_qty = it.get("quantity")
            if raw_qty is None:
                display_qty = None
            elif isinstance(raw_qty, (int, float)):
                display_qty = int(raw_qty) if float(raw_qty).is_integer() else round(float(raw_qty), 3)
            else:
                display_qty = raw_qty

        # 4. Unit Categorization Resolution
        if meta.get("unit"):
            final_unit = meta["unit"]
            unit_cat = meta.get("unit_category", "general")
            unit_disp = meta.get("unit_display", final_unit)
        elif it.get("unit"):
            final_unit = it.get("unit")
            unit_cat, unit_disp = categorize_unit(final_unit)
        else:
            final_unit = ""
            unit_cat = "none"
            unit_disp = "-"

        conf_percent = f"{int(round(conf * 100))}%" if is_catalog_match else "Custom"

        formatted_items.append({
            "raw_text": raw_text,
            "product": product_name,
            "product_text": product_text,
            "product_id": active_pid,
            "category": product_category,
            "is_catalog_item": is_catalog_match,
            "quantity": display_qty,
            "unit": final_unit,
            "unit_category": unit_cat,
            "unit_display": unit_disp,
            "confidence": round(conf, 4) if is_catalog_match else 0.0,
            "confidence_percent": conf_percent,
            "confidence_tier": conf_tier,
            "status": it.get("status", "unidentified"),
            "display_status": disp_status,
            "status_category": status_category,
            "needs_confirmation": it.get("needs_confirmation", False),
            "candidates": it.get("candidates", []) if is_catalog_match else []
        })

    return formatted_items, confirmed_count, review_count, unidentified_count


@app.post("/api/scan")
async def scan_document(
    file: Optional[UploadFile] = File(None),
    text_input: Optional[str] = Form(None),
    mock_ocr_text: Optional[str] = Form(None),
    api_key: Optional[str] = Form(None),
    ocr_mode: Optional[str] = Form(None)
):
    """Processes shopping list input via:
    1. Direct user text input (real typing & pasting directly to C engine)
    2. Document upload with Google Cloud Vision OCR
    """
    t0 = time.perf_counter()

    # Route 1: Direct Text Input (instant matching without OCR)
    has_text = bool(text_input and text_input.strip())
    has_file = bool(file and file.filename)

    if has_text and not has_file:
        input_text = text_input.strip()
        subparts = split_shopping_lines(input_text)
        parsed_metas = [parse_line_meta(p) for p in subparts] if subparts else [parse_line_meta(input_text)]
        cleaned_text = "\n".join(p["c_query"] for p in parsed_metas)
        log.info(f"Direct text matching request: {len(input_text)} chars -> {len(parsed_metas)} items: {cleaned_text!r}")
        try:
            engine = get_engine()
        except ScanMatchError as sme:
            log.error(f"ScanMatch engine error: {sme}")
            return JSONResponse(
                status_code=500,
                content={"success": False, "error": {"code": sme.code, "message": str(sme)}}
            )

        t_c_start = time.perf_counter()
        c_result = engine.process_text(cleaned_text)
        c_duration_ms = round((time.perf_counter() - t_c_start) * 1000, 2)

        if not c_result.get("success", False) and "error" in c_result:
            return {
                "success": False,
                "mode": "direct_text",
                "error": c_result.get("error"),
                "items": []
            }

        formatted_items, confirmed_count, review_count, unidentified_count = _format_c_results(c_result, parsed_metas)
        total_time_ms = round((time.perf_counter() - t0) * 1000, 2)

        return {
            "success": True,
            "mode": "direct_text",
            "filename": "direct_input.txt",
            "ocr_text": input_text,
            "ocr_confidence": 1.0,
            "items": formatted_items,
            "summary": {
                "total_items": len(formatted_items),
                "confirmed_items": confirmed_count,
                "needs_confirmation": review_count,
                "unidentified_items": unidentified_count
            },
            "timings_ms": {
                "ocr": 0.0,
                "matching": c_duration_ms,
                "total": total_time_ms
            }
        }

    # Route 2: Document Upload Validation
    if not has_file:
        return JSONResponse(
            status_code=400,
            content={
                "success": False,
                "error": {
                    "code": "NO_FILE_SELECTED",
                    "message": "No file was selected for upload and no text was entered."
                }
            }
        )

    # 2. Validation: file extension
    ext = Path(file.filename).suffix.lower()
    if ext not in ALLOWED_EXTENSIONS:
        return JSONResponse(
            status_code=400,
            content={
                "success": False,
                "error": {
                    "code": "UNSUPPORTED_FORMAT",
                    "message": f"Unsupported file type '{ext}'. Allowed: JPG, PNG, WEBP, PDF."
                }
            }
        )

    # 3. Read uploaded bytes with size validation
    content = await file.read()
    if not content or len(content) == 0:
        return JSONResponse(
            status_code=400,
            content={
                "success": False,
                "error": {
                    "code": "EMPTY_FILE",
                    "message": "The uploaded file is empty."
                }
            }
        )

    if len(content) > MAX_FILE_BYTES:
        return JSONResponse(
            status_code=413,
            content={
                "success": False,
                "error": {
                    "code": "FILE_TOO_LARGE",
                    "message": f"File size ({len(content) // 1024} KB) exceeds the 10 MB limit."
                }
            }
        )

    # 4. Safe temporary file handling
    tmp_fd, tmp_path = tempfile.mkstemp(prefix="scanmatch_upload_", suffix=ext)
    try:
        with os.fdopen(tmp_fd, "wb") as f:
            f.write(content)

        # 5. Extract OCR text via Google Cloud Vision
        active_mode = "cloud_vision"
        t_ocr_start = time.perf_counter()
        ocr_res = _ocr_engine.extract_text(
            content,
            filename=file.filename,
            mock_override=mock_ocr_text,
            api_key=api_key
        )
        ocr_duration_ms = round((time.perf_counter() - t_ocr_start) * 1000, 2)

        # Handle OCR extraction errors
        if not ocr_res.success:
            err_msg = ocr_res.error or "OCR extraction failed."
            code = "API_KEY_REQUIRED" if "key" in err_msg.lower() else "OCR_EXTRACTION_FAILED"
            status_code = 400 if code == "API_KEY_REQUIRED" else 500

            return JSONResponse(
                status_code=status_code,
                content={
                    "success": False,
                    "error": {
                        "code": code,
                        "message": err_msg
                    }
                }
            )

        # Handle empty text extracted
        if not ocr_res.text or not ocr_res.text.strip():
            return {
                "success": False,
                "mode": active_mode,
                "error": {
                    "code": "NO_TEXT_DETECTED",
                    "message": "No readable text was detected in the document."
                },
                "items": [],
                "summary": {
                    "total_items": 0,
                    "confirmed_items": 0,
                    "needs_confirmation": 0,
                    "unidentified_items": 0
                }
            }

        # 6. Pass OCR text to libscanmatch C library via ctypes FFI
        try:
            engine = get_engine()
        except ScanMatchError as sme:
            log.error(f"ScanMatch engine error: {sme}")
            return JSONResponse(
                status_code=500,
                content={
                    "success": False,
                    "error": {
                        "code": sme.code,
                        "message": str(sme)
                    }
                }
            )

        t_c_start = time.perf_counter()
        subparts = split_shopping_lines(ocr_res.text)
        parsed_metas = [parse_line_meta(p) for p in subparts] if subparts else [parse_line_meta(ocr_res.text)]
        cleaned_ocr_text = "\n".join(p["c_query"] for p in parsed_metas)
        log.info(f"Document OCR extracted: {len(ocr_res.text)} chars -> {len(parsed_metas)} items: {cleaned_ocr_text!r}")
        c_result = engine.process_text(cleaned_ocr_text)
        c_duration_ms = round((time.perf_counter() - t_c_start) * 1000, 2)

        if not c_result.get("success", False) and "error" in c_result:
            return {
                "success": False,
                "mode": active_mode,
                "error": c_result.get("error"),
                "items": []
            }

        # 7. Format results
        formatted_items, confirmed_count, review_count, unidentified_count = _format_c_results(c_result, parsed_metas)
        total_time_ms = round((time.perf_counter() - t0) * 1000, 2)

        return {
            "success": True,
            "mode": active_mode,
            "filename": file.filename,
            "ocr_text": ocr_res.text,
            "ocr_confidence": ocr_res.confidence,
            "items": formatted_items,
            "summary": {
                "total_items": len(formatted_items),
                "confirmed_items": confirmed_count,
                "needs_confirmation": review_count,
                "unidentified_items": unidentified_count
            },
            "timings_ms": {
                "ocr": ocr_duration_ms,
                "matching": c_duration_ms,
                "total": total_time_ms
            }
        }

    finally:
        # Safe temporary file cleanup
        if os.path.exists(tmp_path):
            try:
                os.unlink(tmp_path)
            except OSError:
                pass
