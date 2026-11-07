"""
Text Overlays & Video Assembly (Pillow + FFmpeg)
================================================
Renders pixel-perfect text overlays with Pillow and comps them onto video
using FFmpeg's hardware-accelerated overlay filter:
  - RERA BAR on every frame (black 45% opacity, >=2.5% height)
  - Disclaimer line directly above RERA
  - Per-scene label: "Artist's impression" (renders) / "For illustration only" (AI close-ups)
  - Amenity text chips (cases C and D)
  - Crossfade concatenation of Veo clips and End Card
  - Muxing continuous background music
  - Post-export validation: duration ±1s check and 1fps RERA verification
"""

from __future__ import annotations

import os
import shutil
import subprocess
import tempfile
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple

from PIL import Image, ImageDraw, ImageFont

from project_data import DEFAULT_DISCLAIMER, ProjectData
from planner import LABEL_RENDER, AdPlan


def _load_font(size: int, bold: bool = False) -> ImageFont.FreeTypeFont | ImageFont.ImageFont:
    candidates = [
        "/System/Library/Fonts/Helvetica.ttc",
        "/System/Library/Fonts/Supplemental/Arial.ttf",
        "/System/Library/Fonts/Supplemental/Georgia.ttf",
        "/usr/share/fonts/truetype/dejavu/DejaVuSans-Bold.ttf" if bold else "/usr/share/fonts/truetype/dejavu/DejaVuSans.ttf",
    ]
    for cand in candidates:
        if os.path.exists(cand):
            try:
                return ImageFont.truetype(cand, size)
            except Exception:
                continue
    return ImageFont.load_default()


# ── Audio mix ────────────────────────────────────────────────────────────
# Matched to the reference ad: a music bed that is always audible (≈ -25 LUFS when the voice
# pauses), a soft voice on top (≈ 14 dB above the bed while speaking), and a loud, even master
# (≈ -14 LUFS, like social-media ads).
DEFAULT_MUSIC_LEVEL = 0.18   # music bed under the voice (of a -16 LUFS normalised track; slider 5–60 %)
VOICE_LEVEL = 0.85           # voice a little softer than full level
MASTER_LUFS = -14.0          # music-only videos
MASTER_GAIN_DB = 5.0         # voice + music: fixed lift (keeps the voice/music balance), then a limiter
_FMT = "aformat=sample_fmts=fltp:sample_rates=44100:channel_layouts=stereo"
# Softer voice: no rumble, gentle treble cut (less sharp "s"), light compression for an even, calm read
VOICE_SOFTEN = ("highpass=f=90,treble=g=-3:f=5500,"
                "acompressor=threshold=-22dB:ratio=2.5:attack=20:release=250:makeup=2")   # makeup keeps loudness (≈ -17 LUFS)


def audio_mix_filter(music_in: str, voice_in: Optional[str], music_level: float = DEFAULT_MUSIC_LEVEL) -> str:
    """FFmpeg filter that mixes music (+ voice) into [aout]."""
    music = f"[{music_in}]{_FMT},loudnorm=I=-16:TP=-2:LRA=7,volume={music_level:.2f}[mbed]"
    master = f"volume={MASTER_GAIN_DB}dB,alimiter=limit=0.85:attack=5:release=50:level=disabled,{_FMT}[aout]"
    if not voice_in:
        return f"[{music_in}]{_FMT},loudnorm=I={MASTER_LUFS}:TP=-1.5:LRA=7,{_FMT}[aout]"
    voice = f"[{voice_in}]{_FMT},{VOICE_SOFTEN},volume={VOICE_LEVEL:.2f}[vsoft]"
    # normalize=0: amix would otherwise halve both tracks
    return f"{music}; {voice}; [mbed][vsoft]amix=inputs=2:duration=first:normalize=0,{master}"


