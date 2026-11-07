"""
Poster Layout Templates
=======================
Four distinct visual templates for festive real-estate posters.
All share the same function signature as the original render_poster()
so they drop-in to the existing app.py.

Templates
---------
1. luxury_navy   – Original deep-navy glassmorphic card (existing behaviour)
2. minimal_white – Clean white bottom panel, black text, accent colour border
3. cinematic     – Full-bleed dark overlay, large centred headline, minimal info strip
4. split_panel   – Left-side vertical colour band with rotated project name; right side info

Usage
-----
from poster_generator.layout_templates import render_poster_with_template

img = render_poster_with_template(
    template="minimal_white",          # or "luxury_navy" / "cinematic" / "split_panel"
    background_path=...,
    project=project,
    logo_path=...,
    headline=...,
    festival=...,
    size_id="instagram_post",
    output_path=...,
)
"""

from __future__ import annotations

import math
from pathlib import Path
from typing import Optional, Tuple

from PIL import Image, ImageColor, ImageDraw, ImageFilter, ImageFont

try:
    from config import SIZES
    from project_data import ProjectData, is_valid_content
except ImportError:
    from poster_generator.config import SIZES
    from poster_generator.project_data import ProjectData, is_valid_content


# ─────────────────────────────────────────────────────────────────────────────
# Shared Utilities
# ─────────────────────────────────────────────────────────────────────────────

class _LiningFont(ImageFont.FreeTypeFont):
    """
    Cormorant Garamond defaults to old-style numerals (descending 3/5/9, a "1" that looks
    like "I"), which make prices and areas hard to read. Turn on lining figures for every
    measure and draw call unless the caller asks for other OpenType features.
    """
    _FEATURES = ["lnum", "kern", "liga"]

    def getbbox(self, text, mode="", direction=None, features=None, *args, **kwargs):
        return super().getbbox(text, mode, direction, features or self._FEATURES, *args, **kwargs)

    def getlength(self, text, mode="", direction=None, features=None, *args, **kwargs):
        return super().getlength(text, mode, direction, features or self._FEATURES, *args, **kwargs)

    def getmask2(self, text, mode="", direction=None, features=None, *args, **kwargs):
        return super().getmask2(text, mode, direction, features or self._FEATURES, *args, **kwargs)


def _get_font(font_name: str, size: int) -> ImageFont.FreeTypeFont:
    fonts_dir = Path(__file__).parent / "fonts"
    font_str = str(font_name or "").lower()
    if "playfair" in font_str:
        target_ttf = fonts_dir / "PlayfairDisplay.ttf"
    elif "cormorant" in font_str or "garamond" in font_str:
        target_ttf = fonts_dir / "CormorantGaramond.ttf"
    else:
        target_ttf = fonts_dir / "Inter.ttf"
    if target_ttf.exists():
        try:
            if target_ttf.name.startswith("Cormorant"):
                return _LiningFont(str(target_ttf), size)
            return ImageFont.truetype(str(target_ttf), size)
        except Exception:
            pass
    for sc in [
        "/System/Library/Fonts/Supplemental/Arial.ttf",
        "/System/Library/Fonts/Helvetica.ttc",
        "/System/Library/Fonts/Times.ttc",
        "/Library/Fonts/Arial.ttf",
        "/usr/share/fonts/truetype/dejavu/DejaVuSans.ttf",
    ]:
        if Path(sc).exists():
            try:
                return ImageFont.truetype(sc, size)
            except Exception:
                continue
    return ImageFont.load_default()


def _fit_text(
    draw: ImageDraw.ImageDraw,
    text: str,
    font_name: str,
    max_w: int,
    max_h: int,
    initial_size: int,
    min_size: int = 12,
) -> Tuple[ImageFont.FreeTypeFont, int, int]:
    size = initial_size
    while size >= min_size:
        font = _get_font(font_name, size)
        bbox = draw.textbbox((0, 0), text, font=font)
        w, h = bbox[2] - bbox[0], bbox[3] - bbox[1]
        if w <= max_w and h <= max_h:
            return font, w, h
        size -= 1
    font = _get_font(font_name, min_size)
    bbox = draw.textbbox((0, 0), text, font=font)
    return font, bbox[2] - bbox[0], bbox[3] - bbox[1]


def _load_background(background_path, target_w: int, target_h: int) -> Image.Image:
    bg = Image.open(Path(background_path)).convert("RGBA")
    if bg.size != (target_w, target_h):
        bg = bg.resize((target_w, target_h), Image.LANCZOS)
    return bg


def _paste_logo(
    overlay: Image.Image,
    draw: ImageDraw.ImageDraw,
    logo_path,
    target_w: int,
    target_h: int,
    align: str = "center",          # "left" | "center" | "right"
    bg_fill=(255, 255, 255, 220),
    border_color=(201, 162, 39, 180),
    cursor_y: int = 0,
) -> int:
    """Paste logo onto overlay; returns new cursor_y below the logo."""
    if not logo_path or not Path(logo_path).exists():
        return cursor_y + int(target_h * 0.02)
    try:
        logo_img = Image.open(logo_path).convert("RGBA")
        bbox = logo_img.getbbox()
        if bbox:
            logo_img = logo_img.crop(bbox)
        logo_w_target = int(target_w * 0.18)
        ratio = min(logo_w_target / logo_img.width, (target_h * 0.10) / logo_img.height)
        new_w = max(10, int(logo_img.width * ratio))
        new_h = max(10, int(logo_img.height * ratio))
        logo_resized = logo_img.resize((new_w, new_h), Image.LANCZOS)

        if align == "left":
            logo_x = int(target_w * 0.05)
        elif align == "right":
            logo_x = target_w - new_w - int(target_w * 0.05)
        else:
            logo_x = (target_w - new_w) // 2

        pad_x = int(new_w * 0.14)
        pad_y = int(new_h * 0.12)
        draw.rounded_rectangle(
            [(logo_x - pad_x, cursor_y - pad_y),
             (logo_x + new_w + pad_x, cursor_y + new_h + pad_y)],
            radius=max(8, int(new_h * 0.22)),
            fill=bg_fill,
            outline=border_color,
            width=max(1, int(target_w * 0.0015)),
        )
        overlay.paste(logo_resized, (logo_x, cursor_y), logo_resized)
        return cursor_y + new_h + int(target_h * 0.024)
    except Exception:
        return cursor_y + int(target_h * 0.02)


