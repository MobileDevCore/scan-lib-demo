# ScanMatch - Shopping List Matcher

A focused, lightweight local production-style web application for Gujarati, Hindi, and English handwritten and printed shopping-list processing and catalog matching powered by Google Cloud Vision and a high-performance C matching engine (`libscanmatch`).

---

## 1. What the Mini-Project Does

ScanMatch accepts an uploaded shopping list document (image or PDF), extracts handwritten and printed text in Gujarati, Hindi, and English via **Google Cloud Vision OCR**, passes the raw text to the compiled C engine via Python ctypes FFI, matches items against the product catalog, and displays the structured result in a responsive web table.

---

## 2. Architecture

```
User (Browser)
    ↓  Upload Image / PDF (JPG, PNG, WEBP, PDF) + Cloud Vision API Key
FastAPI (/api/scan)
    ↓  Validate & safe temporary storage
Google Cloud Vision OCR (server/ocr_service.py)
    ↓  DOCUMENT_TEXT_DETECTION (Gujarati, Hindi, English)
Python ctypes FFI (python/scanmatch_ctypes.py)
    ↓  UTF-8 byte buffer
libscanmatch (build/libscanmatch.dll or libscanmatch.so)
    ↓  Normalization, Indic digit conversion, quantity/unit parsing, catalog matching
ScanMatch JSON Output
    ↓  Structured response & status categorization
Browser Results Table & Summary Cards
```

---

## 3. Requirements

- Python 3.10+
- Compiled C library: `build/libscanmatch.so` (authoritative Linux ELF shared object for Linux / DigitalOcean) and/or `build/libscanmatch.dll` (for Windows environments).

---

## 4. Build Requirement for `libscanmatch.so`

The authoritative matching engine is compiled into `build/libscanmatch.so`.

To compile on Linux:
```bash
gcc -O3 -shared -fPIC -std=c11 \
    src/scanmatch.c src/text.c src/parser.c src/embedding.c src/ffi.c \
    -Iinclude -o build/libscanmatch.so -lm
```

---

## 5. Python Setup

Install the minimal required dependencies:

```bash
pip install -r requirements.txt
```

*(Dependencies: `fastapi`, `uvicorn`, `python-multipart`)*

---

## 6. Run Command

Start the local FastAPI server:

```bash
uvicorn server.app:app --host 127.0.0.1 --port 8000
```

---

## 7. Browser URL

Open your web browser and navigate to:

```
http://127.0.0.1:8000/
```

---

## 8. API Endpoints

- **`GET /`**: Web user interface with dual input options (Direct Text Input & Cloud Vision Document Upload).
- **`GET /health`**: Health check probe returning engine, catalog, and Cloud Vision configuration status.
- **`POST /api/scan`**: Accepts:
  - `text_input`: Direct plain text shopping list (real typing & pasting, zero-latency direct C engine matching).
  - `file`: Multipart file upload (`.jpg`, `.jpeg`, `.png`, `.webp`, `.pdf`) for Google Cloud Vision OCR.
  - `api_key`: Optional Google Cloud Vision API key (can also be configured via `GOOGLE_VISION_API_KEY` on the server).

---

## 9. Input & Matching Modes

ScanMatch provides two high-efficiency input pathways:
1. **Direct Text Input (Instant & Real-Time)**:
   Type or paste raw shopping items in Gujarati, Hindi, English, or mixed scripts. Matches directly against the product catalog using the C engine with zero OCR overhead.
2. **Google Cloud Vision OCR (Document Upload)**:
   Extracts handwritten and printed text from images/PDFs using Google Cloud Vision API (`DOCUMENT_TEXT_DETECTION`). Provide your API key in the UI (saved locally) or export `GOOGLE_VISION_API_KEY`.

---

## 10. Example Multilingual Inputs

The application handles Gujarati, Hindi, English, and mixed-language inputs:

- **Gujarati**: `ચોખા ૫ કિલો` → Rice (5 kg, Matched)
- **Gujarati**: `કાજુ ૨૫૦ ગ્રામ` → Cashew (250 g, Matched)
- **Gujarati**: `ગોળ ૧ કિલો` → Jaggery (1 kg, Matched)
- **Gujarati**: `પાપડ ૨ પેકેટ` → Papad (2 packet, Matched)
- **English**: `Rice 2 kg` → Rice (2 kg, Matched)
- **Hindi**: `चावल 2 किलो` → Rice (2 kg, Matched)
- **Mixed**: `5 kg ચોખા` → Rice (5 kg, Matched)

---

## 11. Running the Automated Test Suite

Run the focused test suite covering all 12+ functional criteria:

```bash
python -m unittest tests/test_mini_project.py
```
