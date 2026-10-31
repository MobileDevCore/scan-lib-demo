"""Targeted test suite for ScanMatch Local Mini Application.

Verifies:
1. /health
2. upload image fixture
3. upload PDF fixture
4. MockOCR result
5. ctypes -> libscanmatch C library FFI
6. Gujarati example (ચોખા ૫ કિલો)
7. Hindi example (चावल 2 किलो)
8. English example (Rice 2 kg)
9. Mixed-language example (5 kg ચોખા)
10. Invalid file format handling
11. Missing library error handling
12. Malformed / unconfigured fixture error handling
"""

import io
import os
import unittest
from pathlib import Path
from fastapi.testclient import TestClient

from server.app import app, get_engine
from server.ocr_service import GoogleCloudVisionOCR, OCRResult
from python.scanmatch_ctypes import ScanMatch, ScanMatchError


class TestScanMatchMiniProject(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.client = TestClient(app)
        cls.root_dir = Path(__file__).resolve().parents[1]

    def test_01_health_endpoint(self):
        """1. Verify GET /health endpoint returns healthy status and loaded catalog."""
        resp = self.client.get("/health")
        self.assertEqual(resp.status_code, 200)
        data = resp.json()
        self.assertTrue(data.get("success"))
        self.assertEqual(data.get("status"), "healthy")
        self.assertEqual(data.get("catalog"), "loaded")
        self.assertEqual(data.get("ocr_engine"), "google_cloud_vision")

    def test_02_cloud_vision_ocr_override(self):
        """2. Verify GoogleCloudVisionOCR extraction with override."""
        ocr = GoogleCloudVisionOCR()
        res = ocr.extract_text(b"fake_image_bytes", filename="test.png", mock_override="ચોખા ૫ કિલો")
        self.assertIsInstance(res, OCRResult)
        self.assertTrue(res.success)
        self.assertEqual(res.text, "ચોખા ૫ કિલો")
        self.assertGreaterEqual(res.confidence, 0.90)

    def test_03_ctypes_to_c_library_direct(self):
        """3. Verify ctypes directly invokes the C library matching engine."""
        engine = get_engine()
        self.assertIsNotNone(engine.ctx)

        # Directly invoke C library with multilingual line
        res = engine.process_text("Rice 2 kg\n")
        self.assertTrue(res.get("success"))
        self.assertIn("items", res)
        items = res["items"]
        self.assertGreater(len(items), 0)
        self.assertEqual(items[0]["product_id"], "RICE001")
        self.assertEqual(items[0]["name"], "Rice")
        self.assertEqual(items[0]["quantity"], 2.0)
        self.assertEqual(items[0]["unit"], "kg")

    def test_04_upload_image_fixture(self):
        """4. Verify uploading an image document via POST /api/scan."""
        file_bytes = b"Simulated image header and bytes"
        resp = self.client.post(
            "/api/scan",
            files={"file": ("shopping_list.png", io.BytesIO(file_bytes), "image/png")},
            data={"mock_ocr_text": "Rice 2 kg"}
        )
        self.assertEqual(resp.status_code, 200)
        data = resp.json()
        self.assertTrue(data.get("success"))
        self.assertEqual(data.get("mode"), "cloud_vision")
        self.assertIn("items", data)
        self.assertIn("summary", data)
        self.assertGreater(data["summary"]["total_items"], 0)

    def test_05_upload_pdf_fixture(self):
        """5. Verify uploading a PDF document via POST /api/scan."""
        pdf_bytes = b"%PDF-1.4 Simulated PDF Document"
        resp = self.client.post(
            "/api/scan",
            files={"file": ("shopping_order.pdf", io.BytesIO(pdf_bytes), "application/pdf")},
            data={"mock_ocr_text": "Sugar 1 kg\nચોખા ૫ કિલો"}
        )
        self.assertEqual(resp.status_code, 200)
        data = resp.json()
        self.assertTrue(data.get("success"))
        self.assertEqual(data.get("mode"), "cloud_vision")
        self.assertIn("items", data)
        self.assertGreater(data["summary"]["total_items"], 0)

    def test_06_gujarati_example(self):
        """6. Verify Gujarati input: 'ચોખા ૫ કિલો' matches Rice."""
        resp = self.client.post(
            "/api/scan",
            files={"file": ("test_gujarati.png", io.BytesIO(b"img"), "image/png")},
            data={"mock_ocr_text": "ચોખા ૫ કિલો"}
        )
        self.assertEqual(resp.status_code, 200)
        data = resp.json()
        self.assertTrue(data.get("success"))
        item = data["items"][0]
        self.assertEqual(item["product_id"], "RICE001")
        self.assertEqual(item["product"], "Rice")
        self.assertEqual(item["quantity"], 5)
        self.assertEqual(item["unit"], "kg")
        self.assertEqual(item["status_category"], "matched")
        self.assertEqual(item["display_status"], "Matched successfully")

    def test_07_hindi_example(self):
        """7. Verify Hindi input: 'चावल 2 किलो' matches Rice."""
        resp = self.client.post(
            "/api/scan",
            files={"file": ("test_hindi.png", io.BytesIO(b"img"), "image/png")},
            data={"mock_ocr_text": "चावल 2 किलो"}
        )
        self.assertEqual(resp.status_code, 200)
        data = resp.json()
        self.assertTrue(data.get("success"))
        item = data["items"][0]
        self.assertEqual(item["product_id"], "RICE001")
        self.assertEqual(item["product"], "Rice")
        self.assertEqual(item["quantity"], 2)
        self.assertEqual(item["unit"], "kg")
        self.assertEqual(item["status_category"], "matched")

    def test_08_english_example(self):
        """8. Verify English input: 'Rice 2 kg' matches Rice."""
        resp = self.client.post(
            "/api/scan",
            files={"file": ("test_english.jpg", io.BytesIO(b"img"), "image/jpeg")},
            data={"mock_ocr_text": "Rice 2 kg"}
        )
        self.assertEqual(resp.status_code, 200)
        data = resp.json()
        self.assertTrue(data.get("success"))
        item = data["items"][0]
        self.assertEqual(item["product_id"], "RICE001")
        self.assertEqual(item["product"], "Rice")
        self.assertEqual(item["quantity"], 2)
        self.assertEqual(item["unit"], "kg")

    def test_09_mixed_language_example(self):
        """9. Verify mixed-language input: '5 kg ચોખા' matches Rice."""
        resp = self.client.post(
            "/api/scan",
            files={"file": ("test_mixed.webp", io.BytesIO(b"img"), "image/webp")},
            data={"mock_ocr_text": "5 kg ચોખા"}
        )
        self.assertEqual(resp.status_code, 200)
        data = resp.json()
        self.assertTrue(data.get("success"))
        item = data["items"][0]
        self.assertEqual(item["product_id"], "RICE001")
        self.assertEqual(item["product"], "Rice")
        self.assertEqual(item["quantity"], 5)
        self.assertEqual(item["unit"], "kg")

    def test_10_invalid_file_handling(self):
        """10. Verify unsupported extensions (e.g. .exe) are safely rejected."""
        resp = self.client.post(
            "/api/scan",
            files={"file": ("malware.exe", io.BytesIO(b"binary"), "application/octet-stream")}
        )
        self.assertEqual(resp.status_code, 400)
        data = resp.json()
        self.assertFalse(data.get("success"))
        self.assertEqual(data["error"]["code"], "UNSUPPORTED_FORMAT")

    def test_11_empty_file_handling(self):
        """11. Verify empty uploads are cleanly rejected."""
        resp = self.client.post(
            "/api/scan",
            files={"file": ("empty.png", io.BytesIO(b""), "image/png")}
        )
        self.assertEqual(resp.status_code, 400)
        data = resp.json()
        self.assertFalse(data.get("success"))
        self.assertEqual(data["error"]["code"], "EMPTY_FILE")

    def test_12_unconfigured_cloud_vision_handling(self):
        """12. Verify document upload without API key prompts for Google Cloud Vision API key."""
        resp = self.client.post(
            "/api/scan",
            files={"file": ("unconfigured_random_doc.pdf", io.BytesIO(b"dummy"), "application/pdf")}
        )
        self.assertEqual(resp.status_code, 400)
        data = resp.json()
        self.assertFalse(data.get("success"))
        self.assertEqual(data["error"]["code"], "API_KEY_REQUIRED")
        self.assertIn("Google Cloud Vision API key", data["error"]["message"])

    def test_13_missing_library_handling(self):
        """13. Verify ScanMatch raises clean ScanMatchError if library is absent."""
        fake_path = self.root_dir / "build" / "nonexistent_lib.so"
        with self.assertRaises(ScanMatchError) as ctx:
            ScanMatch(fake_path)
        self.assertEqual(ctx.exception.code, "LIBRARY_NOT_FOUND")

    def test_14_no_file_rejected(self):
        """14. Verify request without document file is rejected."""
        resp = self.client.post(
            "/api/scan",
            data={}
        )
        self.assertEqual(resp.status_code, 400)
        data = resp.json()
        self.assertFalse(data.get("success"))
        self.assertEqual(data["error"]["code"], "NO_FILE_SELECTED")

    def test_15_cloud_vision_unconfigured_error(self):
        """15. Verify Cloud Vision OCR mode returns descriptive error when API key is missing."""
        resp = self.client.post(
            "/api/scan",
            files={"file": ("receipt.png", io.BytesIO(b"dummy image bytes"), "image/png")}
        )
        self.assertEqual(resp.status_code, 400)
        data = resp.json()
        self.assertFalse(data.get("success"))
        self.assertEqual(data["error"]["code"], "API_KEY_REQUIRED")

    def test_16_direct_text_input(self):
        """16. Verify direct text input matches items directly without file upload."""
        resp = self.client.post(
            "/api/scan",
            data={"text_input": "ચોખા ૫ કિલો\nSugar 1 kg"}
        )
        self.assertEqual(resp.status_code, 200)
        data = resp.json()
        self.assertTrue(data.get("success"))
        self.assertEqual(data.get("mode"), "direct_text")
        self.assertEqual(len(data.get("items", [])), 2)
        self.assertEqual(data["items"][0]["product_id"], "RICE001")
        self.assertEqual(data["items"][1]["product_id"], "SUGAR001")

    def test_17_get_catalog_endpoint(self):
        """17. Verify GET /api/catalog returns loaded catalog items."""
        resp = self.client.get("/api/catalog")
        self.assertEqual(resp.status_code, 200)
        data = resp.json()
        self.assertTrue(data.get("success"))
        self.assertGreaterEqual(data.get("count", 0), 30)
        self.assertIsInstance(data.get("products"), list)

    def test_18_direct_text_flexible_formatting(self):
        """18. Verify comma separation, numbering, and bullets match correctly."""
        text = "1. Rice 2kg, 2. Sugar 1kg, 3. Salt 1 packet, 4. Oil 2L"
        resp = self.client.post("/api/scan", data={"text_input": text})
        self.assertEqual(resp.status_code, 200)
        data = resp.json()
        self.assertTrue(data.get("success"))
        self.assertEqual(data["summary"]["total_items"], 4)
        matched_skus = {it["product_id"] for it in data["items"]}
        self.assertIn("RICE001", matched_skus)
        self.assertIn("SUGAR001", matched_skus)
        self.assertIn("SALT001", matched_skus)
        self.assertIn("OIL001", matched_skus)

    def test_19_uncataloged_item_fallback(self):
        """19. Verify uncataloged items fall back to parsed product_text with quantities."""
        text = "2 kg dragon fruit\n1 packet masala oats"
        resp = self.client.post("/api/scan", data={"text_input": text})
        self.assertEqual(resp.status_code, 200)
        data = resp.json()
        self.assertTrue(data.get("success"))
        self.assertEqual(len(data.get("items", [])), 2)

        it0 = data["items"][0]
        self.assertEqual(it0["product"], "dragon fruit")
        self.assertEqual(it0["quantity"], 2)
        self.assertEqual(it0["unit"], "kg")
        self.assertFalse(it0["is_catalog_item"])
        self.assertEqual(it0["display_status"], "New / Uncataloged Item")

        it1 = data["items"][1]
        self.assertEqual(it1["product"], "masala oats")
        self.assertEqual(it1["quantity"], 1)
        self.assertEqual(it1["unit"], "packet")
        self.assertFalse(it1["is_catalog_item"])

    def test_20_user_reported_shopping_items(self):
        """20. Verify specific items from user test list match catalog, categorize units, and provide high confidence."""
        input_text = "૧૦₹ આમબલિ\n100 ग्रा मिर्च सुका\n500 Gram અડદ દાળ\n૧૦ નું સંચળ\n250 ગ્રાm સુકી દ્રાક્ષ\n20 rupiya ના મગ"
        resp = self.client.post("/api/scan", data={"text_input": input_text})
        self.assertEqual(resp.status_code, 200)
        data = resp.json()
        self.assertTrue(data.get("success"))
        items = data.get("items", [])
        self.assertEqual(len(items), 6)

        # 1. ૧૦₹ આમબલિ -> Tamarind (TAMARIND001), 10, ₹ (Value Pack), High Conf
        self.assertEqual(items[0]["product"], "Tamarind")
        self.assertEqual(items[0]["product_id"], "TAMARIND001")
        self.assertEqual(items[0]["quantity"], 10)
        self.assertEqual(items[0]["unit"], "₹")
        self.assertEqual(items[0]["unit_category"], "value_pack")
        self.assertEqual(items[0]["confidence_tier"], "high")

        # 2. 100 ग्रा मिर्च सुका -> Whole Dry Red Chilli (DRYCHILLI001), 100 g
        self.assertEqual(items[1]["product"], "Whole Dry Red Chilli")
        self.assertEqual(items[1]["product_id"], "DRYCHILLI001")
        self.assertEqual(items[1]["quantity"], 100)
        self.assertEqual(items[1]["unit"], "g")
        self.assertEqual(items[1]["unit_category"], "weight")
        self.assertEqual(items[1]["confidence_tier"], "high")

        # 3. 500 Gram અડદ દાળ -> Urad Dal (URADDAL001), 500 g
        self.assertEqual(items[2]["product"], "Urad Dal")
        self.assertEqual(items[2]["product_id"], "URADDAL001")
        self.assertEqual(items[2]["quantity"], 500)
        self.assertEqual(items[2]["unit"], "g")
        self.assertEqual(items[2]["unit_category"], "weight")
        self.assertEqual(items[2]["confidence_tier"], "high")

        # 4. ૧૦ નું સંચળ -> Black Salt (BLACKSALT001), 10, ₹ (Value Pack)
        self.assertEqual(items[3]["product"], "Black Salt")
        self.assertEqual(items[3]["product_id"], "BLACKSALT001")
        self.assertEqual(items[3]["quantity"], 10)
        self.assertEqual(items[3]["unit"], "₹")
        self.assertEqual(items[3]["unit_category"], "value_pack")
        self.assertEqual(items[3]["confidence_tier"], "high")

        # 5. 250 ગ્રાm સુકી દ્રાક્ષ -> Raisins (RAISINS001), 250 g
        self.assertEqual(items[4]["product"], "Raisins")
        self.assertEqual(items[4]["product_id"], "RAISINS001")
        self.assertEqual(items[4]["quantity"], 250)
        self.assertEqual(items[4]["unit"], "g")
        self.assertEqual(items[4]["unit_category"], "weight")
        self.assertEqual(items[4]["confidence_tier"], "high")

        # 6. 20 rupiya ના મગ -> Moong Whole (MOONGWHOLE001), 20, ₹ (Value Pack)
        self.assertEqual(items[5]["product"], "Moong Whole")
        self.assertEqual(items[5]["product_id"], "MOONGWHOLE001")
        self.assertEqual(items[5]["quantity"], 20)
        self.assertEqual(items[5]["unit"], "₹")
        self.assertEqual(items[5]["unit_category"], "value_pack")
        self.assertEqual(items[5]["confidence_tier"], "high")


if __name__ == "__main__":
    unittest.main()


