"""
Ad Copy Writer Service
======================
Generates platform-compliant ad copy from a confirmed Project fact sheet.

Flow:
  1. Build a plain-text fact sheet context from confirmed Project fields
  2. Send to Groq with the copy_writer prompt
  3. Parse + enforce character limits from config/platforms.yaml
  4. Persist AdCopy to SQLite and return the model
"""

from __future__ import annotations

import json
import os
import re
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

import groq as groq_sdk
import yaml
from dotenv import load_dotenv

from models.fact_sheet import (
    Project, AdCopy, GoogleSearchCopy, MetaCopy,
)
from models.db import save_ad_copy, get_latest_ad_copy

load_dotenv()

# ─────────────────────────────────────────────
# Clients & Config
# ─────────────────────────────────────────────

_client = groq_sdk.Groq(api_key=os.getenv("GROQ_API_KEY"))
_MODEL = os.getenv("GROQ_MODEL", "openai/gpt-oss-120b")

_PLATFORMS_PATH = Path("config/platforms.yaml")
_COPY_PROMPT_PATH = Path("prompts/copy_writer.txt")

# Load once at module import
_CONFIG: dict = yaml.safe_load(_PLATFORMS_PATH.read_text())
_PLATFORMS: dict = _CONFIG["platforms"]
_COPY_PROMPT: str = _COPY_PROMPT_PATH.read_text()


# ─────────────────────────────────────────────
# Fact Sheet → Plain Text Context
# ─────────────────────────────────────────────

def _format_price(rupees: int) -> str:
    """Format whole rupees as Indian Cr notation. e.g. 14200000 → '₹1.42 Cr'"""
    if rupees >= 10_000_000:
        return f"₹{rupees / 10_000_000:.2f} Cr"
    if rupees >= 100_000:
        return f"₹{rupees / 100_000:.2f} Lakh"
    return f"₹{rupees:,}"


def build_fact_context(project: Project) -> str:
    """
    Render the project fact sheet as a structured plain-text block
    that the LLM will use as its ONLY information source.
    """
    lines: list[str] = ["=== CONFIRMED PROJECT FACT SHEET ===", ""]

    # Core identity
    if project.name:
        lines.append(f"Project Name: {project.name}")
    if project.rera_number:
        lines.append(f"RERA Number:  {project.rera_number}")
    if project.locality:
        lines.append(f"Location:     {project.locality}")
    if project.possession_date:
        lines.append(f"Possession:   {project.possession_date}")
    if project.construction_stage:
        lines.append(f"Stage:        {project.construction_stage}")

    # Units
    if project.units:
        lines.append("")
        lines.append("Unit Types:")
        for u in project.units:
            price_str = ""
            if u.price_min and u.price_max:
                price_str = f"{_format_price(u.price_min)} – {_format_price(u.price_max)}"
            elif u.price_min:
                price_str = f"{_format_price(u.price_min)} onwards"

            area_str = ""
            if u.carpet_sqft:
                area_str = f"{int(u.carpet_sqft)} sq ft carpet"
                if u.saleable_sqft:
                    area_str += f" / {int(u.saleable_sqft)} sq ft saleable"

            lines.append(
                f"  • {u.type_name}"
                + (f" — {area_str}" if area_str else "")
                + (f" — {price_str}" if price_str else "")
            )

    # Confirmed price range (from fact sheet if explicitly confirmed)
    price_range_fact = project.confirmed_facts.get("price_range")
    if price_range_fact:
        lines.append(f"\nPrice Range (confirmed): {price_range_fact.value}")

    # Amenities
    if project.amenities:
        lines.append("")
        lines.append("Amenities: " + ", ".join(project.amenities))

    # Landmarks
    if project.landmarks:
        lines.append("")
        lines.append("Nearby Landmarks:")
        for lm in project.landmarks:
            lines.append(f"  • {lm.name}: {lm.distance_minutes} min")

    lines.append("")
    lines.append("=== END FACT SHEET ===")
    return "\n".join(lines)


def build_platform_limits_context() -> str:
    """Render platform character limits as a plain-text reference for the LLM."""
    gs = _PLATFORMS.get("google_search", {})
    meta = _PLATFORMS.get("meta", {})
    return (
        "Platform character limits:\n"
        f"  Google Search headlines:    max {gs.get('headline', {}).get('max_chars', 30)} chars each, "
        f"up to {gs.get('headline', {}).get('max_count', 15)}\n"
        f"  Google Search descriptions: max {gs.get('description', {}).get('max_chars', 90)} chars each, "
        f"up to {gs.get('description', {}).get('max_count', 4)}\n"
        f"  Meta primary text hook:     first {meta.get('primary_text', {}).get('hook_chars', 125)} chars visible\n"
        f"  Meta headline:              max {meta.get('headline', {}).get('max_chars', 40)} chars\n"
        f"  Meta link description:      max {meta.get('link_description', {}).get('max_chars', 30)} chars\n"
    )


