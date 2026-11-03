"""
Project Data Parser & RERA Validator
====================================
Parses real-estate project JSON files according to the standard schema.
Enforces strict RERA validation and formats prices in Indian numbering.
"""

from __future__ import annotations

import json
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Dict, List, Optional


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


def format_indian_currency(amount: Optional[int | float]) -> str:
    """Format numerical INR amount in standard Indian notation (Lakh / Cr)."""
    if not amount or amount <= 0:
        return "Price on Request"
    amount = float(amount)
    if amount >= 10_000_000:
        val = amount / 10_000_000
        return f"₹{val:.2f} Cr".rstrip("0").rstrip(".") if val % 1 != 0 else f"₹{int(val)} Cr"
    elif amount >= 100_000:
        val = amount / 100_000
        return f"₹{val:.2f} Lakh".rstrip("0").rstrip(".") if val % 1 != 0 else f"₹{int(val)} Lakh"
    return f"₹{int(amount):,}"


@dataclass
class BrandInfo:
    primary_colour: str = "#1F2A44"
    secondary_colour: str = "#C9A227"
    background_colour: str = "#0D1117"
    heading_font: str = "PlayfairDisplay"
    body_font: str = "Inter"


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
class RenderInfo:
    filepath: str
    render_type: str = "exterior"  # "exterior", "interior", "amenity"
    approved: bool = True
    needs_review: bool = False

    @property
    def path(self) -> Path:
        return Path(self.filepath)

    @property
    def filename(self) -> str:
        return self.path.name


@dataclass
class ProjectData:
    name: str
    promoter: str
    status: str
    rera_number: str
    is_verified: bool
    marketing_name: str
    city: str
    travel_times: List[str]
    available_units: List[str]
    lowest_price_inr: Optional[int]
    site_visits: SiteVisitInfo
    marketing_phone: str
    brand: BrandInfo
    disclaimers: List[str]
    extra_charges: List[str]
    raw_data: Dict[str, Any] = field(default_factory=dict)

    @property
    def formatted_lowest_price(self) -> str:
        return format_indian_currency(self.lowest_price_inr)

    @property
    def formatted_units_summary(self) -> str:
        if not self.available_units:
            return "Residential"
        return " & ".join(self.available_units)


def parse_project_json(file_path: Path | str) -> ProjectData:
    """
    Parse project information JSON and validate required fields.
    Refuses poster creation if RERA number is missing or empty.
    """
    p = Path(file_path)
    if not p.exists():
        raise FileNotFoundError(f"Project JSON file not found: {p}")

    with open(p, "r", encoding="utf-8") as f:
        data = json.load(f)

    # 1. Project details
    proj = data.get("project", {})
    name = (proj.get("name") or data.get("name") or "Unnamed Property").strip()
    promoter_raw = (proj.get("promoter") or data.get("promoter") or "").strip()
    promoter = promoter_raw if is_valid_content(promoter_raw) else ""
    status = (proj.get("status") or data.get("status") or "draft").strip().lower()
    is_verified = (status == "verified")

    # 2. Strict RERA validation
    rera_obj = data.get("rera", {})
    rera_number = (
        rera_obj.get("number")
        or data.get("rera_number")
        or ""
    ).strip()

    if not rera_number:
        raise ValueError(
            f"STRICT RERA COMPLIANCE REFUSAL: 'rera.number' is missing or empty in {p.name}. "
            "Real-estate advertisements cannot be generated without an authentic RERA registration number."
        )

    # 3. Location & Travel Times
    loc = data.get("location", {})
    mkt_raw = (loc.get("marketing_name") or loc.get("area") or "").strip()
    marketing_name = mkt_raw if is_valid_content(mkt_raw) else ""
    city_raw = (loc.get("city") or "").strip()
    city = city_raw if is_valid_content(city_raw) else ""
    raw_travel = loc.get("travel_times", [])
    travel_times: List[str] = []
    if isinstance(raw_travel, list):
        for item in raw_travel[:3]:  # First 3 as per specification
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

    # 4. Units & Lowest Price
    units_data = data.get("units", [])
    avail_types: List[str] = []
    min_prices: List[int] = []

    if isinstance(units_data, list):
        for u in units_data:
            if isinstance(u, dict):
                u_status = str(u.get("status", "available")).lower()
                if u_status == "available":
                    u_type = u.get("type") or u.get("configuration")
                    if u_type and u_type not in avail_types:
                        avail_types.append(u_type)
                    price = u.get("price_min_inr") or u.get("price_inr") or u.get("price")
                    if price and isinstance(price, (int, float)) and price > 0:
                        min_prices.append(int(price))

    lowest_price = min(min_prices) if min_prices else None

    # Fallback price checks
    if lowest_price is None:
        p_obj = data.get("pricing", {})
        starting_p = p_obj.get("starting_price_inr") or p_obj.get("lowest_price_inr")
        if starting_p and isinstance(starting_p, (int, float)):
            lowest_price = int(starting_p)

    # 5. Site Visits
    sv = data.get("site_visits", {})
    site_visit_obj = SiteVisitInfo(
        days=str(sv.get("days", "")).strip(),
        start=str(sv.get("start", "")).strip(),
        end=str(sv.get("end", "")).strip(),
    )

    # 6. Contact Phone
    contacts = data.get("contacts", {})
    mkt_contact = contacts.get("marketing", {})
    phone_raw = (mkt_contact.get("phone") or contacts.get("phone") or "").strip()
    phone = phone_raw if is_valid_content(phone_raw) else ""

    # 7. Brand Configuration
    brand_data = data.get("brand", {})
    colours = brand_data.get("colours", {}) or brand_data.get("colors", {})
    fonts = brand_data.get("fonts", {})
    brand_obj = BrandInfo(
        primary_colour=colours.get("primary") or "#1F2A44",
        secondary_colour=colours.get("secondary") or "#C9A227",
        background_colour=colours.get("background") or "#0D1117",
        heading_font=fonts.get("heading") or "PlayfairDisplay",
        body_font=fonts.get("body") or "Inter",
    )

    # 8. Disclaimers & Extra Charges
    disclaimers = [str(d).strip() for d in data.get("disclaimers", []) if str(d).strip()]
    pricing_obj = data.get("pricing", {})
    extra_charges = [str(c).strip() for c in pricing_obj.get("extra_charges", []) if str(c).strip()]

    return ProjectData(
        name=name,
        promoter=promoter,
        status=status,
        rera_number=rera_number,
        is_verified=is_verified,
        marketing_name=marketing_name,
        city=city,
        travel_times=travel_times,
        available_units=avail_types,
        lowest_price_inr=lowest_price,
        site_visits=site_visit_obj,
        marketing_phone=phone,
        brand=brand_obj,
        disclaimers=disclaimers,
        extra_charges=extra_charges,
        raw_data=data,
    )


def filter_approved_renders(renders: List[RenderInfo], review_data: Optional[Dict[str, Any]] = None) -> List[RenderInfo]:
    """
    Filter renders to only those approved by user and not flagged with needs_review: true.
    """
    review_map = review_data or {}
    approved: List[RenderInfo] = []
    for r in renders:
        r_name = r.filename
        rev_entry = review_map.get(r_name, {})
        needs_rev = rev_entry.get("needs_review", False) if isinstance(rev_entry, dict) else False

        if r.approved and not needs_rev and not r.needs_review:
            approved.append(r)

    return approved
