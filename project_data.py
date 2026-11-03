"""
Project Data Parser & Validator
================================
Parses project JSON files matching the real-estate specification, validates
mandatory fields (especially RERA number), extracts unit availability,
brand styles, and review status.
"""

from __future__ import annotations

import json
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple


@dataclass
class RenderInfo:
    filepath: str
    render_type: str = "exterior"      # "exterior", "interior", "amenity"
    approved: bool = True
    needs_review: bool = False
    notes: str = ""

    @property
    def path(self) -> Path:
        return Path(self.filepath)

    @property
    def filename(self) -> str:
        return self.path.name


def is_valid_content(val: Any) -> bool:
    """Check if a field value is real user content and not an unfilled placeholder."""
    if val is None:
        return False
    s = str(val).strip()
    if not s:
        return False
    s_clean = s.lower().replace(" ", "").replace("_", "").replace("-", "")
    placeholders = {
        "tobefilled",
        "tbd",
        "tba",
        "na",
        "none",
        "null",
        "placeholder",
        "dummy",
        "undefined",
        "unknown",
        "filllater",
    }
    if s_clean in placeholders or s in ("-", "--", "...", ".", "N/A"):
        return False
    return True


@dataclass
class SiteVisitInfo:
    days: str = ""
    start: str = ""
    end: str = ""

    @property
    def formatted_text(self) -> str:
        """Format as specified: 'Book your site visit – {days}, {start}–{end}'"""
        d = self.days.strip() if is_valid_content(self.days) else ""
        s = self.start.strip() if is_valid_content(self.start) else ""
        e = self.end.strip() if is_valid_content(self.end) else ""
        if d and s and e:
            return f"Book your site visit – {d}, {s} – {e}"
        elif d:
            return f"Book your site visit – {d}"
        return ""


@dataclass
class BrandConfig:
    primary_colour: str = "#1F2A44"    # Fallback dark navy
    secondary_colour: str = "#D4AF37"  # Fallback warm gold
    background_colour: str = "#FFFFFF"
    heading_font: str = "Playfair Display"
    body_font: str = "Inter"


@dataclass
class ProjectData:
    name: str
    promoter: str
    marketing_name: str
    city: str
    rera_number: str
    status: str = "verified"           # "verified", "draft", "dummy"
    verified_by: Optional[str] = None
    available_units: List[str] = field(default_factory=list)
    lowest_price_inr: Optional[int] = None
    travel_times: List[str] = field(default_factory=list)
    site_visits: SiteVisitInfo = field(default_factory=SiteVisitInfo)
    marketing_phone: str = ""
    brand: BrandConfig = field(default_factory=BrandConfig)
    disclaimers: List[str] = field(default_factory=list)
    extra_charges: List[str] = field(default_factory=list)
    raw_data: Dict[str, Any] = field(default_factory=dict)

    @property
    def is_verified(self) -> bool:
        return self.status.lower() in ("verified", "approved", "active")

    @property
    def formatted_lowest_price(self) -> str:
        if not self.lowest_price_inr:
            return "Price on Request"
        return format_inr(self.lowest_price_inr)

    @property
    def formatted_units_summary(self) -> str:
        if not self.available_units:
            return "Luxury"
        # e.g., ["2BHK", "3BHK"] -> "2 & 3 BHK"
        cleaned = [u.upper().replace("BHK", "").strip() for u in self.available_units]
        if len(cleaned) == 1:
            return f"{cleaned[0]} BHK"
        elif len(cleaned) == 2:
            return f"{cleaned[0]} & {cleaned[1]} BHK"
        else:
            return f"{', '.join(cleaned[:-1])} & {cleaned[-1]} BHK"


def format_inr(amount: int | float) -> str:
    """
    Format whole rupees into Indian numbering system:
      e.g. 9600000 -> '₹96 Lakh'
           14200000 -> '₹1.42 Cr'
           50000 -> '₹50,000'
    """
    val = float(amount)
    if val >= 10_000_000:
        cr = val / 10_000_000
        return f"₹{cr:.2f}".rstrip("0").rstrip(".") + " Cr"
    elif val >= 100_000:
        lakh = val / 100_000
        return f"₹{lakh:.2f}".rstrip("0").rstrip(".") + " Lakh"
    else:
        return f"₹{int(val):,}"