# ─────────────────────────────────────────────
# LLM Call
# ─────────────────────────────────────────────

def _validate_numbers(voice_script: str, fact_context: str) -> list[str]:
    """
    Ensure no hallucinated numbers in the voice script.
    Checks if every digit sequence in the script exists in the plain-text fact sheet.
    """
    numbers = re.findall(r'\b\d+(?:\.\d+)?\b', voice_script)
    violations = []
    for num in numbers:
        if num not in fact_context:
            violations.append(f"Number '{num}' not found in confirmed facts.")
    return violations


def _strip_fences(text: str) -> str:
    text = text.strip()
    if text.startswith("```"):
        lines = text.splitlines()
        text = "\n".join(
            lines[1:-1] if lines[-1].strip() == "```" else lines[1:]
        )
    return text.strip()


def _call_groq(fact_context: str) -> dict[str, Any]:
    """
    Send fact context to Groq and return parsed JSON copy dict.

    NOTE: openai/gpt-oss-* models on Groq suppress output when given a
    'system' role. We merge the system prompt into the user message instead.
    """
    # Merge system prompt + platform limits + fact sheet into one user message
    combined_message = (
        f"{_COPY_PROMPT}\n\n"
        f"---\n\n"
        f"{build_platform_limits_context()}\n\n"
        f"{fact_context}"
    )

    for attempt in range(3):
        response = _client.chat.completions.create(
            model=_MODEL,
            messages=[
                {"role": "user", "content": combined_message},
            ],
            temperature=0.7,
            max_tokens=4096,
        )
        choice = response.choices[0]
        finish = choice.finish_reason

        if finish == "length":
            raise ValueError(
                f"Groq truncated the response (finish_reason=length). "
                f"Reduce the prompt or increase max_tokens."
            )

        raw = _strip_fences(choice.message.content or "")
        if not raw:
            if attempt < 2:
                continue
            raise ValueError("Groq returned an empty response after 3 attempts.")

        try:
            parsed = json.loads(raw)
        except json.JSONDecodeError:
            match = re.search(r"\{.*\}", raw, re.DOTALL)
            if match:
                try:
                    parsed = json.loads(match.group())
                except json.JSONDecodeError:
                    if attempt == 2:
                        raise ValueError(f"Groq returned malformed JSON.\nRaw: {raw[:500]}")
                    continue
            else:
                if attempt == 2:
                    raise ValueError(f"Groq returned malformed JSON.\nRaw: {raw[:500]}")
                continue
                
        # Validate numbers in voice_script
        voice_script = parsed.get("voice_script", "")
        num_violations = _validate_numbers(voice_script, fact_context)
        
        if num_violations and attempt < 2:
            print(f"[copy_writer] Number violations found: {num_violations}. Retrying...")
            combined_message += (
                f"\n\nERROR in previous attempt: Your voice script contained hallucinated numbers: "
                f"{', '.join(num_violations)}. Please stick STRICTLY to the facts provided."
            )
            continue
            
        return parsed
        
    return {}


# ─────────────────────────────────────────────
# Enforcement
# ─────────────────────────────────────────────

def _enforce_limits(raw: dict[str, Any]) -> dict[str, Any]:
    """
    Hard-enforce all platform character limits against config/platforms.yaml.
    Truncates strings that exceed limits and caps list lengths.
    Returns a cleaned copy dict.
    """
    gs_cfg = _PLATFORMS.get("google_search", {})
    meta_cfg = _PLATFORMS.get("meta", {})

    hl_max   = gs_cfg.get("headline",    {}).get("max_chars", 30)
    hl_count = gs_cfg.get("headline",    {}).get("max_count", 15)
    desc_max  = gs_cfg.get("description", {}).get("max_chars", 90)
    desc_count = gs_cfg.get("description",{}).get("max_count", 4)

    meta_hook_max  = meta_cfg.get("primary_text",    {}).get("hook_chars", 125)
    meta_hl_max    = meta_cfg.get("headline",         {}).get("max_chars", 40)
    meta_link_max  = meta_cfg.get("link_description", {}).get("max_chars", 30)

    gs = raw.get("google_search", {})
    headlines    = [h[:hl_max]   for h in gs.get("headlines", [])[:hl_count]]
    descriptions = [d[:desc_max] for d in gs.get("descriptions", [])[:desc_count]]

    meta = raw.get("meta", {})
    primary_text     = meta.get("primary_text", "")
    meta_headline    = meta.get("headline", "")[:meta_hl_max]
    meta_link        = meta.get("link_description", "")[:meta_link_max]
    
    voice_script = raw.get("voice_script", "Luxury apartments available now. Book your visit today.")

    return {
        "google_search": {
            "headlines":    headlines,
            "descriptions": descriptions,
        },
        "meta": {
            "primary_text":     primary_text,
            "headline":         meta_headline,
            "link_description": meta_link,
        },
        "voice_script": voice_script
    }


