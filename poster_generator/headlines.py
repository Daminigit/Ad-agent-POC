"""
Headline Ideas Generator (Gemini Text Model)
============================================
Generates 3 punchy, compliant real-estate headlines (max 8 words each)
for the chosen festival and project using Google Gemini (gemini-2.5-flash).
Strictly relies on project JSON facts without inventing claims.
"""

from __future__ import annotations

import json
import os
import re
from typing import List, Optional

import requests
from dotenv import load_dotenv

try:
    from config import TEXT_MODEL_ID
    from project_data import ProjectData
except ImportError:
    from poster_generator.config import TEXT_MODEL_ID
    from poster_generator.project_data import ProjectData

load_dotenv()


def generate_headlines(
    project: ProjectData,
    festival: str = "Diwali",
    api_key: Optional[str] = None,
) -> List[str]:
    """
    Generate 3 short headline ideas (max 8 words each) for the poster.
    """
    effective_key = (
        api_key
        or os.getenv("GEMINI_API_KEY")
        or os.getenv("GOOGLE_API_KEY")
        or ""
    ).strip()

    if effective_key and not effective_key.startswith("your_"):
        try:
            return _call_gemini_for_headlines(project, festival, effective_key)
        except Exception:
            pass

    return _fallback_headlines(project, festival)


def _call_gemini_for_headlines(
    project: ProjectData,
    festival: str,
    api_key: str,
) -> List[str]:
    """Invoke Gemini text model to generate 3 short headlines."""
    festive_theme = festival if festival != "None" else "New Home"
    prompt = f"""You are a luxury real-estate copywriter for premier Indian developments.
Write 3 short, inspiring advertising headlines for a poster celebrating {festive_theme}.

PROJECT DETAILS:
- Name: {project.name}
- Location: {project.marketing_name}, {project.city}
- Units: {project.formatted_units_summary}
- Starting Price: {project.formatted_lowest_price}

CRITICAL RULES:
1. Each headline MUST be at most 8 words.
2. Emotional, elegant, and aspirational.
3. Examples of style:
   "This Diwali, Step Into Your Own Home"
   "New Lights, New Beginnings"
   "Celebrate Festive Joy at Aurelia Heights"
4. NEVER invent offers, discounts, percentages, 'best', 'guaranteed', or 'lowest price'.
5. Return ONLY a valid JSON array of 3 strings. No markdown fences, no explanations.

["Headline 1", "Headline 2", "Headline 3"]"""

    url = f"https://generativelanguage.googleapis.com/v1beta/models/{TEXT_MODEL_ID}:generateContent?key={api_key}"
    resp = requests.post(
        url,
        headers={"Content-Type": "application/json"},
        json={
            "contents": [{"parts": [{"text": prompt}]}],
            "generationConfig": {"temperature": 0.7, "maxOutputTokens": 300},
        },
        timeout=15,
    )

    if resp.status_code == 200:
        res_json = resp.json()
        candidates = res_json.get("candidates", [])
        if candidates:
            raw_text = candidates[0].get("content", {}).get("parts", [{}])[0].get("text", "")
            cleaned = re.sub(r"^```(?:json)?\s*|\s*```$", "", raw_text.strip(), flags=re.MULTILINE)
            items = json.loads(cleaned)
            if isinstance(items, list) and len(items) >= 3:
                return [str(h).strip().strip('"') for h in items[:3]]

    raise RuntimeError("Could not parse valid headlines from Gemini response.")


def _fallback_headlines(project: ProjectData, festival: str) -> List[str]:
    """Rule-based factually grounded headlines."""
    pname = project.name
    loc = project.marketing_name or project.city or "Prime Location"

    if festival and festival != "None":
        return [
            f"This {festival}, Step Into Your Own Home",
            f"Celebrate {festival} In Elegance at {pname}",
            f"New Lights, Auspicious Beginnings at {loc}",
        ]
    return [
        f"Elevated Living Begins at {pname}",
        f"Your Dream Home in {loc}",
        f"Experience Refined Luxury at {pname}",
    ]
