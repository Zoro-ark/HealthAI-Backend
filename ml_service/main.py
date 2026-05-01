import io
import json
import os
import re
import tempfile
import time
import zipfile
from contextlib import nullcontext
from functools import lru_cache
from pathlib import Path
from typing import Any, Literal

from dotenv import load_dotenv

load_dotenv(Path(__file__).resolve().parent.parent / ".env")

import httpx
import nibabel as nib
import numpy as np
from fastapi import FastAPI, HTTPException
from PIL import Image
from pydantic import BaseModel, Field


app = FastAPI(title="HealthAI ML Pipeline", version="2.0.0")

BUNDLE_ROOT = Path(__file__).resolve().parent.parent / "bundles"
CT_BUNDLE_DIR = BUNDLE_ROOT / "wholeBody_ct_segmentation"
MRI_BUNDLE_DIR = BUNDLE_ROOT / "brats_mri_segmentation"


def ensure_monai_bundle(bundle_name: str, repo: str, bundle_dir: Path) -> None:
    if (bundle_dir / "configs" / "metadata.json").exists() and (bundle_dir / "models" / "model.pt").exists():
        return

    from monai.bundle.scripts import download

    BUNDLE_ROOT.mkdir(parents=True, exist_ok=True)
    download(
        name=bundle_name,
        source="huggingface_hub",
        repo=repo,
        bundle_dir=str(BUNDLE_ROOT),
    )


class PatientContext(BaseModel):
    id: str
    name: str
    age: int | None = None
    gender: str | None = None
    symptoms: str | None = None


class AnalysisDocument(BaseModel):
    id: str
    name: str
    url: str
    analysis_type: Literal["ocr_only", "xray", "ct", "mri"] = "ocr_only"


class AnalysisRequest(BaseModel):
    patient: PatientContext
    documents: list[AnalysisDocument] = Field(default_factory=list)
    doctor_suggestions: str | None = None


class AnalysisResponse(BaseModel):
    ocr_text: str
    ocr_items: list[dict[str, Any]]
    clinicalbert_findings: list[str]
    imaging_findings: list[dict[str, Any]]
    biogpt_summary: str
    limitations: list[str]
    models_used: dict[str, Any]


def split_sentences(text: str) -> list[str]:
    parts = re.split(r"(?<=[.!?])\s+|\n+", text)
    return [part.strip() for part in parts if len(part.strip()) > 20]


def clean_filename(name: str) -> str:
    return re.sub(r"[^a-zA-Z0-9._-]+", "_", name)


async def fetch_bytes(url: str) -> bytes:
    async with httpx.AsyncClient(timeout=120) as client:
        response = await client.get(url)
        response.raise_for_status()
        return response.content


def read_pdf_text(payload: bytes) -> str:
    from pypdf import PdfReader

    reader = PdfReader(io.BytesIO(payload))
    text_parts: list[str] = []
    for page in reader.pages:
        text_parts.append(page.extract_text() or "")
    return "\n".join(text_parts).strip()


def read_image_text(payload: bytes) -> str:
    import pytesseract

    image = Image.open(io.BytesIO(payload)).convert("RGB")
    return pytesseract.image_to_string(image).strip()


def extract_text_from_payload(name: str, payload: bytes) -> str:
    lowered = name.lower()
    if lowered.endswith(".pdf"):
        return read_pdf_text(payload)
    if lowered.endswith((".png", ".jpg", ".jpeg", ".bmp", ".tif", ".tiff", ".webp")):
        return read_image_text(payload)
    return ""


def write_volume_payload(payload: bytes, file_name: str, target_dir: Path) -> Path:
    safe_name = clean_filename(file_name)
    lower_name = safe_name.lower()

    if lower_name.endswith(".nii.gz") or lower_name.endswith(".nii"):
        destination = target_dir / safe_name
        destination.write_bytes(payload)
        return destination

    if lower_name.endswith(".zip"):
        extract_dir = target_dir / safe_name.replace(".zip", "")
        extract_dir.mkdir(parents=True, exist_ok=True)
        with zipfile.ZipFile(io.BytesIO(payload)) as archive:
            archive.extractall(extract_dir)
        for candidate in extract_dir.rglob("*"):
            lowered = candidate.name.lower()
            if lowered.endswith(".nii.gz") or lowered.endswith(".nii"):
                return candidate
        raise ValueError("Zip archive did not contain a NIfTI file.")

    raise ValueError("Volumetric imaging currently supports NIfTI (.nii/.nii.gz) or ZIPs containing NIfTI files.")


