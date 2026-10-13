"""
Document Intake Service
=======================
Handles all document ingestion logic:
  - Validates file types and sizes
  - Detects blurry / cut-off images via OpenCV Laplacian variance
  - Extracts text from images (pytesseract) and PDFs (pdf2image → pytesseract)
  - Stores files under uploads/{project_id}/
  - Persists Document records to SQLite
  - Tracks which required documents are still missing
"""

from __future__ import annotations

import io
import os
import uuid
from datetime import datetime, timezone
from pathlib import Path
from typing import Optional

import cv2
import numpy as np
import pytesseract
from PIL import Image
from dotenv import load_dotenv

from models.fact_sheet import Document
from models.db import save_document, get_documents

load_dotenv()

# ─────────────────────────────────────────────
# Configuration
# ─────────────────────────────────────────────

UPLOAD_ROOT = Path(os.getenv("UPLOAD_ROOT", "uploads"))

# Laplacian variance below this → image considered blurry
BLURRINESS_THRESHOLD = float(os.getenv("BLURRINESS_THRESHOLD", "100.0"))

# Maximum file size (20 MB)
MAX_FILE_BYTES = 20 * 1024 * 1024

ALLOWED_EXTENSIONS = {".jpg", ".jpeg", ".png", ".webp", ".pdf"}

# ─────────────────────────────────────────────
# Document Catalogue
# ─────────────────────────────────────────────

DOCUMENT_TYPES: list[dict] = [
    {
        "key":      "rera_certificate",
        "label":    "RERA registration certificate",
        "required": True,
        "hint":     "Upload the RERA certificate PDF or a clear photo of it.",
    },
    {
        "key":      "price_list",
        "label":    "Current price list (with issue date)",
        "required": True,
        "hint":     "Upload the latest price list — PDF or a photo is fine.",
    },
    {
        "key":      "floor_plans",
        "label":    "Approved floor plans",
        "required": False,
        "hint":     "Upload floor plan PDFs or images.",
    },
    {
        "key":      "brochure",
        "label":    "Project brochure (PDF)",
        "required": False,
        "hint":     "Upload the developer brochure as a PDF.",
    },
    {
        "key":      "exterior_renders",
        "label":    "Exterior renders (3–4 images)",
        "required": False,
        "hint":     "Upload high-resolution exterior renders (JPG/PNG).",
    },
    {
        "key":      "interior_renders",
        "label":    "Interior renders (2 per unit type)",
        "required": False,
        "hint":     "Upload interior render images for each unit type.",
    },
    {
        "key":      "logo",
        "label":    "Logo & brand colours",
        "required": False,
        "hint":     "Upload the developer logo (PNG with transparency preferred).",
    },
    {
        "key":      "marketing_contact",
        "label":    "Marketing contact (name and phone)",
        "required": False,
        "hint":     "Type or upload a document with the marketing contact details.",
    },
]

# Fast lookup: key → metadata
DOCUMENT_MAP: dict[str, dict] = {d["key"]: d for d in DOCUMENT_TYPES}


# ─────────────────────────────────────────────
# Image Quality Check
# ─────────────────────────────────────────────

def _laplacian_variance(image_bytes: bytes) -> float:
    """Compute Laplacian variance — proxy for image sharpness."""
    arr = np.frombuffer(image_bytes, np.uint8)
    img = cv2.imdecode(arr, cv2.IMREAD_GRAYSCALE)
    if img is None:
        return 0.0
    return float(cv2.Laplacian(img, cv2.CV_64F).var())


def is_blurry(image_bytes: bytes) -> bool:
    """Return True if the image sharpness is below the configured threshold."""
    return _laplacian_variance(image_bytes) < BLURRINESS_THRESHOLD


def is_cut_off(image_bytes: bytes) -> bool:
    """
    Heuristic: if the image has extreme aspect ratio (very wide or very tall)
    it may be a cropped / cut-off scan. Flags for review — not an automatic reject.
    """
    arr = np.frombuffer(image_bytes, np.uint8)
    img = cv2.imdecode(arr, cv2.IMREAD_COLOR)
    if img is None:
        return False
    h, w = img.shape[:2]
    ratio = max(w, h) / max(min(w, h), 1)
    return ratio > 5.0   # e.g. a strip that is 5× as long as it is wide


# ─────────────────────────────────────────────
# Text Extraction
# ─────────────────────────────────────────────

def _ocr_image_bytes(image_bytes: bytes) -> str:
    """Run Tesseract OCR on raw image bytes and return extracted text."""
    pil_img = Image.open(io.BytesIO(image_bytes)).convert("RGB")
    return pytesseract.image_to_string(pil_img, lang="eng")


def _ocr_pdf_bytes(pdf_bytes: bytes) -> str:
    """Convert each PDF page to an image and OCR it. Returns concatenated text."""
    try:
        from pdf2image import convert_from_bytes
    except ImportError:
        return "[pdf2image not available — install poppler]"

    pages = convert_from_bytes(pdf_bytes, dpi=200)
    texts: list[str] = []
    for i, page in enumerate(pages, start=1):
        text = pytesseract.image_to_string(page, lang="eng")
        texts.append(f"--- Page {i} ---\n{text}")
    return "\n".join(texts)


def extract_text(file_bytes: bytes, filename: str) -> str:
    """
    Extract text from an uploaded file.
    Images → pytesseract directly.
    PDFs → pdf2image → pytesseract.
    Returns empty string on failure (never raises).
    """
    ext = Path(filename).suffix.lower()
    try:
        if ext == ".pdf":
            return _ocr_pdf_bytes(file_bytes)
        else:
            return _ocr_image_bytes(file_bytes)
    except Exception as exc:
        return f"[text extraction failed: {exc}]"