def _draw_rera_strip(
    draw: ImageDraw.ImageDraw,
    project: ProjectData,
    target_w: int,
    target_h: int,
    bg_fill=(250, 248, 245, 255),
    text_color="#0F172A",
    disc_color="#475569",
    accent_line_color=(201, 162, 39, 210),
) -> None:
    """Draw the mandatory RERA + disclaimer footer strip (bottom ~8% of poster)."""
    bottom_strip_h = int(target_h * 0.078)
    strip_top = target_h - bottom_strip_h

    draw.rectangle([(0, strip_top), (target_w, target_h)], fill=bg_fill)
    draw.line([(0, strip_top), (target_w, strip_top)],
              fill=accent_line_color, width=max(1, int(target_h * 0.0015)))

    rera_text = f"RERA No: {project.rera_number}"
    r_font, rw, rh = _fit_text(
        draw, rera_text, "Inter",
        max_w=int(target_w * 0.88),
        max_h=int(bottom_strip_h * 0.38),
        initial_size=max(26, int(target_h * 0.026)),
        min_size=max(14, int(target_h * 0.016)),
    )
    rera_y = strip_top + int(bottom_strip_h * 0.12)
    draw.text(((target_w - rw) // 2, rera_y), rera_text, font=r_font, fill=text_color)

    disc_y = rera_y + rh + int(bottom_strip_h * 0.06)
    for d_line in [
        "*Price excludes car park, clubhouse, GST, stamp duty & registration. Prices subject to revision.",
        "Artist's impression. Travel times approximate. Terms & conditions apply.",
    ]:
        d_font, dw, dh = _fit_text(
            draw, d_line, "Inter",
            max_w=int(target_w * 0.88),
            max_h=int(bottom_strip_h * 0.22),
            initial_size=max(16, int(target_h * 0.013)),
            min_size=max(12, int(target_h * 0.011)),
        )
        draw.text(((target_w - dw) // 2, disc_y), d_line, font=d_font, fill=disc_color)
        disc_y += dh + int(bottom_strip_h * 0.03)


def _apply_draft_watermark(img: Image.Image, width: int, height: int) -> Image.Image:
    wm_layer = Image.new("RGBA", (width, height), (0, 0, 0, 0))
    wm_draw = ImageDraw.Draw(wm_layer)
    text = "DRAFT – NOT FOR PUBLICATION"
    wm_font = _get_font("Inter", int(height * 0.065))
    bbox = wm_draw.textbbox((0, 0), text, font=wm_font)
    tw, th = bbox[2] - bbox[0], bbox[3] - bbox[1]
    txt_img = Image.new("RGBA", (tw + 40, th + 40), (0, 0, 0, 0))
    txt_draw = ImageDraw.Draw(txt_img)
    txt_draw.text((20, 20), text, font=wm_font, fill=(239, 68, 68, 90))
    rotated = txt_img.rotate(35, expand=True, resample=Image.BICUBIC)
    wm_layer.paste(rotated, ((width - rotated.width) // 2, (height - rotated.height) // 2), rotated)
    return Image.alpha_composite(img, wm_layer)


def _finalise(
    canvas: Image.Image,
    overlay: Image.Image,
    project: ProjectData,
    output_path,
) -> Image.Image:
    result = Image.alpha_composite(canvas, overlay)
    # Draft watermark disabled per user preference
    final = result.convert("RGB")
    if output_path:
        p = Path(output_path)
        p.parent.mkdir(parents=True, exist_ok=True)
        final.save(p, format="PNG")
    return final


# ─────────────────────────────────────────────────────────────────────────────
# Template 1 – Luxury Navy (original, preserved here for completeness)
# ─────────────────────────────────────────────────────────────────────────────

def _render_luxury_navy(
    background_path, project: ProjectData, logo_path, headline, festival, size_id, output_path
) -> Image.Image:
    """Original deep-navy glassmorphic card template."""
    # Import and delegate to original layout.py so behaviour is identical
    try:
        from poster_generator.layout import render_poster
    except ImportError:
        from layout import render_poster  # type: ignore
    return render_poster(
        background_path=background_path,
        project=project,
        logo_path=logo_path,
        headline=headline,
        festival=festival,
        size_id=size_id,
        output_path=output_path,
    )


# ─────────────────────────────────────────────────────────────────────────────
# Template 2 – Minimal White
# ─────────────────────────────────────────────────────────────────────────────

def _render_minimal_white(
    background_path, project: ProjectData, logo_path, headline, festival, size_id, output_path
) -> Image.Image:
    """
    Minimal White Template
    ----------------------
    • Full-bleed photo background (top 65%)
    • Clean white bottom panel with black typography
    • Thin brand-colour top border on the panel
    • RERA strip matches the white panel aesthetic
    """
    sc = SIZES.get(size_id, SIZES["instagram_post"])
    W, H = sc["width"], sc["height"]

    canvas = _load_background(background_path, W, H)
    overlay = Image.new("RGBA", (W, H), (0, 0, 0, 0))
    draw = ImageDraw.Draw(overlay)

    # Subtle top gradient so logo stays readable
    top_h = int(H * 0.28)
    for y in range(top_h):
        alpha = int(200 * ((1.0 - y / top_h) ** 1.8))
        draw.line([(0, y), (W, y)], fill=(255, 255, 255, alpha))

    # Logo – top center on frosted white
    cursor_y = int(H * 0.038)
    cursor_y = _paste_logo(
        overlay, draw, logo_path, W, H,
        align="center",
        bg_fill=(255, 255, 255, 240),
        border_color=(180, 180, 180, 180),
        cursor_y=cursor_y,
    )

    # Headline over photo
    if festival and festival != "None":
        greet = f"Happy {festival}!"
        g_font, gw, gh = _fit_text(draw, greet, project.brand.heading_font,
                                    max_w=int(W * 0.85), max_h=int(H * 0.035),
                                    initial_size=int(H * 0.025))
        draw.text(((W - gw) // 2 + 1, cursor_y + 1), greet, font=g_font, fill=(0, 0, 0, 160))
        draw.text(((W - gw) // 2, cursor_y), greet, font=g_font, fill=(255, 255, 255, 230))
        cursor_y += gh + int(H * 0.010)

    if headline:
        words = headline.split()
        lines = []
        if len(words) > 4 and len(headline) > 26:
            mid = len(words) // 2
            lines = [" ".join(words[:mid]), " ".join(words[mid:])]
        else:
            lines = [headline]
        for line in lines:
            h_font, hw, hh = _fit_text(draw, line, project.brand.heading_font,
                                        max_w=int(W * 0.88), max_h=int(H * 0.048),
                                        initial_size=int(H * 0.036))
            hx = (W - hw) // 2
            draw.text((hx + 2, cursor_y + 2), line, font=h_font, fill=(0, 0, 0, 190))
            draw.text((hx, cursor_y), line, font=h_font, fill=(255, 255, 255, 245))
            cursor_y += hh + int(H * 0.007)

    # White bottom panel
    rera_h = int(H * 0.078)
    panel_h = int(H * 0.33)
    panel_top = H - rera_h - panel_h

    # Parse brand primary for accent line
    try:
        accent_rgb = ImageColor.getrgb(project.brand.primary_colour)
    except Exception:
        accent_rgb = (31, 42, 68)

    draw.rectangle([(0, panel_top), (W, H - rera_h)], fill=(255, 255, 255, 252))
    # Thin brand-colour accent line at top of panel
    draw.line([(0, panel_top), (W, panel_top)],
              fill=(*accent_rgb, 255), width=max(3, int(H * 0.004)))

    # Panel content – dark ink on white
    TEXT_DARK = "#111827"
    TEXT_MID  = "#374151"
    TEXT_ACC  = project.brand.primary_colour  # brand colour for price

    py = panel_top + int(panel_h * 0.07)
    cx = W // 2

    # Project name
    pname_font, pnw, pnh = _fit_text(draw, project.name.upper(), project.brand.heading_font,
                                      max_w=int(W * 0.90), max_h=int(panel_h * 0.17),
                                      initial_size=int(panel_h * 0.135))
    draw.text((cx - pnw // 2, py), project.name.upper(), font=pname_font, fill=TEXT_DARK)
    py += pnh + int(panel_h * 0.025)

    # Promoter (only if specified in JSON)
    prom_str = getattr(project, "promoter", "").strip()
    if prom_str and prom_str.lower() != "promoter":
        prom_font, pmw, pmh = _fit_text(draw, f"by {prom_str}", project.brand.body_font,
                                         max_w=int(W * 0.85), max_h=int(panel_h * 0.09),
                                         initial_size=int(panel_h * 0.07))
        draw.text((cx - pmw // 2, py), f"by {prom_str}", font=prom_font, fill=TEXT_MID)
        py += pmh + int(panel_h * 0.03)

    # Thin divider
    dw = int(W * 0.40)
    draw.line([(cx - dw // 2, py), (cx + dw // 2, py)], fill=(*accent_rgb, 160), width=2)
    py += int(panel_h * 0.035)

    # Price + units (only if provided in JSON)
    has_units = bool(getattr(project, "available_units", []))
    has_price = bool(getattr(project, "lowest_price_inr", None) and "Request" not in getattr(project, "formatted_lowest_price", ""))
    offer_parts = []
    if has_units and project.formatted_units_summary:
        offer_parts.append(f"{project.formatted_units_summary} Homes")
    if has_price:
        offer_parts.append(f"from {project.formatted_lowest_price}*")

    if offer_parts:
        offer = " ".join(offer_parts)
        off_font, ofw, ofh = _fit_text(draw, offer, project.brand.heading_font,
                                        max_w=int(W * 0.90), max_h=int(panel_h * 0.13),
                                        initial_size=int(panel_h * 0.105))
        draw.text((cx - ofw // 2, py), offer, font=off_font, fill=TEXT_ACC)
        py += ofh + int(panel_h * 0.025)

    # Location + travel (only if provided in JSON)
    loc_parts = [x for x in [getattr(project, "marketing_name", ""), getattr(project, "city", "")] if x]
    travel_line = "   •   ".join(loc_parts + list(getattr(project, "travel_times", [])[:2]))
    if travel_line.strip():
        t_font, tw, th = _fit_text(draw, travel_line, project.brand.body_font,
                                    max_w=int(W * 0.90), max_h=int(panel_h * 0.09),
                                    initial_size=int(panel_h * 0.068))
        draw.text((cx - tw // 2, py), travel_line, font=t_font, fill=TEXT_MID)
        py += th + int(panel_h * 0.028)

    # Site visit + phone (only if real values provided)
    site_visits = getattr(project, "site_visits", None)
    sv_text = getattr(site_visits, "formatted_text", "") if site_visits else ""
    if sv_text and is_valid_content(sv_text):
        sv_font, svw, svh = _fit_text(draw, sv_text,
                                       project.brand.body_font,
                                       max_w=int(W * 0.90), max_h=int(panel_h * 0.09),
                                       initial_size=int(panel_h * 0.068))
        draw.text((cx - svw // 2, py), sv_text,
                  font=sv_font, fill=TEXT_MID)
        py += svh + int(panel_h * 0.022)

    phone_val = getattr(project, "marketing_phone", "")
    if phone_val and is_valid_content(phone_val):
        ph_text = f"Call: {phone_val}"
        ph_font, phw, _ = _fit_text(draw, ph_text, project.brand.body_font,
                                     max_w=int(W * 0.90), max_h=int(panel_h * 0.09),
                                     initial_size=int(panel_h * 0.068))
        draw.text((cx - phw // 2, py), ph_text, font=ph_font, fill=TEXT_ACC)

    # RERA strip – white background with dark text
    _draw_rera_strip(draw, project, W, H,
                     bg_fill=(248, 248, 248, 255),
                     text_color="#0F172A",
                     disc_color="#4B5563",
                     accent_line_color=(*accent_rgb, 200))

    return _finalise(canvas, overlay, project, output_path)


# ─────────────────────────────────────────────────────────────────────────────
# Template 3 – Cinematic Dark
# ─────────────────────────────────────────────────────────────────────────────

def _render_cinematic(
    background_path, project: ProjectData, logo_path, headline, festival, size_id, output_path
) -> Image.Image:
    """
    Cinematic Dark Template
    -----------------------
    • Full-bleed photo with a deep dark vignette covering the entire canvas
    • Large centred festival headline dominates the upper half
    • Thin horizontal frosted-glass info bar in the lower third
    • Cream RERA strip at the bottom
    """
    sc = SIZES.get(size_id, SIZES["instagram_post"])
    W, H = sc["width"], sc["height"]

    canvas = _load_background(background_path, W, H)
    overlay = Image.new("RGBA", (W, H), (0, 0, 0, 0))
    draw = ImageDraw.Draw(overlay)

    # Full canvas dark cinematic vignette
    for y in range(H):
        t = y / H
        # Dark at top and bottom, lighter in middle
        alpha = int(200 * (1 - math.sin(math.pi * t) ** 1.4))
        draw.line([(0, y), (W, y)], fill=(5, 8, 18, alpha))

    # Logo – top left, smaller
    cursor_y = int(H * 0.035)
    cursor_y = _paste_logo(
        overlay, draw, logo_path, W, H,
        align="left",
        bg_fill=(10, 10, 20, 210),
        border_color=(201, 162, 39, 160),
        cursor_y=cursor_y,
    )

    # Big centred headline (upper 40% of poster)
    if festival and festival != "None":
        greet = f"-- {festival.upper()} --"
        g_font, gw, gh = _fit_text(draw, greet, "Inter",
                                    max_w=int(W * 0.80), max_h=int(H * 0.04),
                                    initial_size=int(H * 0.030))
        gx = (W - gw) // 2
        draw.text((gx, cursor_y), greet, font=g_font, fill=(201, 162, 39, 200))
        cursor_y += gh + int(H * 0.018)

    if headline:
        words = headline.split()
        lines = []
        if len(words) > 3 and len(headline) > 22:
            mid = len(words) // 2
            lines = [" ".join(words[:mid]), " ".join(words[mid:])]
        else:
            lines = [headline]

        for line in lines:
            h_font, hw, hh = _fit_text(draw, line, project.brand.heading_font,
                                        max_w=int(W * 0.88), max_h=int(H * 0.070),
                                        initial_size=int(H * 0.058))
            hx = (W - hw) // 2
            # Cinematic glow effect: layered shadows
            for dx, dy, a in [(3, 3, 120), (1, 1, 60)]:
                draw.text((hx + dx, cursor_y + dy), line, font=h_font, fill=(0, 0, 0, a))
            draw.text((hx, cursor_y), line, font=h_font, fill="#FFFFFF")
            cursor_y += hh + int(H * 0.006)

    # Thin frosted-glass info bar (lower third)
    bar_h = int(H * 0.22)
    bar_top = H - int(H * 0.078) - bar_h - int(H * 0.01)

    draw.rectangle([(0, bar_top), (W, bar_top + bar_h)], fill=(5, 8, 18, 200))
    # Thin gold accent lines
    draw.line([(0, bar_top), (W, bar_top)],
              fill=(201, 162, 39, 180), width=max(2, int(H * 0.002)))
    draw.line([(0, bar_top + bar_h), (W, bar_top + bar_h)],
              fill=(201, 162, 39, 100), width=1)

    by = bar_top + int(bar_h * 0.07)
    cx = W // 2

    # Project name
    pname_font, pnw, pnh = _fit_text(draw, project.name.upper(), project.brand.heading_font,
                                      max_w=int(W * 0.88), max_h=int(bar_h * 0.22),
                                      initial_size=int(bar_h * 0.195))
    draw.text((cx - pnw // 2, by), project.name.upper(), font=pname_font, fill="#FFFFFF")
    by += pnh + int(bar_h * 0.04)

    # Price offer (only if provided in JSON)
    has_units = bool(getattr(project, "available_units", []))
    has_price = bool(getattr(project, "lowest_price_inr", None) and "Request" not in getattr(project, "formatted_lowest_price", ""))
    offer_parts = []
    if has_units and project.formatted_units_summary:
        offer_parts.append(project.formatted_units_summary)
    if has_price:
        offer_parts.append(f"from {project.formatted_lowest_price}*")

    if offer_parts:
        offer = "   •   ".join(offer_parts)
        off_font, ofw, ofh = _fit_text(draw, offer, project.brand.body_font,
                                        max_w=int(W * 0.88), max_h=int(bar_h * 0.17),
                                        initial_size=int(bar_h * 0.145))
        draw.text((cx - ofw // 2, by), offer, font=off_font, fill="#FBBF24")
        by += ofh + int(bar_h * 0.035)

    # Location line (only if provided in JSON)
    loc_parts = [x for x in [getattr(project, "marketing_name", ""), getattr(project, "city", "")] if x]
    travel_line = "   •   ".join(loc_parts + list(getattr(project, "travel_times", [])[:2]))
    if travel_line.strip():
        t_font, tw, th = _fit_text(draw, travel_line, project.brand.body_font,
                                    max_w=int(W * 0.90), max_h=int(bar_h * 0.14),
                                    initial_size=int(bar_h * 0.115))
        draw.text((cx - tw // 2, by), travel_line, font=t_font, fill="#CBD5E1")
        by += th + int(bar_h * 0.03)

    # Phone (only if real number provided)
    phone_val = getattr(project, "marketing_phone", "")
    if phone_val and is_valid_content(phone_val):
        ph_text = f"Call: {phone_val}"
        ph_font, phw, _ = _fit_text(draw, ph_text, project.brand.body_font,
                                     max_w=int(W * 0.80), max_h=int(bar_h * 0.14),
                                     initial_size=int(bar_h * 0.115))
        draw.text((cx - phw // 2, by), ph_text, font=ph_font, fill="#94A3B8")

    # RERA strip – dark variant
    _draw_rera_strip(draw, project, W, H,
                     bg_fill=(10, 14, 28, 255),
                     text_color="#E2E8F0",
                     disc_color="#64748B",
                     accent_line_color=(201, 162, 39, 200))

    return _finalise(canvas, overlay, project, output_path)


# ─────────────────────────────────────────────────────────────────────────────
# Template 4 – Split Panel
# ─────────────────────────────────────────────────────────────────────────────

def _render_split_panel(
    background_path, project: ProjectData, logo_path, headline, festival, size_id, output_path
) -> Image.Image:
    """
    Split Panel Template
    --------------------
    • Photo on the right ~60% of the poster
    • Brand-colour vertical panel on the left ~40% with rotated project name
    • Info grid (price, location, phone) in the left panel
    • RERA strip at the bottom spanning full width
    Note: Works best for Instagram Post (4:5). Story format adjusts proportions.
    """
    sc = SIZES.get(size_id, SIZES["instagram_post"])
    W, H = sc["width"], sc["height"]

    is_story = (H > W)
    # For story (9:16) use top/bottom split instead of left/right
    split_horizontal = is_story

    canvas = _load_background(background_path, W, H)
    overlay = Image.new("RGBA", (W, H), (0, 0, 0, 0))
    draw = ImageDraw.Draw(overlay)

    try:
        prim_rgb = ImageColor.getrgb(project.brand.primary_colour)
    except Exception:
        prim_rgb = (31, 42, 68)
    try:
        sec_rgb = ImageColor.getrgb(project.brand.secondary_colour)
    except Exception:
        sec_rgb = (201, 162, 39)

    rera_h = int(H * 0.078)

    if not split_horizontal:
        # ── Left/Right Split (portrait 4:5) ──────────────────────────────
        panel_w = int(W * 0.42)

        # Left brand panel
        draw.rectangle([(0, 0), (panel_w, H - rera_h)], fill=(*prim_rgb, 240))

        # Decorative diagonal slash at right edge of panel
        slash_w = int(W * 0.06)
        points = [(panel_w - slash_w, 0), (panel_w, 0),
                  (panel_w, H - rera_h), (panel_w - slash_w, H - rera_h)]
        draw.polygon(points, fill=(*prim_rgb, 240))

        # Right photo – darken slightly for readability
        for y in range(H - rera_h):
            draw.line([(panel_w, y), (W, y)], fill=(0, 0, 0, 60))

        # Gold vertical accent stripe
        stripe_x = panel_w - int(W * 0.012)
        draw.rectangle([(stripe_x, 0), (stripe_x + max(3, int(W * 0.005)), H - rera_h)],
                       fill=(*sec_rgb, 200))

        # Logo top-left inside panel
        lx = int(panel_w * 0.12)
        ly = int(H * 0.04)
        if logo_path and Path(logo_path).exists():
            try:
                logo_img = Image.open(logo_path).convert("RGBA")
                bbox = logo_img.getbbox()
                if bbox:
                    logo_img = logo_img.crop(bbox)
                max_lw = int(panel_w * 0.70)
                max_lh = int(H * 0.09)
                ratio = min(max_lw / logo_img.width, max_lh / logo_img.height)
                nw, nh = max(10, int(logo_img.width * ratio)), max(10, int(logo_img.height * ratio))
                logo_r = logo_img.resize((nw, nh), Image.LANCZOS)
                overlay.paste(logo_r, (lx, ly), logo_r)
                ly += nh + int(H * 0.025)
            except Exception:
                ly += int(H * 0.025)

        # Thin gold separator under logo
        draw.line([(lx, ly), (panel_w - lx, ly)], fill=(*sec_rgb, 180), width=2)
        ly += int(H * 0.025)

        # Project name (large, vertical centre)
        content_h = (H - rera_h) - ly - int(H * 0.05)
        avail_w = panel_w - 2 * lx

        pname_font, pnw, pnh = _fit_text(draw, project.name.upper(), project.brand.heading_font,
                                          max_w=avail_w, max_h=int(content_h * 0.18),
                                          initial_size=int(content_h * 0.15))
        draw.text((lx, ly), project.name.upper(), font=pname_font, fill="#FFFFFF")
        ly += pnh + int(H * 0.018)

        # Promoter (only if provided in JSON)
        prom_str = getattr(project, "promoter", "").strip()
        if prom_str and prom_str.lower() != "promoter":
            prom_font, pmw, pmh = _fit_text(draw, f"by {prom_str}", project.brand.body_font,
                                             max_w=avail_w, max_h=int(content_h * 0.09),
                                             initial_size=int(content_h * 0.07))
            draw.text((lx, ly), f"by {prom_str}", font=prom_font, fill="#94A3B8")
            ly += pmh + int(H * 0.02)

        # Offer (only if provided in JSON)
        has_units = bool(getattr(project, "available_units", []))
        has_price = bool(getattr(project, "lowest_price_inr", None) and "Request" not in getattr(project, "formatted_lowest_price", ""))
        offer_lines = []
        if has_units and project.formatted_units_summary:
            offer_lines.append(project.formatted_units_summary)
        if has_price:
            offer_lines.append(f"from {project.formatted_lowest_price}*")

        for line in offer_lines:
            off_font, ofw, ofh = _fit_text(draw, line, project.brand.heading_font,
                                            max_w=avail_w, max_h=int(content_h * 0.12),
                                            initial_size=int(content_h * 0.10))
            draw.text((lx, ly), line, font=off_font, fill="#FBBF24")
            ly += ofh + int(H * 0.01)
        if offer_lines:
            ly += int(H * 0.015)

        # Location + travel (each on its own line)
        for line in ([f"{getattr(project, 'marketing_name', '')}, {getattr(project, 'city', '')}"] if getattr(project, "marketing_name", "") else []) + list(getattr(project, "travel_times", [])[:2]):
            lf, lw, lh = _fit_text(draw, line, project.brand.body_font,
                                    max_w=avail_w, max_h=int(content_h * 0.075),
                                    initial_size=int(content_h * 0.060))
            draw.text((lx, ly), line, font=lf, fill="#CBD5E1")
            ly += lh + int(H * 0.012)

        # Site visit + phone near bottom (only if real number provided)
        phone_val = getattr(project, "marketing_phone", "")
        if phone_val and is_valid_content(phone_val):
            ph_text = f"Call: {phone_val}"
            ph_font, phw, phh = _fit_text(draw, ph_text, project.brand.body_font,
                                           max_w=avail_w, max_h=int(content_h * 0.075),
                                           initial_size=int(content_h * 0.060))
            draw.text((lx, H - rera_h - phh - int(H * 0.03)), ph_text,
                      font=ph_font, fill="#FBBF24")

        # Headline over photo (right side, top)
        if headline:
            words = headline.split()
            lines = []
            if len(words) > 3 and len(headline) > 22:
                mid = len(words) // 2
                lines = [" ".join(words[:mid]), " ".join(words[mid:])]
            else:
                lines = [headline]
            hy = int(H * 0.04)
            for line in lines:
                hf, hw, hh = _fit_text(draw, line, project.brand.heading_font,
                                        max_w=int((W - panel_w) * 0.85),
                                        max_h=int(H * 0.065),
                                        initial_size=int(H * 0.050))
                hx = panel_w + int((W - panel_w - hw) / 2)
                draw.text((hx + 2, hy + 2), line, font=hf, fill=(0, 0, 0, 160))
                draw.text((hx, hy), line, font=hf, fill="#FFFFFF")
                hy += hh + int(H * 0.007)

    else:
        # ── Top/Bottom Split (story 9:16) ─────────────────────────────────
        photo_h = int((H - rera_h) * 0.56)
        panel_top = photo_h

        # Dark photo overlay
        for y in range(photo_h):
            draw.line([(0, y), (W, y)], fill=(0, 0, 0, 70))

        # Headline over photo
        hy = int(H * 0.035)
        cursor_y = _paste_logo(overlay, draw, logo_path, W, H,
                               align="center",
                               bg_fill=(10, 10, 20, 210),
                               border_color=(201, 162, 39, 160),
                               cursor_y=hy)
        if festival and festival != "None":
            gf, gw_t, gh_t = _fit_text(draw, f"Happy {festival}!", project.brand.heading_font,
                                        max_w=int(W * 0.85), max_h=int(photo_h * 0.06),
                                        initial_size=int(photo_h * 0.045))
            draw.text(((W - gw_t) // 2, cursor_y), f"Happy {festival}!", font=gf, fill="#FFF8E7")
            cursor_y += gh_t + int(H * 0.01)

        if headline:
            words = headline.split()
            hlines = ([" ".join(words[:len(words) // 2]), " ".join(words[len(words) // 2:])]
                      if len(words) > 3 and len(headline) > 22 else [headline])
            for line in hlines:
                hf, hw_t, hh_t = _fit_text(draw, line, project.brand.heading_font,
                                            max_w=int(W * 0.88), max_h=int(photo_h * 0.09),
                                            initial_size=int(photo_h * 0.073))
                hx = (W - hw_t) // 2
                draw.text((hx + 2, cursor_y + 2), line, font=hf, fill=(0, 0, 0, 160))
                draw.text((hx, cursor_y), line, font=hf, fill="#FFFFFF")
                cursor_y += hh_t + int(H * 0.006)

        # Brand panel bottom
        draw.rectangle([(0, panel_top), (W, H - rera_h)], fill=(*prim_rgb, 245))
        draw.line([(0, panel_top), (W, panel_top)], fill=(*sec_rgb, 220),
                  width=max(3, int(H * 0.004)))

        bh = (H - rera_h) - panel_top
        by = panel_top + int(bh * 0.06)
        cx = W // 2
        avail_w = int(W * 0.88)

        pname_font, pnw, pnh = _fit_text(draw, project.name.upper(), project.brand.heading_font,
                                          max_w=avail_w, max_h=int(bh * 0.17),
                                          initial_size=int(bh * 0.14))
        draw.text((cx - pnw // 2, by), project.name.upper(), font=pname_font, fill="#FFFFFF")
        by += pnh + int(bh * 0.025)

        # Offer (only if provided in JSON)
        has_units = bool(getattr(project, "available_units", []))
        has_price = bool(getattr(project, "lowest_price_inr", None) and "Request" not in getattr(project, "formatted_lowest_price", ""))
        offer_parts = []
        if has_units and project.formatted_units_summary:
            offer_parts.append(project.formatted_units_summary)
        if has_price:
            offer_parts.append(f"from {project.formatted_lowest_price}*")

        if offer_parts:
            offer = "   •   ".join(offer_parts)
            off_font, ofw, ofh = _fit_text(draw, offer, project.brand.heading_font,
                                            max_w=avail_w, max_h=int(bh * 0.13),
                                            initial_size=int(bh * 0.105))
            draw.text((cx - ofw // 2, by), offer, font=off_font, fill="#FBBF24")
            by += ofh + int(bh * 0.025)

        # Location line (only if provided in JSON)
        loc_parts = [x for x in [getattr(project, "marketing_name", ""), getattr(project, "city", "")] if x]
        travel_line = "   •   ".join(loc_parts + list(getattr(project, "travel_times", [])[:2]))
        if travel_line.strip():
            t_font, tw_t, th_t = _fit_text(draw, travel_line, project.brand.body_font,
                                            max_w=avail_w, max_h=int(bh * 0.09),
                                            initial_size=int(bh * 0.072))
            draw.text((cx - tw_t // 2, by), travel_line, font=t_font, fill="#CBD5E1")
            by += th_t + int(bh * 0.025)

        phone_val = getattr(project, "marketing_phone", "")
        if phone_val and is_valid_content(phone_val):
            ph_text = f"Call: {phone_val}"
            ph_font, phw, _ = _fit_text(draw, ph_text, project.brand.body_font,
                                         max_w=avail_w, max_h=int(bh * 0.09),
                                         initial_size=int(bh * 0.072))
            draw.text((cx - phw // 2, by), ph_text, font=ph_font, fill="#FBBF24")

    # RERA strip
    _draw_rera_strip(draw, project, W, H,
                     bg_fill=(250, 248, 245, 255),
                     text_color="#0F172A",
                     disc_color="#475569",
                     accent_line_color=(*sec_rgb, 200))

    return _finalise(canvas, overlay, project, output_path)


# ─────────────────────────────────────────────────────────────────────────────
# Template 5 – Executive Editorial (Camp Capitol / Luxury Developer Style)
# ─────────────────────────────────────────────────────────────────────────────

def _make_qr_badge(size: int = 64) -> Image.Image:
    """Procedurally generates a crisp QR-code verification badge with corner finder marks."""
    img = Image.new("RGBA", (size, size), (255, 255, 255, 255))
    draw = ImageDraw.Draw(img)
    draw.rectangle([(0, 0), (size - 1, size - 1)], outline=(30, 30, 30, 255), width=2)

    def finder(x: int, y: int, s: int):
        draw.rectangle([(x, y), (x + s, y + s)], fill=(20, 20, 20, 255))
        draw.rectangle([(x + 3, y + 3), (x + s - 3, y + s - 3)], fill=(255, 255, 255, 255))
        draw.rectangle([(x + 6, y + 6), (x + s - 6, y + s - 6)], fill=(20, 20, 20, 255))

    finder(4, 4, 18)
    finder(size - 22, 4, 18)
    finder(4, size - 22, 18)

    import random
    rng = random.Random(108)
    for px in range(24, size - 24, 4):
        for py in range(4, size - 4, 4):
            if rng.random() > 0.42:
                draw.rectangle([(px, py), (px + 2, py + 2)], fill=(25, 25, 25, 255))
    return img


def _make_phone_icon(size: int = 54) -> Image.Image:
    """Renders a smooth, anti-aliased luxury phone icon."""
    scale = 4
    S = size * scale
    big = Image.new("RGBA", (S, S), (0, 0, 0, 0))
    d = ImageDraw.Draw(big)

    d.ellipse([(int(S * 0.06), int(S * 0.06)), (int(S * 0.94), int(S * 0.94))],
              outline=(255, 255, 255, 240), width=int(S * 0.06))

    d.rounded_rectangle([(int(S * 0.56), int(S * 0.24)), (int(S * 0.74), int(S * 0.38))],
                        radius=int(S * 0.06), fill=(255, 255, 255, 240))
    d.rounded_rectangle([(int(S * 0.24), int(S * 0.56)), (int(S * 0.38), int(S * 0.74))],
                        radius=int(S * 0.06), fill=(255, 255, 255, 240))
    d.arc([(int(S * 0.28), int(S * 0.28)), (int(S * 0.82), int(S * 0.82))],
          start=135, end=270, fill=(255, 255, 255, 240), width=int(S * 0.12))

    return big.resize((size, size), Image.LANCZOS)


def _render_executive_editorial(
    background_path, project: ProjectData, logo_path, headline, festival, size_id, output_path
) -> Image.Image:
    """
    Executive Editorial Template
    ----------------------------
    Inspired by high-end commercial & luxury residential print / social campaigns:
      1. Top Header: Charcoal background, RERA & QR badge top-right, centered brand logo,
         spaced out location tracking.
      2. Middle Hero: Framed high-resolution property render (left) +
         bold typographic statement & dual-spec metric box (right).
      3. Standout Ribbon: Solid warm bronze/gold ribbon with prominent phone CTA.
      4. Developer Footer: Dual-column partner credentials with vertical divider & legal disclaimers.
    """
    sc = SIZES.get(size_id, SIZES["story"])
    W, H = sc["width"], sc["height"]

    BG_DARK = (26, 23, 22, 255)         # Charcoal matte #1A1716
    BRONZE_ACCENT = (142, 116, 88, 255) # Refined warm bronze #8E7458
    BRONZE_CTA = (133, 108, 80, 255)    # Solid CTA bronze #856C50
    TEXT_BRONZE = "#BA9E7E"
    TEXT_MUTED = "#9E948C"

    canvas = Image.new("RGBA", (W, H), BG_DARK)
    overlay = Image.new("RGBA", (W, H), (0, 0, 0, 0))
    draw = ImageDraw.Draw(overlay)

    is_story = (H > 1400)
    top_h = int(H * 0.22) if is_story else int(H * 0.20)
    hero_h = int(H * 0.44) if is_story else int(H * 0.45)
    cta_h = int(H * 0.088) if is_story else int(H * 0.098)
    footer_h = H - top_h - hero_h - cta_h

    # ── 1. HEADER SECTION ───────────────────────────────────────────
    # Top-right RERA + QR badge
    qr_size = max(44, int(H * 0.030))
    qr_img = _make_qr_badge(qr_size)
    qr_x = W - qr_size - int(W * 0.045)
    qr_y = int(H * 0.032)
    overlay.paste(qr_img, (qr_x, qr_y), qr_img)

    rf1 = _get_font("Inter", max(11, int(H * 0.009)))
    rf2 = _get_font("Inter", max(11, int(H * 0.009)))
    draw.text((qr_x - 12, qr_y + 2),
              "MAHARERA NO. :" if "MH" in project.rera_number else "RERA NO. :",
              font=rf1, fill=TEXT_MUTED, anchor="ra")

    rera_val = project.rera_number
    if len(rera_val) > 20:
        cut = len(rera_val) // 2
        draw.text((qr_x - 12, qr_y + 20), rera_val[:cut], font=rf2, fill="#FFFFFF", anchor="ra")
        draw.text((qr_x - 12, qr_y + 36), rera_val[cut:], font=rf2, fill="#FFFFFF", anchor="ra")
    else:
        draw.text((qr_x - 12, qr_y + 20), rera_val, font=rf2, fill="#FFFFFF", anchor="ra")

    # Center Logo & Project Identity
    cy = int(H * 0.035)
    if logo_path and Path(logo_path).exists():
        try:
            lim = Image.open(logo_path).convert("RGBA")
            bbox = lim.getbbox()
            if bbox:
                lim = lim.crop(bbox)
            max_lw = int(W * 0.22)
            max_lh = int(top_h * 0.38)
            r = min(max_lw / lim.width, max_lh / lim.height)
            nw, nh = max(10, int(lim.width * r)), max(10, int(lim.height * r))
            lim_r = lim.resize((nw, nh), Image.LANCZOS)
            overlay.paste(lim_r, ((W - nw) // 2, cy), lim_r)
            cy += nh + int(H * 0.014)
        except Exception:
            cy += int(H * 0.02)
    else:
        p_logo_font, pw, ph = _fit_text(draw, project.name.upper(), "PlayfairDisplay",
                                        int(W * 0.70), int(top_h * 0.28), int(top_h * 0.18))
        draw.text(((W - pw) // 2, cy), project.name.upper(), font=p_logo_font, fill="#FFFFFF")
        cy += ph + int(H * 0.020)

    sub_title = "PREMIUM COMMERCIAL SPACES AT" if "commercial" in project.name.lower() else "PREMIUM RESIDENCES AT"
    loc_clean = (getattr(project, "marketing_name", "") or getattr(project, "city", "") or "").upper()
    if loc_clean:
        st_font = _get_font("Inter", max(12, int(H * 0.012)))
        bbox = draw.textbbox((0, 0), sub_title, font=st_font)
        sw = bbox[2] - bbox[0]
        draw.text(((W - sw) // 2, cy), sub_title, font=st_font, fill=TEXT_MUTED)
        cy += (bbox[3] - bbox[1]) + int(H * 0.012)

        spaced_loc = "  ".join(loc_clean.replace(",", ""))
        loc_font, lw, lh = _fit_text(draw, spaced_loc, "Inter", int(W * 0.85), int(top_h * 0.22), int(H * 0.025))
        draw.text(((W - lw) // 2, cy), spaced_loc, font=loc_font, fill="#FFFFFF")

    # Bronze horizontal separator line
    draw.line([(0, top_h), (W, top_h)], fill=BRONZE_ACCENT, width=max(2, int(H * 0.002)))

    # ── 2. HERO MIDDLE SECTION ──────────────────────────────────────
    hero_top = top_h
    img_card_margin = int(W * 0.038)
    img_card_w = int(W * 0.46)
    img_card_h = hero_h - (2 * img_card_margin)

    if background_path and Path(background_path).exists():
        raw_bg = Image.open(background_path).convert("RGBA")
        target_card_ratio = img_card_w / img_card_h
        bg_ratio = raw_bg.width / raw_bg.height
        if bg_ratio > target_card_ratio:
            crop_w = int(raw_bg.height * target_card_ratio)
            left = (raw_bg.width - crop_w) // 2
            card_img = raw_bg.crop((left, 0, left + crop_w, raw_bg.height))
        else:
            crop_h = int(raw_bg.width / target_card_ratio)
            top = (raw_bg.height - crop_h) // 2
            card_img = raw_bg.crop((0, top, raw_bg.width, top + crop_h))
        card_img = card_img.resize((img_card_w, img_card_h), Image.LANCZOS)

        mask = Image.new("L", (img_card_w, img_card_h), 0)
        mask_draw = ImageDraw.Draw(mask)
        mask_draw.rounded_rectangle([(0, 0), (img_card_w, img_card_h)],
                                     radius=int(img_card_w * 0.04), fill=255)
        overlay.paste(card_img, (img_card_margin, hero_top + img_card_margin), mask)
        draw.rounded_rectangle(
            [(img_card_margin, hero_top + img_card_margin),
             (img_card_margin + img_card_w, hero_top + img_card_margin + img_card_h)],
            radius=int(img_card_w * 0.04),
            outline=BRONZE_ACCENT,
            width=2,
        )

    rx = img_card_margin + img_card_w + int(W * 0.04)
    rw = W - rx - int(W * 0.04)
    ry = hero_top + int(hero_h * 0.08)

    top_label = f"THE {festival.upper()}" if festival and festival != "None" else "THE EXCLUSIVE"
    tl_font = _get_font("Inter", max(12, int(H * 0.012)))
    draw.text((rx, ry), top_label, font=tl_font, fill=TEXT_MUTED)
    ry += int(H * 0.024)

    # Giant Bold Typography
    big_word = "BARON" if "commercial" in sub_title.lower() else "LIVING"
    bw_font, bww, bwh = _fit_text(draw, big_word, "Inter", rw, int(hero_h * 0.22), int(hero_h * 0.17))
    draw.text((rx, ry), big_word, font=bw_font, fill="#7D6752")

    script_text = "Lead from here." if "commercial" in sub_title.lower() else "Live beyond."
    sc_font = _get_font("PlayfairDisplay", max(16, int(H * 0.017)))
    draw.text((rx + int(bww * 0.52), ry + int(bwh * 0.42)), script_text, font=sc_font, fill="#FFFFFF")
    ry += bwh + int(hero_h * 0.09)

    # Value Proposition Section (only if units provided)
    has_units = bool(getattr(project, "available_units", []))
    if has_units and project.formatted_units_summary:
        vp_title = f"{project.formatted_units_summary.upper()} HOMES"
        vp_font, vpw, vph = _fit_text(draw, vp_title, "Inter", rw, int(hero_h * 0.09), int(H * 0.015))
        draw.text((rx, ry), vp_title, font=vp_font, fill=TEXT_BRONZE)
        ry += vph + int(hero_h * 0.035)

    # Stat box (dynamically renders carpet sqft and/or price ONLY if present in JSON)
    raw = getattr(project, "raw_data", {})
    units_raw = raw.get("units", [])
    sqft_candidates = [
        u.get("carpet_sqft") or u.get("carpet_area") or u.get("sqft") or u.get("area_sqft")
        for u in units_raw
        if isinstance(u, dict) and (u.get("carpet_sqft") or u.get("carpet_area") or u.get("sqft") or u.get("area_sqft"))
    ]
    has_sqft = bool(sqft_candidates)
    has_price = bool(getattr(project, "lowest_price_inr", None) and "Request" not in getattr(project, "formatted_lowest_price", ""))

    if has_sqft and has_price:
        col_w = rw // 2
        pipe_x = rx + col_w
        stat_left_val = f"{int(min(sqft_candidates)):,}+"

        # Left: SQ.FT
        v1_font, w1, h1 = _fit_text(draw, stat_left_val, "Inter", col_w - 12, int(hero_h * 0.11), int(H * 0.022))
        draw.text((rx, ry), stat_left_val, font=v1_font, fill="#FFFFFF")
        l1_font = _get_font("Inter", max(10, int(H * 0.009)))
        draw.text((rx, ry + h1 + 6), "SQ.FT", font=l1_font, fill=TEXT_MUTED)

        # Divider Pipe
        draw.line([(pipe_x, ry - 2), (pipe_x, ry + h1 + 24)], fill=BRONZE_ACCENT, width=2)

        # Right: Price
        stat_right_val = project.formatted_lowest_price
        v2_font, w2, h2 = _fit_text(draw, stat_right_val, "Inter", col_w - 12, int(hero_h * 0.11), int(H * 0.022))
        draw.text((pipe_x + 14, ry), stat_right_val, font=v2_font, fill=TEXT_BRONZE)
        l2_font = _get_font("Inter", max(10, int(H * 0.009)))
        draw.text((pipe_x + 14, ry + h2 + 6), "ALL IN. ONWARDS", font=l2_font, fill=TEXT_MUTED)
    elif has_price:
        stat_right_val = project.formatted_lowest_price
        v2_font, w2, h2 = _fit_text(draw, stat_right_val, "Inter", rw - 12, int(hero_h * 0.11), int(H * 0.022))
        draw.text((rx, ry), stat_right_val, font=v2_font, fill=TEXT_BRONZE)
        l2_font = _get_font("Inter", max(10, int(H * 0.009)))
        draw.text((rx, ry + h2 + 6), "STARTING PRICE (ONWARDS)", font=l2_font, fill=TEXT_MUTED)
    elif has_sqft:
        stat_left_val = f"{int(min(sqft_candidates)):,}+"
        v1_font, w1, h1 = _fit_text(draw, stat_left_val, "Inter", rw - 12, int(hero_h * 0.11), int(H * 0.022))
        draw.text((rx, ry), stat_left_val, font=v1_font, fill="#FFFFFF")
        l1_font = _get_font("Inter", max(10, int(H * 0.009)))
        draw.text((rx, ry + h1 + 6), "SQ.FT CARPET AREA", font=l1_font, fill=TEXT_MUTED)

    # ── 3. SOLID BRONZE CTA RIBBON (only shows contact info if present in JSON) ──
    cta_top = top_h + hero_h
    phone_val = getattr(project, "marketing_phone", "").strip()
    site_visits = getattr(project, "site_visits", None)
    sv_text = getattr(site_visits, "formatted_text", "").strip() if site_visits else ""

    has_real_phone = bool(phone_val and is_valid_content(phone_val))
    has_real_sv = bool(sv_text and is_valid_content(sv_text))

    if has_real_phone or has_real_sv:
        draw.rectangle([(0, cta_top), (W, cta_top + cta_h)], fill=BRONZE_CTA)
        if has_real_phone:
            ph_icon_size = int(cta_h * 0.48)
            ph_icon = _make_phone_icon(ph_icon_size)
            ph_num_font, nw, nh = _fit_text(draw, phone_val, "Inter", int(W * 0.72), int(cta_h * 0.65), int(cta_h * 0.50))
            total_cta_w = ph_icon_size + 18 + nw
            cta_start_x = (W - total_cta_w) // 2
            overlay.paste(ph_icon, (cta_start_x, cta_top + (cta_h - ph_icon_size) // 2), ph_icon)
            draw.text((cta_start_x + ph_icon_size + 18, cta_top + (cta_h - nh) // 2), phone_val, font=ph_num_font, fill="#FFFFFF")
        else:
            sv_font, svw, svh = _fit_text(draw, sv_text, "Inter", int(W * 0.88), int(cta_h * 0.60), int(cta_h * 0.45))
            draw.text(((W - svw) // 2, cta_top + (cta_h - svh) // 2), sv_text, font=sv_font, fill="#FFFFFF")

    # ── 4. FOOTER & CREDENTIALS SECTION ─────────────────────────────
    foot_top = cta_top + cta_h
    fy = foot_top + int(footer_h * 0.20)
    promoter_val = getattr(project, "promoter", "").strip()
    partner_val = (raw.get("partner") or raw.get("in_venture_with") or "").strip()
    website_val = (raw.get("website") or raw.get("contacts", {}).get("website") or "").strip()

    if partner_val and promoter_val:
        # Split partner credentials
        mid_x = W // 2
        draw.line([(mid_x, fy - 6), (mid_x, fy + int(footer_h * 0.38))], fill=(65, 56, 52, 255), width=2)
        draw.text((mid_x - 30, fy), "IN VENTURE WITH", font=_get_font("Inter", max(10, int(H * 0.009))), fill=TEXT_MUTED, anchor="ra")
        partner_font, prw, prh = _fit_text(draw, partner_val, "Inter", int(W * 0.40), int(footer_h * 0.22), int(H * 0.016))
        draw.text((mid_x - 30, fy + 22), partner_val, font=partner_font, fill="#FFFFFF", anchor="ra")

        draw.text((mid_x + 30, fy), "A PROJECT BY", font=_get_font("Inter", max(10, int(H * 0.009))), fill=TEXT_MUTED)
        pname_f, pnw, pnh = _fit_text(draw, promoter_val, "Inter", int(W * 0.40), int(footer_h * 0.22), int(H * 0.016))
        draw.text((mid_x + 30, fy + 22), promoter_val, font=pname_f, fill="#FFFFFF")

        if website_val:
            draw.text((mid_x + 30, fy + 22 + pnh + 6), website_val, font=_get_font("Inter", max(10, int(H * 0.009))), fill=TEXT_BRONZE)
    elif promoter_val and promoter_val.lower() != "promoter":
        # Single centered promoter block
        draw.text((W // 2, fy), "A PROJECT BY", font=_get_font("Inter", max(10, int(H * 0.009))), fill=TEXT_MUTED, anchor="mm")
        pname_f, pnw, pnh = _fit_text(draw, promoter_val, "Inter", int(W * 0.80), int(footer_h * 0.22), int(H * 0.018))
        draw.text(((W - pnw) // 2, fy + 16), promoter_val, font=pname_f, fill="#FFFFFF")

        if website_val:
            draw.text((W // 2, fy + 16 + pnh + 8), website_val, font=_get_font("Inter", max(10, int(H * 0.009))), fill=TEXT_BRONZE, anchor="mm")

    # Legal
    disc_y = H - int(H * 0.038)
    disc_text = "*T&C apply. Price excludes registration & stamp duty. Artist's impression only."
    df = _get_font("Inter", max(9, int(H * 0.008)))
    draw.text((W // 2, disc_y), disc_text, font=df, fill="#6B625B", anchor="mm")

    return _finalise(canvas, overlay, project, output_path)


# ─────────────────────────────────────────────────────────────────────────────
# Template 6 – Reel Overlay
# ─────────────────────────────────────────────────────────────────────────────

def _weighted_font(font_name: str, size: int, weight: str = "Regular") -> ImageFont.FreeTypeFont:
    """Like _get_font, but selects a named weight on variable fonts (Inter / Playfair)."""
    font = _get_font(font_name, size)
    try:
        font.set_variation_by_name(weight)
    except Exception:
        pass
    return font


def _fit_weighted(draw, text, font_name, weight, max_w, initial_size, min_size=12):
    size = initial_size
    while size > min_size:
        font = _weighted_font(font_name, size, weight)
        if draw.textlength(text, font=font) <= max_w:
            return font
        size -= 1
    return _weighted_font(font_name, min_size, weight)


def _shadow_text(draw, sdraw, xy, text, font, fill="#FFFFFF", offset=2, anchor=None):
    """Draw text on `draw`, and its silhouette on `sdraw` (a layer blurred later into a soft shadow)."""
    x, y = xy
    sdraw.text((x + offset, y + offset), text, font=font, fill=(0, 0, 0, 190), anchor=anchor)
    draw.text((x, y), text, font=font, fill=fill, anchor=anchor)


def _text_h(draw, text, font) -> int:
    bbox = draw.textbbox((0, 0), text, font=font)
    return bbox[3]


def _draw_pin(draw, x: int, y: int, size: int, fill="#FFFFFF") -> None:
    """Map-pin icon: circle head with a point below, hole punched in the middle."""
    r = size // 3
    cx = x + size // 2
    draw.ellipse([(cx - r, y), (cx + r, y + 2 * r)], fill=fill)
    draw.polygon([(cx - int(r * 0.85), y + int(r * 1.5)), (cx + int(r * 0.85), y + int(r * 1.5)), (cx, y + size)], fill=fill)
    hr = max(2, r // 3)
    draw.ellipse([(cx - hr, y + r - hr), (cx + hr, y + r + hr)], fill=(0, 0, 0, 0))


def _contrast_with_white(rgb) -> float:
    def lin(c):
        c /= 255
        return c / 12.92 if c <= 0.03928 else ((c + 0.055) / 1.055) ** 2.4
    lum = 0.2126 * lin(rgb[0]) + 0.7152 * lin(rgb[1]) + 0.0722 * lin(rgb[2])
    return 1.05 / (lum + 0.05)


def _photo_palette(bg: Image.Image, fallback_rgb) -> dict:
    """
    Pick an accent that belongs to the photo (forest green on foliage, terracotta on a
    warm facade, teal on a pool) instead of a fixed brand colour that may clash with it.
    The dominant saturated hue of the lower 60% (the subject, not the sky) is rebuilt at a
    rich saturation and darkened until white text on it meets WCAG AA (>= 4.5:1).
    Returns {"accent", "deep", "tint"} RGB tuples.
    """
    import colorsys

    small = bg.convert("RGB").resize((64, 64))
    small = small.crop((0, int(64 * 0.4), 64, 64))
    bins = [0.0] * 12
    hue_sum = [0.0] * 12
    for r, g, b in small.getdata():
        h, s, v = colorsys.rgb_to_hsv(r / 255, g / 255, b / 255)
        if s < 0.22 or not (0.15 < v < 0.92):
            continue
        i = int(h * 12) % 12
        bins[i] += s * v
        hue_sum[i] += h * s * v

    total = sum(bins)
    if total < 6.0:  # mostly grey / white photo → keep the brand colour
        h, l, s = colorsys.rgb_to_hls(*(c / 255 for c in fallback_rgb))
    else:
        i = max(range(12), key=lambda k: bins[k])
        h = hue_sum[i] / bins[i]
        s = 0.55
        # Muddy orange/yellow (wood, sunsets) reads cheap when darkened; push it toward
        # terracotta / olive so it stays premium.
        if 0.06 < h < 0.14:
            h = 0.045
        elif 0.14 <= h < 0.19:
            h = 0.22
        l = 0.42

    def build(light):
        return tuple(int(c * 255) for c in colorsys.hls_to_rgb(h, light, s))

    accent = build(l)
    while _contrast_with_white(accent) < 4.8 and l > 0.12:
        l -= 0.02
        accent = build(l)
    return {
        "accent": accent,
        "deep": build(max(0.06, l * 0.32)),
        "tint": build(min(0.88, l + 0.42)),
    }


def _reel_highlights(project: ProjectData) -> list:
    """
    Up to 2 big-number stats (e.g. "53 Acres | 53 Amenities").
    Uses `highlights: [{"value": "53", "label": "Acres"}, ...]` from the project JSON when
    present; otherwise derives them from travel times ("5 min to Hoodi Metro").
    """
    raw = project.raw_data.get("highlights") or []
    stats = [
        (str(h.get("value", "")).strip(), str(h.get("label", "")).strip())
        for h in raw if isinstance(h, dict) and str(h.get("value", "")).strip()
    ]
    if not stats:
        # "5 min to Hoodi Metro" -> ("5", "min to Hoodi Metro")
        for t in getattr(project, "travel_times", []) or []:
            num, _, rest = t.strip().partition(" ")
            if num.replace(".", "", 1).isdigit() and rest:
                stats.append((num, rest))
    return stats[:2]


def _reel_size_line(project: ProjectData) -> Optional[Tuple[str, str]]:
    """("Carpet area starting", "1,100 Sq. Ft.") from the smallest available unit, if any."""
    sizes = []
    for u in project.raw_data.get("units", []) or []:
        if not isinstance(u, dict) or str(u.get("status", "available")).lower() != "available":
            continue
        sqft = u.get("plot_sqft") or u.get("carpet_sqft") or u.get("sqft")
        if isinstance(sqft, (int, float)) and sqft > 0:
            sizes.append(sqft)
    if not sizes:
        return None
    label = project.raw_data.get("size_label") or (
        "Plot sizes starting"
        if any(isinstance(u, dict) and u.get("plot_sqft") for u in project.raw_data.get("units", []))
        else "Carpet area starting"
    )
    return label, f"{int(min(sizes)):,} Sq. Ft."


def _apply_scrims(canvas: Image.Image, boxes) -> Image.Image:
    """
    Darken the photo softly behind text that sits low on the poster (below the top fade),
    so white type stays readable on bright facades or sky. The darker the area already
    is, the lighter the scrim, so dark foliage keeps its look.
    """
    if not boxes:
        return canvas
    from PIL import ImageStat
    W, H = canvas.size
    layer = Image.new("RGBA", (W, H), (0, 0, 0, 0))
    ldraw = ImageDraw.Draw(layer)
    for box in boxes:
        box = (max(0, box[0]), max(0, box[1]), min(W, box[2]), min(H, box[3]))
        lum = ImageStat.Stat(canvas.crop(box).convert("L")).mean[0] / 255
        alpha = int(max(70, min(190, (lum - 0.15) * 330)))
        ldraw.rounded_rectangle(box, radius=int(H * 0.03), fill=(0, 0, 0, alpha))
    layer = layer.filter(ImageFilter.GaussianBlur(int(H * 0.018)))
    return Image.alpha_composite(canvas, layer)


# Reel Overlay type system: one classic serif for every number and name, one clean sans
# for every label and sentence, three weights in total, so the poster reads as one family.
SERIF = "Cormorant Garamond"   # project name, prices, sizes, big numbers, greeting
SANS = "Inter"                 # labels, tagline, location, headline tag, CTA, notes
DISPLAY = "SemiBold"           # every serif line
BODY = "Regular"               # every supporting sans line
EMPHASIS = "SemiBold"          # sans lines that must pop: headline tag, CTA, stat labels


def _render_reel_overlay(
    background_path, project: ProjectData, logo_path, headline, festival, size_id, output_path
) -> Image.Image:
    """
    Reel Overlay Template
    ---------------------
    • Full-bleed photo with a soft dark fade behind the upper text
    • Logo top-left; small RERA no. + serif project name top-right
    • Left-aligned info stack: unit size, "Price starts from ₹X onwards*",
      headline in a white tag, pin + location
    • Two big-number highlights split by a thin divider
    • Vertical "T&C Apply | Representative image" note on the right edge
    • Site-visit CTA pill above a dark RERA strip
    """
    sc = SIZES.get(size_id, SIZES["instagram_post"])
    W, H = sc["width"], sc["height"]

    canvas = _load_background(background_path, W, H)
    overlay = Image.new("RGBA", (W, H), (0, 0, 0, 0))
    draw = ImageDraw.Draw(overlay)
    shadow_layer = Image.new("RGBA", (W, H), (0, 0, 0, 0))
    sdraw = ImageDraw.Draw(shadow_layer)

    try:
        brand_rgb = ImageColor.getrgb(project.brand.primary_colour)
    except Exception:
        brand_rgb = (31, 42, 68)
    try:
        gold_rgb = ImageColor.getrgb(project.brand.secondary_colour)
    except Exception:
        gold_rgb = (201, 162, 39)
    palette = _photo_palette(canvas, brand_rgb)
    accent_rgb = palette["accent"]

    rera_h = int(H * 0.078)
    margin = int(W * 0.09)

    # Dark fade over the top ~70% so white type reads on busy foliage / facades
    fade_h = int(H * 0.70)
    for y in range(fade_h):
        alpha = int(185 * ((1.0 - y / fade_h) ** 0.9))
        draw.line([(0, y), (W, y)], fill=(0, 0, 0, alpha))
    # Lighter fade under the CTA
    low_h = int(H * 0.16)
    for i in range(low_h):
        alpha = int(140 * (i / low_h) ** 1.6)
        y = H - rera_h - low_h + i
        draw.line([(0, y), (W, y)], fill=(0, 0, 0, alpha))

    # ── Top row: logo left, RERA + project name right ──
    top_y = int(H * 0.06)
    if logo_path and Path(logo_path).exists():
        try:
            logo_img = Image.open(logo_path).convert("RGBA")
            bbox = logo_img.getbbox()
            if bbox:
                logo_img = logo_img.crop(bbox)
            ratio = min((W * 0.24) / logo_img.width, (H * 0.07) / logo_img.height)
            logo_img = logo_img.resize(
                (max(10, int(logo_img.width * ratio)), max(10, int(logo_img.height * ratio))), Image.LANCZOS
            )
            pad = int(logo_img.height * 0.16)
            draw.rounded_rectangle(
                [(margin - pad, top_y - pad), (margin + logo_img.width + pad, top_y + logo_img.height + pad)],
                radius=max(8, pad), fill=(255, 255, 255, 215),
            )
            overlay.paste(logo_img, (margin, top_y), logo_img)
        except Exception:
            pass

    right_edge = W - int(W * 0.07)
    ry = top_y - int(H * 0.012)
    rera_small = _weighted_font(SANS, max(13, int(H * 0.0095)), BODY)
    rera_label = project.rera_number
    rw = draw.textlength(rera_label, font=rera_small)
    draw.text((right_edge - rw, ry), rera_label, font=rera_small, fill=(255, 255, 255, 220))
    ry += _text_h(draw, rera_label, rera_small) + int(H * 0.014)

    name_font = _fit_weighted(draw, project.name, SERIF, DISPLAY,
                              max_w=int(W * 0.50), initial_size=int(H * 0.052), min_size=int(H * 0.026))
    nw = draw.textlength(project.name, font=name_font)
    _shadow_text(draw, sdraw, (right_edge - nw, ry), project.name, name_font)
    ry += _text_h(draw, project.name, name_font) + int(H * 0.010)

    # Tagline between two short rules, e.g. "— BY AURELIA DEVELOPERS —"
    prom = (getattr(project, "promoter", "") or "").strip()
    tagline = f"BY {prom.upper()}" if prom and prom.lower() != "promoter" else ""
    if tagline:
        tag_font = _fit_weighted(draw, tagline, SANS, BODY,
                                 max_w=int(nw * 0.80), initial_size=max(13, int(H * 0.0105)), min_size=11)
        tw = draw.textlength(tagline, font=tag_font)
        rule = int(W * 0.03)
        gap = int(W * 0.008)
        total = tw + 2 * (rule + gap)
        tx = right_edge - (nw + total) / 2
        ty = ry + _text_h(draw, tagline, tag_font) // 2
        draw.line([(tx, ty), (tx + rule, ty)], fill=(255, 255, 255, 200), width=1)
        draw.text((tx + rule + gap, ry), tagline, font=tag_font, fill=(255, 255, 255, 230))
        draw.line([(tx + rule + 2 * gap + tw, ty), (tx + total, ty)], fill=(255, 255, 255, 200), width=1)

    # ── Left info stack ──
    y = int(H * 0.235)
    block_w = int(W * 0.62)

    if festival and festival != "None":
        greet_font = _weighted_font(SERIF, int(H * 0.030), DISPLAY)
        greet = f"Happy {festival}"
        _shadow_text(draw, sdraw, (margin, y), greet, greet_font, fill=(*gold_rgb, 255))
        y += _text_h(draw, greet, greet_font) + int(H * 0.018)

    size_line = _reel_size_line(project)
    if size_line:
        label, value = size_line
        lf = _weighted_font(SANS, int(H * 0.0165), BODY)
        vf = _weighted_font(SERIF, int(H * 0.032), DISPLAY)
        lw = draw.textlength(label + " ", font=lf)
        ascent, descent = vf.getmetrics()
        base = y + ascent
        # Sans label and serif value share one baseline
        _shadow_text(draw, sdraw, (margin, base), label, lf, anchor="ls")
        _shadow_text(draw, sdraw, (margin + lw, base), value, vf, anchor="ls")
        y = base + int(descent * 0.6) + int(H * 0.012)
        draw.line([(margin, y), (margin + block_w, y)], fill=(255, 255, 255, 210), width=max(1, int(H * 0.0012)))
        y += int(H * 0.022)

    has_price = bool(project.lowest_price_inr) and "Request" not in project.formatted_lowest_price
    if has_price:
        sf = _weighted_font(SANS, int(H * 0.0175), BODY)
        _shadow_text(draw, sdraw, (margin, y), "Price starts from", sf)
        y += _text_h(draw, "Price starts from", sf) + int(H * 0.008)

        price = project.formatted_lowest_price
        pf = _fit_weighted(draw, price, SERIF, DISPLAY,
                           max_w=int(block_w * 0.72), initial_size=int(H * 0.068), min_size=int(H * 0.036))
        of = _weighted_font(SANS, int(H * 0.0175), BODY)
        ascent, descent = pf.getmetrics()
        base = y + ascent
        px = margin + draw.textlength(price, font=pf) + int(W * 0.015)
        _shadow_text(draw, sdraw, (margin, base), price, pf, anchor="ls")
        _shadow_text(draw, sdraw, (px, base), "onwards*", of, anchor="ls")
        y = base + int(descent * 0.4) + int(H * 0.020)

    if headline:
        hf = _fit_weighted(draw, headline, SANS, EMPHASIS,
                           max_w=int(W * 0.78), initial_size=int(H * 0.0205), min_size=int(H * 0.013))
        hw = draw.textlength(headline, font=hf)
        hh = _text_h(draw, headline, hf)
        pad_x, pad_y = int(W * 0.014), int(H * 0.008)
        draw.rectangle([(margin, y), (margin + hw + 2 * pad_x, y + hh + 2 * pad_y)], fill=(255, 255, 255, 245))
        draw.text((margin + pad_x, y + pad_y), headline, font=hf, fill=(*accent_rgb, 255))
        y += hh + 2 * pad_y + int(H * 0.016)

    loc = ", ".join(x for x in [getattr(project, "marketing_name", ""), getattr(project, "city", "")] if x)
    if loc:
        lof = _fit_weighted(draw, loc, SANS, BODY,
                            max_w=int(W * 0.74), initial_size=int(H * 0.0175), min_size=12)
        pin = int(_text_h(draw, loc, lof) * 1.05)
        _draw_pin(draw, margin, y, pin)
        _shadow_text(draw, sdraw, (margin + int(pin * 0.95), y), loc, lof)
        y += pin + int(H * 0.035)

    # ── Big-number highlights ──
    scrim_boxes = []
    stats = _reel_highlights(project)
    if stats:
        col_w = int(W * 0.30)
        gap = int(W * 0.04)
        total_w = len(stats) * col_w + (len(stats) - 1) * gap
        x0 = (W - total_w) // 2
        sy = max(y, int(H * 0.47))
        num_h = 0
        for i, (value, label) in enumerate(stats):
            cx = x0 + i * (col_w + gap) + col_w // 2
            nf = _fit_weighted(draw, value, SERIF, DISPLAY,
                               max_w=col_w, initial_size=int(H * 0.080), min_size=int(H * 0.036))
            lf = _fit_weighted(draw, label, SANS, EMPHASIS,
                               max_w=int(col_w * 1.1), initial_size=int(H * 0.0195), min_size=12)
            vw = draw.textlength(value, font=nf)
            num_h = _text_h(draw, value, nf)
            _shadow_text(draw, sdraw, (cx - vw / 2, sy), value, nf)
            lw = draw.textlength(label, font=lf)
            _shadow_text(draw, sdraw, (cx - lw / 2, sy + num_h + int(H * 0.008)), label, lf)
            stats_bottom = sy + num_h + int(H * 0.008) + _text_h(draw, label, lf)
        for i in range(1, len(stats)):
            dx = x0 + i * (col_w + gap) - gap // 2
            draw.line([(dx, sy + int(num_h * 0.05)), (dx, sy + num_h + int(H * 0.03))],
                      fill=(255, 255, 255, 140), width=max(1, int(W * 0.0015)))
        pad = int(H * 0.025)
        scrim_boxes.append((x0 - pad, sy - pad, x0 + total_w + pad, stats_bottom + pad))

    # ── Vertical T&C note on the right edge ──
    note = "*T & C Apply | Representative image"
    nf = _weighted_font(SANS, max(12, int(H * 0.0095)), BODY)
    nb = draw.textbbox((0, 0), note, font=nf)
    note_img = Image.new("RGBA", (nb[2] + 4, nb[3] + 4), (0, 0, 0, 0))
    ImageDraw.Draw(note_img).text((2, 2), note, font=nf, fill=(255, 255, 255, 200))
    note_img = note_img.rotate(90, expand=True, resample=Image.BICUBIC)
    overlay.alpha_composite(note_img, (W - int(W * 0.035) - note_img.width,
                                       H - rera_h - int(H * 0.17) - note_img.height))

    # ── CTA pill (site visits / phone) ──
    cta_parts = []
    sv = getattr(project, "site_visits", None)
    if sv and is_valid_content(sv.formatted_text):
        cta_parts.append(sv.formatted_text)
    if is_valid_content(getattr(project, "marketing_phone", "")):
        cta_parts.append(f"Call {project.marketing_phone}")
    if cta_parts:
        cta = "   |   ".join(cta_parts)
        cta_h = int(H * 0.05)
        cta_top = H - rera_h - cta_h - int(H * 0.035)
        cf = _fit_weighted(draw, cta, SANS, EMPHASIS,
                           max_w=W - 2 * margin - int(W * 0.06), initial_size=int(cta_h * 0.36), min_size=12)
        draw.rounded_rectangle([(int(W * 0.05), cta_top), (W - int(W * 0.05), cta_top + cta_h)],
                               radius=cta_h // 3, fill=(*accent_rgb, 235))
        cw = draw.textlength(cta, font=cf)
        ch = _text_h(draw, cta, cf)
        draw.text(((W - cw) / 2, cta_top + (cta_h - ch) / 2 - 1), cta, font=cf, fill="#FFFFFF")

    _draw_rera_strip(draw, project, W, H,
                     bg_fill=(*palette["deep"], 255),
                     text_color="#F8FAFC",
                     disc_color=(*palette["tint"], 230),
                     accent_line_color=(*palette["tint"], 160))

    canvas = _apply_scrims(canvas, scrim_boxes)
    shadow_layer = shadow_layer.filter(ImageFilter.GaussianBlur(max(2, int(H * 0.004))))
    canvas = Image.alpha_composite(canvas, shadow_layer)
    return _finalise(canvas, overlay, project, output_path)


# ─────────────────────────────────────────────────────────────────────────────
# Public Dispatcher
# ─────────────────────────────────────────────────────────────────────────────

TEMPLATES = {
    "luxury_navy":         ("🏙️ Luxury Navy",         "Deep navy glassmorphic card — original template"),
    "executive_editorial": ("👑 Executive Editorial",    "Camp Capitol style — charcoal matte, framed render, QR badge & bronze CTA"),
    "minimal_white":       ("🤍 Minimal White",        "Clean white panel, black ink, brand accent border"),
    "cinematic":           ("🎬 Cinematic Dark",       "Full-bleed dark overlay, large headline, frosted info bar"),
    "split_panel":         ("◧ Split Panel",           "Brand-colour vertical band + photo — bold editorial look"),
    "reel_overlay":        ("🌿 Reel Overlay",         "Full-bleed photo, left-aligned price stack, big-number highlights & CTA pill"),
}


def render_poster_with_template(
    template: str = "luxury_navy",
    background_path=None,
    project: ProjectData = None,
    logo_path=None,
    headline: str = "",
    festival: str = "Diwali",
    size_id: str = "instagram_post",
    output_path=None,
) -> Image.Image:
    """
    Render a poster using the named template.

    Parameters
    ----------
    template : str
        One of: "luxury_navy" | "executive_editorial" | "minimal_white" | "cinematic" | "split_panel"
        | "reel_overlay"
    (All other parameters are identical to the original render_poster().)
    """
    dispatch = {
        "luxury_navy":         _render_luxury_navy,
        "executive_editorial": _render_executive_editorial,
        "minimal_white":       _render_minimal_white,
        "cinematic":           _render_cinematic,
        "split_panel":         _render_split_panel,
        "reel_overlay":        _render_reel_overlay,
    }
    fn = dispatch.get(template, _render_luxury_navy)
    return fn(background_path, project, logo_path, headline, festival, size_id, output_path)