def classify_mri_sequence(name: str) -> str | None:
    lowered = name.lower()
    checks = [
        ("t1c", [r"\bt1c\b", r"\bt1ce\b", r"post[_-]?contrast", r"contrast"]),
        ("flair", [r"\bflair\b"]),
        ("t2", [r"\bt2\b"]),
        ("t1", [r"\bt1\b"]),
    ]
    for label, patterns in checks:
        if any(re.search(pattern, lowered) for pattern in patterns):
            return label
    return None


def autocast_context(torch_module: Any, enabled: bool):
    if not enabled:
        return nullcontext()
    return torch_module.amp.autocast("cuda")


@lru_cache(maxsize=1)
def get_ct_metadata() -> dict[str, str]:
    ensure_monai_bundle("wholeBody_ct_segmentation", "MONAI/wholeBody_ct_segmentation", CT_BUNDLE_DIR)
    metadata = json.loads((CT_BUNDLE_DIR / "configs" / "metadata.json").read_text())
    outputs = metadata["network_data_format"]["outputs"]["pred"]["channel_def"]
    return {key: value.replace("_", " ") for key, value in outputs.items()}


@lru_cache(maxsize=1)
def get_mri_metadata() -> dict[str, str]:
    ensure_monai_bundle("brats_mri_segmentation", "MONAI/brats_mri_segmentation", MRI_BUNDLE_DIR)
    metadata = json.loads((MRI_BUNDLE_DIR / "configs" / "metadata.json").read_text())
    outputs = metadata["network_data_format"]["outputs"]["pred"]["channel_def"]
    return {key: value for key, value in outputs.items()}


@lru_cache(maxsize=1)
def get_clinicalbert():
    import torch
    from transformers import AutoModel, AutoTokenizer

    model_name = os.getenv("CLINICALBERT_MODEL", "emilyalsentzer/Bio_ClinicalBERT")
    tokenizer = AutoTokenizer.from_pretrained(model_name, token=os.getenv("HF_TOKEN"))
    model = AutoModel.from_pretrained(model_name, token=os.getenv("HF_TOKEN"))
    model.eval()
    return tokenizer, model, torch


def sentence_embedding(sentence: str) -> np.ndarray:
    tokenizer, model, torch = get_clinicalbert()
    encoded = tokenizer(
        sentence,
        return_tensors="pt",
        truncation=True,
        padding=True,
        max_length=128,
    )
    with torch.no_grad():
        output = model(**encoded).last_hidden_state.mean(dim=1).squeeze(0)
    return output.detach().cpu().numpy()


def clinicalbert_findings(text: str, max_findings: int = 5) -> list[str]:
    sentences = split_sentences(text)
    if not sentences:
        return []

    embeddings = np.stack([sentence_embedding(sentence) for sentence in sentences])
    centroid = embeddings.mean(axis=0)
    centroid_norm = np.linalg.norm(centroid) or 1.0
    keyword_boosts = (
        "pain",
        "fracture",
        "opacity",
        "mass",
        "lesion",
        "tumor",
        "infection",
        "pneumonia",
        "effusion",
        "abnormal",
        "mri",
        "ct",
        "x-ray",
        "xray",
        "prescription",
    )

    scored: list[tuple[float, str]] = []
    for index, sentence in enumerate(sentences):
        vector = embeddings[index]
        similarity = float(np.dot(vector, centroid) / ((np.linalg.norm(vector) or 1.0) * centroid_norm))
        boost = 0.08 * sum(keyword in sentence.lower() for keyword in keyword_boosts)
        scored.append((similarity + boost, sentence))

    scored.sort(key=lambda item: item[0], reverse=True)
    unique: list[str] = []
    for _, sentence in scored:
        if sentence not in unique:
            unique.append(sentence)
        if len(unique) >= max_findings:
            break
    return unique


@lru_cache(maxsize=1)
def get_biogpt():
    import torch
    from transformers import BioGptForCausalLM, BioGptTokenizer

    model_name = os.getenv("BIOGPT_MODEL", "microsoft/biogpt")
    tokenizer = BioGptTokenizer.from_pretrained(model_name, token=os.getenv("HF_TOKEN"))
    model = BioGptForCausalLM.from_pretrained(model_name, token=os.getenv("HF_TOKEN"))
    model.eval()
    return tokenizer, model, torch


