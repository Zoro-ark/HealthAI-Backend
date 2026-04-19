## ML Service

This FastAPI service handles the doctor analysis pipeline:

- OCR for uploaded medical files
- ClinicalBERT sentence-level finding extraction
- Imaging analysis adapters
- BioGPT summary generation

Run it with:

```bash
pip install -r requirements-ml.txt
uvicorn ml_service.main:app --host 0.0.0.0 --port 8000 --reload
```

Environment variables:

- `HF_TOKEN` optional, used when downloading gated or rate-limited Hugging Face assets
- `OCR_ENGINE` optional, defaults to `pytesseract`
- `CLINICALBERT_MODEL`, defaults to `emilyalsentzer/Bio_ClinicalBERT`
- `BIOGPT_MODEL`, defaults to `microsoft/biogpt`
- `XRAY_MODEL_WEIGHTS`, defaults to `densenet121-res224-all`

Important limits:

- Chest X-ray image analysis is implemented with TorchXRayVision.
- CT and MRI branches validate the modality and return guidance for MONAI-compatible
  volumes. The current code does not claim general CT/MRI diagnosis from arbitrary 2D uploads.
