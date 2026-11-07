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

from dotenv import load_dotenv

from planner import (
    BANNED_CLAIMS,
    PRICE_HINT_WORDS,
    build_facts,
    build_voiceover_sentences,
    cta_spoken,
    speak,
    REFERENCE_TONES,
    amenity_highlight,
    spoken_budget,
    spoken_word_count,
    endcard_seconds,
    max_voiceover_words,
)
from gemini_text import credentials_available, generate_json
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

    # End card (rule 7): 3 s if <= 15 s, otherwise 4 s
    endcard_sec = float(endcard_seconds(duration))

    # 0.5s breathing pause between voiceover completion and endcard transition
    speaking_sec = max(6.0, float(duration) - endcard_sec - 0.5)

    # Word limits from the scene-planner spec (10 s -> 17, 20 s -> 40, 60 s -> 120)
    max_words = spoken_budget(duration)          # spoken words ("2.0" = "two point o" = 3)
    target_words = max(10, int(max_words * 0.85))
    min_words = max(8, int(max_words * 0.6))

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
    if credentials_available(key):
        try:
            live_options = _call_gemini_for_scripts(
                project=project,
                festival=festival,
                profile=profile,
                api_key=key,
            )
            live_options = [o for o in live_options if _script_is_compliant(o.text, project, profile["max_words"])]
            if live_options:
                # Top up with fact-based options if Gemini returned fewer than 3 compliant scripts
                fallback = _build_fact_based_options(project, festival, profile)
                return (live_options + fallback)[:3]
        except Exception as e:
            print(f"[ScriptWriter] Gemini note ({e}), using precision fact-based scripts for {duration}s.")

    # 2. Fact-only fallback built by the scene planner's rules
    return _build_fact_based_options(project, festival, profile)


def _build_fact_based_options(
    project: ProjectData,
    festival: str,
    profile: Dict[str, Any],
) -> List[ScriptOption]:
    """Three scripts that use only JSON facts and the selling-line fallback chain."""
    duration = profile["duration"]
    options = []
    for sid, (title, tone) in REFERENCE_TONES.items():
        text = " ".join(build_voiceover_sentences(project, festival, duration, style=sid))
        wc = len(text.split())
        options.append(ScriptOption(
            id=sid, title=title, tone=tone, text=text, word_count=wc,
            estimated_speech_seconds=round(wc / 2.0, 1), target_duration=duration,
            speaking_window=profile["speaking_seconds"],
        ))
    return options


