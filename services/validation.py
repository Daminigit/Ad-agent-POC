"""
Validation Service
==================
Runs post-generation checks on creatives and copy to ensure compliance:
  1. Image OCR: verifies 'Artist's impression' is visible.
  2. Image OCR: verifies RERA number is visible.
  3. Ad Copy: basic verification that copy contains RERA.
"""

from __future__ import annotations

import re
from pathlib import Path
from typing import Any

import pytesseract
from PIL import Image

from models.db import save_validation_result
from models.fact_sheet import ValidationResult, Project


# ─────────────────────────────────────────────
# Image Validation (OCR)
# ─────────────────────────────────────────────

def _clean_ocr_text(text: str) -> str:
    """Lowercases and removes non-alphanumeric chars for looser matching."""
    return re.sub(r'[^a-z0-9]', '', text.lower())


def check_rera_visible(image_path: str, rera_number: str) -> bool:
    """
    Run OCR on an image and check if the RERA number is present.
    Strips slashes and spaces for robust matching.
    """
    try:
        img = Image.open(image_path)
        text = pytesseract.image_to_string(img)
        clean_text = _clean_ocr_text(text)
        clean_rera = _clean_ocr_text(rera_number)
        return clean_rera in clean_text
    except Exception as e:
        print(f"OCR failed for RERA check on {image_path}: {e}")
        return False


def check_artist_impression(image_path: str) -> bool:
    """
    Run OCR to verify that the 'Artist's impression' watermark is visible.
    """
    try:
        img = Image.open(image_path)
        text = pytesseract.image_to_string(img).lower()
        return "artist" in text and "impression" in text
    except Exception as e:
        print(f"OCR failed for watermark check on {image_path}: {e}")
        return False


def validate_image_creative(project_id: str, image_path: str, rera_number: str) -> ValidationResult:
    """
    Validate a single static image.
    Records the ValidationResult to the database.
    """
    reasons = []

    if not check_rera_visible(image_path, rera_number):
        reasons.append("RERA number not detected in image by OCR")
    
    if not check_artist_impression(image_path):
        reasons.append("'Artist's impression' watermark not visible")

    status = "failed" if reasons else "passed"
    
    result = ValidationResult(
        creative_path=image_path,
        status=status,
        reasons=reasons,
    )
    
    save_validation_result(project_id, result.model_dump(mode="json"))
    return result


# ─────────────────────────────────────────────
# Ad Copy Validation
# ─────────────────────────────────────────────

def validate_ad_copy_content(copy_dict: dict[str, Any], rera_number: str) -> list[str]:
    """
    Check that the generated ad copy contains the RERA number.
    (We enforce this in the prompt, but this is a final programmatic check).
    """
    reasons = []
    clean_rera = _clean_ocr_text(rera_number)
    
    # Check Google Descriptions (headlines are too short for full RERA usually)
    google_desc = " ".join(copy_dict.get("google_search", {}).get("descriptions", []))
    if clean_rera not in _clean_ocr_text(google_desc):
        reasons.append("RERA number missing from Google Search descriptions")
        
    # Check Meta primary text
    meta_primary = copy_dict.get("meta", {}).get("primary_text", "")
    if clean_rera not in _clean_ocr_text(meta_primary):
        reasons.append("RERA number missing from Meta primary text")
        
    return reasons


def validate_project_creatives(project: Project, image_paths: list[str]) -> dict[str, Any]:
    """
    Run validation over a batch of images for a project.
    
    Returns:
        {
           "total": int,
           "passed": int,
           "failed": int,
           "results": [ValidationResult, ...]
        }
    """
    if not project.rera_number:
        raise ValueError("Cannot validate creatives: Project has no confirmed RERA number.")
        
    results = []
    for path in image_paths:
        res = validate_image_creative(project.id, path, project.rera_number)
        results.append(res)
        
    return {
        "total": len(results),
        "passed": sum(1 for r in results if r.status == "passed"),
        "failed": sum(1 for r in results if r.status == "failed"),
        "results": [r.model_dump(mode="json") for r in results]
    }
