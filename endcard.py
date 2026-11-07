"""
End Card Generator (Pillow + FFmpeg)
====================================
Generates the non-AI final title/brand card conforming to Section 6:
  - Background: brand primary colour (fallback #1F2A44)
  - Uploaded logo centred in upper half, fades in
  - Project name in heading font, brand secondary colour (#D4AF37)
  - "by {promoter}" in body font
  - Lines come from the scene plan's end card (main selling line with fallbacks,
    location, CTA); "by {promoter}" is skipped when the promoter is missing
  - No logo -> the project name is shown in large text
  - "Happy {festival}!" (skipped if festival is None)
  - Downloads Google Fonts if missing, falls back to DejaVu / System fonts
"""

from __future__ import annotations

import os
import subprocess
import urllib.request
from pathlib import Path
from typing import Any, Dict, Optional, Tuple

from PIL import Image, ImageColor, ImageDraw, ImageFont

from project_data import ProjectData

FONTS_DIR = Path("./fonts")
FONTS_DIR.mkdir(parents=True, exist_ok=True)


def _get_font(font_name: str, size: int) -> ImageFont.FreeTypeFont | ImageFont.ImageFont:
    """Load or download requested font, or fall back to system fonts."""
    # Common system font candidates
    system_candidates = [
        "/System/Library/Fonts/Supplemental/PlayfairDisplay.ttf",
        "/System/Library/Fonts/Supplemental/Georgia.ttf",
        "/System/Library/Fonts/Supplemental/Times New Roman.ttf",
        "/System/Library/Fonts/Helvetica.ttc",
        "/usr/share/fonts/truetype/dejavu/DejaVuSans-Bold.ttf",
        "/usr/share/fonts/truetype/dejavu/DejaVuSans.ttf",
    ]

    # Try local fonts directory
    local_path = FONTS_DIR / f"{font_name.replace(' ', '')}.ttf"
    if local_path.exists():
        try:
            return ImageFont.truetype(str(local_path), size)
        except Exception:
            pass

    # Try to download popular Google Fonts
    google_font_urls = {
        "Playfair Display": "https://github.com/google/fonts/raw/main/ofl/playfairdisplay/PlayfairDisplay%5Bwght%5D.ttf",
        "Inter": "https://github.com/google/fonts/raw/main/ofl/inter/Inter%5Bopsz%2Cwght%5D.ttf",
        "Cinzel": "https://github.com/google/fonts/raw/main/ofl/cinzel/Cinzel%5Bwght%5D.ttf",
    }

    if font_name in google_font_urls and not local_path.exists():
        try:
            urllib.request.urlretrieve(google_font_urls[font_name], local_path)
            return ImageFont.truetype(str(local_path), size)
        except Exception:
            pass

    # Try system candidates
    for cand in system_candidates:
        if os.path.exists(cand):
            try:
                return ImageFont.truetype(cand, size)
            except Exception:
                continue

    return ImageFont.load_default()