def biogpt_summary(
    patient: PatientContext,
    findings: list[str],
    imaging_findings: list[dict[str, Any]],
    doctor_suggestions: str | None,
) -> str:
    tokenizer, model, torch = get_biogpt()
    imaging_text = "\n".join(
        f"- {item['document_name']}: {item['summary']}" for item in imaging_findings if item.get("summary")
    )
    findings_text = "\n".join(f"- {finding}" for finding in findings)
    prompt = (
        "Patient case summary.\n"
        f"Patient: {patient.name}, age {patient.age or 'unknown'}, gender {patient.gender or 'unknown'}.\n"
        f"Chief symptoms: {patient.symptoms or 'not provided'}.\n"
        "ClinicalBERT key findings:\n"
        f"{findings_text or '- No textual findings extracted.'}\n"
        "Imaging findings:\n"
        f"{imaging_text or '- No imaging findings extracted.'}\n"
        f"Doctor additions: {doctor_suggestions or 'None'}\n"
        "Write a concise medical summary with findings, supporting evidence, and likely concerns. "
        "Mention uncertainty and avoid stating a diagnosis as certain when the evidence is limited. "
        "Keep it under 220 words.\n"
        "Summary:"
    )
    inputs = tokenizer(prompt, return_tensors="pt", truncation=True, max_length=1024)
    with torch.no_grad():
        output = model.generate(
            **inputs,
            max_new_tokens=180,
            do_sample=False,
            num_beams=4,
            early_stopping=True,
            no_repeat_ngram_size=3,
        )
    decoded = tokenizer.decode(output[0], skip_special_tokens=True)
    summary = decoded.split("Summary:", 1)[-1].strip()
    return summary[:1800]


def gemini_summary(
    patient: PatientContext,
    findings: list[str],
    imaging_findings: list[dict[str, Any]],
    doctor_suggestions: str | None,
) -> str:
    """Generate a medical summary using the Gemini API."""
    api_key = os.getenv("GEMINI_API_KEY", "")
    if not api_key:
        raise RuntimeError("GEMINI_API_KEY is not set.")

    from google import genai

    client = genai.Client(api_key=api_key)

    imaging_text = "\n".join(
        f"- {item['document_name']}: {item['summary']}" for item in imaging_findings if item.get("summary")
    )
    findings_text = "\n".join(f"- {finding}" for finding in findings)

    prompt = (
        "You are a board-certified clinical decision support system generating a summary "
        "for a reviewing physician. Write a structured clinical summary (200-300 words) "
        "using standard medical documentation format. Target audience: attending physician.\n\n"
        "FORMAT:\n"
        "1. CLINICAL PRESENTATION: Brief HPI with demographics and chief complaint.\n"
        "2. KEY FINDINGS: Synthesize ClinicalBERT NLP-extracted findings. Note pathological "
        "keywords, abnormal values, and medication interactions.\n"
        "3. IMAGING CORRELATION: Interpret imaging model outputs. Cite confidence scores. "
        "Correlate imaging findings with textual findings where applicable.\n"
        "4. DIFFERENTIAL DIAGNOSIS: List 2-4 differential diagnoses ranked by likelihood "
        "based on the combined evidence. Use clinical reasoning.\n"
        "5. RECOMMENDED WORKUP: Suggest next diagnostic steps (labs, imaging, referrals) "
        "based on the differentials.\n\n"
        "RULES:\n"
        "- Use standard medical abbreviations (CXR, RML, CBC, CRP, etc.)\n"
        "- Never state a definitive diagnosis; use 'consistent with', 'suggestive of', "
        "'cannot exclude'\n"
        "- Reference specific findings from the data provided below\n"
        "- Do NOT use markdown formatting, headers, or bullet symbols. "
        "Write in continuous clinical prose with numbered sections.\n\n"
        f"PATIENT: {patient.name}, {patient.age or 'unknown'} y/o {patient.gender or 'unknown'}.\n"
        f"CHIEF COMPLAINT / HPI: {patient.symptoms or 'not provided'}.\n\n"
        "NLP-EXTRACTED FINDINGS (ClinicalBERT, ranked by semantic relevance):\n"
        f"{findings_text or 'No textual findings extracted from uploaded documents.'}\n\n"
        "IMAGING MODEL OUTPUTS:\n"
        f"{imaging_text or 'No imaging analysis performed.'}\n\n"
        f"ADDITIONAL CLINICAL CONTEXT FROM REFERRING PHYSICIAN: {doctor_suggestions or 'None provided.'}\n\n"
        "Generate the clinical summary now."
    )

    last_error = None
    for model_name in ("gemini-2.5-flash", "gemini-2.0-flash", "gemini-2.0-flash-lite", "gemini-1.5-flash", "gemini-1.5-pro"):
        for attempt in range(2):
            try:
                response = client.models.generate_content(
                    model=model_name,
                    contents=prompt,
                )
                summary = (response.text or "").strip()
                return summary[:2500]
            except Exception as e:
                last_error = e
                error_str = str(e)
                if "503" in error_str or "429" in error_str or "UNAVAILABLE" in error_str or "RESOURCE_EXHAUSTED" in error_str:
                    time.sleep((attempt + 1) * 2)
                    continue
                else:
                    raise

    raise RuntimeError(f"Gemini API failed after all retries: {last_error}")