# ─────────────────────────────────────────────
# File Storage
# ─────────────────────────────────────────────

def _save_file(project_id: str, filename: str, file_bytes: bytes) -> Path:
    """Write file bytes to uploads/{project_id}/{filename}. Returns the path."""
    dest_dir = UPLOAD_ROOT / project_id
    dest_dir.mkdir(parents=True, exist_ok=True)
    dest = dest_dir / filename
    dest.write_bytes(file_bytes)
    return dest


# ─────────────────────────────────────────────
# Validation
# ─────────────────────────────────────────────

def validate_upload(filename: str, file_bytes: bytes) -> list[str]:
    """
    Run pre-storage checks. Returns a list of error strings (empty = OK).
    Checks:
      - File extension is allowed
      - File size is within limit
      - Image files are not blurry
    """
    errors: list[str] = []
    ext = Path(filename).suffix.lower()

    if ext not in ALLOWED_EXTENSIONS:
        errors.append(
            f"File type '{ext}' is not supported. "
            f"Allowed: {', '.join(sorted(ALLOWED_EXTENSIONS))}"
        )
        return errors   # no point checking further

    if len(file_bytes) > MAX_FILE_BYTES:
        errors.append(
            f"File is too large ({len(file_bytes) / 1024 / 1024:.1f} MB). "
            f"Maximum allowed is {MAX_FILE_BYTES // 1024 // 1024} MB."
        )

    if ext in {".jpg", ".jpeg", ".png", ".webp"}:
        if is_blurry(file_bytes):
            errors.append(
                "This image looks blurry or out of focus. "
                "Please upload a sharper version."
            )
        elif is_cut_off(file_bytes):
            errors.append(
                "This image may be cut off (extreme aspect ratio). "
                "Please check that the full document is visible."
            )

    return errors


# ─────────────────────────────────────────────
# Main Intake Function
# ─────────────────────────────────────────────

def ingest_document(
    project_id: str,
    doc_type: str,
    filename: str,
    file_bytes: bytes,
    extract: bool = True,
) -> dict:
    """
    Full document intake pipeline:
      1. Validate file (type, size, sharpness)
      2. Save file to disk
      3. Extract text (OCR / PDF)
      4. Persist Document record to SQLite

    Returns a result dict:
      {
        "ok":      bool,
        "errors":  list[str],      # non-empty when ok=False
        "doc":     dict | None,    # Document model dict when ok=True
        "text":    str,            # extracted text (may be empty)
      }
    """
    # 1. Validate
    errors = validate_upload(filename, file_bytes)
    if errors:
        return {"ok": False, "errors": errors, "doc": None, "text": ""}

    # 2. Save to disk
    filepath = _save_file(project_id, filename, file_bytes)

    # 3. Extract text
    text = extract_text(file_bytes, filename) if extract else ""

    # 4. Build Document record
    doc = Document(
        id=str(uuid.uuid4()),
        project_id=project_id,
        doc_type=doc_type,
        filename=filename,
        filepath=str(filepath),
        uploaded_at=datetime.now(timezone.utc),
        status="ok",
        extracted_text=text,
    )

    # 5. Persist
    save_document(doc.model_dump(mode="json"))

    return {
        "ok":     True,
        "errors": [],
        "doc":    doc.model_dump(mode="json"),
        "text":   text,
    }


# ─────────────────────────────────────────────
# Intake State Helpers
# ─────────────────────────────────────────────

def get_intake_status(project_id: str) -> dict:
    """
    Return a structured summary of what has been uploaded vs. what is missing.

    Returns:
      {
        "uploaded":  { doc_type: [filename, ...] },
        "missing":   [{ key, label, required }],
        "complete":  bool,   # True when all required docs are uploaded
      }
    """
    docs = get_documents(project_id)

    # Group by doc_type (a type may have multiple files, e.g. exterior_renders)
    uploaded: dict[str, list[str]] = {}
    for d in docs:
        uploaded.setdefault(d["doc_type"], []).append(d["filename"])

    missing = [
        {"key": dt["key"], "label": dt["label"], "required": dt["required"]}
        for dt in DOCUMENT_TYPES
        if dt["key"] not in uploaded
    ]

    required_missing = [m for m in missing if m["required"]]

    return {
        "uploaded": uploaded,
        "missing":  missing,
        "complete": len(required_missing) == 0,
    }


def get_next_required_doc(project_id: str) -> Optional[dict]:
    """
    Return the next document the chatbot should ask for,
    prioritising required documents first, then optional ones.
    Returns None when all documents have been uploaded.
    """
    status = get_intake_status(project_id)
    if not status["missing"]:
        return None
    # Required first, then optional
    required = [m for m in status["missing"] if m["required"]]
    if required:
        return DOCUMENT_MAP[required[0]["key"]]
    optional = [m for m in status["missing"] if not m["required"]]
    return DOCUMENT_MAP[optional[0]["key"]] if optional else None


def mark_document_skipped(project_id: str, doc_type: str) -> None:
    """
    Record a placeholder 'missing' Document so the chatbot can move on
    and re-ask at the end of intake.
    """
    doc = Document(
        id=str(uuid.uuid4()),
        project_id=project_id,
        doc_type=doc_type,
        filename=f"[skipped] {doc_type}",
        filepath="",
        uploaded_at=datetime.now(timezone.utc),
        status="missing",
    )
    save_document(doc.model_dump(mode="json"))


def sharpness_score(image_bytes: bytes) -> float:
    """Expose Laplacian variance for the UI to show a quality indicator."""
    return _laplacian_variance(image_bytes)
