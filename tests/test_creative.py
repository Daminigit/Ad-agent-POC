"""
Phase 6 test — Creative Generation Pipeline
Run with: python3 tests/test_creative.py

Offline tests (no FAL_KEY / FFmpeg needed):
  - Image preparation (crop, watermark)
  - Static image production for all platform sizes
  - Output directory structure

Live tests (require FAL_KEY + ffmpeg):
  - Wan 2.2 animation
  - Hyperframes reel assembly
"""

import io
import os
import sys
import uuid
from pathlib import Path

import numpy as np
import cv2
from PIL import Image

sys.path.insert(0, str(Path(__file__).parent.parent))

from services.creative import (
    prepare_render,
    produce_static_images,
    animate_render,
    assemble_reel,
    run_creative_pipeline,
    _centre_crop,
    _bake_watermark,
    ASPECT_RATIOS,
)

PROJECT_ID = str(uuid.uuid4())
RERA = "PRM/KA/RERA/1251/446"
PRICE = "₹1.42 Cr onwards"


# ── Helpers ──────────────────────────────────

def make_test_render(width=2048, height=1365, path: str = None) -> str:
    """Create a realistic landscape render image and save to disk."""
    img = np.zeros((height, width, 3), dtype=np.uint8)
    # Sky gradient (blue)
    for y in range(height // 2):
        c = int(100 + (155 * y / (height // 2)))
        img[y, :] = [c, c // 2, 0][::-1]
    # Building (grey rectangle)
    bx1, bx2 = width // 4, 3 * width // 4
    by1, by2 = height // 4, height - 1
    img[by1:by2, bx1:bx2] = [180, 180, 180]
    # Windows
    for wy in range(by1 + 20, by2 - 20, 50):
        for wx in range(bx1 + 20, bx2 - 20, 40):
            img[wy:wy+20, wx:wx+25] = [220, 200, 100]
    # Ground (green)
    img[height - height // 6:, :] = [60, 120, 60]

    if path is None:
        tmp = Path(f"/tmp/test_render_{uuid.uuid4().hex[:8]}.jpg")
    else:
        tmp = Path(path)
    tmp.parent.mkdir(parents=True, exist_ok=True)
    cv2.imwrite(str(tmp), img)
    return str(tmp)


# ── Tests ─────────────────────────────────────

def test_centre_crop_portrait():
    img = Image.new("RGB", (2048, 1365), color=(100, 150, 200))
    cropped = _centre_crop(img, 1080, 1920)
    assert cropped.size == (1080, 1920), f"Expected (1080,1920) got {cropped.size}"
    print(f"✓ Centre crop portrait: {img.size} → {cropped.size}")


def test_centre_crop_landscape():
    img = Image.new("RGB", (800, 800), color=(200, 100, 50))
    cropped = _centre_crop(img, 1200, 628)
    assert cropped.size == (1200, 628), f"Expected (1200,628) got {cropped.size}"
    print(f"✓ Centre crop landscape: (800,800) → {cropped.size}")


def test_watermark_baked():
    img = Image.new("RGB", (1080, 1920), color=(50, 100, 200))
    watermarked = _bake_watermark(img)
    assert watermarked.size == img.size
    # Verify it's different from the original (watermark changed pixels)
    orig_arr = np.array(img)
    new_arr = np.array(watermarked)
    assert not np.array_equal(orig_arr, new_arr), "Watermark made no visible change"
    print("✓ Watermark baked into image")


def test_prepare_render_9_16():
    render_path = make_test_render()
    jpeg_bytes = prepare_render(render_path, aspect="9:16")
    assert len(jpeg_bytes) > 1000, "Output too small"

    # Verify dimensions
    pil = Image.open(io.BytesIO(jpeg_bytes))
    assert pil.size == (1080, 1920), f"Expected (1080,1920), got {pil.size}"
    print(f"✓ prepare_render 9:16: output size={pil.size}, bytes={len(jpeg_bytes):,}")


def test_prepare_render_4_5():
    render_path = make_test_render()
    jpeg_bytes = prepare_render(render_path, aspect="4:5")
    pil = Image.open(io.BytesIO(jpeg_bytes))
    assert pil.size == (1080, 1350), f"Expected (1080,1350), got {pil.size}"
    print(f"✓ prepare_render 4:5: output size={pil.size}")


def test_prepare_render_invalid_aspect():
    render_path = make_test_render()
    try:
        prepare_render(render_path, aspect="16:9:3")
        assert False, "Should have raised ValueError"
    except ValueError as e:
        assert "Unknown aspect ratio" in str(e)
    print("✓ Invalid aspect ratio raises ValueError")


def test_produce_static_images():
    render_path = make_test_render()
    static = produce_static_images(PROJECT_ID, render_path)

    expected_platforms = {"meta", "linkedin", "x", "reddit", "google_display"}
    assert expected_platforms == set(static.keys()), \
        f"Missing platforms: {expected_platforms - set(static.keys())}"

    total = sum(len(v) for v in static.values())
    print(f"✓ Static images: {total} files across {len(static)} platforms")

    for platform, paths in static.items():
        for p in paths:
            assert Path(p).exists(), f"File not written: {p}"
            size = Path(p).stat().st_size
            assert size > 1000, f"File too small ({size} bytes): {p}"
        print(f"   {platform}: {len(paths)} image(s)")


def test_output_directory_structure():
    base = Path("outputs") / PROJECT_ID
    assert (base / "images").exists(), "images dir missing"
    print(f"✓ Output directory structure correct: {base}")


def test_animate_render_live():
    """Live test — requires FAL_KEY and fal.ai balance."""
    fal_key = os.getenv("FAL_KEY", "")
    if not fal_key or fal_key == "your_fal_api_key_here":
        print("⚠  Skipping Wan 2.2 live test (FAL_KEY not set)")
        return None

    render_path = make_test_render()
    image_bytes = prepare_render(render_path, aspect="9:16")

    print("  Submitting to Wan 2.2 (fal.ai)… this may take 60–90 seconds")
    try:
        clip_path = animate_render(
            project_id=PROJECT_ID,
            image_bytes=image_bytes,
            duration=5,
            aspect="9:16",
        )
    except RuntimeError as e:
        err = str(e).lower()
        if "balance" in err or "locked" in err or "billing" in err:
            print(f"⚠  Skipping Wan 2.2 live test (fal.ai balance issue): {e}")
            return None
        raise

    assert Path(clip_path).exists(), f"Clip not downloaded: {clip_path}"
    size = Path(clip_path).stat().st_size
    assert size > 10_000, f"Clip too small ({size} bytes)"
    print(f"✓ Wan 2.2 animation: {clip_path} ({size:,} bytes)")
    return clip_path


def test_assemble_reel_live(clip_path: str):
    """Live test — requires FFmpeg."""
    import shutil
    if not shutil.which("ffmpeg"):
        print("⚠  Skipping reel assembly test (ffmpeg not installed)")
        return

    reel_path = assemble_reel(
        project_id=PROJECT_ID,
        clip_path=clip_path,
        rera_number=RERA,
        price_text=PRICE,
        logo_path=None,
        aspect="9:16",
        duration=5,
        music_path=None,
    )
    assert Path(reel_path).exists(), f"Reel not created: {reel_path}"
    size = Path(reel_path).stat().st_size
    assert size > 10_000, f"Reel too small ({size} bytes)"
    print(f"✓ Reel assembled: {reel_path} ({size:,} bytes)")


def test_pipeline_offline():
    """
    Run the full pipeline with animate=False (no FAL_KEY needed).
    Verifies static image production and error-free execution.
    """
    render_path = make_test_render()
    result = run_creative_pipeline(
        project_id=str(uuid.uuid4()),
        render_paths=[render_path],
        rera_number=RERA,
        price_text=PRICE,
        animate=False,
    )
    assert result["static_images"], "No static images produced"
    assert result["errors"] == [], f"Pipeline errors: {result['errors']}"
    total = sum(len(v) for v in result["static_images"].values())
    print(f"✓ Offline pipeline: {total} static images, 0 errors")


# ── Runner ────────────────────────────────────

if __name__ == "__main__":
    from dotenv import load_dotenv
    load_dotenv()

    print("\n=== Phase 6: Creative Generation Pipeline — tests ===\n")

    offline = [
        test_centre_crop_portrait,
        test_centre_crop_landscape,
        test_watermark_baked,
        test_prepare_render_9_16,
        test_prepare_render_4_5,
        test_prepare_render_invalid_aspect,
        test_produce_static_images,
        test_output_directory_structure,
        test_pipeline_offline,
    ]

    passed = failed = 0
    print("--- Offline tests (no API keys needed) ---")
    for t in offline:
        try:
            t()
            passed += 1
        except Exception as e:
            print(f"✗ {t.__name__}: {e}")
            import traceback; traceback.print_exc()
            failed += 1

    print("\n--- Live tests (FAL_KEY + ffmpeg) ---")
    clip_path = None
    try:
        clip_path = test_animate_render_live()
        if clip_path:
            passed += 1
    except Exception as e:
        print(f"✗ test_animate_render_live: {e}")
        failed += 1

    if clip_path:
        try:
            test_assemble_reel_live(clip_path)
            passed += 1
        except Exception as e:
            print(f"✗ test_assemble_reel_live: {e}")
            failed += 1

    total = passed + failed
    print(f"\n{'='*50}")
    print(f"Passed: {passed}/{total}", "✓" if failed == 0 else "✗")
    if failed:
        sys.exit(1)