@lru_cache(maxsize=1)
def get_xray_model():
    import torch
    import torchvision
    import torchxrayvision as xrv

    weights = os.getenv("XRAY_MODEL_WEIGHTS", "densenet121-res224-all")
    model = xrv.models.DenseNet(weights=weights)
    transform = torchvision.transforms.Compose(
        [xrv.datasets.XRayCenterCrop(), xrv.datasets.XRayResizer(224)]
    )
    model.eval()
    return model, transform, xrv, torch


def analyze_xray(payload: bytes, document_name: str) -> dict[str, Any]:
    model, transform, xrv, torch = get_xray_model()
    image = np.array(Image.open(io.BytesIO(payload)).convert("RGB"))
    if image.ndim == 3:
      image = image.mean(axis=2)
    image = xrv.datasets.normalize(image, 255)
    image = transform(image[None, ...])
    tensor = torch.from_numpy(image).float()[None, ...]
    with torch.no_grad():
        outputs = model(tensor)[0].detach().cpu().numpy()
    scores = dict(zip(model.pathologies, outputs.tolist()))
    top_labels = sorted(scores.items(), key=lambda item: item[1], reverse=True)[:5]
    readable = ", ".join(f"{label} ({score:.2f})" for label, score in top_labels)
    return {
        "document_name": document_name,
        "modality": "xray",
        "summary": f"Top chest X-ray signals detected: {readable}.",
        "scores": top_labels,
        "analysis_method": "torchxrayvision DenseNet chest X-ray classifier",
    }


@lru_cache(maxsize=1)
def get_ct_model():
    import torch
    from monai.inferers import SlidingWindowInferer
    from monai.networks.nets import SegResNet
    from monai.transforms import (
        Compose,
        EnsureChannelFirstd,
        EnsureTyped,
        LoadImaged,
        NormalizeIntensityd,
        Orientationd,
        ScaleIntensityd,
        Spacingd,
    )

    metadata = get_ct_metadata()
    device = torch.device("cuda:0" if torch.cuda.is_available() else "cpu")
    highres = torch.cuda.is_available()
    network = SegResNet(
        spatial_dims=3,
        in_channels=1,
        out_channels=105,
        init_filters=32,
        blocks_down=[1, 2, 2, 4],
        blocks_up=[1, 1, 1],
        dropout_prob=0.2,
    ).to(device)
    model_name = "model.pt" if highres else "model_lowres.pt"
    state_dict = torch.load(CT_BUNDLE_DIR / "models" / model_name, map_location=device)
    network.load_state_dict(state_dict)
    network.eval()
    transform = Compose(
        [
            LoadImaged(keys="image"),
            EnsureTyped(keys="image"),
            EnsureChannelFirstd(keys="image"),
            Orientationd(keys="image", axcodes="RAS"),
            Spacingd(keys="image", pixdim=[1.5, 1.5, 1.5] if highres else [3.0, 3.0, 3.0], mode="bilinear"),
            NormalizeIntensityd(keys="image", nonzero=True),
            ScaleIntensityd(keys="image", minv=-1.0, maxv=1.0),
        ]
    )
    inferer = SlidingWindowInferer(
        roi_size=(96, 96, 96),
        sw_batch_size=1,
        overlap=0.25,
        padding_mode="replicate",
        mode="gaussian",
        device=device,
    )
    return {
        "torch": torch,
        "network": network,
        "transform": transform,
        "inferer": inferer,
        "device": device,
        "metadata": metadata,
        "highres": highres,
    }


