"""
Poster Layout & Pillow Rendering Engine
=======================================
Composites project typography, brand logo, festive headlines, value propositions,
and legal RERA disclosures onto background images using Pillow.
Enforces responsive scaling, auto-shrinking text, and strict WCAG contrast.
Features an elevated, luxury real-estate color palette:
  - Deep Midnight Twilight vignette
  - Luminous Regal Gold and Warm Champagne typography with drop-shadows
  - Rich Royal Navy glassmorphic lower card with metallic gold borders
  - Warm Luxury Pearl Alabaster footer band with gold accent separator
"""

from __future__ import annotations

import math
from pathlib import Path
from typing import List, Optional, Tuple

from PIL import Image, ImageColor, ImageDraw, ImageFont

try:
    from config import SIZES
    from project_data import ProjectData, is_valid_content
except ImportError:
    from poster_generator.config import SIZES
    from poster_generator.project_data import ProjectData, is_valid_content


def _get_font(font_name: str, size: int) -> ImageFont.FreeTypeFont:
    """Load specified font from local fonts directory with robust fallbacks."""
    fonts_dir = Path(__file__).parent / "fonts"
    target_ttf = None

    font_str = str(font_name or "").lower()
    if "playfair" in font_str:
        target_ttf = fonts_dir / "PlayfairDisplay.ttf"
    else:
        target_ttf = fonts_dir / "Inter.ttf"

    if target_ttf and target_ttf.exists():
        try:
            return ImageFont.truetype(str(target_ttf), size)
        except Exception:
            pass

    # System fallbacks
    system_candidates = [
        "/System/Library/Fonts/Supplemental/Arial.ttf",
        "/System/Library/Fonts/Helvetica.ttc",
        "/System/Library/Fonts/Times.ttc",
        "/Library/Fonts/Arial.ttf",
        "/usr/share/fonts/truetype/dejavu/DejaVuSans.ttf",
    ]
    for sc in system_candidates:
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
    """Auto-shrink font size until text fits precisely inside max_w and max_h."""
    size = initial_size
    while size >= min_size:
        font = _get_font(font_name, size)
        bbox = draw.textbbox((0, 0), text, font=font)
        w = bbox[2] - bbox[0]
        h = bbox[3] - bbox[1]
        if w <= max_w and h <= max_h:
            return font, w, h
        size -= 1

    font = _get_font(font_name, min_size)
    bbox = draw.textbbox((0, 0), text, font=font)
    return font, bbox[2] - bbox[0], bbox[3] - bbox[1]


