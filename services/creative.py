"""
Creative Generation Pipeline
=============================
Three-stage pipeline:

  Stage 6a — Image Preparation
    • Crop render to target aspect ratio (centre crop, building never cut off)
    • Bake in "Artist's impression" watermark
    • Produce static ad images for all platform sizes

  Stage 6b — Wan 2.2 Animation (via fal.ai)
    • Animate the cropped 9:16 render with gentle motion
    • Never generates buildings from text — only animates developer-supplied renders

  Stage 6c — Hyperframes Assembly (Node.js + FFmpeg via render.js)
    • Combines animated clip + price overlay + logo + RERA number + music bed
    • Produces reels (9:16 / 4:5 × 15s / 30s) and static images at all platform sizes
"""

from __future__ import annotations

import base64
import io
import json
import os
import subprocess
import tempfile
import urllib.request
from datetime import datetime, timezone
from pathlib import Path
from typing import Optional

import fal_client
import yaml
from dotenv import load_dotenv
from PIL import Image, ImageDraw, ImageFont

from services.video_service import VideoJobRequest, get_video_service

load_dotenv()

# ─────────────────────────────────────────────
# Config
# ─────────────────────────────────────────────

OUTPUT_ROOT = Path(os.getenv("OUTPUT_ROOT", "outputs"))
_CONFIG = yaml.safe_load(Path("config/platforms.yaml").read_text())
_CREATIVE_SIZES = _CONFIG["creative_sizes"]
_WAN_CFG = _CONFIG.get("wan", {})

WAN_PROVIDER = _WAN_CFG.get("provider", "fal")
WAN_MODEL = _WAN_CFG.get("model", "fal-ai/wan/v2.2/image-to-video")
WAN_PROMPT = _WAN_CFG.get(
    "prompt",
    "gentle slow zoom, drifting clouds, cinematic real estate, smooth motion",
)
WAN_MOTION = float(_WAN_CFG.get("motion_strength", 0.4))
WAN_RESOLUTIONS = _WAN_CFG.get("resolutions", {"draft": "480p", "final": "720p"})

ASPECT_RATIOS: dict[str, tuple[int, int]] = {
    spec["aspect"]: (spec["width"], spec["height"])
    for spec in _CREATIVE_SIZES["reels"]
}
# Add square, portrait, and landscape ratios
ASPECT_RATIOS["1:1"] = (1080, 1080)
ASPECT_RATIOS["4:5"] = (1080, 1350)
ASPECT_RATIOS["16:9"] = (1920, 1080)


# ─────────────────────────────────────────────
# 6a — Image Preparation
# ─────────────────────────────────────────────

def _centre_crop(img: Image.Image, target_w: int, target_h: int) -> Image.Image:
    """Centre-crop a PIL image to the target (w, h). Scales first if needed."""
    src_w, src_h = img.size
    tgt_ratio = target_w / target_h
    src_ratio = src_w / src_h

    if src_ratio > tgt_ratio:
        # Image is wider than target — crop sides
        new_w = int(src_h * tgt_ratio)
        left = (src_w - new_w) // 2
        img = img.crop((left, 0, left + new_w, src_h))
    else:
        # Image is taller than target — crop top/bottom
        new_h = int(src_w / tgt_ratio)
        top = (src_h - new_h) // 2
        img = img.crop((0, top, src_w, top + new_h))

    return img.resize((target_w, target_h), Image.LANCZOS)