def summarize_ct_mask(mask: np.ndarray, metadata: dict[str, str]) -> tuple[str, list[tuple[str, int]]]:
    unique_labels, counts = np.unique(mask.astype(np.int32), return_counts=True)
    by_label = {
        metadata.get(str(int(label)), f"class_{int(label)}"): int(count)
        for label, count in zip(unique_labels, counts)
        if int(label) != 0 and int(count) > 0
    }

    highlighted = {
        "liver": by_label.get("liver", 0),
        "spleen": by_label.get("spleen", 0),
        "kidney right": by_label.get("kidney right", 0),
        "kidney left": by_label.get("kidney left", 0),
        "urinary bladder": by_label.get("urinary bladder", 0),
        "brain": by_label.get("brain", 0),
        "heart myocardium": by_label.get("heart myocardium", 0),
        "lung tissue": sum(
            by_label.get(name, 0)
            for name in [
                "lung upper lobe left",
                "lung lower lobe left",
                "lung upper lobe right",
                "lung middle lobe right",
                "lung lower lobe right",
            ]
        ),
    }
    important = [(name, count) for name, count in highlighted.items() if count > 0]
    important.sort(key=lambda item: item[1], reverse=True)
    top_structures = sorted(by_label.items(), key=lambda item: item[1], reverse=True)[:8]

    structure_text = ", ".join(name for name, _ in important[:5]) or ", ".join(
        name for name, _ in top_structures[:5]
    )
    summary = (
        "Whole-body CT segmentation completed with the MONAI TotalSegmentator-style bundle. "
        f"Major segmented anatomy included {structure_text}. "
        "This model localizes anatomical structures; it does not provide a general disease diagnosis from CT."
    )
    return summary, top_structures


def analyze_ct_volume(volume_path: Path, document_name: str) -> dict[str, Any]:
    resources = get_ct_model()
    torch = resources["torch"]
    data = resources["transform"]({"image": str(volume_path)})
    image = data["image"].unsqueeze(0).to(resources["device"])
    with torch.no_grad():
        with autocast_context(torch, resources["device"].type == "cuda"):
            logits = resources["inferer"](image, resources["network"])
        mask = torch.argmax(logits, dim=1)[0].detach().cpu().numpy()
    summary, structures = summarize_ct_mask(mask, resources["metadata"])
    return {
        "document_name": document_name,
        "modality": "ct",
        "summary": summary,
        "scores": structures,
        "analysis_method": "MONAI wholeBody_ct_segmentation bundle",
    }


@lru_cache(maxsize=1)
def get_mri_model():
    import torch
    from monai.inferers import SlidingWindowInferer
    from monai.networks.nets import SegResNet

    metadata = get_mri_metadata()
    device = torch.device("cuda:0" if torch.cuda.is_available() else "cpu")
    network = SegResNet(
        blocks_down=[1, 2, 2, 4],
        blocks_up=[1, 1, 1],
        init_filters=16,
        in_channels=4,
        out_channels=3,
        dropout_prob=0.2,
    ).to(device)
    state_dict = torch.load(MRI_BUNDLE_DIR / "models" / "model.pt", map_location=device)
    network.load_state_dict(state_dict)
    network.eval()
    inferer = SlidingWindowInferer(roi_size=(240, 240, 160), sw_batch_size=1, overlap=0.5)
    return {
        "torch": torch,
        "network": network,
        "inferer": inferer,
        "device": device,
        "metadata": metadata,
    }


def load_nifti_array(path: Path) -> np.ndarray:
    return np.asarray(nib.load(str(path)).get_fdata(), dtype=np.float32)


def normalize_nonzero_channelwise(volume: np.ndarray) -> np.ndarray:
    normalized = volume.copy()
    for index in range(normalized.shape[0]):
        channel = normalized[index]
        mask = channel != 0
        if np.any(mask):
            mean = channel[mask].mean()
            std = channel[mask].std() or 1.0
            normalized[index][mask] = (channel[mask] - mean) / std
    return normalized


