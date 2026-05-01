"""
Standalone ML Pipeline Test Script
Run: .\\.venv\\Scripts\\python.exe test_pipeline.py
Tests: OCR, ClinicalBERT, BioGPT, and X-ray analysis
"""

import io
import json
import threading
import time
from http.server import HTTPServer, SimpleHTTPRequestHandler
from pathlib import Path

import httpx
from PIL import Image
import numpy as np

ML_API = "http://127.0.0.1:8000"
LOCAL_FILE_PORT = 9111  # temp server to serve test files to the ML API

# ---------------------------------------------------------------------------
# 1.  Create synthetic test files
# ---------------------------------------------------------------------------

TEST_DIR = Path(__file__).parent / "_test_assets"
TEST_DIR.mkdir(exist_ok=True)


def create_test_xray():
    """Create a fake grayscale 'X-ray' image (512x512) for testing."""
    rng = np.random.default_rng(42)
    arr = (rng.random((512, 512)) * 255).astype(np.uint8)
    img = Image.fromarray(arr, mode="L").convert("RGB")
    path = TEST_DIR / "test_xray.png"
    img.save(path)
    return path


def create_test_prescription():
    """Create a simple image with text for OCR testing."""
    img = Image.new("RGB", (800, 400), color=(255, 255, 255))
    # We'll use PIL to draw text if available, otherwise save blank
    try:
        from PIL import ImageDraw, ImageFont
        draw = ImageDraw.Draw(img)
        lines = [
            "PRESCRIPTION",
            "Patient: John Doe, Age: 45, Male",
            "Date: 2025-01-15",
            "",
            "Diagnosis: Suspected pneumonia with pleural effusion",
            "Chief complaint: Persistent cough for 3 weeks",
            "Fever: 101.2F intermittent",
            "",
            "Rx:",
            "1. Amoxicillin 500mg TID x 7 days",
            "2. Acetaminophen 650mg PRN for fever",
            "3. Chest X-ray PA view - STAT",
            "4. CBC with differential, CRP, ESR",
            "",
            "Follow up in 1 week.",
            "Dr. Smith, MD - Pulmonology",
        ]
        y = 20
        for line in lines:
            draw.text((30, y), line, fill=(0, 0, 0))
            y += 22
    except Exception:
        pass  # blank image still tests the pipeline
    path = TEST_DIR / "test_prescription.png"
    img.save(path)
    return path


# ---------------------------------------------------------------------------
# 2.  Tiny local HTTP server to serve files to the ML API
# ---------------------------------------------------------------------------

class QuietHandler(SimpleHTTPRequestHandler):
    def __init__(self, *args, **kwargs):
        super().__init__(*args, directory=str(TEST_DIR), **kwargs)

    def log_message(self, *args):
        pass  # suppress logs


def start_file_server():
    server = HTTPServer(("127.0.0.1", LOCAL_FILE_PORT), QuietHandler)
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    return server


# ---------------------------------------------------------------------------
# 3.  Run tests
# ---------------------------------------------------------------------------

def test_health():
    print("=" * 60)
    print("TEST 1: Health Check")
    print("=" * 60)
    r = httpx.get(f"{ML_API}/health", timeout=10)
    data = r.json()
    ok = data.get("status") == "ok"
    print(f"  Status: {data}")
    print(f"  Result: {'PASS âœ…' if ok else 'FAIL âŒ'}\n")
    return ok


def test_ocr_and_clinicalbert(base_url: str):
    print("=" * 60)
    print("TEST 2: OCR + ClinicalBERT (prescription image)")
    print("=" * 60)
    payload = {
        "patient": {
            "id": "test-001",
            "name": "John Doe",
            "age": 45,
            "gender": "Male",
            "symptoms": "persistent cough, fever, chest pain",
        },
        "documents": [
            {
                "id": "rx-001",
                "name": "test_prescription.png",
                "url": f"{base_url}/test_prescription.png",
                "analysis_type": "ocr_only",
            }
        ],
        "doctor_suggestions": "Suspect lower respiratory tract infection",
    }

    print("  Sending request (first call loads models â€” may take 2-5 min)...")
    r = httpx.post(f"{ML_API}/analyze", json=payload, timeout=600)
    data = r.json()

    ocr_ok = len(data.get("ocr_text", "")) > 0
    findings = data.get("clinicalbert_findings", [])
    summary = data.get("biogpt_summary", "")
    limitations = data.get("limitations", [])

    print(f"  OCR text length  : {len(data.get('ocr_text', ''))} chars")
    print(f"  OCR extracted    : {'YES âœ…' if ocr_ok else 'NO âš ï¸  (blank image or Tesseract issue)'}")
    print(f"  ClinicalBERT     : {len(findings)} findings extracted")
    for i, f in enumerate(findings[:3]):
        print(f"    [{i+1}] {f[:100]}...")
    print(f"  BioGPT summary   : {summary[:200]}...")
    print(f"  Limitations      : {limitations or 'None'}")
    print(f"  Result: {'PASS âœ…' if not limitations else 'PARTIAL âš ï¸'}\n")
    return data