def validate_copy_limits(copy_dict: dict[str, Any]) -> list[str]:
    """
    Check a copy dict against platform limits.
    Returns a list of violation strings (empty = all good).
    """
    gs_cfg = _PLATFORMS.get("google_search", {})
    meta_cfg = _PLATFORMS.get("meta", {})
    violations: list[str] = []

    hl_max    = gs_cfg.get("headline",    {}).get("max_chars", 30)
    desc_max  = gs_cfg.get("description", {}).get("max_chars", 90)
    meta_hl_max   = meta_cfg.get("headline",         {}).get("max_chars", 40)
    meta_link_max = meta_cfg.get("link_description", {}).get("max_chars", 30)

    gs = copy_dict.get("google_search", {})
    for i, h in enumerate(gs.get("headlines", []), 1):
        if len(h) > hl_max:
            violations.append(
                f"Google headline {i} is {len(h)} chars (limit {hl_max}): '{h}'"
            )
    for i, d in enumerate(gs.get("descriptions", []), 1):
        if len(d) > desc_max:
            violations.append(
                f"Google description {i} is {len(d)} chars (limit {desc_max})"
            )

    meta = copy_dict.get("meta", {})
    hl = meta.get("headline", "")
    if len(hl) > meta_hl_max:
        violations.append(
            f"Meta headline is {len(hl)} chars (limit {meta_hl_max}): '{hl}'"
        )
    link = meta.get("link_description", "")
    if len(link) > meta_link_max:
        violations.append(
            f"Meta link description is {len(link)} chars (limit {meta_link_max}): '{link}'"
        )

    return violations


# ─────────────────────────────────────────────
# Public API
# ─────────────────────────────────────────────

def generate_copy(project: Project) -> AdCopy:
    """
    Generate platform-ready ad copy for a project.

    Args:
        project: A Project with all required facts confirmed.
                 Raises ValueError if the generation gate is not open.

    Returns:
        AdCopy model (also persisted to SQLite).
    """
    if not project.is_ready_for_generation():
        raise ValueError(
            "Generation gate is locked. "
            "Both RERA number and price list must be confirmed before generating copy."
        )

    fact_context = build_fact_context(project)
    raw = _call_groq(fact_context)
    enforced = _enforce_limits(raw)

    # Check for any remaining violations (shouldn't happen after enforcement)
    violations = validate_copy_limits(enforced)
    if violations:
        # Log but don't block — limits were already truncated
        print(f"[copy_writer] Limit violations after enforcement: {violations}")

    ad_copy = AdCopy(
        project_id=project.id,
        google_search=GoogleSearchCopy(
            headlines=enforced["google_search"]["headlines"],
            descriptions=enforced["google_search"]["descriptions"],
        ),
        meta=MetaCopy(
            primary_text=enforced["meta"]["primary_text"],
            headline=enforced["meta"]["headline"],
            link_description=enforced["meta"]["link_description"],
        ),
        voice_script=enforced["voice_script"]
    )

    save_ad_copy(project.id, ad_copy.model_dump(mode="json"))
    return ad_copy


def get_copy(project_id: str) -> AdCopy | None:
    """Load the most recently generated AdCopy for a project."""
    raw = get_latest_ad_copy(project_id)
    if not raw:
        return None
    gs = raw["google_search"]
    meta = raw["meta"]
    return AdCopy(
        project_id=project_id,
        google_search=GoogleSearchCopy(**gs),
        meta=MetaCopy(**meta),
        voice_script=raw.get("voice_script", "")
    )


def copy_to_display(ad_copy: AdCopy) -> dict[str, Any]:
    """
    Render AdCopy as a display-friendly dict with char counts
    (useful for the Streamlit UI to show violations).
    """
    gs_cfg = _PLATFORMS.get("google_search", {})
    meta_cfg = _PLATFORMS.get("meta", {})

    hl_max   = gs_cfg.get("headline",    {}).get("max_chars", 30)
    desc_max = gs_cfg.get("description", {}).get("max_chars", 90)
    meta_hl_max   = meta_cfg.get("headline",         {}).get("max_chars", 40)
    meta_link_max = meta_cfg.get("link_description", {}).get("max_chars", 30)

    return {
        "google_search": {
            "headlines": [
                {"text": h, "chars": len(h), "limit": hl_max, "ok": len(h) <= hl_max}
                for h in ad_copy.google_search.headlines
            ],
            "descriptions": [
                {"text": d, "chars": len(d), "limit": desc_max, "ok": len(d) <= desc_max}
                for d in ad_copy.google_search.descriptions
            ],
        },
        "meta": {
            "primary_text":     ad_copy.meta.primary_text,
            "headline":         {"text": ad_copy.meta.headline,         "chars": len(ad_copy.meta.headline),         "limit": meta_hl_max,   "ok": len(ad_copy.meta.headline)         <= meta_hl_max},
            "link_description": {"text": ad_copy.meta.link_description, "chars": len(ad_copy.meta.link_description), "limit": meta_link_max, "ok": len(ad_copy.meta.link_description) <= meta_link_max},
        },
    }
