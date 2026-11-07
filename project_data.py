"""
Project Data Parser & Validator
================================
Parses project JSON files matching the real-estate specification, validates
mandatory fields (especially RERA number), extracts unit availability,
brand styles, and review status.
"""

from __future__ import annotations

import json
import re
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
    description: str = ""              # What the image shows (sent to the scene planner)

    @property
    def path(self) -> Path:
        return Path(self.filepath)

    @property
    def filename(self) -> str:
        return self.path.name


DEFAULT_DISCLAIMER = "All images are artist's impressions. T&C apply."


# Infrastructure / services that are not selling amenities (never spoken or shown as chips)
_INFRA_WORDS = {
    "gate", "entrance", "lobby", "cctv", "security", "cabin", "parking", "car", "vehicular", "vehicle",
    "podium", "stp", "sewage", "transformer", "generator", "dg", "lift", "lifts", "elevator", "road",
    "roads", "compound", "boundary", "wall", "borewell", "meter", "paving", "intercom", "power",
    "backup", "water", "supply", "fire", "fighting", "rainwater", "harvesting", "solar", "waste",
    "management", "drainage", "plumbing", "wiring", "amenities", "facilities",
}
# Same thing said twice ("Club House & Gymnasium", "State of the Art Club House", "Fitness Centre")
_AMENITY_GROUPS = {
    "clubhouse": ("club house", "clubhouse", "club-house"),
    "gym": ("gym", "gymnasium", "fitness"),
    "pool": ("pool",),
    "play": ("play area", "play zone", "playground", "kids play", "children's play"),
    "jogging": ("jogging", "walking track"),
}
_PUFFERY = re.compile(r"^\s*(state[- ]of[- ]the[- ]art|world[- ]class|luxurious|luxury|premium|grand|exclusive)\s+", re.I)