def parse_project_json(data: Dict[str, Any] | str | Path) -> ProjectData:
    """
    Parse and validate a project details JSON dictionary or file path.
    Enforces REQUIRED rera.number. Never hardcodes any project values.
    """
    if isinstance(data, (str, Path)):
        p = Path(data)
        if not p.exists():
            raise FileNotFoundError(f"Project JSON file not found: {p}")
        raw = json.loads(p.read_text(encoding="utf-8"))
    elif isinstance(data, dict):
        raw = data
    else:
        raise TypeError("Expected dict, Path, or str for project JSON")

    # 1. Project identity
    proj_block = raw.get("project", {})
    name = proj_block.get("name") or raw.get("name") or "Residential Project"
    promoter_raw = proj_block.get("promoter") or proj_block.get("developer") or raw.get("promoter") or ""
    promoter = promoter_raw if is_valid_content(promoter_raw) else ""

    # 2. Location
    loc_block = raw.get("location", {})
    mkt_raw = loc_block.get("marketing_name") or loc_block.get("address") or loc_block.get("locality") or ""
    marketing_name = mkt_raw if is_valid_content(mkt_raw) else ""
    city_raw = loc_block.get("city") or ""
    city = city_raw if is_valid_content(city_raw) else ""

    raw_travel = loc_block.get("travel_times", [])
    travel_times: List[str] = []
    if isinstance(raw_travel, list):
        for item in raw_travel[:3]:
            if isinstance(item, dict):
                t_val = item.get("time") or item.get("duration")
                dest = item.get("destination") or item.get("to")
                if t_val and dest and is_valid_content(t_val) and is_valid_content(dest):
                    travel_times.append(f"{t_val} to {dest}")
                elif dest and is_valid_content(dest):
                    travel_times.append(str(dest))
            elif isinstance(item, str) and is_valid_content(item):
                travel_times.append(item.strip())

    travel_times = [t for t in travel_times if is_valid_content(t)]

    # Site visits & Contacts
    sv_block = raw.get("site_visits", {})
    site_visit_obj = SiteVisitInfo(
        days=str(sv_block.get("days", "")).strip(),
        start=str(sv_block.get("start", "")).strip(),
        end=str(sv_block.get("end", "")).strip(),
    )
    contacts_block = raw.get("contacts", {})
    mkt_contact = contacts_block.get("marketing", {})
    phone_raw = (mkt_contact.get("phone") or contacts_block.get("phone") or "").strip()
    marketing_phone = phone_raw if is_valid_content(phone_raw) else ""

    # 3. RERA (REQUIRED - Refuse to generate if missing or empty)
    rera_block = raw.get("rera", {})
    rera_num = None
    if isinstance(rera_block, dict):
        rera_num = rera_block.get("number") or rera_block.get("registration_number")
    elif isinstance(rera_block, str):
        rera_num = rera_block

    if not rera_num:
        rera_num = raw.get("rera_number") or raw.get("rera_no")

    if not rera_num or not str(rera_num).strip():
        raise ValueError(
            "RERA number is REQUIRED by law for real estate ads. "
            "Please ensure 'rera.number' is present and non-empty in the project JSON."
        )
    rera_number = str(rera_num).strip()

    # 4. Units & Pricing
    units_list = raw.get("units", [])
    available_units: List[str] = []
    prices: List[int] = []

    for u in units_list:
        status = str(u.get("status", "available")).lower()
        if status in ("available", "open", "active", "for_sale"):
            utype = u.get("type") or u.get("type_name") or u.get("name")
            if utype and utype not in available_units:
                available_units.append(utype)
            p_min = u.get("price_min_inr") or u.get("price_min") or u.get("price")
            if p_min:
                try:
                    prices.append(int(p_min))
                except (ValueError, TypeError):
                    pass

    lowest_price_inr = min(prices) if prices else None

    # 5. Brand styles
    brand_raw = raw.get("brand", {})
    colours = brand_raw.get("colours") or brand_raw.get("colors") or {}
    fonts = brand_raw.get("fonts") or {}

    brand = BrandConfig(
        primary_colour=colours.get("primary", "#1F2A44"),
        secondary_colour=colours.get("secondary", "#D4AF37"),
        background_colour=colours.get("background", "#FFFFFF"),
        heading_font=fonts.get("heading", "Playfair Display"),
        body_font=fonts.get("body", "Inter"),
    )

    # 6. Disclaimers & Pricing extras
    disclaimers = raw.get("disclaimers") or []
    pricing_block = raw.get("pricing", {})
    extra_charges = pricing_block.get("extra_charges") or []

    # 7. Status & verification
    status = raw.get("status") or proj_block.get("status") or "verified"
    verified_by = raw.get("verified_by") or proj_block.get("verified_by")

    return ProjectData(
        name=name,
        promoter=promoter,
        marketing_name=marketing_name,
        city=city,
        rera_number=rera_number,
        status=status,
        verified_by=verified_by,
        available_units=available_units,
        lowest_price_inr=lowest_price_inr,
        travel_times=travel_times,
        site_visits=site_visit_obj,
        marketing_phone=marketing_phone,
        brand=brand,
        disclaimers=disclaimers,
        extra_charges=extra_charges,
        raw_data=raw,
    )


def filter_approved_renders(
    renders: List[RenderInfo],
    review_dict: Optional[Dict[str, Any]] = None,
) -> List[RenderInfo]:
    """
    Filter renders that are approved for ads, skipping any whose review entry
    has needs_review: true.
    """
    review_dict = review_dict or {}
    valid: List[RenderInfo] = []

    for r in renders:
        # Check explicit approval
        if not r.approved:
            continue

        # Check review dict from project JSON if present
        fname = Path(r.filepath).name
        review_entry = review_dict.get(fname) or review_dict.get(Path(r.filepath).stem)
        if isinstance(review_entry, dict) and review_entry.get("needs_review") is True:
            continue

        valid.append(r)

    return valid
