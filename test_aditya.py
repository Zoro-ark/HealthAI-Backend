"""Test ML pipeline with Aditya's actual reports."""

import json
import threading
from http.server import HTTPServer, SimpleHTTPRequestHandler
from pathlib import Path

import httpx

ML_API = "http://127.0.0.1:8000"
LOCAL_FILE_PORT = 9112
TEST_DIR = Path(__file__).parent / "_test_assets"


class QuietHandler(SimpleHTTPRequestHandler):
    def __init__(self, *args, **kwargs):
        super().__init__(*args, directory=str(TEST_DIR), **kwargs)
    def log_message(self, *args):
        pass


def start_file_server():
    server = HTTPServer(("127.0.0.1", LOCAL_FILE_PORT), QuietHandler)
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    return server


if __name__ == "__main__":
    print("\n[+] Testing with Aditya's reports\n")

    server = start_file_server()
    base = f"http://127.0.0.1:{LOCAL_FILE_PORT}"

    payload = {
        "patient": {
            "id": "aditya-001",
            "name": "Aditya",
            "age": 22,
            "gender": "Male",
            "symptoms": "medical checkup reports",
        },
        "documents": [
            {
                "id": "pdf-001",
                "name": "report.pdf",
                "url": f"{base}/report.pdf",
                "analysis_type": "ocr_only",
            },
            {
                "id": "xr-001",
                "name": "chest_xray.jpg",
                "url": f"{base}/chest_xray.jpg",
                "analysis_type": "xray",
            },
        ],
        "doctor_suggestions": "Patient is from Agra. Complete checkup requested.",
    }

    print("Sending to ML pipeline (may take 1-2 min)...")
    r = httpx.post(f"{ML_API}/analyze", json=payload, timeout=600)
    data = r.json()

    print("\n" + "=" * 60)
    print("OCR EXTRACTED TEXT")
    print("=" * 60)
    print(data.get("ocr_text", "(none)")[:2000])

    print("\n" + "=" * 60)
    print("CLINICALBERT KEY FINDINGS")
    print("=" * 60)
    for i, f in enumerate(data.get("clinicalbert_findings", []), 1):
        print(f"  [{i}] {f}")

    print("\n" + "=" * 60)
    print("X-RAY ANALYSIS")
    print("=" * 60)
    for img in data.get("imaging_findings", []):
        print(f"  Method : {img.get('analysis_method')}")
        print(f"  Summary: {img.get('summary')}")
        print(f"  Scores :")
        for label, score in img.get("scores", []):
            bar = "#" * int(max(score, 0) * 30)
            print(f"    {label:30s} {score:+.3f}  {bar}")

    print("\n" + "=" * 60)
    print("BIOGPT SUMMARY")
    print("=" * 60)
    print(data.get("biogpt_summary", "(none)"))

    if data.get("limitations"):
        print("\n" + "=" * 60)
        print("LIMITATIONS")
        print("=" * 60)
        for lim in data["limitations"]:
            print(f"  - {lim}")

    print("\n" + "=" * 60)
    print("MODELS USED")
    print("=" * 60)
    print(json.dumps(data.get("models_used", {}), indent=2))

    server.shutdown()
    print("\n[+] Done!")