def _script_is_compliant(text: str, project: ProjectData, max_words: int) -> bool:
    low = text.lower()
    if spoken_word_count(text) > max_words:
        return False
    if any(re.search(rf"\b{re.escape(w)}\b", low) for w in BANNED_CLAIMS):
        return False
    if not project.lowest_price_inr and any(re.search(rf"\b{re.escape(w)}\b", low) for w in PRICE_HINT_WORDS):
        return False
    return True


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

    if festival == "Family":
        theme_header = f"a {duration}-second warm, family-first real estate video ad"
    elif festival == "None":
        theme_header = f"a {duration}-second elegant, modern real estate video ad"
    else:
        theme_header = f"a {duration}-second festive real estate video ad for {festival}"
    angles = [(k, t, tone) for k, (t, tone) in REFERENCE_TONES.items()]
    options_schema = json.dumps(
        [{"id": i, "title": t, "tone": tone, "text": "..."} for i, t, tone in angles], indent=2
    )

    has_price = bool(project.lowest_price_inr and project.lowest_price_inr > 0)
    facts = build_facts(project)
    facts_str = "\n".join(f"  {i+1}. {f.display}  →  say: \"{f.spoken}\"" for i, f in enumerate(facts))
    loc = project.marketing_name or project.city
    if project.travel_times:
        travel_str = "; ".join(f"{t}  →  say: \"{speak(t)}\"" for t in project.travel_times[:3])
    else:
        travel_str = "NOT GIVEN – no 'minutes from' or 'near' claims"
    amenities_str = ", ".join(project.amenities) if project.amenities else "NOT GIVEN – do not mention any amenity"
    if has_price:
        price_rule = f"the main selling line (price: \"{facts[0].spoken}\")"
    else:
        price_rule = ("the main selling line. There is NO price: never mention or hint at price "
                      "(no 'affordable', 'budget', 'value for money'); you may say 'Enquire now for price details.'")
    short = duration <= 12
    cta = ("Do NOT add a call-to-action sentence (the end card shows it)." if short
           else f"End with this call to action: \"{cta_spoken(project)}\"")
    example = (
        "CLIENT-APPROVED STYLE REFERENCES – match this rhythm, length and tone exactly (these happen to be\n"
        "for another Diwali project; use only THIS project's facts and festival):\n"
        "  Short & Punchy: \"Celebrate Diwali at Kundan Eternia 2.0, Pune. Explore luxury living with a "
        "world-class clubhouse and gym today!\"\n"
        "  Warm & Festive: \"Light up your Diwali at Kundan Eternia 2.0, Pune—featuring exclusive club "
        "amenities and a modern gym. Visit now.\"\n"
        "  Crisp & Direct: \"Your dream Diwali awaits at Kundan Eternia 2.0, Pune. Discover the clubhouse "
        "and gym today!\"\n"
        "Pattern: festive hook + project name + CITY, then the headline amenities (or the price if given), "
        "then a 1–3 word call to action (\"today!\", \"Visit now.\")."
    )
    highlight = amenity_highlight(project)
    prompt = f"""You are a senior Indian real-estate copywriter writing voiceover for {theme_header}.
Write 3 voiceover scripts, one for each angle in the JSON below. Each must sound clearly different.

TIMING (hard limit – the voice is measured, not guessed):
- The narrator speaks about 2 words per second. The voice must finish in {speaking_sec} seconds,
  before the {endcard_sec:.0f}-second end card.
- Each script: {min_words}–{max_words} SPOKEN words ("2.0" is said "two point o" = 3 words). Never more than
  {max_words}. Count before answering.

FACTS – the ONLY facts you may use (use the spoken form shown after the arrow):
- Project: {project.name}{f" by {project.promoter}" if project.promoter else ""}
- Location: {loc}{f", {project.city}" if project.city and project.city not in loc else ""}
- Selling lines in priority order (1 is the main line):
{facts_str}
- City: {project.city or loc}
- Headline amenities to feature: {highlight or "none – use the main selling line instead"}
- Travel times: {travel_str}
- Amenities: {amenities_str}

HOW TO WRITE IT
1. Follow the client style references above: hook{f" with {festival}" if festival not in ("None", "Family") else ""}, project name and city once.
2. Use {price_rule}. {"Add one more fact from the list if it fits." if not short else "Nothing else fits in 10 seconds."}
3. Short, spoken sentences (under 12 words each), one idea per sentence. Talk to the viewer ("you", "your").
4. {cta}
5. Numbers as spoken in India: "ninety-six lakh", "one point four two crore", "two and three B-H-K",
   "sixteen hundred and eighty square feet". Decimals digit by digit with zero as "o": 2.0 → "two point o".
   Never read the RERA number, phone numbers or website addresses.
6. Never invent prices, offers, discounts, amenities, distances or dates. Never repeat a fact.
7. Banned words: best, luxury-most, guaranteed, lowest price, high returns, investment, appreciation.
   Light style words from the references are fine ("luxury living", "modern", "dream").

{example}

Return ONLY a JSON array (no markdown) in exactly this shape:
{options_schema}"""

    data, used = generate_json(prompt, api_key=api_key, temperature=0.65, max_output_tokens=16384, timeout=120)
    print(f"[ScriptWriter] Scripts written by {used}")
    options = []
    for item in (data or [])[:3]:
        txt = str(item.get("text", "")).strip()
        if not txt:
            continue
        wcount = len(txt.split())
        options.append(ScriptOption(
            id=item.get("id", "opt"),
            title=item.get("title", "Script Option"),
            tone=item.get("tone", "Professional"),
            text=txt,
            word_count=wcount,
            estimated_speech_seconds=round(wcount / 2.0, 1),
            target_duration=duration,
            speaking_window=speaking_sec,
        ))
    return options