def _bake_watermark(img: Image.Image, text: str = "Artist's impression") -> Image.Image:
    """Overlay a semi-transparent watermark at the bottom-right of the image."""
    draw = ImageDraw.Draw(img)
    w, h = img.size

    # Choose font size relative to image width
    font_size = max(18, w // 55)
    try:
        font = ImageFont.truetype("/System/Library/Fonts/Helvetica.ttc", font_size)
    except (IOError, OSError):
        font = ImageFont.load_default()

    # Measure text
    bbox = draw.textbbox((0, 0), text, font=font)
    tw, th = bbox[2] - bbox[0], bbox[3] - bbox[1]
    padding = 10
    x = w - tw - padding * 2
    y = h - th - padding * 2

    # Semi-transparent background box
    box_coords = (x - padding, y - padding, x + tw + padding, y + th + padding)
    overlay = Image.new("RGBA", img.size, (0, 0, 0, 0))
    overlay_draw = ImageDraw.Draw(overlay)
    overlay_draw.rectangle(box_coords, fill=(0, 0, 0, 140))
    img = img.convert("RGBA")
    img = Image.alpha_composite(img, overlay).convert("RGB")

    draw = ImageDraw.Draw(img)
    draw.text((x, y), text, fill=(255, 255, 255, 220), font=font)
    return img


def prepare_render(
    image_path: str,
    aspect: str = "9:16",
    add_watermark: bool = True,
) -> bytes:
    """
    Crop a developer render to the target aspect ratio and optionally
    bake in the "Artist's impression" watermark.

    Args:
        image_path:    Absolute path to the source render image.
        aspect:        Target aspect ratio string, e.g. "9:16", "4:5", "1:1".
        add_watermark: Whether to bake the watermark (always True for ad creatives).

    Returns:
        JPEG bytes of the prepared image.
    """
    if aspect not in ASPECT_RATIOS:
        raise ValueError(
            f"Unknown aspect ratio '{aspect}'. "
            f"Available: {list(ASPECT_RATIOS.keys())}"
        )
    target_w, target_h = ASPECT_RATIOS[aspect]

    img = Image.open(image_path).convert("RGB")
    img = _centre_crop(img, target_w, target_h)

    if add_watermark:
        img = _bake_watermark(img)

    buf = io.BytesIO()
    img.save(buf, format="JPEG", quality=92)
    return buf.getvalue()


def produce_static_images(
    project_id: str,
    render_path: str,
    logo_path: Optional[str] = None,
) -> dict[str, list[str]]:
    """
    Crop a render to every configured platform image size and save to disk.

    Returns:
        Dict mapping platform name → list of output file paths.
    """
    out_dir = OUTPUT_ROOT / project_id / "images"
    out_dir.mkdir(parents=True, exist_ok=True)

    result: dict[str, list[str]] = {}
    stem = Path(render_path).stem

    for platform_spec in _CREATIVE_SIZES["images"]:
        platform = platform_spec["platform"]
        paths: list[str] = []
        for size in platform_spec["sizes"]:
            w, h = size["width"], size["height"]
            label = size.get("label", f"{w}x{h}")

            img = Image.open(render_path).convert("RGB")
            img = _centre_crop(img, w, h)
            img = _bake_watermark(img)

            fname = f"{stem}_{platform}_{label}.jpg"
            fpath = out_dir / fname
            img.save(str(fpath), format="JPEG", quality=92)
            paths.append(str(fpath))

        result[platform] = result.get(platform, []) + paths

    return result


# ─────────────────────────────────────────────
# 6b — Wan 2.2 Animation
# ─────────────────────────────────────────────

def _image_to_data_uri(image_bytes: bytes) -> str:
    """Encode image bytes as a base64 data URI for fal.ai upload."""
    b64 = base64.b64encode(image_bytes).decode()
    return f"data:image/jpeg;base64,{b64}"


def _download_file(url: str, dest: Path) -> None:
    """Download a URL to a local file path."""
    with urllib.request.urlopen(url) as r:
        dest.write_bytes(r.read())


def _animate_fal(
    project_id: str,
    image_bytes: bytes,
    duration: int,
    aspect: str,
    resolution: str,
) -> str:
    """
    Submit a prepared render to Wan 2.2 via fal.ai and return the local
    path of the downloaded video clip.
    """
    os.environ.setdefault("FAL_KEY", os.getenv("FAL_KEY", ""))

    out_dir = OUTPUT_ROOT / project_id / "clips"
    out_dir.mkdir(parents=True, exist_ok=True)

    data_uri = _image_to_data_uri(image_bytes)
    aspect_tag = aspect.replace(":", "_")
    out_path = out_dir / f"clip_{aspect_tag}_{duration}s.mp4"

    try:
        result = fal_client.subscribe(
            WAN_MODEL,
            arguments={
                "image_url":       data_uri,
                "prompt":          WAN_PROMPT,
                "duration":        duration,
                "motion_strength": WAN_MOTION,
                "aspect_ratio":    aspect,
                "resolution":      resolution,
            },
        )
    except Exception as exc:
        raise RuntimeError(f"Wan 2.2 fal.ai call failed: {exc}") from exc

    video_url = (
        result.get("video", {}).get("url")
        or result.get("video_url")
        or result.get("url")
    )
    if not video_url:
        raise RuntimeError(
            f"fal.ai returned no video URL. Full result: {result}"
        )

    _download_file(video_url, out_path)
    return str(out_path)


def animate_render(
    project_id: str,
    image_bytes: bytes,
    duration: int = 15,
    aspect: str = "9:16",
    quality: str = "draft",
    provider: str = "wan_flash",
    prompt: Optional[str] = None,
    script_text: Optional[str] = None,
    options: Optional[dict] = None,
) -> str:
    """
    Animate a prepared render using the specified video generation engine.
    
    Supported providers:
      - 'wan_flash': Wan 2.6 Flash via fal.ai ($0.75 / 10s)
      - 'veo_fast': Veo 3.1 Fast via Google Gemini Veo API ($1.20 / 10s)
      - 'heygen_avatar': HeyGen API Avatar IV ($0.39 - $0.81 / 10s)
      - 'fal': Legacy alias for Wan
    """
    options = options or {}
    video_service = get_video_service()
    effective_provider = "wan_flash" if provider in ("fal", "wan", "wan_2.2") else provider

    if effective_provider in video_service.engines:
        target_quality = "1080p" if quality == "final" else "720p"
        req = VideoJobRequest(
            project_id=project_id,
            aspect=aspect,
            duration=duration,
            quality=target_quality,
            prompt=prompt,
            image_bytes=image_bytes,
            script_text=script_text,
            options=options,
        )
        res = video_service.generate(effective_provider, req)
        if res.success and res.video_path:
            return res.video_path
        raise RuntimeError(f"Video generation failed with {effective_provider}: {res.error}")

    # Fallback to legacy _animate_fal if provider is explicitly fal
    resolution = WAN_RESOLUTIONS.get(quality, "720p")
    if WAN_PROVIDER == "fal":
        return _animate_fal(project_id, image_bytes, duration, aspect, resolution)
    else:
        raise ValueError(f"Unknown animation provider: {provider}")


# ─────────────────────────────────────────────
# 6c — Hyperframes Assembly
# ─────────────────────────────────────────────

def assemble_reel(
    project_id: str,
    clip_path: str,
    rera_number: str,
    price_text: str,
    logo_path: Optional[str],
    aspect: str = "9:16",
    duration: int = 15,
    music_path: Optional[str] = None,
    voice_url: Optional[str] = None,
    srt_path: Optional[str] = None,
) -> str:
    """
    Assemble a single reel by calling HeyGen Hyperframes Local Renderer.
    """
    import shutil
    
    out_dir = OUTPUT_ROOT / project_id / "reels"
    out_dir.mkdir(parents=True, exist_ok=True)

    aspect_tag = aspect.replace(":", "_")
    out_path = str(out_dir / f"reel_{aspect_tag}_{duration}s.mp4")
    
    # 1. Create temporary build directory
    build_dir = out_dir / f"build_{aspect_tag}_{duration}s"
    if build_dir.exists():
        shutil.rmtree(build_dir)
        
    # Copy base hyperframes project
    shutil.copytree("hyperframes_project", build_dir)
    
    # 2. Copy assets into build directory
    assets_dir = build_dir / "assets"
    assets_dir.mkdir(exist_ok=True)
    
    local_clip = ""
    if clip_path:
        local_clip = "assets/clip" + Path(clip_path).suffix
        shutil.copy2(clip_path, build_dir / local_clip)
        
    local_logo = ""
    if logo_path:
        local_logo = "assets/logo" + Path(logo_path).suffix
        shutil.copy2(logo_path, build_dir / local_logo)
        
    audio_tags = ""
    if music_path:
        local_music = "assets/music" + Path(music_path).suffix
        shutil.copy2(music_path, build_dir / local_music)
        audio_tags += f'<audio src="{local_music}" autoplay loop></audio>\n'
        
    if voice_url:
        local_voice = "assets/voice" + Path(voice_url).suffix
        shutil.copy2(voice_url, build_dir / local_voice)
        audio_tags += f'<audio src="{local_voice}" autoplay></audio>\n'
        
    # Read SRT (if any)
    import json
    subtitles_json = "[]"
    if srt_path and Path(srt_path).exists():
        try:
            # Basic SRT parser to JSON format (simplified)
            import re
            subs = []
            with open(srt_path, "r") as f:
                content = f.read()
            blocks = re.split(r'\n\n+', content.strip())
            for block in blocks:
                lines = block.split('\n')
                if len(lines) >= 3:
                    time_line = lines[1]
                    text = ' '.join(lines[2:])
                    m = re.match(r'(\d+):(\d+):(\d+),(\d+) --> (\d+):(\d+):(\d+),(\d+)', time_line)
                    if m:
                        start_time = int(m.group(1))*3600 + int(m.group(2))*60 + int(m.group(3)) + int(m.group(4))/1000
                        end_time = int(m.group(5))*3600 + int(m.group(6))*60 + int(m.group(7)) + int(m.group(8))/1000
                        subs.append({"start": start_time, "end": end_time, "text": text})
            subtitles_json = json.dumps(subs)
        except Exception as e:
            print("Failed to parse SRT", e)

    # 3. Read template and inject props
    template_path = build_dir / "index_template.html"
    with open(template_path, "r") as f:
        html = f.read()
        
    html = html.replace("{{duration}}", str(duration))
    html = html.replace("{{image_path}}", local_clip)
    html = html.replace("{{logo_path}}", local_logo)
    html = html.replace("{{price_text}}", price_text)
    html = html.replace("{{rera_number}}", rera_number)
    html = html.replace("{{audio_tags}}", audio_tags)
    html = html.replace("{{subtitles_json}}", subtitles_json)
    
    # Write to index.html
    with open(build_dir / "index.html", "w") as f:
        f.write(html)
        
    # 4. Run hyperframes local render
    try:
        import subprocess
        abs_out_path = str(Path(out_path).absolute())
        print(f"[{aspect_tag} {duration}s] Rendering locally with Hyperframes...")
        result = subprocess.run(
            ["npx", "--yes", "hyperframes", "render", "--format", "mp4", "-o", abs_out_path],
            cwd=str(build_dir),
            capture_output=True,
            text=True
        )
        if result.returncode != 0:
            raise RuntimeError(
                f"Hyperframes Local Render failed (exit {result.returncode}):\n"
                f"stdout: {result.stdout}\n"
                f"stderr: {result.stderr}"
            )
        return out_path
    finally:
        # Cleanup build directory
        shutil.rmtree(build_dir, ignore_errors=True)


# ─────────────────────────────────────────────
# Full Pipeline Orchestrator
# ─────────────────────────────────────────────

def run_creative_pipeline(
    project_id: str,
    render_paths: list[str],
    rera_number: str,
    price_text: str,
    logo_path: Optional[str] = None,
    music_path: Optional[str] = None,
    voice_script: Optional[str] = None,
    animate: bool = True,
    quality: str = "draft",
    video_provider: str = "wan_flash",
    provider_options: Optional[dict] = None,
) -> dict:
    """
    Run the full creative pipeline for a project.

    Steps:
      1. Prepare renders (crop + watermark) for each aspect ratio
      2. Produce static images for all platform sizes
      3. Animate render via selected video engine:
         - 'wan_flash': Wan 2.6 Flash via fal.ai
         - 'veo_fast': Veo 3.1 Fast via Google Gemini Veo API
         - 'heygen_avatar': HeyGen API Avatar IV
         - 'hyperframes': Fast Ken Burns zoom motion
      4. Assemble reels via Hyperframes for each aspect × duration

    Args:
        project_id:        Project UUID (used for output directory structure).
        render_paths:      List of paths to developer exterior render images.
        rera_number:       Confirmed RERA number to overlay on all creatives.
        price_text:        Price string to overlay, e.g. "₹1.42 Cr onwards".
        logo_path:         Optional path to developer logo PNG.
        music_path:        Optional path to licensed music bed MP3.
        voice_script:      Voice narration script.
        animate:           Set False to skip AI video generation (for local testing).
        quality:           "draft" or "final" (maps to 720p or 1080p).
        video_provider:    Video engine: 'wan_flash', 'veo_fast', 'heygen_avatar', or 'hyperframes'.
        provider_options:  Additional engine-specific options.

    Returns:
        {
          "static_images": { platform: [path, ...] },
          "clips":         { "9:16": path, "4:5": path },
          "reels":         [path, ...],
          "video_provider": str,
          "errors":        [str, ...],
        }
    """
    result: dict = {
        "static_images":  {},
        "clips":          {},
        "reels":          [],
        "video_provider": video_provider,
        "errors":         [],
    }

    if not render_paths:
        result["errors"].append("No render images provided.")
        return result

    primary_render = render_paths[0]

    # ── Step 1 & 2: Static images for all platform sizes ──────────────────
    try:
        static = produce_static_images(project_id, primary_render, logo_path)
        result["static_images"] = static
    except Exception as exc:
        result["errors"].append(f"Static image generation failed: {exc}")

    # ── Step 3: Animate for each reel aspect ratio ────────────────────────
    for reel_spec in _CREATIVE_SIZES["reels"]:
        aspect = reel_spec["aspect"]
        fallback_path = None
        try:
            prepped = prepare_render(primary_render, aspect=aspect)
            
            # Save prepped image as fallback
            out_dir = OUTPUT_ROOT / project_id / "clips"
            out_dir.mkdir(parents=True, exist_ok=True)
            fallback_path = out_dir / f"fallback_{aspect.replace(':', '_')}.jpg"
            fallback_path.write_bytes(prepped)
            
            if animate and video_provider != "hyperframes":
                clip_path = animate_render(
                    project_id=project_id,
                    image_bytes=prepped,
                    duration=reel_spec["durations"][0],
                    aspect=aspect,
                    quality=quality,
                    provider=video_provider,
                    script_text=voice_script,
                    options=provider_options,
                )
                result["clips"][aspect] = clip_path
            else:
                result["clips"][aspect] = str(fallback_path)
                
        except Exception as exc:
            result["errors"].append(f"Animation failed for {aspect} via {video_provider}: {exc}")
            if fallback_path:
                result["clips"][aspect] = str(fallback_path)

    # ── Step 3.5: Voiceover (Kokoro TTS) ───────────────────────────────
    # For HeyGen Avatar IV, the avatar already speaks the script with lip-sync!
    voice_wav = None
    voice_srt = None
    if voice_script and video_provider != "heygen_avatar":
        try:
            from services.tts import generate_voiceover
            out_dir = str(OUTPUT_ROOT / project_id / "audio")
            voice_wav, voice_srt = generate_voiceover(voice_script, out_dir)
        except Exception as exc:
            result["errors"].append(f"Voice generation failed: {exc}")

    # ── Step 4: Assemble reels (Hyperframes) ─────────────────────────────
    for reel_spec in _CREATIVE_SIZES["reels"]:
        aspect = reel_spec["aspect"]
        clip_path = result["clips"].get(aspect)
        if not clip_path:
            continue

        for duration in reel_spec["durations"]:
            try:
                reel_path = assemble_reel(
                    project_id=project_id,
                    clip_path=clip_path,
                    rera_number=rera_number,
                    price_text=price_text,
                    logo_path=logo_path,
                    aspect=aspect,
                    duration=duration,
                    music_path=music_path if video_provider != "heygen_avatar" else None,
                    voice_url=voice_wav,
                    srt_path=voice_srt,
                )
                result["reels"].append(reel_path)
            except Exception as exc:
                result["errors"].append(
                    f"Reel assembly failed for {aspect} {duration}s: {exc}"
                )

    return result
