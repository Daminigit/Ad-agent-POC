"""
End Card Generator (Pillow + FFmpeg)
====================================
Generates the non-AI final title/brand card conforming to Section 6:
  - Background: brand primary colour (fallback #1F2A44)
  - Uploaded logo centred in upper half, fades in
  - Project name in heading font, brand secondary colour (#D4AF37)
  - "by {promoter}" in body font
  - "{available unit types} Homes from {lowest price}* | {marketing_name}, {city}"
  - "Happy {festival}!" (skipped if festival is None)
  - Downloads Google Fonts if missing, falls back to DejaVu / System fonts
"""

from __future__ import annotations

import os
import subprocess
import urllib.request
from pathlib import Path
from typing import Optional, Tuple

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
    resolution: str = "1080p",
) -> Image.Image:
    """
    Render static high-resolution end card image with Pillow.
    """
    width, height = (1920, 1080) if aspect == "16:9" else (1080, 1920)
    if resolution == "720p":
        width, height = (1280, 720) if aspect == "16:9" else (720, 1280)

    # Background: Brand primary colour
    bg_color_hex = project.brand.primary_colour or "#1F2A44"
    try:
        bg_color = ImageColor.getrgb(bg_color_hex)
    except Exception:
        bg_color = (31, 42, 68)

    img = Image.new("RGBA", (width, height), bg_color)
    draw = ImageDraw.Draw(img)

    # Decorative warm border
    border_color = project.brand.secondary_colour or "#D4AF37"
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
        y_cursor += int(height * 0.06)

    # 2. Festive Greeting (skip if festival is None)
    if festival and festival != "None":
        festive_font = _get_font(project.brand.heading_font, int(height * 0.038))
        greeting = f"Happy {festival}!"
        draw.text(
            (width // 2, y_cursor),
            greeting,
            font=festive_font,
            fill="#F3E5AB",
            anchor="mm",
        )
        y_cursor += int(height * 0.065)

    # 3. Project Name in Heading Font (brand secondary colour)
    title_font_size = int(height * 0.062) if aspect == "16:9" else int(height * 0.045)
    title_font = _get_font(project.brand.heading_font, title_font_size)
    project_title = project.name.upper()
    title_color = project.brand.secondary_colour or "#D4AF37"
    draw.text(
        (width // 2, y_cursor),
        project_title,
        font=title_font,
        fill=title_color,
        anchor="mm",
    )
    y_cursor += int(height * 0.055)

    # 4. "by {promoter}" in body font
    body_font_size = int(height * 0.030) if aspect == "16:9" else int(height * 0.024)
    body_font = _get_font(project.brand.body_font, body_font_size)
    promoter_text = f"by {project.promoter}"
    draw.text(
        (width // 2, y_cursor),
        promoter_text,
        font=body_font,
        fill="#E5E7EB",
        anchor="mm",
    )
    y_cursor += int(height * 0.065)

    # 5. Units, Price & Location
    # "{available unit types} Homes from {lowest price}* | {marketing_name}, {city}"
    units_str = project.formatted_units_summary
    price_str = project.formatted_lowest_price
    loc_part = f"{project.marketing_name}, {project.city}" if project.marketing_name else project.city
    offer_line = f"{units_str} Homes from {price_str}* | {loc_part}"

    offer_font_size = int(height * 0.032) if aspect == "16:9" else int(height * 0.025)
    offer_font = _get_font(project.brand.body_font, offer_font_size)
    draw.text(
        (width // 2, y_cursor),
        offer_line,
        font=offer_font,
        fill="#FFFFFF",
        anchor="mm",
    )

    return img.convert("RGB")


def create_endcard_clip(
    project: ProjectData,
    duration: int = 4,
    logo_path: Optional[str] = None,
    festival: str = "Diwali",
    aspect: str = "16:9",
    resolution: str = "1080p",
    output_path: Optional[Path] = None,
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