def summarize_mri_prediction(prediction: np.ndarray) -> tuple[str, list[tuple[str, int]]]:
    labels = get_mri_metadata()
    counts = {
        labels["0"]: int(prediction[0].sum()),
        labels["1"]: int(prediction[1].sum()),
        labels["2"]: int(prediction[2].sum()),
    }
    nonzero = [(label, count) for label, count in counts.items() if count > 0]
    nonzero.sort(key=lambda item: item[1], reverse=True)
    if nonzero:
        readable = ", ".join(f"{label} ({count} voxels)" for label, count in nonzero)
        summary = (
            "Brain MRI tumor-segmentation completed with the MONAI BraTS bundle. "
            f"Detected tumor subregions: {readable}. "
            "This model is specifically for aligned 4-sequence brain MRI studies and is not a general MRI diagnosis model."
        )
    else:
        summary = (
            "Brain MRI tumor-segmentation completed with the MONAI BraTS bundle, but no tumor subregion passed the segmentation threshold. "
            "This model only applies to aligned 4-sequence brain MRI studies."
        )
    return summary, nonzero


def analyze_mri_volumes(volume_paths: dict[str, Path], document_names: list[str]) -> dict[str, Any]:
    resources = get_mri_model()
    torch = resources["torch"]

    ordered_modalities = ["t1c", "t1", "t2", "flair"]
    arrays = [load_nifti_array(volume_paths[modality]) for modality in ordered_modalities]
    base_shape = arrays[0].shape
    if any(array.shape != base_shape for array in arrays[1:]):
        raise ValueError("All MRI modalities must be aligned and share the same volume shape.")

    image = np.stack(arrays, axis=0)
    image = normalize_nonzero_channelwise(image)
    tensor = torch.from_numpy(image).unsqueeze(0).to(resources["device"])

    with torch.no_grad():
        with autocast_context(torch, resources["device"].type == "cuda"):
            logits = resources["inferer"](tensor, resources["network"])
        prediction = (torch.sigmoid(logits)[0] > 0.5).to(torch.uint8).cpu().numpy()

    summary, scores = summarize_mri_prediction(prediction)
    return {
        "document_name": ", ".join(document_names),
        "modality": "mri",
        "summary": summary,
        "scores": scores,
        "analysis_method": "MONAI brats_mri_segmentation bundle",
    }


@app.get("/health")
def health():
    return {"status": "ok"}


