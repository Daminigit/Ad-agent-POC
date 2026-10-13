"""
Phase 7 test — Validation Service
Run with: python3 tests/test_validation.py
"""

import sys
import uuid
from pathlib import Path

import cv2
import numpy as np
from PIL import Image, ImageDraw, ImageFont

sys.path.insert(0, str(Path(__file__).parent.parent))

from services.validation import (
    _clean_ocr_text,
    check_rera_visible,
    check_artist_impression,
    validate_image_creative,
    validate_ad_copy_content,
)
from models.fact_sheet import Project
from models.db import save_project


RERA_NUM = "PRM/KA/RERA/1251/446"
PROJECT_ID = str(uuid.uuid4())

# ── Helpers ──────────────────────────────────

def make_test_image(text: str, filename: str) -> str:
    """Create a simple image with given text to test OCR."""
    img = Image.new("RGB", (800, 400), color=(255, 255, 255))
    draw = ImageDraw.Draw(img)
    try:
        font = ImageFont.truetype("/System/Library/Fonts/Helvetica.ttc", 36)
    except IOError:
        font = ImageFont.load_default()
        
    draw.text((50, 150), text, fill=(0, 0, 0), font=font)
    
    tmp_path = Path(f"/tmp/{filename}.jpg")
    img.save(tmp_path)
    return str(tmp_path)


# ── Tests ─────────────────────────────────────

def test_clean_ocr_text():
    assert _clean_ocr_text("PRM/KA/RERA/1251/446") == "prmkarera1251446"
    assert _clean_ocr_text("Artist's impression") == "artistsimpression"
    print("✓ _clean_ocr_text works correctly")


def test_rera_visible_pass():
    img_path = make_test_image(f"RERA No: {RERA_NUM} - Buy now", "rera_pass")
    assert check_rera_visible(img_path, RERA_NUM) is True
    print("✓ check_rera_visible (pass)")


def test_rera_visible_fail():
    img_path = make_test_image("Just a normal image without the number", "rera_fail")
    assert check_rera_visible(img_path, RERA_NUM) is False
    print("✓ check_rera_visible (fail)")


def test_artist_impression_pass():
    img_path = make_test_image("This is an Artist's impression of the site", "artist_pass")
    assert check_artist_impression(img_path) is True
    print("✓ check_artist_impression (pass)")


def test_artist_impression_fail():
    img_path = make_test_image("Real photo of the site", "artist_fail")
    assert check_artist_impression(img_path) is False
    print("✓ check_artist_impression (fail)")


def test_validate_image_creative():
    # Setup DB project
    p = Project(id=PROJECT_ID, rera_number=RERA_NUM)
    save_project(p.model_dump(mode="json"))
    
    # Passing image
    good_img = make_test_image(f"{RERA_NUM}\nArtist's impression", "creative_good")
    res1 = validate_image_creative(PROJECT_ID, good_img, RERA_NUM)
    assert res1.status == "passed", f"Good image failed: {res1.reasons}"
    
    # Failing image
    bad_img = make_test_image("Missing everything", "creative_bad")
    res2 = validate_image_creative(PROJECT_ID, bad_img, RERA_NUM)
    assert res2.status == "failed"
    assert len(res2.reasons) == 2, f"Expected 2 reasons, got {res2.reasons}"
    
    print("✓ validate_image_creative logs to DB and returns correct status")


def test_validate_ad_copy_pass():
    copy = {
        "google_search": {
            "descriptions": [f"Some text. RERA: {RERA_NUM}"]
        },
        "meta": {
            "primary_text": f"Great project! {RERA_NUM} available."
        }
    }
    reasons = validate_ad_copy_content(copy, RERA_NUM)
    assert not reasons, f"Expected pass, got: {reasons}"
    print("✓ validate_ad_copy_content (pass)")


def test_validate_ad_copy_fail():
    copy = {
        "google_search": {
            "descriptions": ["No rera here"]
        },
        "meta": {
            "primary_text": "Also missing here"
        }
    }
    reasons = validate_ad_copy_content(copy, RERA_NUM)
    assert len(reasons) == 2
    print("✓ validate_ad_copy_content (fail)")


# ── Runner ────────────────────────────────────

if __name__ == "__main__":
    print("\n=== Phase 7: Validation Service — tests ===\n")
    
    tests = [
        test_clean_ocr_text,
        test_rera_visible_pass,
        test_rera_visible_fail,
        test_artist_impression_pass,
        test_artist_impression_fail,
        test_validate_image_creative,
        test_validate_ad_copy_pass,
        test_validate_ad_copy_fail,
    ]
    
    passed = failed = 0
    for t in tests:
        try:
            t()
            passed += 1
        except Exception as e:
            print(f"✗ {t.__name__}: {e}")
            import traceback; traceback.print_exc()
            failed += 1
            
    print(f"\n{'='*50}")
    print(f"Passed: {passed}/{len(tests)}", "✓" if failed == 0 else "✗")
    if failed:
        sys.exit(1)
