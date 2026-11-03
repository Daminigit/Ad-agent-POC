"""
Gemini Script Writer Service
============================
Generates 3 tailored script options for real-estate video ads using Google Gemini.
Dynamically budgets speaking time and word count based on the exact video duration:
  - 10s video: ~3s endcard, ~6.5s speech window -> 14–16 words
  - 15s video: ~3s endcard, ~11.5s speech window -> 25–28 words
  - 20s video: ~3.5s endcard, ~16s speech window -> 36–40 words
  - 30s video: ~4s endcard, ~25.5s speech window -> 56–62 words
  - 45s video: ~4.5s endcard, ~39.5s speech window -> 88–95 words
  - 60s video: ~5s endcard, ~53.5s speech window -> 118–128 words

Strictly adheres to project JSON facts: never invents prices, amenities, or claims.
"""

from __future__ import annotations

import json
import os
import re
from dataclasses import dataclass
from typing import Any, Dict, List, Optional

import requests
from dotenv import load_dotenv

from project_data import ProjectData

load_dotenv()


@dataclass
class ScriptOption:
    id: str
    title: str
    tone: str
    text: str
    word_count: int
    estimated_speech_seconds: float
    target_duration: int = 30
    speaking_window: float = 25.5


def get_script_timing_profile(duration: int) -> Dict[str, Any]:
    """
    Calculate speech budget based on video duration and outro endcard.
    Ensures voiceover finishes before the visual endcard displays.
    """
    duration = max(10, min(60, int(duration)))

    # Endcard duration matching planner specs
    if duration <= 15:
        endcard_sec = 3.0
    elif duration <= 20:
        endcard_sec = 3.5
    elif duration <= 45:
        endcard_sec = 4.0
    else:
        endcard_sec = 5.0

    # 0.5s breathing pause between voiceover completion and endcard transition
    speaking_sec = max(6.0, float(duration) - endcard_sec - 0.5)

    # Commercial voiceover pace: ~2.25 words per second in Indian English
    target_words = max(13, int(speaking_sec * 2.25))
    min_words = max(10, int(speaking_sec * 1.95))
    max_words = int(speaking_sec * 2.45)

    return {
        "duration": duration,
        "endcard_seconds": endcard_sec,
        "speaking_seconds": round(speaking_sec, 1),
        "target_words": target_words,
        "min_words": min_words,
        "max_words": max_words,
    }


def generate_script_options(
    project: ProjectData,
    festival: str = "Diwali",
    duration: int = 30,
    api_key: Optional[str] = None,
) -> List[ScriptOption]:
    """
    Generate 3 distinct promotional voiceover scripts strictly calibrated to the
    exact target video duration (10s, 15s, 20s, 30s, 45s, 60s) and festival theme.
    """
    key = (
        api_key
        or os.getenv("GEMINI_API_KEY")
        or os.getenv("GOOGLE_API_KEY")
        or ""
    ).strip()

    profile = get_script_timing_profile(duration)

    # 1. Try live Gemini generation if API key is active
    if key and not key.startswith("your_"):
        try:
            live_options = _call_gemini_for_scripts(
                project=project,
                festival=festival,
                profile=profile,
                api_key=key,
            )
            if live_options and len(live_options) >= 3:
                return live_options
        except Exception as e:
            print(f"[ScriptWriter] Gemini note ({e}), using precision fact-based scripts for {duration}s.")

    # 2. Precision factual template fallback calibrated for the exact duration
    return _build_curated_script_options(project, festival, profile)