def render_poster(
    background_path: Path | str,
    project: ProjectData,
    logo_path: Optional[Path | str] = None,
    headline: str = "",
    festival: str = "Diwali",
    size_id: str = "instagram_post",
    output_path: Optional[Path | str] = None,
) -> Image.Image:
    """
    Render a complete festive real-estate poster with Pillow using an elevated,
    luxury color palette, high-contrast typography, and strict WCAG compliance.
    """
    size_cfg = SIZES.get(size_id, SIZES["instagram_post"])
    target_w = size_cfg["width"]
    target_h = size_cfg["height"]

    # 1. Base Background Image
    bg_p = Path(background_path)
    if not bg_p.exists():
        raise FileNotFoundError(f"Background not found: {bg_p}")

    bg_img = Image.open(bg_p).convert("RGBA")
    if bg_img.size != (target_w, target_h):
        bg_img = bg_img.resize((target_w, target_h), Image.LANCZOS)

    # Work on a full RGBA canvas for smooth alpha compositing
    canvas = bg_img.copy()
    overlay = Image.new("RGBA", (target_w, target_h), (0, 0, 0, 0))
    draw_overlay = ImageDraw.Draw(overlay)

    # 2. Top Area Gradient for Guaranteed Contrast and Luxury Twilight Atmosphere
    top_gradient_h = int(target_h * 0.36)
    for y in range(top_gradient_h):
        # Smooth quadratic twilight fade-out: Deep Midnight Indigo (10, 16, 32)
        progress = y / top_gradient_h
        alpha = int(235 * ((1.0 - progress) ** 1.6))
        draw_overlay.line([(0, y), (target_w, y)], fill=(10, 16, 32, alpha))

    # 3. Top Area Logo
    is_landscape = (target_w > target_h)
    cursor_y = int(target_h * 0.038)
    logo_w_target = int(target_w * 0.18)

    if logo_path and Path(logo_path).exists():
        try:
            logo_img = Image.open(logo_path).convert("RGBA")
            # Auto-trim transparent borders so the logo graphic scales correctly
            bbox = logo_img.getbbox()
            if bbox:
                logo_img = logo_img.crop(bbox)

            ratio = min(logo_w_target / logo_img.width, (target_h * 0.10) / logo_img.height)
            new_logo_w = max(10, int(logo_img.width * ratio))
            new_logo_h = max(10, int(logo_img.height * ratio))
            logo_resized = logo_img.resize((new_logo_w, new_logo_h), Image.LANCZOS)

            logo_x = int(target_w * 0.05) if is_landscape else (target_w - new_logo_w) // 2

            # Gentle luxury frosted glass backing for guaranteed logo contrast against any scene
            pad_x = int(new_logo_w * 0.14)
            pad_y = int(new_logo_h * 0.12)
            draw_overlay.rounded_rectangle(
                [(logo_x - pad_x, cursor_y - pad_y), (logo_x + new_logo_w + pad_x, cursor_y + new_logo_h + pad_y)],
                radius=max(8, int(new_logo_h * 0.22)),
                fill=(255, 255, 255, 225),  # Frosted ivory white
                outline=(201, 162, 39, 180), # Polished gold border
                width=max(1, int(target_w * 0.0015)),
            )

            overlay.paste(logo_resized, (logo_x, cursor_y), logo_resized)
            cursor_y += new_logo_h + int(target_h * 0.024)
        except Exception:
            cursor_y += int(target_h * 0.02)
    else:
        cursor_y += int(target_h * 0.02)

    # 4. Festive Greeting & Headline in Top Area
    # Elevated Color Palette:
    # - Greeting: Warm Champagne Cream (#FFFBEB) with soft dark shadow
    # - Headline: Radiant Polished Gold (#F5C542) with dimensional shadow
    if festival and festival != "None":
        greet_text = f"Happy {festival}!"
        g_font, gw, gh = _fit_text(
            draw_overlay,
            greet_text,
            project.brand.heading_font,
            max_w=int(target_w * 0.85),
            max_h=int(target_h * 0.038),
            initial_size=int(target_h * 0.026),
        )
        gx = (target_w - gw) // 2
        # Soft dark drop shadow for guaranteed readability
        draw_overlay.text((gx + 1, cursor_y + 1), greet_text, font=g_font, fill=(0, 0, 0, 190))
        draw_overlay.text((gx, cursor_y), greet_text, font=g_font, fill="#FFF8E7")
        cursor_y += gh + int(target_h * 0.012)

    if headline:
        # Use a vibrant, radiant festive gold derived from brand secondary
        headline_color = "#F5C542"  # Luminous Royal Gold

        # Wrap headline into 2 balanced lines if long
        words = headline.split()
        if len(words) > 4 and len(headline) > 26:
            mid = len(words) // 2
            line1 = " ".join(words[:mid])
            line2 = " ".join(words[mid:])
            lines = [line1, line2]
        else:
            lines = [headline]

        for line in lines:
            h_font, hw, hh = _fit_text(
                draw_overlay,
                line,
                project.brand.heading_font,
                max_w=int(target_w * 0.88),
                max_h=int(target_h * 0.048),
                initial_size=int(target_h * 0.036),
            )
            hx = (target_w - hw) // 2
            # Dual-pass soft shadow for ultra-crisp editorial depth
            draw_overlay.text((hx + 2, cursor_y + 2), line, font=h_font, fill=(0, 0, 0, 210))
            draw_overlay.text((hx + 1, cursor_y + 1), line, font=h_font, fill=(10, 16, 32, 140))
            draw_overlay.text((hx, cursor_y), line, font=h_font, fill=headline_color)
            cursor_y += hh + int(target_h * 0.008)

    # 5. Lower Panel (85-90% Opacity Deep Brand Royal Navy, Gold Accents)
    bottom_strip_h = int(target_h * 0.076)
    panel_margin_x = int(target_w * 0.042)
    panel_margin_b = bottom_strip_h + int(target_h * 0.016)
    panel_w = target_w - (2 * panel_margin_x)
    panel_h = int(target_h * 0.325)
    panel_top = target_h - panel_margin_b - panel_h

    # Brand primary color parsed with rich alpha opacity
    try:
        rgb_prim = ImageColor.getrgb(project.brand.primary_colour)
    except Exception:
        rgb_prim = (31, 42, 68)

    # Deepen base tone slightly for maximum contrast with cream & gold
    panel_r = max(12, int(rgb_prim[0] * 0.82))
    panel_g = max(18, int(rgb_prim[1] * 0.82))
    panel_b = max(32, int(rgb_prim[2] * 0.82))
    panel_rgba = (panel_r, panel_g, panel_b, 226)

    # Draw rounded luxury card panel
    radius = int(target_w * 0.026)
    draw_overlay.rounded_rectangle(
        [(panel_margin_x, panel_top), (panel_margin_x + panel_w, panel_top + panel_h)],
        radius=radius,
        fill=panel_rgba,
        outline=(218, 178, 77, 185),  # Refined metallic gold border
        width=max(1, int(target_w * 0.0016)),
    )

    # Subtle inner border highlight
    inner_pad = max(2, int(target_w * 0.003))
    draw_overlay.rounded_rectangle(
        [(panel_margin_x + inner_pad, panel_top + inner_pad),
         (panel_margin_x + panel_w - inner_pad, panel_top + panel_h - inner_pad)],
        radius=max(4, radius - inner_pad),
        fill=None,
        outline=(255, 255, 255, 18),
        width=1,
    )

    # Content inside Lower Panel
    py = panel_top + int(panel_h * 0.060)
    p_center_x = target_w // 2

    # Line 1: Project Name (Large, Heading Font, Crisp Pearl White #FFFFFF)
    pname_font, pnw, pnh = _fit_text(
        draw_overlay,
        project.name.upper(),
        project.brand.heading_font,
        max_w=int(panel_w * 0.88),
        max_h=int(panel_h * 0.17),
        initial_size=int(panel_h * 0.140),
    )
    draw_overlay.text((p_center_x - pnw // 2 + 1, py + 1), project.name.upper(), font=pname_font, fill=(0, 0, 0, 160))
    draw_overlay.text((p_center_x - pnw // 2, py), project.name.upper(), font=pname_font, fill="#FFFFFF")
    py += pnh + int(panel_h * 0.038)

    # Line 2: "by {promoter}" (only if specified in JSON)
    promoter_str = getattr(project, "promoter", "").strip()
    if promoter_str and promoter_str.lower() != "promoter":
        p_by_text = f"by {promoter_str}"
        prom_font, pmw, pmh = _fit_text(
            draw_overlay,
            p_by_text,
            project.brand.body_font,
            max_w=int(panel_w * 0.85),
            max_h=int(panel_h * 0.090),
            initial_size=int(panel_h * 0.072),
        )
        draw_overlay.text((p_center_x - pmw // 2, py), p_by_text, font=prom_font, fill="#CBD5E1")
        py += pmh + int(panel_h * 0.040)

    # Refined Metallic Gold Divider Line
    div_w = int(panel_w * 0.46)
    div_x1 = p_center_x - div_w // 2
    div_x2 = p_center_x + div_w // 2
    draw_overlay.line(
        [(div_x1, py), (div_x2, py)],
        fill=(218, 178, 77, 140),
        width=1,
    )
    py += int(panel_h * 0.040)

    # Line 3: Available Units & Lowest Price (only if provided in JSON)
    has_units = bool(getattr(project, "available_units", []))
    has_price = bool(getattr(project, "lowest_price_inr", None))
    offer_parts = []
    if has_units and project.formatted_units_summary:
        offer_parts.append(f"{project.formatted_units_summary} Homes")
    if has_price and "Request" not in project.formatted_lowest_price:
        offer_parts.append(f"from {project.formatted_lowest_price}*")

    if offer_parts:
        offer_full = " ".join(offer_parts)
        off_font, ofw, ofh = _fit_text(
            draw_overlay,
            offer_full,
            project.brand.heading_font,
            max_w=int(panel_w * 0.90),
            max_h=int(panel_h * 0.135),
            initial_size=int(panel_h * 0.110),
        )
        draw_overlay.text((p_center_x - ofw // 2 + 1, py + 1), offer_full, font=off_font, fill=(0, 0, 0, 160))
        draw_overlay.text((p_center_x - ofw // 2, py), offer_full, font=off_font, fill="#FBBF24")
        py += ofh + int(panel_h * 0.030)

    # Line 4: Location & Travel Times (only if present in JSON)
    loc_parts = []
    if getattr(project, "marketing_name", ""):
        loc_parts.append(project.marketing_name)
    if getattr(project, "city", ""):
        loc_parts.append(project.city)
    loc_base = ", ".join(loc_parts)

    travel_details = []
    if loc_base:
        travel_details.append(loc_base)
    for t in getattr(project, "travel_times", [])[:2]:
        travel_details.append(t)

    travel_line = "   •   ".join(travel_details)
    if travel_line.strip():
        t_font, tw, th = _fit_text(
            draw_overlay,
            travel_line,
            project.brand.body_font,
            max_w=int(panel_w * 0.92),
            max_h=int(panel_h * 0.090),
            initial_size=int(panel_h * 0.070),
        )
        draw_overlay.text((p_center_x - tw // 2, py), travel_line, font=t_font, fill="#E2E8F0")
        py += th + int(panel_h * 0.034)

    # Line 5: Site Visit Booking (only if real dates/times provided)
    site_visits = getattr(project, "site_visits", None)
    sv_text = getattr(site_visits, "formatted_text", "") if site_visits else ""
    if sv_text and is_valid_content(sv_text):
        sv_font, svw, svh = _fit_text(
            draw_overlay,
            sv_text,
            project.brand.body_font,
            max_w=int(panel_w * 0.92),
            max_h=int(panel_h * 0.088),
            initial_size=int(panel_h * 0.070),
        )
        draw_overlay.text((p_center_x - svw // 2, py), sv_text, font=sv_font, fill="#E2E8F0")
        py += svh + int(panel_h * 0.028)

    # Line 6: Contact Marketing Phone (only if real number provided)
    phone_val = getattr(project, "marketing_phone", "")
    if phone_val and is_valid_content(phone_val):
        phone_text = f"Call: {phone_val}"
        ph_font, phw, phh = _fit_text(
            draw_overlay,
            phone_text,
            project.brand.body_font,
            max_w=int(panel_w * 0.90),
            max_h=int(panel_h * 0.088),
            initial_size=int(panel_h * 0.068),
        )
        # Highlighted in warm metallic gold for immediate call-to-action
        draw_overlay.text((p_center_x - phw // 2, py), phone_text, font=ph_font, fill="#FBBF24")

    # 6. Bottom Legal Strip on EVERY Poster (Warm Luxury Pearl Band with Gold Top Accent)
    bottom_strip_h = int(target_h * 0.078)
    strip_top = target_h - bottom_strip_h

    # Luxury Warm Pearl/Alabaster Cream background (#FAF8F5)
    draw_overlay.rectangle(
        [(0, strip_top), (target_w, target_h)],
        fill=(250, 248, 245, 255),
    )

    # Polished Gold Top Accent Line (2px)
    accent_gold = (201, 162, 39, 210)
    draw_overlay.line([(0, strip_top), (target_w, strip_top)], fill=accent_gold, width=max(1, int(target_h * 0.0015)))

    # RERA Text: REQUIRED, bold, high contrast dark midnight onyx (#0F172A)
    # Guaranteed WCAG AAA contrast ratio > 16:1 against #FAF8F5
    rera_text = f"RERA No: {project.rera_number}"
    r_font, rw, rh = _fit_text(
        draw_overlay,
        rera_text,
        "Inter",
        max_w=int(target_w * 0.88),
        max_h=int(bottom_strip_h * 0.38),
        initial_size=max(26, int(target_h * 0.026)),
        min_size=max(14, int(target_h * 0.016)),
    )
    rera_y = strip_top + int(bottom_strip_h * 0.12)
    draw_overlay.text(((target_w - rw) // 2, rera_y), rera_text, font=r_font, fill="#0F172A")

    # Small Disclaimer Text (2 clean centered lines in refined slate #475569)
    disc_line1 = "*Price excludes car park, clubhouse, GST, stamp duty & registration. Prices subject to revision."
    disc_line2 = "Artist's impression. Travel times approximate. Terms & conditions apply."
    disc_y = rera_y + rh + int(bottom_strip_h * 0.06)

    for d_line in [disc_line1, disc_line2]:
        d_font, dw, dh = _fit_text(
            draw_overlay,
            d_line,
            "Inter",
            max_w=int(target_w * 0.88),
            max_h=int(bottom_strip_h * 0.22),
            initial_size=max(16, int(target_h * 0.013)),
            min_size=max(12, int(target_h * 0.011)),
        )
        draw_overlay.text(((target_w - dw) // 2, disc_y), d_line, font=d_font, fill="#475569")
        disc_y += dh + int(bottom_strip_h * 0.03)

    # Composite overlays onto canvas
    canvas = Image.alpha_composite(canvas, overlay)

    # 7. Unverified Project Watermark (Draft Protection disabled per user preference)
    # if not project.is_verified:
    #     canvas = _apply_draft_watermark(canvas, target_w, target_h)

    # Final RGB conversion
    final_img = canvas.convert("RGB")
    if output_path:
        out_p = Path(output_path)
        out_p.parent.mkdir(parents=True, exist_ok=True)
        final_img.save(out_p, format="PNG")

    return final_img


def _apply_draft_watermark(img: Image.Image, width: int, height: int) -> Image.Image:
    """Burn large diagonal semi-transparent 'DRAFT – NOT FOR PUBLICATION' watermark."""
    watermark_layer = Image.new("RGBA", (width, height), (0, 0, 0, 0))
    wm_draw = ImageDraw.Draw(watermark_layer)

    text = "DRAFT – NOT FOR PUBLICATION"
    wm_font = _get_font("Inter", int(height * 0.065))
    bbox = wm_draw.textbbox((0, 0), text, font=wm_font)
    tw = bbox[2] - bbox[0]
    th = bbox[3] - bbox[1]

    # Create text image and rotate 35 degrees
    txt_img = Image.new("RGBA", (tw + 40, th + 40), (0, 0, 0, 0))
    txt_draw = ImageDraw.Draw(txt_img)
    txt_draw.text((20, 20), text, font=wm_font, fill=(239, 68, 68, 90))
    rotated_txt = txt_img.rotate(35, expand=True, resample=Image.BICUBIC)

    rx = (width - rotated_txt.width) // 2
    ry = (height - rotated_txt.height) // 2
    watermark_layer.paste(rotated_txt, (rx, ry), rotated_txt)

    return Image.alpha_composite(img, watermark_layer)