def _format_natural_amenities_for_speech(amenities: List[str]) -> Tuple[str, str]:
    """
    Format builder amenities into broadcast-quality conversational voiceover copy.
    Filters out infrastructural keywords (entrance gate, stp, security cabin, transformer).
    """
    infra_terms = {
        "gate", "entrance", "security", "cabin", "stp", "sewage", "transformer",
        "parking", "paving", "compound", "boundary", "meter", "borewell", "dg",
        "generator", "lift", "elevator", "lobby", "road", "internal", "layout"
    }

    lifestyle_amenities = []
    for a in amenities:
        a_clean = a.strip()
        words = set(re.findall(r"\b\w+\b", a_clean.lower()))
        if not words.intersection(infra_terms):
            clean_name = re.sub(r"\s+", " ", a_clean).strip().lower()
            if clean_name not in [x.lower() for x in lifestyle_amenities]:
                lifestyle_amenities.append(clean_name)

    if not lifestyle_amenities:
        return "clubhouse and landscaped gardens", "resort-style clubhouse, swimming pool, and landscaped gardens"

    if len(lifestyle_amenities) == 1:
        quick = f"{lifestyle_amenities[0]} and landscaped gardens"
        full = f"{lifestyle_amenities[0]} and landscaped gardens"
    elif len(lifestyle_amenities) == 2:
        quick = f"{lifestyle_amenities[0]} and {lifestyle_amenities[1]}"
        full = f"{lifestyle_amenities[0]}, {lifestyle_amenities[1]}, and landscaped green gardens"
    else:
        quick = f"{lifestyle_amenities[0]} and {lifestyle_amenities[1]}"
        full = f"{lifestyle_amenities[0]}, {lifestyle_amenities[1]}, and {lifestyle_amenities[2]}"

    return quick, full


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
    raw_units = project.formatted_units_summary.strip()
    if not raw_units or raw_units.lower() in ("luxury", "premium"):
        u_space = ""
        units = ""
    else:
        u_space = f"{raw_units} "
        units = raw_units

    price = project.formatted_lowest_price
    name = project.name
    promoter = project.promoter
    fest = festival if festival not in ("None", "Family") else "the festive season"
    is_family = festival == "Family"

    has_price = bool(project.lowest_price_inr and project.lowest_price_inr > 0)

    # Dynamic natural amenity highlights (infrastructure filtered out)
    amenity_quick, amenity_full = _format_natural_amenities_for_speech(project.amenities)

    if project.travel_times:
        transit_quick = f"just {project.travel_times[0]}"
    else:
        transit_quick = f"prime connectivity in {loc}"

    price_s = f"from {price}" if has_price else f"featuring {amenity_quick}"
    price_long = f"starting from {price}" if has_price else f"featuring world-class {amenity_quick} with {transit_quick}"
    price_offer = f"starting prices from {price}" if has_price else f"featuring {amenity_full} and {transit_quick}"

    # ─────────────────────────────────────────────────────────────
    # BUCKET 1: 10s Videos (~6.5s speech window, 12–14 words)
    # ─────────────────────────────────────────────────────────────
    if duration <= 12:
        if is_family:
            opt1_text = f"A home where your family thrives. Luxury {u_space}residences at {name} {price_s}."
            opt2_text = f"Cherish life with your loved ones. Spacious {u_space}homes at {name} {price_s}."
            opt3_text = f"Safe, green community living. Premium {u_space}homes at {name}, {loc}."
        elif festival == "None":
            opt1_text = f"Discover modern luxury at {name}, {loc}. Premium {u_space}homes {price_s}."
            opt2_text = f"Prime living at {name}, {loc}. Luxury {u_space}residences {price_s}."
            opt3_text = f"Elevate your lifestyle at {name}. Spacious {u_space}residences with {transit_quick}."
        elif festival == "Diwali":
            opt1_text = f"Welcome to {name}. Celebrate the festival of lights in luxury. Elevated living every day."
            opt2_text = f"Celebrate Diwali at {name}. Luxury {u_space}residences {price_s}. Book your dream home."
            opt3_text = f"Light up your life at {name}, {loc}. Premium {u_space}homes {price_s}."
        else:
            opt1_text = (
                f"Celebrate {fest} at {name}. "
                f"Luxury {u_space}homes {price_s}."
            )
            opt2_text = (
                f"Smart living at {name}. "
                f"Premium {u_space}residences {price_s}."
            )
            opt3_text = (
                f"Discover {name}, {loc}. "
                f"Spacious {u_space}homes {price_s}."
            )

    # ─────────────────────────────────────────────────────────────
    # BUCKET 2: 15s Videos (~11.5s speech window, 22–24 words)
    # ─────────────────────────────────────────────────────────────
    elif duration <= 18:
        opt1_text = (
            f"This {fest}, find your dream home at {name}. "
            f"Premium {u_space}residences {price_s}. RERA approved. Book your visit today."
        )
        opt2_text = (
            f"Prime location and high appreciation at {name}, {loc}. "
            f"Offering modern {u_space}homes {price_s}. Schedule your site tour today."
        )
        opt3_text = (
            f"Where modern comfort meets prime connectivity. Welcome to {name}, {loc}. "
            f"Thoughtfully planned {u_space}residences {price_s}. Book your tour."
        )

    # ─────────────────────────────────────────────────────────────
    # BUCKET 3: 20s Videos (~16.0s speech window, 30–34 words)
    # ─────────────────────────────────────────────────────────────
    elif duration <= 25:
        opt1_text = (
            f"Make this {fest} memorable at {name}. Located in {loc}, enjoy luxury {u_space}residences {price_s}. "
            f"RERA registered by {promoter}. Schedule your site visit today."
        )
        opt2_text = (
            f"Strategic location and high returns at {name}, {loc}. Offering modern {u_space}homes {price_s}, "
            f"minutes from major hubs. RERA approved by {promoter}. Book now."
        )
        opt3_text = (
            f"Modern elegance at {name}, {loc}. Bespoke {u_space}residences {price_s}, "
            f"with private balconies and clubhouse amenities. Consult with {promoter} today."
        )

    # ─────────────────────────────────────────────────────────────
    # BUCKET 4: 30s Videos (~25.5s speech window, 44–50 words)
    # ─────────────────────────────────────────────────────────────
    elif duration <= 35:
        if is_family:
            opt1_text = (
                f"A home where your family thrives. Welcome to {name}, an exclusive community in {loc}. "
                f"Discover spacious {u_space}residences designed for multi-generational comfort. "
                f"Enjoy landscaped green parks, kids play zones, and vibrant lifestyle spaces {price_long}. "
                f"Developed by {promoter} with certified RERA transparency. Book your private family tour today."
            )
            opt2_text = (
                f"Cherish life with your loved ones in a peaceful, secure gated community. "
                f"{name} in {loc} offers modern {u_space}homes {price_long}, "
                f"with 24-7 security, senior citizen seating, and rapid transit connectivity. "
                f"Built by {promoter} with complete RERA transparency. Schedule your family site visit today."
            )
            opt3_text = (
                f"Where family happiness meets everyday convenience. Welcome to {name}, {loc}. "
                f"Thoughtfully planned {u_space}residences {price_long}, "
                f"featuring sunlit living spaces, green jogging tracks, and wellness amenities. "
                f"Developed by {promoter} and RERA approved. Step into your forever family home today."
            )
        elif festival == "None":
            opt1_text = (
                f"Discover an elevated standard of living at {name}, an iconic residential address in {loc}. "
                f"Featuring thoughtfully designed {u_space}luxury residences with panoramic views and world-class amenities {price_long}. "
                f"Enjoy rapid transit links and tech corridor access. "
                f"Built by {promoter} with certified RERA transparency. Book your private walkthrough today."
            )
            opt2_text = (
                f"Strategic location and high capital appreciation meet at {name}, {loc}. "
                f"Premium {u_space}residences {price_long}, positioned minutes from major IT corridors and transit hubs. "
                f"Backed by {promoter} with complete RERA transparency. "
                f"Contact our advisory team to schedule your private tour today."
            )
            opt3_text = (
                f"Where architectural refinement meets everyday comfort. Welcome to {name}, an exclusive community in {loc}. "
                f"Meticulously planned {u_space}residences {price_long}, complete with private balconies, wellness facilities, and landscaped gardens. "
                f"Developed by {promoter} and RERA approved. Schedule your private walkthrough and step into elevated living."
            )
        else:
            opt1_text = (
                f"Celebrate {fest} by welcoming home prosperity at {name}. "
                f"Located in {loc}, enjoy beautifully crafted {u_space}homes designed for family celebration. "
                f"Featuring landscaped gardens, clubhouse amenities, and seamless connectivity {price_long}. "
                f"Developed by {promoter} with certified RERA transparency. Book your exclusive site tour today."
            )
            opt2_text = (
                f"Looking for prime location and capital growth this {fest}? Discover {name} in {loc}. "
                f"Modern {u_space}residences {price_long}, with rapid transit access and business hubs nearby. "
                f"Backed by {promoter} with complete RERA transparency. "
                f"Contact our sales advisory team to secure your festive pricing advantage today."
            )
            opt3_text = (
                f"Where architectural refinement meets everyday comfort. Welcome to {name}, an exclusive community in {loc}. "
                f"Meticulously planned {u_space}residences {price_long}, complete with private balconies, wellness facilities, and landscaped gardens. "
                f"Developed by {promoter} and RERA approved. Schedule your private walkthrough and step into elevated living."
            )

    # ─────────────────────────────────────────────────────────────
    # BUCKET 5: 45s Videos (~40.5s speech window, 80–85 words)
    # ─────────────────────────────────────────────────────────────
    elif duration <= 50:
        if is_family:
            opt1_text = (
                f"A home is where your family creates lifelong memories. Welcome to {name}, situated in prime {loc}. "
                f"This landmark community offers generously proportioned {u_space}homes crafted for family warmth and comfort. "
                f"Wake up to morning sunlight across landscaped gardens, take leisurely walks along tree-lined boulevards, "
                f"and let your children play safely in dedicated recreation zones. "
                f"With seamless connectivity to top schools, healthcare, and {price_offer}, this is the ideal family address. "
                f"Developed with trusted quality by {promoter} and fully RERA registered. Schedule your family walkthrough today."
            )
            opt2_text = (
                f"Give your loved ones the space, security, and peaceful environment they deserve at {name}, {loc}. "
                f"Surrounded by greenery and top-tier social infrastructure, these premium {u_space}homes offer generous layouts "
                f"and superior finishes {price_offer}. Every home is planned for optimal natural light and multi-generational privacy, "
                f"backed by round-the-clock gated security and clubhouse wellness facilities. "
                f"Built with excellence by {promoter} and backed by complete RERA assurance. Book your private visit today."
            )
            opt3_text = (
                f"Cherish peaceful community living at {name}, an exceptional residential enclave in {loc}. "
                f"Designed for families who value quality of life, each {u_space}residence features expansive private balconies, "
                f"generous bedrooms, and modern lifestyle amenities including swimming pools and sports courts. "
                f"Enjoy peaceful living {price_offer}. "
                f"Brought to you by {promoter} with strict adherence to RERA standards. Reserve your guided tour today."
            )
        elif festival == "None":
            opt1_text = (
                f"Step into an elevated standard of architectural refinement at {name}, an iconic residential address in {loc}. "
                f"Designed for discerning homeowners, this premier development offers thoughtfully designed {u_space}luxury homes "
                f"featuring generous floor plans, floor-to-ceiling windows, and panoramic skyline vistas. "
                f"Unwind with resort-inspired clubhouse amenities, green landscapes, and seamless transit links {price_offer}. "
                f"Developed with uncompromising quality by {promoter} and fully RERA registered. Schedule your private walkthrough today."
            )
            opt2_text = (
                f"Strategic location and exceptional capital appreciation come together at {name}, {loc}. "
                f"Boasting unmatched urban infrastructure, premier business corridors, and transport links within easy reach, "
                f"these premium {u_space}homes offer generous layouts and superior finishes {price_offer}. "
                f"Every residence is engineered for optimal sunlight, ventilation, and privacy, backed by {promoter}. "
                f"Benefit from complete RERA assurance. Speak with our sales specialists and book your visit today."
            )
            opt3_text = (
                f"Experience an elevated standard of luxury living at {name}, an iconic enclave in {loc}. "
                f"Designed for those who appreciate sophistication, each spacious {u_space}residence features expansive private balconies, "
                f"grand living spaces, and state-of-the-art recreation facilities. "
                f"Enjoy temperature-controlled pools, jogging tracks, and multi-tier security, {price_offer}. "
                f"Brought to you by {promoter} with strict adherence to RERA standards. Reserve your private guided tour today."
            )
        else:
            opt1_text = (
                f"As celebrations fill this {fest}, open your doors to prosperity and happiness at {name}. "
                f"Situated in prime {loc}, this landmark address offers thoughtfully designed {u_space}homes crafted for family celebration. "
                f"Wake up to panoramic skyline vistas, stroll through green landscapes, and unwind with resort-style clubhouse amenities. "
                f"With seamless connectivity to major transit routes and {price_offer}, this is the home you've always envisioned. "
                f"Developed with uncompromising quality by {promoter} and fully RERA registered. Schedule your private walkthrough today."
            )
            opt2_text = (
                f"Auspicious beginnings start with smart investment decisions. This {fest}, secure high appreciation and luxury living at {name}, {loc}. "
                f"Boasting unmatched urban infrastructure, world-class schools, and bustling commercial corridors within easy reach, "
                f"these premium {u_space}homes offer generous layouts and superior finishes {price_offer}. "
                f"Every home is designed for optimal sunlight, ventilation, and privacy, backed by the proven development pedigree of {promoter}. "
                f"Benefit from special festive booking advantages and complete RERA assurance. Speak with our sales specialists and book your visit today."
            )
            opt3_text = (
                f"Experience an elevated standard of architectural refinement at {name}, an iconic enclave in {loc}. "
                f"Designed for those who appreciate sophistication, each spacious {u_space}residence features expansive private balconies, "
                f"grand living spaces, and state-of-the-art recreation facilities. "
                f"Enjoy temperature-controlled pools, jogging tracks, and multi-tier security, {price_offer}. "
                f"Brought to you by {promoter} with strict adherence to RERA standards. "
                f"Elevate your lifestyle this festive season—reserve your private guided tour today."
            )

    # ─────────────────────────────────────────────────────────────
    # BUCKET 6: 60s Videos (~53.5s speech, 110–125 words)
    # ─────────────────────────────────────────────────────────────
    else:
        if is_family:
            opt1_text = (
                f"A home is where your family creates lifelong memories. Welcome to {name}, a premier residential sanctuary in the vibrant heart of {loc}. "
                f"Thoughtfully designed for every generation, these expansive {u_space}luxury homes feature sunlit living spaces, spacious bedrooms, "
                f"and scenic private balconies {price_offer}. "
                f"Watch your children play freely across secure landscaped gardens, celebrate milestones in the community clubhouse, and enjoy peaceful morning walks. "
                f"Positioned close to top schools and healthcare, while offering 24-7 gated security and peaceful surroundings. "
                f"Developed with trusted pedigree by {promoter} and complete RERA transparency. "
                f"Give your family the life they truly deserve. Book your private on-site walkthrough today."
            )
            opt2_text = (
                f"Give your loved ones the space, comfort, and peaceful security of a true community at {name}, {loc}. "
                f"Surrounded by green parks and premier social infrastructure, these master-planned {u_space}homes offer superior finishes {price_offer}. "
                f"Every residence is designed with expansive living areas and multi-generational privacy, backed by 24-7 security. "
                f"Enjoy world-class amenities including a fully equipped fitness center, swimming pool, landscaped meditation gardens, and play zones. "
                f"Built with excellence by {promoter} and fully RERA compliant. "
                f"Take the first step toward your forever family home—connect with our property advisors and schedule your visit now."
            )
            opt3_text = (
                f"Step into a home where comfort and family joy come first. Welcome to {name}, {loc}'s premier family residential address. "
                f"From its striking facade to thoughtfully appointed interiors, every home is an expression of warmth and quality. "
                f"Choose from masterfully engineered {u_space}layouts {price_offer}, featuring generous living rooms, designer kitchens, "
                f"and private balconies overlooking peaceful greenery. "
                f"Indulge in resort-inspired lifestyle amenities, sports courts, and elegant banquet spaces for memorable family celebrations. "
                f"Built to the highest construction standards by {promoter} with certified RERA registration. "
                f"Schedule your personalized walkthrough and discover your new family address today."
            )
        elif festival == "None":
            opt1_text = (
                f"Step into an address defined by architectural prestige and timeless sophistication. "
                f"Welcome to {name}, a landmark residential enclave in the vibrant heart of {loc}. "
                f"Designed for discerning homeowners, this premier development offers expansive {u_space}luxury residences {price_offer}. "
                f"Experience generous open floor plans, floor-to-ceiling glass, and panoramic city skyline views. "
                f"Unwind at the signature clubhouse, take a dip in the temperature-controlled pool, and enjoy seamless transit links right at your doorstep. "
                f"Built to the highest standards of construction by {promoter} with certified RERA transparency. "
                f"Elevate your everyday lifestyle. Contact our senior real estate advisors and schedule your exclusive private walkthrough today."
            )
            opt2_text = (
                f"Strategic location, architectural distinction, and enduring investment value come together at {name}, {loc}. "
                f"Whether you are seeking your forever residence or a high-yielding real estate asset, "
                f"these master-planned {u_space}homes deliver exceptional capital growth potential {price_offer}. "
                f"Positioned minutes from premier tech parks, metro stations, and healthcare facilities, {name} balances urban convenience with peaceful tranquility. "
                f"Enjoy world-class amenities including an equipped fitness center, infinity pool, landscaped meditation gardens, and 24-7 security. "
                f"Developed with excellence by {promoter} and fully RERA compliant. "
                f"Take advantage of current pricing—connect with our senior property advisors and book your site visit now."
            )
            opt3_text = (
                f"Experience modern luxury redefined. Welcome to {name}, an iconic residential destination in {loc}. "
                f"From its striking contemporary facade to thoughtfully appointed interiors, every home is an expression of luxury. "
                f"Choose from masterfully engineered {u_space}layouts {price_offer}, featuring expansive living areas, "
                f"designer kitchens, and private balconies overlooking serene green gardens. "
                f"Indulge in resort-inspired lifestyle amenities, active sports courts, and elegant spaces for executive entertaining. "
                f"Built to the highest construction standards by {promoter} with certified RERA registration. "
                f"Schedule your personalized walkthrough and discover your new address today."
            )
        else:
            opt1_text = (
                f"The festival of {fest} symbolizes auspicious new beginnings, warmth, and the joy of coming home. "
                f"Welcome to {name}, a prestigious residential haven in the vibrant heart of {loc}. "
                f"Here, every detail is crafted to elevate your daily living experience. Discover expansive {u_space}luxury homes "
                f"featuring generous floor plans, natural sunlight, and scenic balcony views, {price_offer}. "
                f"Stroll across sprawling green parks, celebrate in the multi-purpose clubhouse, and stay connected with rapid transit links right at your doorstep. "
                f"Backed by the trusted legacy of {promoter} and complete RERA transparency. "
                f"Gift your loved ones the home they truly deserve this festive season. Call our team or visit our on-site experience centre today."
            )
            opt2_text = (
                f"Strategic location, architectural distinction, and enduring value come together this {fest} at {name}, {loc}. "
                f"Whether you are seeking your family's forever residence or a high-yielding real-estate asset, "
                f"these master-planned {u_space}homes deliver exceptional capital growth potential {price_offer}. "
                f"Positioned minutes from premier tech parks, metro stations, and healthcare facilities, {name} balances urban convenience with peaceful tranquility. "
                f"Enjoy world-class amenities including an equipped fitness center, infinity pool, landscaped meditation gardens, and 24-7 security. "
                f"Developed with excellence by {promoter} and fully RERA compliant. "
                f"Take advantage of limited-period festive pricing—connect with our senior property advisors and book your site visit now."
            )
            opt3_text = (
                f"Step into a realm of luxury and timeless comfort. Welcome to {name}, {loc}'s premier residential destination. "
                f"From its striking architectural facade to thoughtfully appointed interiors, every home is an expression of luxury. "
                f"Choose from masterfully engineered {u_space}layouts {price_offer}, featuring expansive living areas, "
                f"designer kitchens, and private balconies overlooking serene green gardens. "
                f"Indulge in resort-inspired lifestyle amenities, active sports courts, and elegant banquet spaces for memorable family celebrations. "
                f"Built to the highest construction standards by {promoter} with certified RERA registration. "
                f"Celebrate this {fest} with pride. Schedule your personalized walkthrough and discover your new address today."
            )

    if festival == "Family":
        t1, tone1 = "👨‍👩‍👧‍👦 Option 1: Where Your Family Thrives", "Heartwarming, emotional, family-first"
        t2, tone2 = "🌳 Option 2: Safe Community & Green Living", "Peaceful, secure, multi-generational"
        t3, tone3 = "🏡 Option 3: Cherished Lifelong Memories", "Aspirational, loving home"
    elif festival == "None":
        t1, tone1 = "📍 Option 1: Prime Location & Connectivity", "Fast-paced, modern, prime connectivity"
        t2, tone2 = "💎 Option 2: Value & High Appreciation", "Direct, high-yield, smart investment"
        t3, tone3 = "🏰 Option 3: Architectural Luxury & Elegance", "Sophisticated, aspirational, premium"
    else:
        t1, tone1 = "✨ Option 1: Festive & Auspicious Celebration", "Warm, emotional, celebratory"
        t2, tone2 = "💎 Option 2: Festive Offers & Investment Advantage", "Direct, festive incentives, smart decision"
        t3, tone3 = "🏰 Option 3: Luxury Living & Festive Elegance", "Sophisticated, aspirational, auspicious"

    return [
        ScriptOption(
            id="opt1",
            title=t1,
            tone=tone1,
            text=opt1_text,
            word_count=len(opt1_text.split()),
            estimated_speech_seconds=round(len(opt1_text.split()) / 2.25, 1),
            target_duration=duration,
            speaking_window=speaking_sec,
        ),
        ScriptOption(
            id="opt2",
            title=t2,
            tone=tone2,
            text=opt2_text,
            word_count=len(opt2_text.split()),
            estimated_speech_seconds=round(len(opt2_text.split()) / 2.25, 1),
            target_duration=duration,
            speaking_window=speaking_sec,
        ),
        ScriptOption(
            id="opt3",
            title=t3,
            tone=tone3,
            text=opt3_text,
            word_count=len(opt3_text.split()),
            estimated_speech_seconds=round(len(opt3_text.split()) / 2.25, 1),
            target_duration=duration,
            speaking_window=speaking_sec,
        ),
    ]