@app.post("/analyze", response_model=AnalysisResponse)
async def analyze(payload: AnalysisRequest):
    if not payload.documents:
        raise HTTPException(status_code=400, detail="At least one document is required.")

    limitations: list[str] = []
    ocr_items: list[dict[str, Any]] = []
    imaging_findings: list[dict[str, Any]] = []

    mri_candidates: list[tuple[AnalysisDocument, bytes]] = []

    with tempfile.TemporaryDirectory(prefix="healthai-ml-") as temp_root:
        temp_root_path = Path(temp_root)

        for document in payload.documents:
            try:
                raw = await fetch_bytes(document.url)
            except Exception as exc:
                limitations.append(f"Failed to download {document.name}: {exc}")
                continue

            extracted_text = ""
            try:
                extracted_text = extract_text_from_payload(document.name, raw)
            except Exception as exc:
                limitations.append(f"OCR/extraction failed for {document.name}: {exc}")

            if extracted_text:
                ocr_items.append(
                    {
                        "document_id": document.id,
                        "document_name": document.name,
                        "text": extracted_text[:12000],
                    }
                )

            if document.analysis_type == "xray":
                try:
                    imaging_findings.append(analyze_xray(raw, document.name))
                except Exception as exc:
                    limitations.append(f"X-ray analysis failed for {document.name}: {exc}")
            elif document.analysis_type == "ct":
                try:
                    volume_path = write_volume_payload(raw, document.name, temp_root_path / "ct")
                    imaging_findings.append(analyze_ct_volume(volume_path, document.name))
                except Exception as exc:
                    limitations.append(f"CT analysis failed for {document.name}: {exc}")
            elif document.analysis_type == "mri":
                mri_candidates.append((document, raw))

        if mri_candidates:
            modality_paths: dict[str, Path] = {}
            names: list[str] = []
            for document, raw in mri_candidates:
                modality = classify_mri_sequence(document.name)
                if modality is None:
                    limitations.append(
                        f"MRI file {document.name} could not be mapped to T1c, T1, T2, or FLAIR from its filename."
                    )
                    continue
                try:
                    path = write_volume_payload(raw, document.name, temp_root_path / "mri")
                except Exception as exc:
                    limitations.append(f"MRI input preparation failed for {document.name}: {exc}")
                    continue
                modality_paths[modality] = path
                names.append(document.name)

            required = {"t1c", "t1", "t2", "flair"}
            if required.issubset(modality_paths):
                try:
                    imaging_findings.append(analyze_mri_volumes(modality_paths, names))
                except Exception as exc:
                    limitations.append(f"MRI analysis failed: {exc}")
            else:
                missing = ", ".join(sorted(required.difference(modality_paths)))
                limitations.append(
                    "MRI analysis requires a brain MRI study with four aligned NIfTI sequences: "
                    f"T1c, T1, T2, and FLAIR. Missing: {missing or 'none'}."
                )

    merged_text = "\n\n".join(item["text"] for item in ocr_items).strip()
    findings = clinicalbert_findings(merged_text) if merged_text else []

    if not findings and merged_text:
        limitations.append("ClinicalBERT did not produce ranked findings from the extracted text.")

    try:
        summary = gemini_summary(payload.patient, findings, imaging_findings, payload.doctor_suggestions)
    except Exception as gemini_exc:
        limitations.append(f"Gemini summary unavailable: {gemini_exc}")
        # Build structured fallback directly from pipeline data (skip BioGPT — poor quality)
        parts = []
        parts.append(f"1. CLINICAL PRESENTATION: {payload.patient.name}, {payload.patient.age or 'unknown'} y/o {payload.patient.gender or 'unknown'}. Chief complaint: {payload.patient.symptoms or 'not provided'}.")
        if findings:
            parts.append("\n2. KEY FINDINGS (ClinicalBERT NLP-extracted):")
            for f in findings[:5]:
                parts.append(f"  - {f}")
        if imaging_findings:
            parts.append("\n3. IMAGING CORRELATION:")
            for img in imaging_findings:
                parts.append(f"  - {img.get('document_name', 'unknown')}: {img.get('summary', 'N/A')}")
        if payload.doctor_suggestions:
            parts.append(f"\n4. PHYSICIAN NOTES: {payload.doctor_suggestions}")
        parts.append("\n[Note: Full AI-generated summary was temporarily unavailable due to API capacity. The above findings are extracted directly from uploaded documents via OCR + ClinicalBERT + imaging models. Please review, edit, and augment before submitting.]")
        summary = "\n".join(parts)

    if not summary:
        # Build a structured fallback from actual pipeline data
        parts = []
        parts.append(f"PATIENT: {payload.patient.name}, {payload.patient.age or 'unknown'} y/o {payload.patient.gender or 'unknown'}.")
        if payload.patient.symptoms:
            parts.append(f"CHIEF COMPLAINT: {payload.patient.symptoms}.")
        if findings:
            parts.append("\nKEY FINDINGS (ClinicalBERT):")
            for f in findings[:5]:
                parts.append(f"- {f}")
        if imaging_findings:
            parts.append("\nIMAGING FINDINGS:")
            for img in imaging_findings:
                parts.append(f"- {img.get('document_name', 'unknown')}: {img.get('summary', 'N/A')}")
        parts.append("\nNote: Automated AI summary generation was temporarily unavailable. The above findings are extracted directly from the uploaded documents. Please review and edit before submitting.")
        summary = "\n".join(parts)

    return AnalysisResponse(
        ocr_text=merged_text,
        ocr_items=ocr_items,
        clinicalbert_findings=findings,
        imaging_findings=imaging_findings,
        biogpt_summary=summary,
        limitations=limitations,
        models_used={
            "ocr": os.getenv("OCR_ENGINE", "pytesseract"),
            "clinicalbert": os.getenv("CLINICALBERT_MODEL", "emilyalsentzer/Bio_ClinicalBERT"),
            "biogpt": os.getenv("BIOGPT_MODEL", "microsoft/biogpt"),
            "imaging": {
                "xray": os.getenv("XRAY_MODEL_WEIGHTS", "torchxrayvision:densenet121-res224-all"),
                "ct": "MONAI/wholeBody_ct_segmentation",
                "mri": "MONAI/brats_mri_segmentation",
            },
        },
    )