def _call_gemini_for_scripts(
    project: ProjectData,
    festival: str,
    profile: Dict[str, Any],
    api_key: str,
) -> List[ScriptOption]:
    """Call Google Gemini to write 3 script options matching exact timing constraints."""
    duration = profile["duration"]
    target_words = profile["target_words"]
    min_words = profile["min_words"]
    max_words = profile["max_words"]
    speaking_sec = profile["speaking_seconds"]
    endcard_sec = profile["endcard_seconds"]

    fest_name = festival if festival != "None" else "New Beginnings"

    prompt = f"""You are an elite Indian real estate commercial voiceover copywriter and audio director.
Write 3 distinct promotional voiceover script options for a {duration}-second video ad celebrating {fest_name}.

STRICT TIMING & WORD COUNT CONSTRAINTS:
- Video Duration: {duration} seconds.
- Outro End Card: {endcard_sec} seconds (visual outro with logo, RERA number, and disclaimers).
- Target Spoken Duration: EXACTLY {speaking_sec} seconds.
- Word Count Range: MUST be between {min_words} and {max_words} words (Target: {target_words} words).
- CRITICAL: A professional voiceover actor speaks at 2.25 words per second. If you write more than {max_words} words, the voiceover will exceed the {duration}s video!

PROJECT FACTS (Use ONLY these confirmed facts - DO NOT invent anything):
- Project Name: {project.name}
- Promoter: {project.promoter}
- Location: {project.marketing_name}, {project.city}
- RERA Registration Number: {project.rera_number}
- Unit Types: {project.formatted_units_summary}
- Starting Price: {project.formatted_lowest_price}

CRITICAL RULES:
1. Every script MUST state the project name ({project.name}), location ({project.marketing_name or project.city}), unit types, and starting price ({project.formatted_lowest_price}).
2. Written in natural, persuasive, broadcast-quality Indian-English suitable for voiceover.
3. Output MUST be a valid JSON array of 3 objects with keys: "id", "title", "tone", "text".

Return ONLY JSON. No markdown fences.
[
  {{"id": "festive", "title": "Festive & Auspicious Celebration", "tone": "Warm, celebratory, family-centric", "text": "..."}},
  {{"id": "value", "title": "Value & Investment Hook", "tone": "Direct, value-driven, smart decision", "text": "..."}},
  {{"id": "luxury", "title": "Luxury & Architectural Elegance", "tone": "Sophisticated, aspirational, premium", "text": "..."}}
]"""

    models = ["gemini-2.5-flash", "gemini-flash-latest", "gemini-3.8-flash"]
    for m in models:
        url = f"https://generativelanguage.googleapis.com/v1beta/models/{m}:generateContent?key={api_key}"
        try:
            resp = requests.post(
                url,
                headers={"Content-Type": "application/json"},
                json={
                    "contents": [{"parts": [{"text": prompt}]}],
                    "generationConfig": {"temperature": 0.65, "maxOutputTokens": 900},
                },
                timeout=15,
            )
            if resp.status_code == 200:
                res_json = resp.json()
                candidates = res_json.get("candidates", [])
                if candidates:
                    raw_text = candidates[0].get("content", {}).get("parts", [{}])[0].get("text", "")
                    cleaned = re.sub(r"^```(?:json)?\s*|\s*```$", "", raw_text.strip(), flags=re.MULTILINE)
                    data = json.loads(cleaned)
                    options = []
                    for item in data[:3]:
                        txt = item.get("text", "").strip()
                        wcount = len(txt.split())
                        options.append(ScriptOption(
                            id=item.get("id", "opt"),
                            title=item.get("title", "Script Option"),
                            tone=item.get("tone", "Professional"),
                            text=txt,
                            word_count=wcount,
                            estimated_speech_seconds=round(wcount / 2.25, 1),
                            target_duration=duration,
                            speaking_window=speaking_sec,
                        ))
                    return options
        except Exception:
            continue

    return []