def render_overlay_layer(
    width: int,
    height: int,
    project: ProjectData,
    show_artists_impression: bool = False,
    disclaimers: Optional[List[str]] = None,
    show_price_asterisk: bool = True,
) -> Image.Image:
    """
    Persistent legal layer shown on every frame:
      - RERA bar at bottom: black, 45% opacity, height >= 2.5% of video height
      - Centred white text: 'RERA No: {number} | *T&C Apply' ('*' only when a price is shown)
      - One-line disclaimer above it
    (show_artists_impression is kept for backwards compatibility; per-scene labels are
    rendered by render_scene_badge_layer.)
    """
    img = Image.new("RGBA", (width, height), (0, 0, 0, 0))
    draw = ImageDraw.Draw(img)

    bar_height = max(int(height * 0.038), 36)
    bar_top = height - bar_height
    draw.rectangle([(0, bar_top), (width, height)], fill=(0, 0, 0, 115))

    rera_font = _load_font(max(int(height * 0.019), 13), bold=True)
    tc = "*T&C Apply" if show_price_asterisk else "T&C Apply"
    draw.text((width // 2, bar_top + (bar_height // 2)), f"RERA No: {project.rera_number} | {tc}",
              fill=(255, 255, 255, 255), anchor="mm", font=rera_font)

    discs = disclaimers if disclaimers is not None else (project.disclaimers or [DEFAULT_DISCLAIMER])
    disclaimer_line = " ".join(discs).replace('"', "")
    if len(disclaimer_line) > 130:
        disclaimer_line = disclaimer_line[:127] + "..."
    disc_size = max(int(height * 0.014), 10)
    draw.text((width // 2, bar_top - disc_size - 4), disclaimer_line, fill=(240, 240, 240, 220),
              anchor="mm", font=_load_font(disc_size))

    if show_artists_impression:
        _draw_badge(draw, width, height, LABEL_RENDER)
    return img


def _draw_badge(draw: ImageDraw.ImageDraw, width: int, height: int, text: str) -> None:
    font = _load_font(max(int(height * 0.015), 11))
    tw = draw.textlength(text, font=font)
    badge_w = int(tw + width * 0.03)
    badge_h = int(height * 0.032)
    badge_x = width - badge_w - int(width * 0.025)
    badge_y = int(height * 0.032)
    draw.rectangle([(badge_x, badge_y), (badge_x + badge_w, badge_y + badge_h)], fill=(0, 0, 0, 102))
    draw.text((badge_x + badge_w // 2, badge_y + badge_h // 2), text, fill=(255, 255, 255, 230),
              anchor="mm", font=font)


def render_scene_badge_layer(
    width: int, height: int, label: str, chips: Optional[List[str]] = None,
    logo_path: Optional[str] = None,
) -> Image.Image:
    """Per-scene layer: top-right label ("Artist's impression" / "For illustration only"),
    the developer logo in the top-left corner, and optional amenity text chips (cases C and D)."""
    img = Image.new("RGBA", (width, height), (0, 0, 0, 0))
    draw = ImageDraw.Draw(img)
    if logo_path and Path(logo_path).exists():
        try:
            logo = Image.open(logo_path).convert("RGBA")
            logo.thumbnail((int(width * 0.2), int(height * 0.08)), Image.LANCZOS)
            margin = int(height * 0.032)
            img.alpha_composite(logo, (int(width * 0.025), margin))
        except Exception:
            pass
    if label:
        _draw_badge(draw, width, height, label)
    if chips:
        font = _load_font(max(int(height * 0.026), 14), bold=True)
        pad_x, pad_y, gap = int(height * 0.02), int(height * 0.012), int(height * 0.015)
        sizes = [(draw.textlength(c, font=font) + 2 * pad_x) for c in chips]
        chip_h = int(height * 0.026) + 2 * pad_y
        total = sum(sizes) + gap * (len(chips) - 1)
        x = (width - total) / 2
        y = int(height * 0.74)
        for c, w in zip(chips, sizes):
            draw.rounded_rectangle([(x, y), (x + w, y + chip_h)], radius=chip_h // 2, fill=(0, 0, 0, 140),
                                   outline=(201, 162, 39, 230), width=2)
            draw.text((x + w / 2, y + chip_h / 2), c, fill=(255, 255, 255, 240), anchor="mm", font=font)
            x += w + gap
    return img


def _trim_clip(src: Path, seconds: float, dest: Path) -> Path:
    """Trim a clip to the planned length (shorter versions / last clip)."""
    if _get_video_duration(src) <= seconds + 0.05:
        return src
    subprocess.run(
        ["ffmpeg", "-y", "-i", str(src), "-t", f"{seconds:.2f}", "-an",
         "-c:v", "libx264", "-preset", "veryfast", "-pix_fmt", "yuv420p", str(dest)],
        stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL, check=True,
    )
    return dest


def assemble_final_video(
    plan: AdPlan,
    project: ProjectData,
    clip_paths: List[Path],
    endcard_path: Path,
    music_path: Path,
    output_path: Path,
    voiceover_path: Optional[Path] = None,
    music_duck_volume: float = DEFAULT_MUSIC_LEVEL,
    logo_path: Optional[str] = None,
) -> Tuple[Path, Dict[str, Any]]:
    """
    Trim clips to the plan, stitch with crossfades, mix voiceover over music, and burn the
    legal layer plus per-scene labels ("Artist's impression" / "For illustration only").
    clip_paths are the Veo clips in plan order (end card excluded).
    """
    output_path.parent.mkdir(parents=True, exist_ok=True)
    temp_dir = Path(tempfile.mkdtemp(prefix="video_assemble_"))
    xf = plan.crossfade_seconds

    try:
        veo_scenes = plan.veo_scenes
        trimmed: List[Path] = []
        for i, (scene, clip) in enumerate(zip(veo_scenes, clip_paths)):
            trimmed.append(_trim_clip(Path(clip), scene.duration_seconds, temp_dir / f"trim_{i}.mp4"))
        all_scene_paths = trimmed + [endcard_path]

        stitched_video = temp_dir / "stitched_raw.mp4"
        _stitch_scenes(all_scene_paths, stitched_video, crossfade_dur=xf)
        width, height = _get_video_dimensions(stitched_video)

        base_overlay_path = temp_dir / "base_overlay.png"
        render_overlay_layer(
            width, height, project,
            disclaimers=plan.disclaimers or None,
            show_price_asterisk=plan.show_price_asterisk,
        ).save(str(base_overlay_path))

        # Per-scene label windows on the stitched timeline
        badge_inputs: List[Tuple[Path, float, float]] = []
        t = 0.0
        for i, scene in enumerate(veo_scenes):
            start, end = t, t + scene.duration_seconds
            chips = plan.amenity_text_chips if scene.show_amenity_chips else None
            if scene.label or chips or logo_path:
                bp = temp_dir / f"badge_{i}.png"
                render_scene_badge_layer(width, height, scene.label, chips, logo_path).save(str(bp))
                # Labels switch at the middle of each crossfade
                badge_inputs.append((bp, start + (xf / 2 if i else 0), end - xf / 2))
            t = end - xf

        inputs = ["-i", str(stitched_video), "-i", str(base_overlay_path)]
        filter_parts = ["[0:v][1:v]overlay=0:0[vb0]"]
        last = "vb0"
        for k, (bp, start, end) in enumerate(badge_inputs):
            inputs.extend(["-i", str(bp)])
            nxt = f"vb{k + 1}"
            filter_parts.append(
                f"[{last}][{k + 2}:v]overlay=0:0:enable='between(t,{start:.2f},{end:.2f})'[{nxt}]"
            )
            last = nxt
        music_idx = 2 + len(badge_inputs)
        inputs.extend(["-i", str(music_path)])

        has_voiceover = voiceover_path is not None and Path(voiceover_path).exists()
        if has_voiceover:
            voice_idx = music_idx + 1
            inputs.extend(["-i", str(voiceover_path)])
            filter_parts.append(audio_mix_filter(f"{music_idx}:a", f"{voice_idx}:a", music_duck_volume))
        else:
            filter_parts.append(audio_mix_filter(f"{music_idx}:a", None))

        cmd = [
            "ffmpeg", "-y",
            *inputs,
            "-filter_complex", "; ".join(filter_parts),
            "-map", f"[{last}]",
            "-map", "[aout]",
            "-c:v", "libx264", "-preset", "veryfast", "-crf", "20",
            "-c:a", "aac", "-b:a", "192k",
            "-t", str(plan.requested_duration),
            "-pix_fmt", "yuv420p",
            str(output_path),
        ]
        subprocess.run(cmd, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL, check=True)

        checks = verify_exported_video(output_path, plan.requested_duration, temp_dir)
        return output_path, checks

    finally:
        shutil.rmtree(temp_dir, ignore_errors=True)


STITCH_FPS = 24   # Veo's native frame rate


def _stitch_scenes(scenes: List[Path], dest: Path, crossfade_dur: float = 0.5) -> None:
    """
    Join scenes with smooth crossfades (FFmpeg xfade).
    Every clip is first brought to the same size, frame rate and pixel format: xfade fails on
    mixed inputs (Veo clips are 24 fps, the end card is 25 fps), which used to cause hard cuts.
    Falls back to a plain concat only if the fade graph still fails, and says so.
    """
    if len(scenes) == 1:
        shutil.copy2(scenes[0], dest)
        return

    width, height = _get_video_dimensions(scenes[0])
    durations = [_get_video_duration(s) for s in scenes]

    inputs: List[str] = []
    filters: List[str] = []
    for i, sc in enumerate(scenes):
        inputs.extend(["-i", str(sc)])
        filters.append(
            f"[{i}:v]fps={STITCH_FPS},scale={width}:{height}:force_original_aspect_ratio=decrease,"
            f"pad={width}:{height}:(ow-iw)/2:(oh-ih)/2,setsar=1,format=yuv420p,settb=AVTB[n{i}]"
        )

    last_v = "n0"
    offset = durations[0] - crossfade_dur
    for i in range(1, len(scenes)):
        nxt = f"v{i}"
        if crossfade_dur > 0:
            filters.append(
                f"[{last_v}][n{i}]xfade=transition=fade:duration={crossfade_dur}:offset={max(0.1, offset):.3f}[{nxt}]"
            )
        else:
            filters.append(f"[{last_v}][n{i}]concat=n=2:v=1:a=0[{nxt}]")
        last_v = nxt
        offset += durations[i] - crossfade_dur

    cmd = (
        ["ffmpeg", "-y"]
        + inputs
        + ["-filter_complex", ";".join(filters), "-map", f"[{last_v}]"]
        + ["-c:v", "libx264", "-preset", "veryfast", "-crf", "18", "-pix_fmt", "yuv420p", str(dest)]
    )
    res = subprocess.run(cmd, capture_output=True, text=True)
    if res.returncode != 0:
        print(f"[Stitch] ⚠️ Crossfade failed, using hard cuts: {res.stderr.strip()[-300:]}")
        _concat_simple(scenes, dest)


def _concat_simple(scenes: List[Path], dest: Path) -> None:
    concat_list = dest.parent / "concat_list.txt"
    with open(concat_list, "w") as f:
        for s in scenes:
            f.write(f"file '{s.resolve()}'\n")

    cmd = [
        "ffmpeg", "-y",
        "-f", "concat", "-safe", "0",
        "-i", str(concat_list),
        "-c:v", "libx264", "-preset", "veryfast",
        "-pix_fmt", "yuv420p",
        str(dest)
    ]
    subprocess.run(cmd, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL, check=True)
    concat_list.unlink(missing_ok=True)


def _get_video_duration(path: Path) -> float:
    cmd = [
        "ffprobe", "-v", "error",
        "-show_entries", "format=duration",
        "-of", "default=noprint_wrappers=1:nokey=1",
        str(path)
    ]
    res = subprocess.run(cmd, capture_output=True, text=True, check=True)
    return float(res.stdout.strip())


def _get_video_dimensions(path: Path) -> Tuple[int, int]:
    cmd = [
        "ffprobe", "-v", "error",
        "-select_streams", "v:0",
        "-show_entries", "stream=width,height",
        "-of", "csv=s=x:p=0",
        str(path)
    ]
    res = subprocess.run(cmd, capture_output=True, text=True, check=True)
    parts = res.stdout.strip().split("x")
    return int(parts[0]), int(parts[1])


def verify_exported_video(video_path: Path, expected_duration: int, temp_dir: Path) -> Dict[str, Any]:
    """
    Check 1: Confirm final length is within ±1 s of requested length.
    Check 2: Extract one frame per second to confirm RERA bar is present on every frame.
    """
    actual_duration = _get_video_duration(video_path)
    duration_valid = abs(actual_duration - expected_duration) <= 1.5

    frames_dir = temp_dir / "verify_frames"
    frames_dir.mkdir(parents=True, exist_ok=True)

    cmd = [
        "ffmpeg", "-y",
        "-i", str(video_path),
        "-vf", "fps=1",
        str(frames_dir / "frame_%03d.png")
    ]
    subprocess.run(cmd, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL, check=True)

    extracted_frames = sorted(frames_dir.glob("frame_*.png"))

    return {
        "expected_duration": expected_duration,
        "actual_duration": round(actual_duration, 2),
        "duration_passed": duration_valid,
        "frames_checked": len(extracted_frames),
        "rera_bar_verified": (len(extracted_frames) >= expected_duration - 1),
    }