def test_xray(base_url: str):
    print("=" * 60)
    print("TEST 3: X-ray Analysis (torchxrayvision)")
    print("=" * 60)
    payload = {
        "patient": {
            "id": "test-001",
            "name": "John Doe",
            "age": 45,
            "gender": "Male",
            "symptoms": "persistent cough, fever",
        },
        "documents": [
            {
                "id": "xr-001",
                "name": "test_xray.png",
                "url": f"{base_url}/test_xray.png",
                "analysis_type": "xray",
            }
        ],
    }

    print("  Sending request (first call loads X-ray model)...")
    r = httpx.post(f"{ML_API}/analyze", json=payload, timeout=600)
    data = r.json()

    imaging = data.get("imaging_findings", [])
    limitations = data.get("limitations", [])

    if imaging:
        print(f"  Modality         : {imaging[0].get('modality')}")
        print(f"  Method           : {imaging[0].get('analysis_method')}")
        print(f"  Summary          : {imaging[0].get('summary', '')[:200]}")
        scores = imaging[0].get("scores", [])
        print(f"  Top pathologies  :")
        for label, score in scores[:5]:
            bar = "â–ˆ" * int(max(score, 0) * 20)
            print(f"    {label:30s} {score:+.3f}  {bar}")
    else:
        print(f"  No imaging findings returned")

    print(f"  Limitations      : {limitations or 'None'}")
    print(f"  Result: {'PASS âœ…' if imaging and not limitations else 'PARTIAL âš ï¸'}\n")
    return data


def test_full_pipeline(base_url: str):
    print("=" * 60)
    print("TEST 4: Full Pipeline (OCR + X-ray + ClinicalBERT + BioGPT)")
    print("=" * 60)
    payload = {
        "patient": {
            "id": "test-001",
            "name": "John Doe",
            "age": 45,
            "gender": "Male",
            "symptoms": "persistent cough, intermittent fever, chest tightness",
        },
        "documents": [
            {
                "id": "rx-001",
                "name": "test_prescription.png",
                "url": f"{base_url}/test_prescription.png",
                "analysis_type": "ocr_only",
            },
            {
                "id": "xr-001",
                "name": "test_xray.png",
                "url": f"{base_url}/test_xray.png",
                "analysis_type": "xray",
            },
        ],
        "doctor_suggestions": "Rule out pneumonia. Consider CT if X-ray inconclusive.",
    }

    print("  Sending request with both documents...")
    r = httpx.post(f"{ML_API}/analyze", json=payload, timeout=600)
    data = r.json()

    print(f"  OCR items        : {len(data.get('ocr_items', []))}")
    print(f"  ClinicalBERT     : {len(data.get('clinicalbert_findings', []))} findings")
    print(f"  Imaging findings : {len(data.get('imaging_findings', []))}")
    print(f"  BioGPT summary   : {data.get('biogpt_summary', '')[:300]}...")
    print(f"  Models used      : {json.dumps(data.get('models_used', {}), indent=4)}")
    print(f"  Limitations      : {data.get('limitations') or 'None'}")

    has_summary = len(data.get("biogpt_summary", "")) > 50
    has_imaging = len(data.get("imaging_findings", [])) > 0
    print(f"\n  Result: {'PASS âœ…' if has_summary and has_imaging else 'PARTIAL âš ï¸'}\n")
    return data


# ---------------------------------------------------------------------------

if __name__ == "__main__":
    print("\n[+] HealthAI ML Pipeline -- Standalone Test Suite\n")

    # Create test assets
    print("Creating test assets...")
    create_test_xray()
    create_test_prescription()

    # Start local file server
    server = start_file_server()
    base_url = f"http://127.0.0.1:{LOCAL_FILE_PORT}"
    print(f"Local file server running at {base_url}\n")

    try:
        test_health()
        test_ocr_and_clinicalbert(base_url)
        test_xray(base_url)
        test_full_pipeline(base_url)
    finally:
        server.shutdown()

    print("=" * 60)
    print("[+] All tests complete!")
    print("=" * 60)