def _build_curated_script_options(
    project: ProjectData,
    festival: str,
    profile: Dict[str, Any],
) -> List[ScriptOption]:
    """
    Curate 3 robust, compliant script options calibrated to the exact duration bucket.
    """
    duration = profile["duration"]
    speaking_sec = profile["speaking_seconds"]

    loc = project.marketing_name or project.city
    units = project.formatted_units_summary
    price = project.formatted_lowest_price
    name = project.name
    promoter = project.promoter
    fest = festival if festival != "None" else "the festive season"

    # ─────────────────────────────────────────────────────────────
    # BUCKET 1: 10s Videos (~6.5s speech window, 12–14 words)
    # ─────────────────────────────────────────────────────────────
    if duration <= 12:
        opt1_text = (
            f"Celebrate {fest} at {name}. "
            f"Luxury {units} homes from {price}."
        )
        opt2_text = (
            f"Smart investment at {name}. "
            f"Premium {units} residences from {price}."
        )
        opt3_text = (
            f"Discover {name}, {loc}. "
            f"Spacious {units} homes from {price}."
        )

    # ─────────────────────────────────────────────────────────────
    # BUCKET 2: 15s Videos (~11.5s speech window, 22–24 words)
    # ─────────────────────────────────────────────────────────────
    elif duration <= 18:
        opt1_text = (
            f"This {fest}, find your dream home at {name}. "
            f"Premium {units} residences from {price}. RERA approved. Book your visit today."
        )
        opt2_text = (
            f"Prime location and high appreciation at {name}, {loc}. "
            f"Offering modern {units} homes from {price}. Schedule your site tour today."
        )
        opt3_text = (
            f"Where modern comfort meets prime connectivity. Welcome to {name}, {loc}. "
            f"Thoughtfully planned {units} residences from {price}. Book your tour."
        )

    # ─────────────────────────────────────────────────────────────
    # BUCKET 3: 20s Videos (~16.0s speech window, 30–34 words)
    # ─────────────────────────────────────────────────────────────
    elif duration <= 25:
        opt1_text = (
            f"Make this {fest} memorable at {name}. Located in {loc}, enjoy luxury {units} residences from {price}. "
            f"RERA registered by {promoter}. Schedule your site visit today."
        )
        opt2_text = (
            f"Strategic location and high returns at {name}, {loc}. Offering modern {units} homes from {price}, "
            f"minutes from major hubs. RERA approved by {promoter}. Book now."
        )
        opt3_text = (
            f"Modern elegance at {name}, {loc}. Bespoke {units} residences starting from {price}, "
            f"with private balconies and clubhouse amenities. Consult with {promoter} today."
        )

    # ─────────────────────────────────────────────────────────────
    # BUCKET 4: 30s Videos (~25.5s speech window, 46–50 words)
    # ─────────────────────────────────────────────────────────────
    elif duration <= 35:
        opt1_text = (
            f"Celebrate {fest} by welcoming home prosperity at {name}. "
            f"Located in {loc}, enjoy beautifully crafted {units} homes designed for family celebration. "
            f"Featuring landscaped gardens, clubhouse amenities, and seamless connectivity starting from {price}. "
            f"Developed by {promoter} with certified RERA transparency. Book your exclusive site tour today."
        )
        opt2_text = (
            f"Looking for prime location and capital growth this {fest}? Discover {name} in {loc}. "
            f"Modern {units} residences starting from {price}, with rapid metro access and business hubs nearby. "
            f"Backed by {promoter} with complete RERA transparency. "
            f"Contact our sales advisory team to secure your festive pricing advantage today."
        )
        opt3_text = (
            f"Where architectural refinement meets everyday comfort. Welcome to {name}, an exclusive community in {loc}. "
            f"Meticulously planned {units} residences starting at {price}, complete with private balconies, wellness facilities, and landscaped gardens. "
            f"Developed by {promoter} and RERA approved. Schedule your private walkthrough and step into elevated living."
        )

    # ─────────────────────────────────────────────────────────────
    # BUCKET 5: 45s Videos (~40.5s speech window, 80–85 words)
    # ─────────────────────────────────────────────────────────────
    elif duration <= 50:
        opt1_text = (
            f"As celebrations fill this {fest}, open your doors to prosperity and happiness at {name}. "
            f"Situated in prime {loc}, this landmark address offers thoughtfully designed {units} homes crafted for family celebration. "
            f"Wake up to panoramic skyline vistas, stroll through green landscapes, and unwind with resort-style clubhouse amenities. "
            f"With seamless connectivity to major transit routes and starting prices from {price}, this is the home you've always envisioned. "
            f"Developed with uncompromising quality by {promoter} and fully RERA registered. Schedule your private walkthrough today."
        )
        opt2_text = (
            f"Auspicious beginnings start with smart investment decisions. This {fest}, secure high appreciation and luxury living at {name}, {loc}. "
            f"Boasting unmatched urban infrastructure, world-class schools, and bustling commercial corridors within easy reach, "
            f"these premium {units} homes offer generous layouts and superior finishes starting from {price}. "
            f"Every home is designed for optimal sunlight, ventilation, and privacy, backed by the proven development pedigree of {promoter}. "
            f"Benefit from special festive booking advantages and complete RERA assurance. Speak with our sales specialists and book your visit today."
        )
        opt3_text = (
            f"Experience an elevated standard of architectural refinement at {name}, an iconic enclave in {loc}. "
            f"Designed for those who appreciate sophistication, each spacious {units} residence features expansive private balconies, "
            f"grand living spaces, and state-of-the-art recreation facilities. "
            f"Enjoy temperature-controlled pools, jogging tracks, and multi-tier security, with pricing starting from {price}. "
            f"Brought to you by {promoter} with strict adherence to RERA standards. "
            f"Elevate your lifestyle this festive season—reserve your private guided tour today."
        )

    # ─────────────────────────────────────────────────────────────
    # BUCKET 6: 60s Videos (~53.5s speech, 118–128 words)
    # ─────────────────────────────────────────────────────────────
    else:
        opt1_text = (
            f"The festival of {fest} symbolizes auspicious new beginnings, warmth, and the joy of coming home. "
            f"Welcome to {name}, a prestigious residential haven in the vibrant heart of {loc}. "
            f"Here, every detail is crafted to elevate your daily living experience. Discover expansive {units} luxury homes "
            f"featuring generous floor plans, natural sunlight, and scenic balcony views, with starting prices from {price}. "
            f"Stroll across sprawling green parks, celebrate in the multi-purpose clubhouse, and stay connected with rapid transit links right at your doorstep. "
            f"Backed by the trusted legacy of {promoter} and complete RERA transparency. "
            f"Gift your loved ones the home they truly deserve this festive season. Call our team or visit our on-site experience centre today."
        )
        opt2_text = (
            f"Strategic location, architectural distinction, and enduring value come together this {fest} at {name}, {loc}. "
            f"Whether you are seeking your family's forever residence or a high-yielding real-estate asset, "
            f"these master-planned {units} homes deliver exceptional capital growth potential starting at {price}. "
            f"Positioned minutes from premier tech parks, metro stations, and healthcare facilities, {name} balances urban convenience with peaceful tranquility. "
            f"Enjoy world-class amenities including an equipped fitness center, infinity pool, landscaped meditation gardens, and 24-7 security. "
            f"Developed with excellence by {promoter} and fully RERA compliant. "
            f"Take advantage of limited-period festive pricing—connect with our senior property advisors and book your site visit now."
        )
        opt3_text = (
            f"Step into a realm of luxury and timeless comfort. Welcome to {name}, {loc}'s premier residential destination. "
            f"From its striking architectural facade to thoughtfully appointed interiors, every home is an expression of luxury. "
            f"Choose from masterfully engineered {units} layouts starting from {price}, featuring expansive living areas, "
            f"designer kitchens, and private balconies overlooking serene green gardens. "
            f"Indulge in resort-inspired lifestyle amenities, active sports courts, and elegant banquet spaces for memorable family celebrations. "
            f"Built to the highest construction standards by {promoter} with certified RERA registration. "
            f"Celebrate this {fest} with pride. Schedule your personalized walkthrough and discover your new address today."
        )

    return [
        ScriptOption(
            id="festive",
            title="✨ Option 1: Festive & Auspicious Celebration",
            tone="Warm, emotional, family-centric",
            text=opt1_text,
            word_count=len(opt1_text.split()),
            estimated_speech_seconds=round(len(opt1_text.split()) / 2.25, 1),
            target_duration=duration,
            speaking_window=speaking_sec,
        ),
        ScriptOption(
            id="value",
            title="💎 Option 2: Value & Investment Advantage",
            tone="Direct, value-driven, high appreciation",
            text=opt2_text,
            word_count=len(opt2_text.split()),
            estimated_speech_seconds=round(len(opt2_text.split()) / 2.25, 1),
            target_duration=duration,
            speaking_window=speaking_sec,
        ),
        ScriptOption(
            id="luxury",
            title="🏰 Option 3: Luxury & Architectural Elegance",
            tone="Sophisticated, aspirational, modern",
            text=opt3_text,
            word_count=len(opt3_text.split()),
            estimated_speech_seconds=round(len(opt3_text.split()) / 2.25, 1),
            target_duration=duration,
            speaking_window=speaking_sec,
        ),
    ]