def lifestyle_amenities(items: List[str]) -> List[str]:
    """Keep amenities a buyer would enjoy; drop gates, lobbies, CCTV, parking, podiums and repeats."""
    out: List[str] = []
    seen_groups: set = set()
    seen_names: set = set()
    for item in items:
        words = set(re.findall(r"[a-z]+", item.lower()))
        if words & _INFRA_WORDS:
            continue
        name = _PUFFERY.sub("", item).strip()
        low = name.lower()
        groups = {g for g, keys in _AMENITY_GROUPS.items() if any(k in low for k in keys)}
        if groups and groups <= seen_groups:
            continue
        if low in seen_names:
            continue
        seen_groups |= groups
        seen_names.add(low)
        out.append(name)
    return out


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
    primary_colour: str = "#1F2A44"    # Fallback navy
    secondary_colour: str = "#C9A227"  # Fallback gold
    background_colour: str = "#F3EFE6" # Fallback cream
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
    amenities: List[str] = field(default_factory=list)
    site_visits: SiteVisitInfo = field(default_factory=SiteVisitInfo)
    marketing_phone: str = ""
    brand: BrandConfig = field(default_factory=BrandConfig)
    disclaimers: List[str] = field(default_factory=list)
    extra_charges: List[str] = field(default_factory=list)
    raw_data: Dict[str, Any] = field(default_factory=dict)
    # Extra facts used by the scene planner's fallback chain
    max_carpet_sqft: Optional[int] = None
    possession: str = ""                # e.g. "Dec 2027"
    open_space_pct_min: Optional[float] = None
    land_area_acres: Optional[float] = None
    units_status_missing: bool = False  # some units had no "status" field
    all_units_sold_out: bool = False    # units listed, none available
    missing_fields: List[str] = field(default_factory=list)

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
    missing: List[str] = []
    proj_block = raw.get("project", {}) or {}
    name_raw = proj_block.get("name") or raw.get("name") or ""
    name = str(name_raw).strip() if is_valid_content(name_raw) else ""
    if not name:
        missing.append("project.name")
    promoter_raw = proj_block.get("promoter") or proj_block.get("developer") or raw.get("promoter") or ""
    promoter = promoter_raw if is_valid_content(promoter_raw) else ""
    if not promoter:
        missing.append("promoter")

    # 2. Location
    loc_block = raw.get("location", {}) or {}
    mkt_raw = loc_block.get("marketing_name") or loc_block.get("address") or loc_block.get("locality") or ""
    marketing_name = mkt_raw if is_valid_content(mkt_raw) else ""
    if not marketing_name:
        missing.append("location.marketing_name")
    city_raw = loc_block.get("city") or ""
    city = city_raw if is_valid_content(city_raw) else ""
    if not city:
        missing.append("location.city")

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
    if not travel_times:
        missing.append("location.travel_times")

    # Site visits & Contacts
    sv_block = raw.get("site_visits", {}) or {}
    site_visit_obj = SiteVisitInfo(
        days=str(sv_block.get("days", "")).strip(),
        start=str(sv_block.get("start", "")).strip(),
        end=str(sv_block.get("end", "")).strip(),
    )
    if not site_visit_obj.formatted_text:
        missing.append("site_visits")
    contacts_block = raw.get("contacts", {}) or {}
    mkt_contact = contacts_block.get("marketing", {}) or {}
    phone_raw = str(mkt_contact.get("phone") or contacts_block.get("phone") or "").strip()
    marketing_phone = phone_raw if is_valid_content(phone_raw) else ""
    if not marketing_phone:
        missing.append("contacts.marketing.phone")

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
    units_list = raw.get("units", []) or []
    available_units: List[str] = []
    prices: List[int] = []
    carpets: List[int] = []
    units_status_missing = False

    for u in units_list:
        if not isinstance(u, dict):
            continue
        raw_status = u.get("status")
        if not is_valid_content(raw_status):
            # Status not given: still mention the unit type, but warn the user.
            units_status_missing = True
            status = "available"
        else:
            status = str(raw_status).lower()
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
            c_sqft = u.get("carpet_sqft") or u.get("carpet_area_sqft")
            if c_sqft:
                try:
                    carpets.append(int(float(c_sqft)))
                except (ValueError, TypeError):
                    pass

    lowest_price_inr = min(prices) if prices else None
    max_carpet_sqft = max(carpets) if carpets else None
    all_units_sold_out = bool(units_list) and not available_units
    if not units_list:
        missing.append("units")
    if lowest_price_inr is None:
        missing.append("units[].price_min_inr")
    if available_units and max_carpet_sqft is None:
        missing.append("units[].carpet_sqft")

    # Amenities (optional list of amenities)
    raw_amenities = raw.get("amenities") or raw.get("amenity_list") or proj_block.get("amenities") or []
    if isinstance(raw_amenities, list):
        amenities = lifestyle_amenities([str(a).strip() for a in raw_amenities if is_valid_content(str(a))])
    else:
        amenities = []
    if not amenities:
        missing.append("amenities")

    # Possession / open space / land area (optional facts for the fallback chain)
    cs_block = raw.get("construction_status") if isinstance(raw.get("construction_status"), dict) else {}
    possession_raw = (
        raw.get("possession") or proj_block.get("possession")
        or cs_block.get("possession") or cs_block.get("possession_date") or ""
    )
    if isinstance(possession_raw, dict):
        possession_raw = possession_raw.get("date") or possession_raw.get("expected") or ""
    possession = str(possession_raw).strip() if is_valid_content(possession_raw) else ""
    if not possession:
        missing.append("possession")

    def _num(*vals: Any) -> Optional[float]:
        for v in vals:
            if v is None or v == "":
                continue
            try:
                return float(v)
            except (ValueError, TypeError):
                continue
        return None

    land_block = raw.get("land") if isinstance(raw.get("land"), dict) else {}
    open_space_pct_min = _num(
        raw.get("open_space_pct_min"), proj_block.get("open_space_pct_min"), land_block.get("open_space_pct_min"),
    )
    land_area_acres = _num(
        raw.get("land_area_acres"), proj_block.get("land_area_acres"), land_block.get("land_area_acres"),
    )

    # 5. Brand styles (fallback: navy #1F2A44, gold #C9A227, cream #F3EFE6; Playfair Display / Inter)
    brand_raw = raw.get("brand", {}) or {}
    colours = brand_raw.get("colours") or brand_raw.get("colors") or {}
    fonts = brand_raw.get("fonts") or {}
    if not colours:
        missing.append("brand.colours")
    if not fonts:
        missing.append("brand.fonts")

    brand = BrandConfig(
        primary_colour=colours.get("primary") or "#1F2A44",
        secondary_colour=colours.get("secondary") or "#C9A227",
        background_colour=colours.get("background") or "#F3EFE6",
        heading_font=fonts.get("heading") or "Playfair Display",
        body_font=fonts.get("body") or "Inter",
    )

    # 6. Disclaimers & Pricing extras
    disclaimers = [d for d in (raw.get("disclaimers") or []) if is_valid_content(d)]
    if not disclaimers:
        missing.append("disclaimers")
        disclaimers = [DEFAULT_DISCLAIMER]
    pricing_block = raw.get("pricing", {}) or {}
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
        amenities=amenities,
        site_visits=site_visit_obj,
        marketing_phone=marketing_phone,
        brand=brand,
        disclaimers=disclaimers,
        extra_charges=extra_charges,
        raw_data=raw,
        max_carpet_sqft=max_carpet_sqft,
        possession=possession,
        open_space_pct_min=open_space_pct_min,
        land_area_acres=land_area_acres,
        units_status_missing=units_status_missing,
        all_units_sold_out=all_units_sold_out,
        missing_fields=missing,
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
        if not r.approved or r.needs_review:
            continue

        # Check review dict from project JSON if present
        fname = Path(r.filepath).name
        review_entry = review_dict.get(fname) or review_dict.get(Path(r.filepath).stem)
        if isinstance(review_entry, dict) and review_entry.get("needs_review") is True:
            continue

        valid.append(r)

    return valid
