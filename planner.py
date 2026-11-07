"""
Scene Planner for Real-Estate Video Ads (render-driven)
=======================================================
Implements the scene-planning rules in prompts/scene_planner_system.txt
(full spec: docs/ad_agent_system_prompt.md).

Rule of thumb: AI may decorate and animate what the developer gave us. It must
never invent a part of the property the developer did not give us.

  - The property is shown ONLY by animating approved renders (image_to_video).
  - Text-to-video is used ONLY for tight "festive close-ups" (hands, diyas,
    flowers, sweets, sky) that never show a room, building or amenity.
  - The video structure depends on which renders exist (cases A-F).
  - Facts come only from the project JSON; missing facts use a fixed
    fallback chain and are reported in missing_fields / fallbacks_used.

Two planners share one output format (AdPlan / the JSON schema in the spec):
  - plan_video_ad():   deterministic rule engine (free, always valid)
  - plan_with_agent(): Gemini with the system prompt; its plan is validated
                       and we fall back to the rule engine if it breaks a rule.
plan_all_versions() makes the 60 s plan first and derives the 20 s and 10 s
versions from its scenes, so Veo is paid for only once.
"""

from __future__ import annotations

import json
import math
import os
import re
from dataclasses import dataclass, field
from datetime import datetime
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple

from project_data import DEFAULT_DISCLAIMER, ProjectData, RenderInfo, format_inr, is_valid_content


SYSTEM_PROMPT_PATH = Path(__file__).parent / "prompts" / "scene_planner_system.txt"

# Veo pricing (per second)
VEO_PRICING = {
    "1080p": 0.12,
    "720p": 0.09,
}

VEO_CLIP_LENGTHS = (4, 6, 8)
DEFAULT_CROSSFADE = 0.8   # seconds of fade between scenes (smoother than a quick cut)
WORDS_PER_SECOND = 2.0   # measured pace of the Indian-English voice (~2.1 words/s once silence is trimmed)
SPEC_MAX_WORDS = {10: 17, 20: 40, 60: 120}

LABEL_RENDER = "Artist's impression"
LABEL_CLOSEUP = "For illustration only"

CAMERA_MOVES = ["drone push-in", "slow orbit", "slow pan left to right", "slow tilt up", "gentle dolly-in"]

BANNED_CLAIMS = ["best", "luxury-most", "guaranteed", "lowest price", "high returns"]
PRICE_HINT_WORDS = ["affordable", "budget", "low price", "best price", "value for money"]

# Festivals that have no religious/cultural decor (generic warm look)
NEUTRAL_THEMES = ("None", "Family")


def veo_suffix(aspect: str) -> str:
    """Rule 5: every Veo prompt ends with this line."""
    return (
        " No text, no captions, no subtitles, no logos, no watermarks, no signage, no readable "
        f"writing anywhere. Photorealistic, cinematic, {aspect} framing."
    )


def load_system_prompt() -> str:
    return SYSTEM_PROMPT_PATH.read_text(encoding="utf-8")


# ═════════════════════════════════════════════════════════════════════
# Data model
# ═════════════════════════════════════════════════════════════════════

@dataclass
class PlannedScene:
    index: int
    name: str
    source_type: str                    # "render_image" | "festive_closeup" | "end_card"
    duration_seconds: float             # seconds used in the final edit (after trimming)
    kind: str = ""                      # render_exterior | render_interior | render_amenity | festive_closeup | end_card
    veo_mode: Optional[str] = None      # image_to_video | text_to_video | None (end card)
    veo_duration: int = 0               # clip length requested from Veo (4, 6 or 8)
    render_path: Optional[str] = None
    render_type: Optional[str] = None
    camera_move: str = ""
    prompt: str = ""
    label: str = ""                     # Artist's impression | For illustration only
    voiceover: str = ""
    estimated_cost_usd: float = 0.0
    is_opening: bool = False
    priority: float = 9.0               # lower = more important (used for trimming / deriving versions)
    reuses_scene_id: Optional[int] = None
    show_amenity_chips: bool = False
    has_people: bool = False

    @property
    def source_render(self) -> Optional[str]:
        return Path(self.render_path).name if self.render_path else None


@dataclass
class AdPlan:
    requested_duration: int
    final_duration: float
    endcard_duration: int
    festival: str
    aspect: str
    resolution: str
    scenes: List[PlannedScene]
    total_veo_seconds: int
    total_estimated_cost_usd: float
    crossfade_seconds: float = DEFAULT_CROSSFADE
    blocked: bool = False
    blocked_reason: Optional[str] = None
    case: str = ""
    warnings: List[str] = field(default_factory=list)
    missing_fields: List[str] = field(default_factory=list)
    fallbacks_used: List[Dict[str, str]] = field(default_factory=list)
    end_card: Dict[str, Any] = field(default_factory=dict)
    amenity_text_chips: List[str] = field(default_factory=list)
    voiceover_script: str = ""
    voiceover_word_count: int = 0
    music_prompt: str = ""
    disclaimers: List[str] = field(default_factory=list)
    show_price_asterisk: bool = True
    planner: str = "rules"              # "rules" | "gemini-agent"

    @property
    def veo_scenes(self) -> List[PlannedScene]:
        return [s for s in self.scenes if s.source_type != "end_card"]

    def to_dict(self) -> Dict[str, Any]:
        """The output JSON format defined in the system prompt."""
        scenes = []
        for s in self.veo_scenes:
            item = {
                "id": s.index,
                "kind": s.kind,
                "veo_mode": s.veo_mode,
                "source_render": s.source_render,
                "camera_move": s.camera_move,
                "duration": s.veo_duration,
                "prompt": s.prompt,
                "label": s.label,
                "voiceover": s.voiceover,
            }
            if s.duration_seconds != s.veo_duration:
                item["trimmed_to"] = round(s.duration_seconds, 2)
            if s.reuses_scene_id is not None:
                item["reuses_scene_id"] = s.reuses_scene_id
            scenes.append(item)
        return {
            "blocked": self.blocked,
            "blocked_reason": self.blocked_reason,
            "case": self.case,
            "warnings": list(self.warnings),
            "missing_fields": list(self.missing_fields),
            "fallbacks_used": list(self.fallbacks_used),
            "duration_seconds": self.requested_duration,
            "aspect_ratio": self.aspect,
            "festival": self.festival,
            "scenes": scenes,
            "end_card": {
                "duration": self.endcard_duration,
                "lines": list(self.end_card.get("lines", [])),
            },
            "amenity_text_chips": list(self.amenity_text_chips),
            "voiceover_script": self.voiceover_script,
            "voiceover_word_count": self.voiceover_word_count,
            "music_prompt": self.music_prompt,
            "veo_seconds_total": self.total_veo_seconds,
        }

    def to_table_data(self) -> List[Dict[str, Any]]:
        rows = []
        for s in self.scenes:
            if s.source_type == "end_card":
                src = "End Card (program)"
            elif s.render_path:
                src = f"Render ({Path(s.render_path).name})"
            else:
                src = "Festive close-up (AI)"
            rows.append({
                "Scene #": s.index,
                "Scene": s.name,
                "Source": src,
                "Sec": fmt_seconds(s.duration_seconds),
                "Label": s.label or "–",
                "Voiceover": s.voiceover or "–",
                "Est. Cost": f"${s.estimated_cost_usd:.2f}",
            })
        return rows


def fmt_seconds(x: float) -> str:
    return f"{int(x)}s" if float(x).is_integer() else f"{x:.1f}s"


def endcard_seconds(duration: int) -> int:
    """Rule 7: 3 s if duration <= 15, otherwise 4 s."""
    return 3 if duration <= 15 else 4


def max_voiceover_words(duration: int) -> int:
    """Words that fit before the end card at the real voice pace (never above the spec limits
    10 s -> 17, 20 s -> 40, 60 s -> 120). Long videos keep ~15% for breathing pauses.
    10 s -> 13, 20 s -> 31, 30 s -> 51, 60 s -> 95."""
    window = duration - endcard_seconds(duration) - 0.5
    words = window * WORDS_PER_SECOND * (0.85 if duration >= 45 else 1.0)
    spec = SPEC_MAX_WORDS.get(duration, int((duration - endcard_seconds(duration)) * 2.5))
    return max(8, min(spec, int(words)))


# ═════════════════════════════════════════════════════════════════════
# Speech helpers ("ninety-six lakh", "two and three B-H-K")
# ═════════════════════════════════════════════════════════════════════

_ONES = ["zero", "one", "two", "three", "four", "five", "six", "seven", "eight", "nine", "ten",
         "eleven", "twelve", "thirteen", "fourteen", "fifteen", "sixteen", "seventeen", "eighteen", "nineteen"]
_TENS = ["", "", "twenty", "thirty", "forty", "fifty", "sixty", "seventy", "eighty", "ninety"]
_MONTHS = {
    "jan": "January", "feb": "February", "mar": "March", "apr": "April", "may": "May", "jun": "June",
    "jul": "July", "aug": "August", "sep": "September", "sept": "September", "oct": "October",
    "nov": "November", "dec": "December",
}


