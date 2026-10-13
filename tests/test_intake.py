"""
Phase 3 test — Document Intake Service
Run with: python3 tests/test_intake.py
"""

import io
import sys
from pathlib import Path

# Make project root importable
sys.path.insert(0, str(Path(__file__).parent.parent))

import numpy as np
import cv2
from PIL import Image, ImageFilter
from services.intake import (
    ingest_document, get_intake_status, get_next_required_doc,
    mark_document_skipped, validate_upload, sharpness_score,
    DOCUMENT_TYPES,
)
import uuid

PROJECT_ID = str(uuid.uuid4())

# ── Helpers ──────────────────────────────────

def make_sharp_jpeg(width=800, height=600) -> bytes:
    """Create a sharp test image with clear edges (high Laplacian variance)."""
    img = np.zeros((height, width, 3), dtype=np.uint8)
    # Checkerboard pattern — very high frequency → not blurry
    for i in range(0, height, 40):
        for j in range(0, width, 40):
            if (i // 40 + j // 40) % 2 == 0:
                img[i:i+40, j:j+40] = [255, 255, 255]
    _, buf = cv2.imencode(".jpg", img, [cv2.IMWRITE_JPEG_QUALITY, 95])
    return buf.tobytes()


def make_blurry_jpeg() -> bytes:
    """Create a heavily blurred test image (low Laplacian variance)."""
    pil = Image.fromarray(np.full((400, 400, 3), 128, dtype=np.uint8))
    pil = pil.filter(ImageFilter.GaussianBlur(radius=30))
    buf = io.BytesIO()
    pil.save(buf, format="JPEG")
    return buf.getvalue()


def make_fake_pdf() -> bytes:
    """Minimal valid PDF bytes for file-type testing."""
    return b"%PDF-1.4\n1 0 obj<</Type/Catalog>>endobj\nxref\n0 0\ntrailer<</Root 1 0 R>>\n%%EOF"


# ── Tests ─────────────────────────────────────

def test_sharp_image_accepted():
    img = make_sharp_jpeg()
    result = ingest_document(PROJECT_ID, "rera_certificate", "rera.jpg", img, extract=False)
    assert result["ok"], f"Sharp image was rejected: {result['errors']}"
    assert result["doc"]["status"] == "ok"
    print("✓ Sharp image accepted")


def test_blurry_image_rejected():
    img = make_blurry_jpeg()
    errors = validate_upload("price_list.jpg", img)
    assert any("blurry" in e.lower() for e in errors), \
        f"Blurry image was not flagged: {errors}"
    print("✓ Blurry image rejected")


def test_invalid_extension_rejected():
    errors = validate_upload("document.exe", b"garbage")
    assert any("not supported" in e for e in errors), \
        f"Bad extension not caught: {errors}"
    print("✓ Invalid file extension rejected")


def test_oversized_file_rejected():
    big = b"x" * (21 * 1024 * 1024)   # 21 MB
    errors = validate_upload("bigfile.jpg", big)
    assert any("large" in e.lower() for e in errors), \
        f"Oversized file not caught: {errors}"
    print("✓ Oversized file rejected")


def test_pdf_accepted():
    pdf = make_fake_pdf()
    result = ingest_document(PROJECT_ID, "brochure", "brochure.pdf", pdf, extract=False)
    assert result["ok"], f"PDF was rejected: {result['errors']}"
    print("✓ PDF file accepted")


def test_intake_status_tracks_uploads():
    status = get_intake_status(PROJECT_ID)
    assert "rera_certificate" in status["uploaded"]
    assert not status["complete"]   # price_list still missing
    print(f"✓ Intake status: {len(status['uploaded'])} uploaded, "
          f"{len(status['missing'])} missing, complete={status['complete']}")


def test_next_required_doc_is_price_list():
    nxt = get_next_required_doc(PROJECT_ID)
    assert nxt is not None
    assert nxt["key"] == "price_list", \
        f"Expected price_list, got {nxt['key']}"
    print(f"✓ Next required doc: {nxt['label']}")


def test_skip_optional_doc():
    mark_document_skipped(PROJECT_ID, "floor_plans")
    status = get_intake_status(PROJECT_ID)
    assert "floor_plans" in status["uploaded"]
    print("✓ Optional doc marked as skipped")


def test_complete_after_required_uploaded():
    # Upload the price list to satisfy the second required doc
    img = make_sharp_jpeg()
    result = ingest_document(PROJECT_ID, "price_list", "price_oct26.jpg", img, extract=False)
    assert result["ok"]
    status = get_intake_status(PROJECT_ID)
    assert status["complete"], \
        f"Intake should be complete now. Missing: {[m['key'] for m in status['missing'] if m['required']]}"
    print("✓ Intake complete after all required docs uploaded")


def test_sharpness_score():
    sharp = make_sharp_jpeg()
    blurry = make_blurry_jpeg()
    s_score = sharpness_score(sharp)
    b_score = sharpness_score(blurry)
    assert s_score > b_score, \
        f"Sharp score ({s_score:.1f}) should be > blurry score ({b_score:.1f})"
    print(f"✓ Sharpness scores — sharp: {s_score:.1f}, blurry: {b_score:.1f}")


# ── Runner ────────────────────────────────────

if __name__ == "__main__":
    tests = [
        test_sharp_image_accepted,
        test_blurry_image_rejected,
        test_invalid_extension_rejected,
        test_oversized_file_rejected,
        test_pdf_accepted,
        test_intake_status_tracks_uploads,
        test_next_required_doc_is_price_list,
        test_skip_optional_doc,
        test_complete_after_required_uploaded,
        test_sharpness_score,
    ]

    print(f"\n=== Phase 3: Document Intake Service — {len(tests)} tests ===\n")
    passed = failed = 0
    for t in tests:
        try:
            t()
            passed += 1
        except Exception as e:
            print(f"✗ {t.__name__}: {e}")
            failed += 1

    print(f"\n{'='*50}")
    print(f"Passed: {passed}/{len(tests)}", "✓" if failed == 0 else "✗")
    if failed:
        sys.exit(1)