def render_endcard_image(
    project: ProjectData,
    logo_path: Optional[str] = None,
    festival: str = "Diwali",
    aspect: str = "16:9",
    resolution: str = "720p",
    card: Optional[Dict[str, Any]] = None,
) -> Image.Image:
    """
    Render static high-resolution end card image with Pillow.
    """
    width, height = (1920, 1080) if aspect == "16:9" else (1080, 1920)
    if resolution == "720p":
        width, height = (1280, 720) if aspect == "16:9" else (720, 1280)

    # Background: Minimalist clean off-white for Diwali, brand primary colour for others
    is_diwali = festival == "Diwali"
    if is_diwali:
        bg_color = (250, 249, 246)  # Clean off-white background
        border_color = (212, 175, 55)  # Polished gold border
        tagline_color = "#996515"
        title_color = "#B8860B"
        promoter_color = "#4B5563"
        offer_color = "#1F2937"
    else:
        bg_color_hex = project.brand.primary_colour or "#1F2A44"
        try:
            bg_color = ImageColor.getrgb(bg_color_hex)
        except Exception:
            bg_color = (31, 42, 68)
        border_color = project.brand.secondary_colour or "#C9A227"
        tagline_color = "#F3E5AB"
        title_color = project.brand.secondary_colour or "#C9A227"
        promoter_color = "#E5E7EB"
        offer_color = "#FFFFFF"

    img = Image.new("RGBA", (width, height), bg_color)
    draw = ImageDraw.Draw(img)

    # Decorative warm border
    border_margin = int(width * 0.035)
    border_thickness = max(2, int(width * 0.002))
    draw.rectangle(
        [
            (border_margin, border_margin),
            (width - border_margin, height - border_margin),
        ],
        outline=border_color,
        width=border_thickness,
    )

    # 1. Logo Centered in Upper Half
    y_cursor = int(height * 0.16)
    if logo_path and Path(logo_path).exists():
        try:
            logo_img = Image.open(logo_path).convert("RGBA")
            max_logo_w = int(width * 0.38)
            max_logo_h = int(height * 0.22)
            logo_img.thumbnail((max_logo_w, max_logo_h), Image.LANCZOS)
            logo_x = (width - logo_img.width) // 2
            img.paste(logo_img, (logo_x, y_cursor), logo_img)
            y_cursor += logo_img.height + int(height * 0.04)
        except Exception:
            y_cursor += int(height * 0.05)
    else:
        y_cursor = int(height * 0.32)   # no logo: centre the text block

    card = card or {}
    has_logo = bool(logo_path and Path(logo_path).exists())
    greeting = card.get("greeting_line", f"Happy {festival}!" if festival not in ("None", "Family") else "")
    promoter_line = card.get("promoter_line", f"by {project.promoter}" if project.promoter else "")
    offer_line = card.get("offer_line", "")
    location = card.get("location_line", "")
    cta = card.get("cta_line", "")
    if not card:
        units_str = project.formatted_units_summary
        location = f"{project.marketing_name}, {project.city}" if project.marketing_name else project.city
        if project.lowest_price_inr:
            offer_line = f"{units_str} Homes from {project.formatted_lowest_price}*"
        elif project.available_units:
            offer_line = f"Spacious {units_str} Homes"

    max_w = width * 0.84   # stay inside the card border

    def _line(text: str, size: float, font_name: str, colour: Any, gap: float) -> None:
        """Draw a centred line; split long "a | b" lines and shrink text so it always fits the card."""
        nonlocal y_cursor
        if not text:
            return
        font = _get_font(font_name, int(height * size))
        parts = [text]
        if draw.textlength(text, font=font) > max_w and " | " in text:
            parts = [x.strip() for x in text.split(" | ") if x.strip()]
        for part in parts:
            px = int(height * size)
            f = _get_font(font_name, px)
            while draw.textlength(part, font=f) > max_w and px > int(height * size * 0.55):
                px -= 1
                f = _get_font(font_name, px)
            draw.text((width // 2, y_cursor), part, font=f, fill=colour, anchor="mm")
            y_cursor += int(height * gap * (0.8 if len(parts) > 1 and part != parts[-1] else 1.0))

    vertical = aspect != "16:9"
    # 2. Greeting
    _line(greeting, 0.032 if vertical else 0.038, project.brand.heading_font, tagline_color, 0.065)
    # 3. Project name (large when there is no logo)
    name_size = (0.06 if vertical else 0.09) if not has_logo else (0.045 if vertical else 0.062)
    _line(project.name.upper(), name_size, project.brand.heading_font, title_color,
          0.075 if not has_logo else 0.055)
    # 4. "by {promoter}" (omitted when promoter is missing)
    _line(promoter_line, 0.024 if vertical else 0.030, project.brand.body_font, promoter_color, 0.065)
    # 5. Selling line, location, CTA
    _line(offer_line, 0.025 if vertical else 0.032, project.brand.body_font, offer_color, 0.052)
    _line(location, 0.022 if vertical else 0.027, project.brand.body_font, promoter_color, 0.05)
    _line(cta, 0.022 if vertical else 0.027, project.brand.body_font, tagline_color, 0.05)

    return img.convert("RGB")


def create_endcard_clip(
    project: ProjectData,
    duration: int = 4,
    logo_path: Optional[str] = None,
    festival: str = "Diwali",
    aspect: str = "16:9",
    resolution: str = "720p",
    output_path: Optional[Path] = None,
    card: Optional[Dict[str, Any]] = None,
) -> Path:
    """
    Generate end card video file using Pillow image and FFmpeg (with gentle fade-in).
    """
    out_file = output_path or Path(f"./cache/endcard_{duration}s_{aspect.replace(':', '_')}.mp4")
    out_file.parent.mkdir(parents=True, exist_ok=True)

    img = render_endcard_image(
        project=project,
        logo_path=logo_path,
        festival=festival,
        aspect=aspect,
        resolution=resolution,
        card=card,
    )

    temp_img_path = out_file.parent / f"temp_{out_file.stem}.png"
    img.save(str(temp_img_path))

    # Convert to video with fade-in 0.8s
    cmd = [
        "ffmpeg", "-y",
        "-loop", "1",
        "-i", str(temp_img_path),
        "-t", str(duration),
        "-vf", "fade=t=in:st=0:d=0.8",
        "-pix_fmt", "yuv420p",
        "-c:v", "libx264", "-preset", "veryfast",
        str(out_file)
    ]
    subprocess.run(cmd, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL, check=True)

    if temp_img_path.exists():
        temp_img_path.unlink(missing_ok=True)

    return out_file