def int_words(n: int) -> str:
    if n < 0:
        return "minus " + int_words(-n)
    if n < 20:
        return _ONES[n]
    if n < 100:
        return _TENS[n // 10] + ("-" + _ONES[n % 10] if n % 10 else "")
    if n < 1000:
        rest = n % 100
        return _ONES[n // 100] + " hundred" + (" and " + int_words(rest) if rest else "")
    for size, word in ((10_000_000, "crore"), (100_000, "lakh"), (1000, "thousand")):
        if n >= size:
            head, rest = divmod(n, size)
            if not rest:
                return f"{int_words(head)} {word}"
            joiner = " and " if rest < 100 else " "
            return f"{int_words(head)} {word}{joiner}{int_words(rest)}"
    return str(n)


def number_words(text: str) -> str:
    """'1.42' -> 'one point four two', '2.0' -> 'two point o', '1,680' -> 'sixteen hundred and eighty'."""
    t = text.replace(",", "")
    if "." in t:
        whole, frac = t.split(".", 1)
        digits = " ".join("o" if d == "0" else _ONES[int(d)] for d in frac if d.isdigit())
        return f"{int_words(int(whole or 0))} point {digits}"
    n = int(t)
    # Speak 1,100–9,999 the short way: "sixteen hundred and eighty" (not "one thousand six hundred…")
    if 1100 <= n <= 9999 and n % 1000 and (n // 100) % 10:
        hi, lo = divmod(n, 100)
        return f"{int_words(hi)} hundred" + (f" and {int_words(lo)}" if lo else "")
    return int_words(n)


def year_words(y: int) -> str:
    if 2000 <= y <= 2009:
        return "two thousand" + (f" and {_ONES[y - 2000]}" if y > 2000 else "")
    hi, lo = divmod(y, 100)
    return f"{int_words(hi)} {int_words(lo) if lo >= 10 else 'oh ' + _ONES[lo] if lo else 'hundred'}"


def price_words(amount: int) -> str:
    """9600000 -> 'ninety-six lakh'; 14200000 -> 'one point four two crore'."""
    val = float(amount)
    if val >= 10_000_000:
        num = f"{val / 10_000_000:.2f}".rstrip("0").rstrip(".")
        return f"{number_words(num)} crore"
    if val >= 100_000:
        num = f"{val / 100_000:.2f}".rstrip("0").rstrip(".")
        return f"{number_words(num)} lakh"
    return f"{int_words(int(val))} rupees"


def speak(text: str) -> str:
    """Convert display text into voiceover text (numbers and abbreviations as spoken)."""
    t = text.replace("₹", "").replace("*", "")
    t = re.sub(r"\bLakhs?\b", "lakh", t)
    t = re.sub(r"\b(Cr|Crore|Crores)\b\.?", "crore", t)
    t = t.replace("|", ",").replace("•", ",").replace("–", ",")
    t = re.sub(r"\s*&\s*", " and ", t)
    t = re.sub(r"\bsq\.?\s*ft\.?", "square feet", t, flags=re.I)
    t = re.sub(r"\bmins?\b\.?", "minutes", t)
    t = re.sub(r"\bhrs?\b\.?", "hours", t)
    t = re.sub(r"(\d+)\.0+\s*km\b", r"\1 km", t)          # "1.0 km" -> "1 km" (names like "2.0" keep "point o")
    t = re.sub(r"(?<![\d.])1\s*km\b", "one kilometre", t)
    t = re.sub(r"\s*km\b", " kilometres", t)
    t = re.sub(r"\s*%", " percent", t)
    t = re.sub(r"(\d)\s*BHK\b", r"\1 BHK", t, flags=re.I)
    t = re.sub(r"\bBHK\b", "B-H-K", t, flags=re.I)
    # Month abbreviations + years: "Dec 2027" -> "December twenty twenty-seven"
    def _month_year(m: re.Match) -> str:
        month = _MONTHS.get(m.group(1).lower()[:3], m.group(1))
        return f"{month} {year_words(int(m.group(2)))}"
    t = re.sub(r"\b(Jan|Feb|Mar|Apr|May|Jun|Jul|Aug|Sept?|Oct|Nov|Dec)[a-z]*\.?\s+(\d{4})\b", _month_year, t)
    # Remaining acronyms: "ITPL" -> "I-T-P-L"
    t = re.sub(r"\b(?!B-H-K)([A-Z]{2,5})\b", lambda m: "-".join(m.group(1)), t)
    t = re.sub(r"\d[\d,]*(?:\.\d+)?", lambda m: number_words(m.group(0)), t)
    t = re.sub(r"\s+,", ",", t)
    t = re.sub(r",\s*,", ",", t)
    return re.sub(r"\s{2,}", " ", t).strip()


def _sentence(text: str) -> str:
    text = text.strip()
    if not text:
        return ""
    text = text[0].upper() + text[1:]
    return text if text[-1] in ".!?" else text + "."


def word_count(text: str) -> int:
    return len(text.split()) if text and text.strip() else 0


# ═════════════════════════════════════════════════════════════════════
# Facts & fallbacks (selling-line chain from the system prompt)
# ═════════════════════════════════════════════════════════════════════

def format_possession(raw: str) -> str:
    """'2027-12-31' / '2027-12' / 'December 2027' -> 'Dec 2027'."""
    raw = (raw or "").strip()
    for fmt in ("%Y-%m-%d", "%Y-%m", "%B %Y", "%b %Y", "%m/%Y", "%d-%m-%Y"):
        try:
            return datetime.strptime(raw, fmt).strftime("%b %Y")
        except ValueError:
            continue
    return raw


def _fmt_num(x: float) -> str:
    return str(int(x)) if float(x).is_integer() else f"{x:g}"


@dataclass
class Fact:
    kind: str       # price | units_size | location | amenities | open_space | possession | enquire
    display: str    # end-card / on-screen text
    spoken: str     # voiceover sentence
    spoken_short: str = ""   # shorter form for 10 s versions
    spoken_tiny: str = ""    # shortest form


def available_unit_prices(project: ProjectData) -> List[Tuple[str, int]]:
    out: List[Tuple[str, int]] = []
    for u in project.raw_data.get("units", []) or []:
        if not isinstance(u, dict):
            continue
        status = str(u.get("status") or "available").lower()
        if status not in ("available", "open", "active", "for_sale"):
            continue
        p = u.get("price_min_inr") or u.get("price_min") or u.get("price")
        t = u.get("type") or u.get("type_name") or u.get("name")
        try:
            if t and p:
                out.append((str(t), int(p)))
        except (TypeError, ValueError):
            continue
    return out


def build_facts(project: ProjectData) -> List[Fact]:
    """Ordered selling lines; the first one is the main selling line."""
    facts: List[Fact] = []
    has_units = bool(project.available_units) and not project.all_units_sold_out
    units = project.formatted_units_summary if has_units else ""

    # 1. Price
    if has_units and project.lowest_price_inr:
        price = format_inr(project.lowest_price_inr)
        pw = price_words(project.lowest_price_inr)
        facts.append(Fact(
            "price",
            f"{units} Homes from {price}*",
            _sentence(f"{speak(units)} homes from {pw}"),
            _sentence(f"{speak(units)} from {pw}"),
            _sentence(f"Homes from {pw}"),
        ))
    # 2. Unit types + size
    if has_units:
        if project.max_carpet_sqft:
            disp = f"Spacious {units} Homes, up to {project.max_carpet_sqft:,} sq ft carpet"
        else:
            disp = f"Spacious {units} Homes"
        short = _sentence(f"Spacious {speak(units)} homes")
        long_form = (_sentence(f"Spacious {speak(units)} homes, up to {speak(f'{project.max_carpet_sqft:,} sq ft')} carpet")
                     if project.max_carpet_sqft else short)
        facts.append(Fact("units_size", disp, long_form, short))
    # 3. Location (travel times)
    if project.travel_times:
        disp = " | ".join(project.travel_times[:2])
        spoken = " and ".join(speak(t) for t in project.travel_times[:2])
        facts.append(Fact("location", disp, _sentence(f"Just {spoken}")))
    # 4. Amenities (up to 3)
    if project.amenities:
        am = project.amenities[:3]
        disp = " • ".join(am)
        spoken = am[0] if len(am) == 1 else ", ".join(am[:-1]) + " and " + am[-1]
        facts.append(Fact("amenities", disp, _sentence(f"With {spoken.lower().replace(' & ', ' and ')}")))
    # 5. Open space / land
    pct, acres = project.open_space_pct_min, project.land_area_acres
    if pct and acres:
        disp = f"{_fmt_num(pct)}% open space on {_fmt_num(acres)} acres"
    elif pct:
        disp = f"{_fmt_num(pct)}% open space"
    elif acres:
        disp = f"Spread across {_fmt_num(acres)} acres"
    else:
        disp = ""
    if disp:
        facts.append(Fact("open_space", disp, _sentence(speak(disp))))
    # 6. Possession
    if project.possession:
        disp = f"Possession {format_possession(project.possession)}"
        facts.append(Fact("possession", disp, _sentence(speak(disp))))
    # 7. Nothing else
    if not facts:
        facts.append(Fact("enquire", "Enquire now to know more", "Enquire now to know more."))
    return facts


def location_line(project: ProjectData) -> str:
    if project.marketing_name and project.city and project.city.lower() not in project.marketing_name.lower():
        return f"{project.marketing_name}, {project.city}"
    return project.marketing_name or project.city or ""


def cta_line(project: ProjectData) -> str:
    """End-card CTA with fallbacks."""
    sv = project.site_visits.formatted_text
    if sv:
        return sv
    if project.marketing_phone:
        return f"Call {project.marketing_phone} to know more"
    return "Enquire today"


def cta_spoken(project: ProjectData) -> str:
    days = (project.site_visits.days or "").strip() if is_valid_content(project.site_visits.days) else ""
    if days:
        if re.search(r"sat|sun|weekend", days, re.I):
            return "Book your site visit this weekend."
        return _sentence(f"Book your site visit, {speak(days)}")
    if project.marketing_phone:
        return "Call now to know more."
    return "Enquire today."


def resolve_disclaimers(project: ProjectData, has_price: bool) -> List[str]:
    discs = [d for d in (project.disclaimers or []) if is_valid_content(d)] or [DEFAULT_DISCLAIMER]
    if not has_price:
        # Remove the "*" price-exclusion disclaimer when no price is shown.
        discs = [d for d in discs if not (d.strip().startswith("*") or re.search(r"price\s+exclu", d, re.I))]
        discs = discs or [DEFAULT_DISCLAIMER]
    return discs


def music_prompt_for(festival: str, duration: int) -> str:
    if festival in NEUTRAL_THEMES:
        return "Warm, elegant Indian fusion instrumental, soft piano with sitar, no vocals"
    return (
        f"Joyful Indian festive instrumental for {festival}: shehnai and sitar melody, tabla and soft "
        f"dholak rhythm, light temple bells, warm and celebratory, no vocals, {duration} seconds, gentle ending."
    )


def build_end_card(project: ProjectData, festival: str, facts: List[Fact], logo_available: bool) -> Dict[str, Any]:
    offer = facts[0].display if facts else ""
    card = {
        "name": project.name,
        "promoter_line": f"by {project.promoter}" if project.promoter else "",
        "offer_line": offer,
        "location_line": location_line(project),
        "cta_line": cta_line(project),
        "greeting_line": f"Happy {festival}!" if festival not in NEUTRAL_THEMES else "",
        "use_logo": logo_available,
        "rera": project.rera_number,
    }
    card["lines"] = [card[k] for k in ("name", "promoter_line", "offer_line", "location_line", "cta_line", "greeting_line") if card[k]]
    return card


# ═════════════════════════════════════════════════════════════════════
# Voiceover
# ═════════════════════════════════════════════════════════════════════

_FESTIVAL_HOOKS = {
    "Diwali": "light up a new beginning at",
    "Ugadi": "begin a new year at",
    "Dussehra": "celebrate a new beginning at",
    "Ganesh Chaturthi": "welcome a new beginning at",
    "Onam": "welcome a new home at",
    "Pongal/Sankranti": "celebrate a fresh start at",
    "Christmas": "come home for the holidays to",
    "Eid": "celebrate togetherness at",
    "New Year": "start the year fresh at",
}


def _opening_variants(project: ProjectData, festival: str, style: str) -> List[str]:
    name = project.name
    loc = project.marketing_name or project.city
    with_loc = f", {loc}" if loc else ""
    if festival == "Family":
        first = [f"A home for your whole family at {name}{with_loc}.", f"A home for your family at {name}."]
    elif festival == "None":
        first = [f"Come home to {name}{with_loc}.", f"Come home to {name}."]
    else:
        hook = _FESTIVAL_HOOKS.get(festival, "come home to")
        first = [
            f"This {festival}, {hook} {name}{with_loc}.",
            f"This {festival}, come home to {name}{with_loc}.",
            f"This {festival}, discover {name}{with_loc}.",
            f"This {festival}, come home to {name}.",
        ]
    if style == "location" and loc:
        first = [f"Your new address in {loc}: {name}.", f"Welcome to {name}."] + first
    elif style == "direct":
        first = [f"{name}{with_loc}.", f"{name}."] + first
    return first + [f"{name}."]


def build_voiceover_sentences(
    project: ProjectData,
    festival: str,
    duration: int,
    style: str = "festive",
    budget: Optional[int] = None,
) -> List[str]:
    """Fact-only voiceover, within the word limit for the length preset."""
    budget = budget or max_voiceover_words(duration)
    facts = build_facts(project)
    short = duration <= 12
    long = duration >= 45

    body: List[Tuple[int, str]] = []   # (drop priority: higher drops first, sentence)
    main = facts[0]
    body.append((0, main.spoken))

    if not short:
        rest = list(facts[1:])
        if main.kind == "price":
            # Unit types are already in the price line: only the carpet area is a new fact.
            rest = [f for f in rest if f.kind != "units_size"]
            if project.max_carpet_sqft:
                rest.insert(0, Fact("carpet", "", _sentence(
                    f"Carpet areas up to {speak(f'{project.max_carpet_sqft:,} sq ft')}")))
        extras = rest[:2] if long else rest[:1]
        for i, f in enumerate(extras):
            body.append((3 + i, f.spoken))
        if long:
            used = {main.kind} | {f.kind for f in extras}
            # 60 s may mention unit types with prices, up to 3 travel times, 4 amenities, possession.
            unit_prices = available_unit_prices(project)
            if "price" in used and len(unit_prices) > 1:
                parts = [f"{speak(t)} from {price_words(p)}" for t, p in unit_prices]
                body[0] = (0, _sentence(", and ".join(parts)))
            if "location" in used and len(project.travel_times) > 2:
                for i, (p, s) in enumerate(body):
                    if s.startswith("Just "):
                        spoken = ", ".join(speak(t) for t in project.travel_times[:3])
                        body[i] = (p, _sentence(f"Just {spoken}"))
            elif "location" not in used and project.travel_times:
                spoken = ", ".join(speak(t) for t in project.travel_times[:3])
                body.append((6, _sentence(f"Just {spoken}")))
            if "amenities" in used and len(project.amenities) > 3:
                for i, (p, s) in enumerate(body):
                    if s.startswith("With "):
                        am = [a.lower().replace(" & ", " and ") for a in project.amenities[:4]]
                        body[i] = (p, _sentence("With " + ", ".join(am[:-1]) + " and " + am[-1]))
            elif "amenities" not in used and project.amenities:
                am = [a.lower().replace(" & ", " and ") for a in project.amenities[:4]]
                spoken = am[0] if len(am) == 1 else ", ".join(am[:-1]) + " and " + am[-1]
                body.append((7, _sentence(f"With {spoken}")))
            if "possession" not in used and project.possession:
                body.append((8, _sentence(speak(f"Possession {format_possession(project.possession)}"))))
            if festival not in NEUTRAL_THEMES:
                body.append((9, f"Celebrate this {festival} in a home of your own."))
        cta = cta_spoken(project)
        if not project.lowest_price_inr:
            if cta == "Enquire today.":
                cta = "Enquire today for price details."
            else:
                body.append((5, "Enquire now for price details."))
        body.append((1, cta))   # CTA (not in 10 s: it is on the end card)

    # Never repeat a sentence
    seen, uniq = set(), []
    for p, s in body:
        if s and s not in seen:
            seen.add(s)
            uniq.append((p, s))
    body = uniq

    openings = _opening_variants(project, festival, style)
    mains = list(dict.fromkeys(x for x in (body[0][1], main.spoken_short, main.spoken_tiny) if x))
    attempts = [(o, m) for o in openings for m in mains]
    for opening, main_text in attempts:
        sentences = [(-1, opening)] + [(p, main_text if p == 0 else s) for p, s in body]
        while sum(word_count(s) for _, s in sentences) > budget:
            droppable = [x for x in sentences if x[0] >= 2]
            if not droppable:
                break
            sentences.remove(max(droppable, key=lambda x: x[0]))
        if sum(word_count(s) for _, s in sentences) <= budget:
            # Keep spoken order: opening, facts (in chain order), extras, CTA last
            ordered = [s for p, s in sentences if p == -1]
            ordered += [s for p, s in sentences if p not in (-1, 1)]
            ordered += [s for p, s in sentences if p == 1]
            return ordered
    return [openings[-1], main.spoken]


def split_sentences(script: str) -> List[str]:
    parts = re.split(r"(?<=[.!?।])\s+", script.strip())
    return [p.strip() for p in parts if p.strip()]


def assign_voiceover(scenes: List[PlannedScene], sentences: List[str], crossfade: float) -> float:
    """Assign each sentence to the scene where it starts. Returns the time the voice ends."""
    for s in scenes:
        s.voiceover = ""
    if not scenes:
        return 0.0
    starts, t = [], 0.0
    for i, s in enumerate(scenes):
        starts.append(t)
        t += s.duration_seconds - crossfade
    total_time = t
    speech = sum(word_count(x) / WORDS_PER_SECOND for x in sentences)
    gap = 0.3
    if sentences:
        gap = min(3.0, max(0.3, (total_time - 0.6 - speech) / len(sentences)))
    cursor = 0.3
    for sent in sentences:
        idx = max(i for i, st in enumerate(starts) if st <= cursor + 1e-6)
        # If the sentence would cross into the next scene, start it at the next scene when that fits better
        length = word_count(sent) / WORDS_PER_SECOND
        remaining = sum(word_count(x) for x in sentences[sentences.index(sent):]) / WORDS_PER_SECOND
        if (scenes[idx].voiceover and idx + 1 < len(scenes) and cursor + length > starts[idx + 1] + 0.5
                and starts[idx + 1] + remaining <= total_time):
            idx += 1
            cursor = max(cursor, starts[idx])
        scenes[idx].voiceover = (scenes[idx].voiceover + " " + sent).strip()
        cursor += length + gap
    return cursor - gap + 0.3


def check_script(script: str, project: ProjectData, budget: int) -> List[str]:
    """Warnings for a user-provided script (it is used exactly as written)."""
    warnings: List[str] = []
    wc = word_count(script)
    if wc > budget:
        warnings.append(f"Your script has {wc} words; the limit for this length is {budget}. It may run into the end card.")
    low = script.lower()
    for w in BANNED_CLAIMS:
        if re.search(rf"\b{re.escape(w)}\b", low):
            warnings.append(f"Script uses the claim \"{w}\", which is not allowed in RERA-compliant ads.")
    if not project.lowest_price_inr:
        for w in PRICE_HINT_WORDS:
            if re.search(rf"\b{re.escape(w)}\b", low):
                warnings.append(f"Script hints at price (\"{w}\") but the project JSON has no price.")
    raw_json = json.dumps(project.raw_data, ensure_ascii=False).lower()
    known = set(re.findall(r"\d+(?:\.\d+)?", raw_json.replace(",", "")))
    for f in build_facts(project):
        known |= set(re.findall(r"\d+(?:\.\d+)?", f.display.replace(",", "")))
    unknown = [n for n in re.findall(r"\d+(?:\.\d+)?", script.replace(",", "")) if n not in known]
    if unknown:
        warnings.append(f"Script mentions numbers not found in the project JSON: {', '.join(sorted(set(unknown)))}.")
    return warnings


# ═════════════════════════════════════════════════════════════════════
# Veo prompts
# ═════════════════════════════════════════════════════════════════════

_MOVE_PHRASE = {
    "drone push-in": "drone push-in",
    "slow orbit": "orbit",
    "slow pan left to right": "pan left to right",
    "slow tilt up": "tilt up",
    "gentle dolly-in": "dolly-in",
}
_EXTERIOR_PREP = {"drone push-in": "toward", "slow orbit": "around", "slow pan left to right": "across",
                  "slow tilt up": "up over", "gentle dolly-in": "toward"}

_INTERIOR_DECOR = {
    "Diwali": "lit brass diyas, marigold garlands and a small flower rangoli",
    "Ugadi": "a fresh mango-leaf toran, marigold flowers and a small rangoli",
    "Dussehra": "marigold garlands and lit brass lamps",
    "Ganesh Chaturthi": "fresh flower garlands and lit brass lamps",
    "Onam": "a small pookalam flower carpet and lit brass lamps",
    "Pongal/Sankranti": "a small kolam and fresh sugarcane stalks",
    "Christmas": "a small lit Christmas tree and a glowing star lantern",
    "Eid": "glowing hanging lanterns and soft candles",
    "New Year": "warm golden string lights and a few candles",
}
_AMENITY_LIGHTS = {
    "Diwali": "warm string lights and diyas around it",
    "Christmas": "warm string lights and star lanterns around it",
    "Eid": "warm string lights and glowing lanterns around it",
}
_SKY_FESTIVALS = ("Diwali", "New Year")


def render_prompt(render_type: str, camera_move: str, festival: str, aspect: str,
                  people: Optional[bool] = None) -> str:
    """people: None = default (interiors and amenities have people, exteriors don't)."""
    if people is None:
        people = render_type in ("interior", "amenity")
    phrase = _MOVE_PHRASE.get(camera_move, camera_move)
    if render_type == "exterior":
        prep = _EXTERIOR_PREP.get(camera_move, "toward")
        if festival == "Family":
            setting = ("on a bright, sunny morning. Soft natural sunlight on the facade, trees and "
                       "landscaping, a clear blue sky.")
        elif festival == "None":
            setting = "at golden hour. Warm light glowing in the windows, a soft amber sky."
        else:
            sky = "gentle fireworks in the distant sky" if festival in _SKY_FESTIVALS else "a soft warm glow in the evening sky"
            setting = (f"at dusk during {festival}. Warm golden fairy lights on the balconies, a few "
                       f"glowing lanterns, {sky}.")
        base = (
            f"Slow, cinematic {phrase} {prep} the residential buildings in this image, {setting} "
            "Keep the buildings EXACTLY as in the image: same number of towers, same height, shape, "
            "facade and colours. Do not add, remove or reshape any building."
            + (render_people("exterior", festival) if people else " No people.")
        )
    elif render_type == "interior":
        if festival == "Family":
            dressing = "filled with soft natural morning light."
            light = ""
        elif festival == "None":
            dressing = "softly lit with warm lamps and a few candles."
            light = ""
        else:
            dressing = f"decorated for {festival} with {_INTERIOR_DECOR.get(festival, 'marigold garlands and lit brass lamps')}."
            light = " Warm evening light."
        base = (
            f"Slow, smooth cinematic {phrase} through this room exactly as shown in the image, {dressing}"
            f"{render_people('interior', festival) if people else ' No people.'} "
            f"Keep the room layout, furniture, windows and finishes exactly as in the image.{light}"
        )
    else:  # amenity
        if festival == "Family":
            setting = "in bright daytime sunlight."
        elif festival == "None":
            setting = "in soft golden-hour evening light."
        else:
            setting = f"in the evening during {festival}, with {_AMENITY_LIGHTS.get(festival, 'warm string lights and lamps around it')}."
        base = (
            f"Slow, cinematic {phrase} across this amenity exactly as shown in the image, {setting}"
            f"{render_people('amenity', festival) if people else ' No people.'} "
            "Keep the architecture, water, landscaping and furniture exactly as in the image."
        )
    return base + veo_suffix(aspect)


_SAREE_BY_FESTIVAL = {
    "Onam": "a cream and gold kasavu saree",
    "Christmas": "a red and gold silk saree",
    "Eid": "an emerald green and gold silk saree",
    "New Year": "a midnight-blue and silver silk saree",
    "Pongal/Sankranti": "a turmeric-yellow and green silk saree",
}


def _person(festival: str) -> str:
    """ONE person description for the whole video.
    Festive and Family themes: an Indian woman in a saree. Standard ("None"): a professional."""
    if festival == "None":
        return "a confident Indian woman professional in her early 30s wearing a tailored navy business suit"
    saree = _SAREE_BY_FESTIVAL.get(festival, "an elegant maroon and gold silk saree")
    return f"a graceful Indian woman in her early 30s with jasmine flowers in her hair, wearing {saree}"


_FESTIVE_ACTION = {
    "Diwali": "kneels and lights a brass diya",
    "Ugadi": "hangs a fresh mango-leaf toran at the doorway",
    "Dussehra": "places a marigold garland",
    "Ganesh Chaturthi": "arranges fresh flowers beside a small brass lamp",
    "Onam": "places flower petals on the pookalam",
    "Pongal/Sankranti": "draws a small kolam on the floor",
    "Christmas": "hangs a glowing ornament on the Christmas tree",
    "Eid": "lights a hanging lantern",
    "New Year": "lights a few candles",
}
_FAMILY = "an Indian family in festive traditional clothes"
# Family theme: only these four people (husband, wife and two children)
_NUCLEAR_FAMILY = ("an Indian husband and wife with their two young children, a boy and a girl, all four in "
                   "festive traditional clothes")
PEOPLE_GUARD = (
    " The people walk in smoothly from the edge of the frame at the start of the shot; nobody appears, "
    "disappears or changes suddenly. Keep them in the foreground at medium distance, faces sharp, well lit "
    "and clearly visible with natural, realistic features that stay consistent from frame to frame; no "
    "blurry, distorted or morphing faces. Do not change, move or cover the architecture, furniture or layout."
)


def render_people(render_type: str, festival: str) -> str:
    """Themed people for render scenes. Amenities and exteriors: one woman simply walking
    (Family theme: the family of four). Interiors: the woman (and her son) at the festive decor."""
    woman = _person(festival)
    W = woman[0].upper() + woman[1:]
    family = _NUCLEAR_FAMILY[0].upper() + _NUCLEAR_FAMILY[1:]
    if render_type == "interior":
        if festival == "None":
            line = (f"{W} walks into the room from the left, pauses in the foreground by the window and "
                    "turns to the camera with a calm smile.")
        elif festival == "Family":
            line = (f"{family} walk into the room together from the left, the children holding their parents' "
                    "hands, and stop in the foreground smiling at each other; the wife wears a silk saree. "
                    "Only these four people, no one else.")
        else:
            action = _FESTIVE_ACTION.get(festival, "lights a brass lamp")
            line = (f"{W} walks into the room from the left with her young son in festive traditional clothes "
                    f"beside her; in the foreground she {action} while the boy watches and smiles. "
                    "Only these two people.")
    elif render_type in ("amenity", "exterior"):
        where = "along the path through this amenity" if render_type == "amenity" else \
            "along the landscaped path in the foreground, in front of the buildings"
        if festival == "Family":
            line = (f"{family} walk slowly {where} from the left, the children holding their parents' hands; "
                    "the wife wears a silk saree. Only these four people, no one else.")
        else:
            line = (f"{W} walks slowly {where} from the left, enjoying the space, and glances at the "
                    "camera with a gentle smile. Only this one person, no one else.")
    else:
        return ""
    return " " + line + PEOPLE_GUARD


# Decor-only AI close-ups (no people). Used only when a long video runs out of renders.
_CLOSEUPS: Dict[str, List[Tuple[str, str]]] = {
    "Diwali": [
        ("row of diyas", "Close-up of a row of lit brass diyas flickering beside marigold flowers, background melting into warm bokeh."),
        ("rangoli", "Top-down close-up of a colourful flower rangoli with lit diyas around it, background softly blurred."),
        ("sweets and diyas", "Close-up of a plate of Indian sweets beside lit diyas on a festive cloth, background blurred."),
        ("fireworks in the sky", "Close-up of colourful fireworks blooming in the dark night sky, only the sky in frame, no buildings or rooftops."),
    ],
    "Ugadi": [
        ("mango-leaf toran", "Close-up of a fresh mango-leaf toran with marigold flowers swaying gently, background softly blurred."),
        ("rangoli", "Top-down close-up of a colourful rangoli with fresh flowers, background softly blurred."),
        ("brass lamp", "Extreme close-up of a lit brass lamp beside jasmine flowers, background in warm bokeh."),
    ],
    "Dussehra": [
        ("marigold garlands", "Close-up of marigold garlands and lit brass lamps, background softly blurred."),
        ("brass lamp", "Extreme close-up of a lit brass lamp with marigold petals around it, background in warm bokeh."),
    ],
    "Ganesh Chaturthi": [
        ("flowers and lamps", "Close-up of fresh flowers and small lit brass lamps, background softly blurred."),
        ("modak plate", "Close-up of a plate of modak sweets with marigold flowers, background blurred."),
    ],
    "Onam": [
        ("pookalam", "Top-down close-up of a vibrant pookalam flower carpet, petals moving gently, background softly blurred."),
        ("nilavilakku lamp", "Extreme close-up of a lit brass nilavilakku lamp with flowers, background in warm bokeh."),
    ],
    "Pongal/Sankranti": [
        ("kolam", "Top-down close-up of a white kolam pattern with marigold petals, background softly blurred."),
        ("kites in the sky", "Close-up of colourful kites flying in a clear blue sky, only the sky in frame, no buildings."),
    ],
    "Christmas": [
        ("tree lights", "Close-up of warm fairy lights and ornaments on pine branches, background in soft bokeh."),
        ("star lantern", "Close-up of a glowing star lantern swaying gently, background softly blurred."),
    ],
    "Eid": [
        ("lanterns", "Close-up of intricate hanging lanterns glowing softly, background in warm bokeh."),
        ("crescent moon", "Close-up of a thin crescent moon in the evening sky, only the sky in frame, no buildings."),
    ],
    "New Year": [
        ("fireworks in the sky", "Close-up of fireworks blooming in the night sky, only the sky in frame, no buildings or rooftops."),
        ("string lights", "Extreme close-up of warm golden string lights twinkling, background softly blurred."),
    ],
    "None": [
        ("candle flame", "Extreme close-up of warm candle flames flickering, background in soft golden bokeh."),
        ("fresh flowers", "Close-up of fresh white flowers in a glass vase in golden-hour light, background softly blurred."),
    ],
    "Family": [
        ("morning light", "Close-up of sunlight streaming through soft sheer curtains, background softly blurred."),
        ("fresh flowers", "Close-up of fresh flowers in a vase in warm morning light, background softly blurred."),
    ],
}
CLOSEUP_GUARD = (
    " Tight framing on decorations only: no people, no faces, no hands, no full room, no building,"
    " no amenity visible. Slow, steady motion with no sudden changes."
)


def closeup_shot(festival: str, idx: int, aspect: str) -> Tuple[str, str]:
    shots = _CLOSEUPS.get(festival) or _CLOSEUPS["None"]
    name, text = shots[idx % len(shots)]
    text = text.replace("{p}'s hands ", "the hands of {p}, ").replace("{p}'s hand ", "the hand of {p}, ")
    if idx >= len(shots):
        text = text.replace("Close-up", "Different-angle close-up", 1)
    return name, text.format(p=_person(festival)) + CLOSEUP_GUARD + veo_suffix(aspect)


# ═════════════════════════════════════════════════════════════════════
# Case detection & scene selection
# ═════════════════════════════════════════════════════════════════════

def detect_case(renders: List[RenderInfo]) -> str:
    types = {r.render_type for r in renders}
    has_ext, has_int, has_am = "exterior" in types, "interior" in types, "amenity" in types
    if not renders:
        return "F"
    if has_ext and has_int and has_am:
        return "A"
    if has_ext and has_am:
        return "B"
    if has_ext and has_int:
        return "C"
    if has_ext:
        return "D"
    return "E"


@dataclass
class _Cand:
    kind: str                       # exterior | interior | amenity | closeup
    render: Optional[RenderInfo]
    move: str
    keep: float                     # lower = more important
    group: int                      # position group in the final order
    seq: float
    closeup_idx: int = -1
    is_reuse: bool = False
    is_opening: bool = False
    cap: int = 8                    # max usable seconds (derived versions are capped by the cached clip)
    source: Optional[PlannedScene] = None
    people: bool = False            # scene shows people (woman walking etc.)


def _first_move(rtype: str, is_opening: bool) -> str:
    if rtype == "exterior":
        return "drone push-in" if is_opening else "slow orbit"
    return "gentle dolly-in" if rtype == "interior" else "slow pan left to right"


def _reuse_move(rtype: str, first: str, case: str) -> str:
    prefs = {
        "exterior": ["slow pan left to right" if case == "D" else "slow tilt up", "slow tilt up", "slow orbit"],
        "interior": ["slow pan left to right", "slow orbit"],
        "amenity": ["slow orbit", "gentle dolly-in"],
    }.get(rtype, CAMERA_MOVES)
    for m in prefs + CAMERA_MOVES:
        if m != first:
            return m
    return CAMERA_MOVES[0]


def _build_candidates(case: str, renders: List[RenderInfo], max_closeups: int = 10) -> List[_Cand]:
    """Scene candidates in priority order. People come from the renders (a woman walking through an
    amenity, the family at an interior); AI close-ups are decor-only and used only when renders run out."""
    ext = [r for r in renders if r.render_type == "exterior"]
    inte = [r for r in renders if r.render_type == "interior"]
    amen = [r for r in renders if r.render_type == "amenity"]
    cands: List[_Cand] = []

    def prim(r: RenderInfo, group: int, seq: float, keep: float, opening: bool = False) -> _Cand:
        c = _Cand(r.render_type, r, _first_move(r.render_type, opening), keep, group, seq, is_opening=opening,
                  people=r.render_type in ("interior", "amenity"))
        cands.append(c)
        return c

    if case == "E":
        # No exterior: open on an amenity (woman walking) or an interior – never a building
        body = amen + inte
        prim(body[0], 0, 0, 0.0, opening=True)
        for i, r in enumerate(body[1:]):
            prim(r, 1 if r.render_type == "amenity" else 2, i, 1 + 0.01 * i)
    else:
        prim(ext[0], 0, 0, 0.0, opening=True)
        if case == "A":
            order = [(amen, 1), (inte, 2), (ext[1:], 3)]
        elif case == "B":
            order = [(amen, 1), (ext[1:], 2)]
        elif case == "C":
            order = [(inte, 1), (ext[1:], 2)]
        else:  # D
            order = [(ext[1:], 2)]
        i = 0
        for lst, grp in order:
            for j, r in enumerate(lst):
                prim(r, grp, j, 1 + 0.01 * i)
                i += 1

    # Reuses (each render at most twice, different camera move)
    primaries = [c for c in cands if c.render is not None]
    reuse_order = sorted(primaries, key=lambda c: (c.render.render_type != "exterior", c.keep))
    reuses = [
        _Cand(c.kind, c.render, _reuse_move(c.kind, c.move, case), 0, 5, 0, is_reuse=True,
              people=c.kind in ("interior", "amenity"))
        for c in reuse_order
    ]
    if case == "D" and reuses:
        # D: same exterior, different camera move, with a woman walking along the path in front
        r0 = reuses.pop(0)
        r0.keep, r0.group, r0.seq, r0.people = 1.5, 1, 0, True
        cands.append(r0)
    ext_reuse_last = None
    if case == "B" and reuses and reuses[0].render is ext[0]:
        ext_reuse_last = reuses.pop(0)   # B: second exterior move comes last
    tail: List[_Cand] = list(reuses)
    if ext_reuse_last is not None:
        tail.append(ext_reuse_last)
    for rank, c in enumerate(tail):
        c.keep = 2 + 0.01 * rank
        c.seq = rank
        if case == "B" and c.render is (ext[0] if ext else None):
            c.group = 6
    cands.extend(tail)
    # Decor-only AI close-ups: last resort when every render has been used twice
    for k in range(max_closeups):
        cands.append(_Cand("closeup", None, "", 3 + 0.01 * k, 5, 100 + k, closeup_idx=k))
    return cands


def _adjusted_keep(cands: List[_Cand], case: str, duration: int) -> Dict[int, float]:
    """Short videos: the first scene with people comes right after the opening."""
    keep = {id(c): c.keep for c in cands}
    if duration <= 25:
        ordered = sorted(cands, key=lambda c: c.keep)
        people = next((c for c in ordered if not c.is_opening and c.people), None)
        if people is not None:
            keep[id(people)] = 0.5
    return keep


def _preferred_clip_count(duration: int, endcard: int) -> int:
    if duration <= 12:
        return 2   # opening + one festive close-up (every video has at least one close-up)
    if 16 <= duration <= 25:
        return 3
    if duration >= 50:
        return 8
    return max(1, round((duration - endcard) / 6.5))


def _choose_durations(
    chosen: List[_Cand], keep: Dict[int, float], total: int,
) -> Optional[List[int]]:
    """Distribute `total` seconds over clips (each 4/6/8, never above its cap)."""
    n = len(chosen)
    caps = [max(4, min(8, c.cap)) for c in chosen]
    if not (4 * n <= total <= sum(caps)):
        return None
    durs = [min(6, cap) for cap in caps]
    diff = total - sum(durs)
    # Upgrades: opening first, then most important; downgrades: least important (close-ups) first
    up_order = sorted(range(n), key=lambda i: (not chosen[i].is_opening, keep[id(chosen[i])]))
    down_order = sorted(range(n), key=lambda i: (chosen[i].is_opening, -keep[id(chosen[i])]))
    guard = 0
    while diff != 0 and guard < 100:
        guard += 1
        if diff > 0:
            i = next((i for i in up_order if durs[i] + 2 <= caps[i]), None)
            if i is None:
                return None
            durs[i] += 2
            diff -= 2
        else:
            i = next((i for i in down_order if durs[i] - 2 >= 4), None)
            if i is None:
                return None
            durs[i] -= 2
            diff += 2
    if diff != 0:
        return None
    # Prefer a strong 8 s opening (e.g. 8 + 6 + 4) over flat 6 + 6 + 6
    o = next((i for i in range(n) if chosen[i].is_opening), None)
    if o is not None and durs[o] + 2 <= caps[o]:
        j = next((i for i in down_order if i != o and durs[i] >= 6), None)
        if j is not None:
            durs[o] += 2
            durs[j] -= 2
    return durs


def _select_and_time(
    cands: List[_Cand], case: str, duration: int, endcard: int, crossfade: float,
) -> Tuple[List[_Cand], List[int], float]:
    """Pick the clips and their Veo lengths. Returns (clips in order, veo durations, trim on last clip)."""
    keep = _adjusted_keep(cands, case, duration)
    by_keep = sorted(cands, key=lambda c: keep[id(c)])
    pref = min(_preferred_clip_count(duration, endcard), len(by_keep))
    tried = []
    for delta in (0, -1, 1, -2, 2, -3, 3, 4, 5):
        n = pref + delta
        if n < 1 or n > len(by_keep) or n in tried:
            continue
        tried.append(n)
        chosen = by_keep[:n]
        # Every video gets at least one scene with people (a woman walking through an amenity etc.)
        if n >= 2 and not any(c.people for c in chosen):
            extra = next((c for c in by_keep[n:] if c.people), None)
            if extra is not None:
                chosen = chosen[:-1] + [extra]
        lo = duration - endcard + n * crossfade
        total = math.ceil(lo - 1e-9)
        if total % 2:
            total += 1
        total = max(total, 4 * n)
        if total + endcard - n * crossfade > duration + 2:
            continue
        durs = _choose_durations(chosen, keep, total)
        if durs is None:
            continue
        pairs = sorted(zip(chosen, durs), key=lambda p: (p[0].group, p[0].seq))
        excess = total + endcard - n * crossfade - duration
        return [p[0] for p in pairs], [p[1] for p in pairs], max(0.0, excess)
    raise ValueError("Could not fit the scenes into the requested length.")


# ═════════════════════════════════════════════════════════════════════
# Rule-based planner
# ═════════════════════════════════════════════════════════════════════

def _blocked_plan(reason: str, duration: int, festival: str, aspect: str, resolution: str,
                  missing: List[str], case: str = "") -> AdPlan:
    return AdPlan(
        requested_duration=duration, final_duration=0.0, endcard_duration=endcard_seconds(duration),
        festival=festival, aspect=aspect, resolution=resolution, scenes=[], total_veo_seconds=0,
        total_estimated_cost_usd=0.0, blocked=True, blocked_reason=reason, case=case,
        missing_fields=missing,
    )


def _common_checks(project: ProjectData, renders: List[RenderInfo]) -> Tuple[Optional[str], List[RenderInfo]]:
    review = project.raw_data.get("review") or {}
    usable = []
    for r in renders:
        if not r.approved or r.needs_review:
            continue
        entry = review.get(Path(r.filepath).name) or review.get(Path(r.filepath).stem)
        if isinstance(entry, dict) and entry.get("needs_review") is True:
            continue
        usable.append(r)
    if not (project.rera_number or "").strip():
        return "RERA number (rera.number) is missing. Real-estate ads cannot be made without it.", usable
    if not (project.name or "").strip():
        return "Project name (project.name) is missing.", usable
    if not usable:
        return "No approved renders. Ask the developer for renders, or make a poster instead.", usable
    return None, usable


def _project_warnings(project: ProjectData, logo_available: bool) -> List[str]:
    w = []
    if not project.is_verified:
        w.append("Project details not verified – confirm the facts before publishing.")
    if project.units_status_missing:
        w.append("Unit availability not given – confirm before publishing.")
    if project.all_units_sold_out:
        w.append("All units are sold out – unit types and price are not mentioned.")
    if not logo_available:
        w.append("No logo – the end card shows the project name in large text.")
    return w


def _fallbacks(facts: List[Fact], project: ProjectData) -> List[Dict[str, str]]:
    out = []
    if facts and facts[0].kind != "price":
        out.append({"replaced": "price line", "with": facts[0].display})
    if not project.lowest_price_inr:
        out.append({"replaced": "price disclaimer and '*'", "with": "removed (no price in JSON)"})
    if not project.site_visits.formatted_text:
        out.append({"replaced": "site visit CTA", "with": cta_line(project)})
    if not project.promoter:
        out.append({"replaced": "'by {promoter}' line", "with": "omitted"})
    if "disclaimers" in project.missing_fields:
        out.append({"replaced": "disclaimers", "with": DEFAULT_DISCLAIMER})
    if "brand.colours" in project.missing_fields:
        out.append({"replaced": "brand colours", "with": "navy #1F2A44, gold #C9A227, cream #F3EFE6"})
    if "brand.fonts" in project.missing_fields:
        out.append({"replaced": "brand fonts", "with": "Playfair Display / Inter"})
    return out


def _finish_plan(
    plan: AdPlan, project: ProjectData, script: Optional[str], style: str,
) -> AdPlan:
    """Voiceover, end card, music, disclaimers and totals (shared by all planners)."""
    budget = max_voiceover_words(plan.requested_duration)
    veo = plan.veo_scenes
    if script and script.strip():
        sentences = split_sentences(script)
        plan.voiceover_script = script.strip()
        plan.warnings.extend(check_script(script, project, budget))
    elif not plan.voiceover_script:
        sentences = build_voiceover_sentences(project, plan.festival, plan.requested_duration, style)
    else:
        sentences = split_sentences(plan.voiceover_script)
    veo_time = sum(s.duration_seconds for s in veo) - len(veo) * plan.crossfade_seconds
    voice_end = assign_voiceover(veo, sentences, plan.crossfade_seconds)
    if not (script and script.strip()) and not plan.voiceover_script:
        # Our own script: drop lines until the voice finishes before the end card
        budget = sum(word_count(x) for x in sentences)
        while voice_end > veo_time + 1.0 and budget > 8:
            budget -= 2
            sentences = build_voiceover_sentences(project, plan.festival, plan.requested_duration, style, budget)
            voice_end = assign_voiceover(veo, sentences, plan.crossfade_seconds)
        plan.voiceover_script = " ".join(sentences)
    if voice_end > veo_time + 1.0:   # a little overlap with the end-card crossfade is fine
        plan.warnings.append("The voiceover is longer than the scenes and will run into the end card.")
    plan.voiceover_word_count = word_count(plan.voiceover_script)

    plan.total_veo_seconds = sum(s.veo_duration for s in veo if s.reuses_scene_id is None)
    plan.total_estimated_cost_usd = round(sum(s.estimated_cost_usd for s in plan.scenes), 2)
    plan.final_duration = round(
        sum(s.duration_seconds for s in plan.scenes) - len(veo) * plan.crossfade_seconds, 2
    )
    return plan


def plan_video_ad(
    project: ProjectData,
    renders: List[RenderInfo],
    requested_duration: int = 30,
    festival: str = "Diwali",
    aspect: str = "16:9",
    resolution: str = "720p",
    script: Optional[str] = None,
    logo_available: bool = True,
    crossfade: float = DEFAULT_CROSSFADE,
    voice_style: str = "festive",
) -> AdPlan:
    """Rule-based scene plan following prompts/scene_planner_system.txt."""
    duration = max(10, min(60, int(requested_duration)))
    festival = festival or "None"
    endcard = endcard_seconds(duration)
    missing = list(project.missing_fields)

    reason, usable = _common_checks(project, renders)
    case = detect_case(usable)
    if reason:
        return _blocked_plan(reason, duration, festival, aspect, resolution, missing, case if usable else "F")

    facts = build_facts(project)
    has_price = facts[0].kind == "price"
    warnings = _project_warnings(project, logo_available)
    if case == "E":
        warnings.append("No exterior render – video has no building shot.")
    if duration >= 45 and len(usable) < 3:
        warnings.append(
            f"Only {len(usable)} renders – the {duration} s video will repeat shots. "
            "Consider 20 s, or ask the developer for more renders."
        )

    cands = _build_candidates(case, usable)
    chosen, durs, trim = _select_and_time(cands, case, duration, endcard, crossfade)
    price_per_sec = VEO_PRICING.get(resolution, 0.12)

    scenes: List[PlannedScene] = []
    # Trim the longest clip (not a short close-up) so every scene stays watchable
    trim_at = max(range(1, len(durs) + 1), key=lambda k: (durs[k - 1], k))
    for i, (c, d) in enumerate(zip(chosen, durs), 1):
        used = d - trim if i == trim_at else d
        if c.kind == "closeup":
            short, prompt = closeup_shot(festival, c.closeup_idx, aspect)
            scenes.append(PlannedScene(
                index=i, name=f"Festive close-up: {short}", source_type="festive_closeup",
                duration_seconds=used, kind="festive_closeup", veo_mode="text_to_video",
                veo_duration=d, prompt=prompt, label=LABEL_CLOSEUP,
                estimated_cost_usd=round(d * price_per_sec, 2), is_opening=c.is_opening, priority=c.keep,
            ))
        else:
            r = c.render
            title = "Opening" if c.is_opening else ("Reuse" if c.is_reuse else r.render_type.title())
            who = " + people" if c.people else ""
            scenes.append(PlannedScene(
                index=i, name=f"{title}: {r.render_type}{who} – {c.move} ({Path(r.filepath).name})",
                source_type="render_image", duration_seconds=used, kind=f"render_{r.render_type}",
                veo_mode="image_to_video", veo_duration=d, render_path=r.filepath,
                render_type=r.render_type, camera_move=c.move,
                prompt=render_prompt(r.render_type, c.move, festival, aspect, people=c.people),
                label=LABEL_RENDER, has_people=c.people,
                estimated_cost_usd=round(d * price_per_sec, 2), is_opening=c.is_opening, priority=c.keep,
            ))

    chips: List[str] = []
    if case in ("C", "D") and project.amenities:
        chips = project.amenities[:4]
        renders_in_plan = [s for s in scenes if s.source_type == "render_image"]
        target = renders_in_plan[1] if len(renders_in_plan) > 1 else renders_in_plan[0]
        target.show_amenity_chips = True

    end_card = build_end_card(project, festival, facts, logo_available)
    scenes.append(PlannedScene(
        index=len(scenes) + 1, name=f"End card: {project.name}", source_type="end_card",
        duration_seconds=endcard, kind="end_card", prompt=" | ".join(end_card["lines"]),
    ))

    plan = AdPlan(
        requested_duration=duration, final_duration=float(duration), endcard_duration=endcard,
        festival=festival, aspect=aspect, resolution=resolution, scenes=scenes,
        total_veo_seconds=0, total_estimated_cost_usd=0.0, crossfade_seconds=crossfade,
        case=case, warnings=warnings, missing_fields=missing,
        fallbacks_used=_fallbacks(facts, project), end_card=end_card, amenity_text_chips=chips,
        music_prompt=music_prompt_for(festival, duration),
        disclaimers=resolve_disclaimers(project, has_price), show_price_asterisk=has_price,
    )
    return _finish_plan(plan, project, script, voice_style)


# ═════════════════════════════════════════════════════════════════════
# "all" mode: 60 s first, then 20 s and 10 s from the same clips
# ═════════════════════════════════════════════════════════════════════

def derive_version(base: AdPlan, project: ProjectData, duration: int, logo_available: bool = True,
                   script: Optional[str] = None) -> AdPlan:
    """Build a shorter version ONLY from scenes already in `base` (same prompts → cached clips)."""
    endcard = endcard_seconds(duration)
    xf = base.crossfade_seconds
    cands = []
    for s in base.veo_scenes:
        kind = "closeup" if s.source_type == "festive_closeup" else (s.render_type or "exterior")
        cands.append(_Cand(
            kind, None, s.camera_move, s.priority, 0, s.index, is_opening=s.is_opening,
            cap=s.veo_duration, source=s, people=s.has_people,
        ))
    chosen, durs, trim = _select_and_time(cands, base.case, duration, endcard, xf)
    scenes: List[PlannedScene] = []
    # Trim the longest clip (not a short close-up) so every scene stays watchable
    trim_at = max(range(1, len(durs) + 1), key=lambda k: (durs[k - 1], k))
    for i, (c, d) in enumerate(zip(chosen, durs), 1):
        src = c.source
        used = d - trim if i == trim_at else d
        scenes.append(PlannedScene(
            index=i, name=src.name, source_type=src.source_type, duration_seconds=used, kind=src.kind,
            veo_mode=src.veo_mode, veo_duration=src.veo_duration, render_path=src.render_path,
            render_type=src.render_type, camera_move=src.camera_move, prompt=src.prompt, label=src.label,
            estimated_cost_usd=0.0, is_opening=src.is_opening, priority=src.priority,
            reuses_scene_id=src.index, show_amenity_chips=src.show_amenity_chips, has_people=src.has_people,
        ))
    if base.amenity_text_chips and not any(s.show_amenity_chips for s in scenes):
        rs = [s for s in scenes if s.source_type == "render_image"]
        if rs:
            (rs[1] if len(rs) > 1 else rs[0]).show_amenity_chips = True
    facts = build_facts(project)
    end_card = build_end_card(project, base.festival, facts, logo_available)
    scenes.append(PlannedScene(
        index=len(scenes) + 1, name=f"End card: {project.name}", source_type="end_card",
        duration_seconds=endcard, kind="end_card", prompt=" | ".join(end_card["lines"]),
    ))
    warnings = [w for w in base.warnings if not w.startswith("Only ")]
    plan = AdPlan(
        requested_duration=duration, final_duration=float(duration), endcard_duration=endcard,
        festival=base.festival, aspect=base.aspect, resolution=base.resolution, scenes=scenes,
        total_veo_seconds=0, total_estimated_cost_usd=0.0, crossfade_seconds=xf, case=base.case,
        warnings=warnings, missing_fields=list(base.missing_fields),
        fallbacks_used=list(base.fallbacks_used), end_card=end_card,
        amenity_text_chips=list(base.amenity_text_chips), music_prompt=music_prompt_for(base.festival, duration),
        disclaimers=list(base.disclaimers), show_price_asterisk=base.show_price_asterisk, planner=base.planner,
    )
    return _finish_plan(plan, project, script, "festive")


def plan_all_versions(
    project: ProjectData,
    renders: List[RenderInfo],
    festival: str = "Diwali",
    aspect: str = "16:9",
    resolution: str = "720p",
    logo_available: bool = True,
    crossfade: float = DEFAULT_CROSSFADE,
    base_plan: Optional[AdPlan] = None,
    scripts: Optional[Dict[int, str]] = None,
) -> List[AdPlan]:
    """Returns [plan_60, plan_20, plan_10]. Veo is paid for only in the 60 s plan.
    scripts: optional user-approved voiceover per length, e.g. {10: "..."}; other lengths get their own."""
    scripts = scripts or {}
    plan60 = base_plan or plan_video_ad(
        project, renders, 60, festival, aspect, resolution,
        logo_available=logo_available, crossfade=crossfade, script=scripts.get(60),
    )
    if plan60.blocked:
        return [plan60]
    return [plan60] + [derive_version(plan60, project, d, logo_available, scripts.get(d)) for d in (20, 10)]


# ═════════════════════════════════════════════════════════════════════
# Validation (applied to every plan, and used to vet the Gemini agent)
# ═════════════════════════════════════════════════════════════════════

def validate_plan(plan: AdPlan, usable_renders: Optional[List[RenderInfo]] = None) -> List[str]:
    if plan.blocked:
        return []
    errors: List[str] = []
    suffix = veo_suffix(plan.aspect).strip()
    approved_names = {Path(r.filepath).name for r in (usable_renders or [])}
    use_count: Dict[str, int] = {}
    veo = plan.veo_scenes
    for s in veo:
        tag = f"Scene {s.index}"
        if s.veo_duration not in VEO_CLIP_LENGTHS:
            errors.append(f"{tag}: Veo duration {s.veo_duration} is not 4, 6 or 8.")
        if not s.prompt.strip().endswith(suffix):
            errors.append(f"{tag}: prompt does not end with the no-text line (rule 5).")
        if plan.end_card and project_rera_in(s.prompt, plan):
            errors.append(f"{tag}: RERA number must not appear in a Veo prompt.")
        if s.veo_mode == "text_to_video":
            if s.kind != "festive_closeup" or s.render_path:
                errors.append(f"{tag}: text-to-video is only allowed for festive close-ups.")
            body = s.prompt.split(" Tight framing")[0].split(" No text,")[0]
            body = re.sub(r"\b(no|without|not)\b[^.]*", "", body, flags=re.I)  # ignore negations
            if re.search(r"\b(buildings?|towers?|facade|apartment|room|bedroom|kitchen|pool|gym|clubhouse)\b",
                         body, re.I):
                errors.append(f"{tag}: festive close-up describes property ({s.prompt[:60]}…).")
        elif s.veo_mode == "image_to_video":
            if not s.render_path:
                errors.append(f"{tag}: image-to-video scene has no render.")
            else:
                name = Path(s.render_path).name
                if approved_names and name not in approved_names:
                    errors.append(f"{tag}: render {name} is not approved.")
                if s.reuses_scene_id is None:
                    use_count[name] = use_count.get(name, 0) + 1
        else:
            errors.append(f"{tag}: unknown veo_mode {s.veo_mode!r}.")
    if len(veo) >= 2 and not any(s.has_people for s in veo):
        errors.append("Every video needs at least one render scene with people (e.g. a woman walking through an amenity).")
    for s in veo:
        if s.veo_mode == "text_to_video" and _PEOPLE_RE.search(s.prompt.split(" Tight framing")[0]):
            errors.append(f"Scene {s.index}: AI close-ups must not show people.")
    for name, n in use_count.items():
        if n > 2:
            errors.append(f"Render {name} is used {n} times (max 2).")
    if plan.endcard_duration != endcard_seconds(plan.requested_duration):
        errors.append("End card duration breaks rule 7.")
    planned = sum(
        s.veo_duration if s.reuses_scene_id is None else math.ceil(s.duration_seconds) for s in veo
    ) + plan.endcard_duration - len(veo) * plan.crossfade_seconds
    if not (plan.requested_duration - 1e-6 <= planned <= plan.requested_duration + 2 + 1e-6):
        errors.append(f"Scene durations add up to {planned:.1f}s; must be {plan.requested_duration}–{plan.requested_duration + 2}s (rule 8).")
    return errors


_PEOPLE_RE = re.compile(r"\b(woman|women|man|men|lady|family|husband|wife|child|children|son|daughter|boy|girl|"
                        r"professionals?|couple|people|person)\b", re.I)


def project_rera_in(prompt: str, plan: AdPlan) -> bool:
    rera = plan.end_card.get("rera", "")
    return bool(rera) and rera in prompt


# ═════════════════════════════════════════════════════════════════════
# Gemini scene-planning agent (uses the system prompt verbatim)
# ═════════════════════════════════════════════════════════════════════

def _agent_user_message(project: ProjectData, renders: List[RenderInfo], duration: int,
                        festival: str, aspect: str, script: Optional[str]) -> str:
    render_list = [
        {
            "file": Path(r.filepath).name,
            "type": r.render_type,
            "approved": bool(r.approved and not r.needs_review),
            "description": r.description or r.notes or Path(r.filepath).stem.replace("_", " "),
        }
        for r in renders
    ]
    # Send only lifestyle amenities (no gates, lobbies, CCTV, parking, podiums)
    project_json = dict(project.raw_data)
    project_json["amenities"] = list(project.amenities)
    msg = (
        f"project: {json.dumps(project_json, ensure_ascii=False)}\n"
        f"renders: {json.dumps(render_list, ensure_ascii=False)}\n"
        f"duration_seconds: {duration}\n"
        f"festival: {festival}\n"
        f"aspect_ratio: {aspect}\n"
    )
    if script and script.strip():
        msg += f"script: {script.strip()}\n"
    return msg


def _call_gemini(system_prompt: str, user_msg: str, api_key: str) -> Tuple[Dict[str, Any], str]:
    """Vertex AI (service account) first, then the Gemini API key. See gemini_text.py."""
    from gemini_text import generate_json

    data, used = generate_json(user_msg, system_prompt=system_prompt, api_key=api_key,
                               temperature=0.3, max_output_tokens=32768, timeout=180)
    if isinstance(data, list):
        data = {"versions": data}
    return data, used


def plan_from_agent_dict(
    data: Dict[str, Any], project: ProjectData, renders: List[RenderInfo],
    duration: int, festival: str, aspect: str, resolution: str, logo_available: bool,
) -> AdPlan:
    """Convert the agent's JSON into an AdPlan (end card / disclaimers stay program-made)."""
    if "versions" in data:
        data = data["versions"][0]
    by_name = {Path(r.filepath).name: r for r in renders}
    endcard = endcard_seconds(duration)
    if data.get("blocked"):
        return _blocked_plan(data.get("blocked_reason") or "Blocked by scene agent.", duration, festival,
                             aspect, resolution, list(data.get("missing_fields") or []), data.get("case", "F"))
    price_per_sec = VEO_PRICING.get(resolution, 0.12)
    scenes: List[PlannedScene] = []
    snapped = []
    for i, sd in enumerate(data.get("scenes", []), 1):
        r = by_name.get(sd.get("source_render") or "")
        mode = sd.get("veo_mode")
        raw_d = float(sd.get("duration", 0) or 0)
        # Veo only makes 4/6/8 s clips; the program trims, so round odd lengths up.
        d = next((x for x in VEO_CLIP_LENGTHS if x >= raw_d), 8) if raw_d > 0 else 0
        if d != raw_d:
            snapped.append(f"scene {i}: {raw_d:g}s → {d}s")
        scenes.append(PlannedScene(
            index=i, name=f"{sd.get('kind', '')}: {sd.get('camera_move') or ''}".strip(": "),
            source_type="render_image" if mode == "image_to_video" else "festive_closeup",
            duration_seconds=float(d), kind=sd.get("kind", ""), veo_mode=mode, veo_duration=d,
            render_path=r.filepath if r else None, render_type=r.render_type if r else None,
            camera_move=sd.get("camera_move") or "", prompt=sd.get("prompt", ""),
            label=LABEL_RENDER if mode == "image_to_video" else LABEL_CLOSEUP,
            has_people=bool(mode == "image_to_video" and _PEOPLE_RE.search(
                re.sub(r"\bno (people|person)\b", "", sd.get("prompt", ""), flags=re.I))),
            voiceover=sd.get("voiceover", ""), estimated_cost_usd=round(d * price_per_sec, 2),
            is_opening=(i == 1), priority=float(i),
        ))
    # Agent plans assume hard cuts; fit the crossfade into whatever slack they left (max 0.5 s).
    n = len(scenes)
    slack = sum(s.veo_duration for s in scenes) + endcard - duration
    xf = max(0.0, min(DEFAULT_CROSSFADE, slack / n)) if n else 0.0
    excess = sum(s.veo_duration for s in scenes) + endcard - n * xf - duration
    if scenes and excess > 0:
        scenes[-1].duration_seconds = scenes[-1].veo_duration - min(excess, scenes[-1].veo_duration - 2)
    facts = build_facts(project)
    has_price = facts[0].kind == "price"
    end_card = build_end_card(project, festival, facts, logo_available)
    end_card["rera"] = project.rera_number
    chips = [c for c in (data.get("amenity_text_chips") or []) if c in project.amenities][:4]
    if chips:
        rs = [s for s in scenes if s.source_type == "render_image"]
        if rs:
            (rs[1] if len(rs) > 1 else rs[0]).show_amenity_chips = True
    scenes.append(PlannedScene(
        index=n + 1, name=f"End card: {project.name}", source_type="end_card",
        duration_seconds=endcard, kind="end_card", prompt=" | ".join(end_card["lines"]),
    ))
    warnings = list(dict.fromkeys(list(data.get("warnings") or []) + _project_warnings(project, logo_available)))
    if snapped:
        warnings.append("Adjusted the agent's clip lengths to Veo's 4/6/8 s (" + ", ".join(snapped) + "); the last clip is trimmed.")
    plan = AdPlan(
        requested_duration=duration, final_duration=float(duration), endcard_duration=endcard,
        festival=festival, aspect=aspect, resolution=resolution, scenes=scenes, total_veo_seconds=0,
        total_estimated_cost_usd=0.0, crossfade_seconds=round(xf, 3), case=data.get("case", ""),
        warnings=warnings,
        missing_fields=list(dict.fromkeys(list(data.get("missing_fields") or []) + project.missing_fields)),
        fallbacks_used=list(data.get("fallbacks_used") or []) or _fallbacks(facts, project),
        end_card=end_card, amenity_text_chips=chips,
        voiceover_script=data.get("voiceover_script", ""),
        music_prompt=data.get("music_prompt") or music_prompt_for(festival, duration),
        disclaimers=resolve_disclaimers(project, has_price), show_price_asterisk=has_price,
        planner="gemini-agent",
    )
    return plan


def plan_with_agent(
    project: ProjectData,
    renders: List[RenderInfo],
    requested_duration: int = 30,
    festival: str = "Diwali",
    aspect: str = "16:9",
    resolution: str = "720p",
    script: Optional[str] = None,
    logo_available: bool = True,
    api_key: Optional[str] = None,
) -> AdPlan:
    """Ask Gemini (with the system prompt) for the plan; validate it; fall back to the rule engine."""
    duration = max(10, min(60, int(requested_duration)))
    rule_plan = plan_video_ad(project, renders, duration, festival, aspect, resolution,
                              script=script, logo_available=logo_available)
    if rule_plan.blocked:
        return rule_plan
    from gemini_text import credentials_available

    key = (api_key or os.getenv("GEMINI_API_KEY") or os.getenv("GOOGLE_API_KEY") or "").strip()
    if not credentials_available(key):
        rule_plan.warnings.append("No Gemini credentials – used the rule-based scene planner.")
        return rule_plan
    _, usable = _common_checks(project, renders)
    try:
        data, used = _call_gemini(load_system_prompt(),
                                  _agent_user_message(project, renders, duration, festival, aspect, script), key)
        plan = plan_from_agent_dict(data, project, usable, duration, festival, aspect, resolution, logo_available)
        plan.planner = f"gemini-agent ({used})"
        if plan.blocked:
            return plan
        plan = _finish_plan(plan, project, script, "festive")
        errors = validate_plan(plan, usable)
        if plan.voiceover_script:
            low = plan.voiceover_script.lower()
            errors += [f"voiceover uses banned claim \"{w}\"" for w in BANNED_CLAIMS if re.search(rf"\b{re.escape(w)}\b", low)]
        if errors:
            rule_plan.warnings.append(
                "Gemini scene agent's plan broke the rules (" + "; ".join(errors[:3])
                + ") – used the rule-based planner instead."
            )
            return rule_plan
        return plan
    except Exception as exc:
        rule_plan.warnings.append(f"Gemini scene agent failed ({exc}) – used the rule-based planner.")
        return rule_plan
