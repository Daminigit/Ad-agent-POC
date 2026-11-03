"""
Poster Review Agent
===================
An LLM-powered visual quality reviewer for real-estate festive posters.

Uses Google Gemini's vision capability to analyse a rendered poster image
against the project's confirmed fact sheet and a structured rubric, then
returns a detailed ReviewReport with scores, pass/fail flags, and
actionable improvement suggestions.

Integrates with:
  - poster_generator/checks.py  (programmatic pre-save checks)
  - services/validation.py      (post-save OCR checks)
  - poster_generator/project_data.py (ProjectData dataclass)

Usage (standalone):
    python agents/poster_reviewer.py \
        --image output/posters/aurelia_heights_diwali_instagram.png \
        --project poster_generator/sample_assets/aurelia_heights.json

Usage (programmatic):
    from agents.poster_reviewer import PosterReviewAgent, ReviewReport
    agent  = PosterReviewAgent()
    report = agent.review(image_path="output/posters/...", project=project_data)
    print(report.summary())
"""

from __future__ import annotations

import argparse
import base64
import json
import os
import sys
import textwrap
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Dict, List, Optional

from dotenv import load_dotenv

# ── resolve imports whether run as a module or from repo root ──────────────
_ROOT = Path(__file__).resolve().parent.parent
if str(_ROOT) not in sys.path:
    sys.path.insert(0, str(_ROOT))
_PG_DIR = _ROOT / "poster_generator"
if str(_PG_DIR) not in sys.path:
    sys.path.insert(0, str(_PG_DIR))

try:
    from poster_generator.project_data import ProjectData
    from poster_generator.checks import verify_poster
except ImportError:
    from project_data import ProjectData  # type: ignore
    from checks import verify_poster      # type: ignore

load_dotenv()

# ─────────────────────────────────────────────────────────────────────────────
# Data Models
# ─────────────────────────────────────────────────────────────────────────────

@dataclass
class CategoryScore:
    """Score + notes for a single review category."""
    name: str
    score: int          # 0–10
    max_score: int = 10
    notes: str = ""
    passed: bool = True

    @property
    def percentage(self) -> float:
        return (self.score / self.max_score) * 100 if self.max_score else 0


@dataclass
class ReviewReport:
    """Full structured output from the PosterReviewAgent."""

    image_path: str
    project_name: str
    rera_number: str

    # ── Programmatic check results (from checks.py) ───────────────────────
    programmatic_checks: Dict[str, Any] = field(default_factory=dict)

    # ── LLM Vision Scores ─────────────────────────────────────────────────
    compliance: CategoryScore = field(
        default_factory=lambda: CategoryScore("Compliance & Legal", 0)
    )
    visual_quality: CategoryScore = field(
        default_factory=lambda: CategoryScore("Visual Quality", 0)
    )
    copy_effectiveness: CategoryScore = field(
        default_factory=lambda: CategoryScore("Copy & Messaging", 0)
    )
    brand_consistency: CategoryScore = field(
        default_factory=lambda: CategoryScore("Brand Consistency", 0)
    )
    platform_fit: CategoryScore = field(
        default_factory=lambda: CategoryScore("Platform Fit", 0)
    )

    # ── Narrative Feedback ────────────────────────────────────────────────
    strengths: List[str] = field(default_factory=list)
    issues: List[str] = field(default_factory=list)
    suggestions: List[str] = field(default_factory=list)

    # ── Overall ───────────────────────────────────────────────────────────
    overall_verdict: str = "pending"   # "approved" | "approved_with_notes" | "rejected"
    raw_llm_response: str = ""
    error: Optional[str] = None

    # ─────────────────────────────────────────────────────────────────────
    @property
    def total_score(self) -> int:
        cats = [
            self.compliance, self.visual_quality,
            self.copy_effectiveness, self.brand_consistency, self.platform_fit,
        ]
        return sum(c.score for c in cats)

    @property
    def max_total_score(self) -> int:
        cats = [
            self.compliance, self.visual_quality,
            self.copy_effectiveness, self.brand_consistency, self.platform_fit,
        ]
        return sum(c.max_score for c in cats)

    @property
    def overall_percentage(self) -> float:
        return (self.total_score / self.max_total_score * 100) if self.max_total_score else 0

    def verdict_emoji(self) -> str:
        if self.overall_verdict == "approved":
            return "✅"
        if self.overall_verdict == "approved_with_notes":
            return "⚠️"
        return "❌"

    # ─────────────────────────────────────────────────────────────────────
    def summary(self) -> str:
        """Return a human-readable review summary."""
        verdict_map = {
            "approved":            "APPROVED",
            "approved_with_notes": "APPROVED WITH NOTES",
            "rejected":            "REJECTED",
            "pending":             "PENDING",
        }
        lines = [
            "=" * 60,
            f"POSTER REVIEW REPORT — {self.project_name}",
            "=" * 60,
            f"Image : {Path(self.image_path).name}",
            f"RERA  : {self.rera_number}",
            "",
            f"Overall Score : {self.total_score}/{self.max_total_score}  "
            f"({self.overall_percentage:.0f}%)",
            f"Verdict       : {self.verdict_emoji()} {verdict_map.get(self.overall_verdict, self.overall_verdict)}",
            "",
            "── Category Scores ─────────────────────────────────────",
        ]
        for cat in [
            self.compliance, self.visual_quality,
            self.copy_effectiveness, self.brand_consistency, self.platform_fit,
        ]:
            bar = "█" * cat.score + "░" * (cat.max_score - cat.score)
            flag = "✓" if cat.passed else "✗"
            lines.append(f"  {flag} {cat.name:<26} {bar} {cat.score}/{cat.max_score}")
            if cat.notes:
                for note in textwrap.wrap(cat.notes, width=70):
                    lines.append(f"      {note}")

        if self.strengths:
            lines += ["", "── Strengths ───────────────────────────────────────────"]
            lines += [f"  ✓ {s}" for s in self.strengths]

        if self.issues:
            lines += ["", "── Issues ──────────────────────────────────────────────"]
            lines += [f"  ✗ {i}" for i in self.issues]

        if self.suggestions:
            lines += ["", "── Suggestions ─────────────────────────────────────────"]
            lines += [f"  → {s}" for s in self.suggestions]

        # Programmatic checks summary
        pc = self.programmatic_checks
        if pc:
            lines += ["", "── Programmatic Checks ─────────────────────────────────"]
            for detail in pc.get("details", []):
                lines.append(f"  {detail}")
            cr = pc.get("contrast_ratios", {})
            if cr:
                lines.append(
                    f"  WCAG Contrast  —  RERA Strip: {cr.get('rera_strip', 'N/A')}:1  |  "
                    f"Panel Text: {cr.get('panel_text', 'N/A')}:1"
                )

        if self.error:
            lines += ["", f"⚠ Review Error: {self.error}"]

        lines.append("=" * 60)
        return "\n".join(lines)

    def to_dict(self) -> Dict[str, Any]:
        """Serialise to a plain dict (for JSON / Streamlit display)."""
        return {
            "image_path": self.image_path,
            "project_name": self.project_name,
            "rera_number": self.rera_number,
            "overall_score": self.total_score,
            "max_score": self.max_total_score,
            "overall_percentage": round(self.overall_percentage, 1),
            "overall_verdict": self.overall_verdict,
            "categories": {
                cat.name: {
                    "score": cat.score,
                    "max": cat.max_score,
                    "passed": cat.passed,
                    "notes": cat.notes,
                }
                for cat in [
                    self.compliance, self.visual_quality,
                    self.copy_effectiveness, self.brand_consistency, self.platform_fit,
                ]
            },
            "strengths": self.strengths,
            "issues": self.issues,
            "suggestions": self.suggestions,
            "programmatic_checks": self.programmatic_checks,
            "error": self.error,
        }


# ─────────────────────────────────────────────────────────────────────────────
# Review Prompt
# ─────────────────────────────────────────────────────────────────────────────

_REVIEW_PROMPT_TEMPLATE = """
You are a senior creative director and compliance expert specialising in
real-estate advertising in India. Review the attached poster image against
the project fact sheet below and return a JSON object — nothing else.

PROJECT FACT SHEET
==================
Project Name    : {project_name}
Promoter        : {promoter}
RERA Number     : {rera_number}
Location        : {marketing_name}, {city}
Available Units : {available_units}
Starting Price  : {formatted_price}
Travel Times    : {travel_times}
Primary Colour  : {primary_colour}
Secondary Colour: {secondary_colour}
Festival        : {festival}

SCORING RUBRIC (score each category 0–10)
==========================================

1. compliance_legal (max 10)
   - RERA number present, legible, ≥ 2.5 % of poster height        (+3)
   - "Artist's impression" text visible                              (+2)
   - Price disclaimer ("*Price excludes …") present                  (+2)
   - "Terms & conditions apply" visible                              (+1)
   - No claim that cannot be confirmed from the fact sheet           (+2)

2. visual_quality (max 10)
   - Hero image sharp, well-lit, not blurry                         (+2)
   - Typography is readable — no awkward line breaks                 (+2)
   - Layout hierarchy clear: headline → details → CTA               (+2)
   - No clutter or elements bleeding off edges                       (+2)
   - Overall premium, luxury feel appropriate to the segment         (+2)

3. copy_effectiveness (max 10)
   - Headline is specific and compelling (not generic)               (+3)
   - Price / unit type / area facts visible and accurate             (+3)
   - CTA (phone / site visit) present and actionable                 (+2)
   - Location + landmark mentioned                                   (+2)

4. brand_consistency (max 10)
   - Logo present and unobscured                                     (+3)
   - Primary/secondary brand colours used correctly                  (+3)
   - Fonts match a premium real-estate aesthetic                     (+2)
   - Developer name clearly shown                                    (+2)

5. platform_fit (max 10)
   - Composition works for this aspect ratio (no awkward crops)      (+3)
   - Key text stays in the safe-zone (not near edges)               (+3)
   - Font sizes readable at a mobile thumb-scroll speed              (+2)
   - Visual weight is appropriate for feed vs story format           (+2)

RESPONSE FORMAT — return ONLY this JSON (no markdown fences):
{{
  "compliance": {{
    "score": <int 0-10>,
    "passed": <bool>,
    "notes": "<one concise sentence>"
  }},
  "visual_quality": {{
    "score": <int 0-10>,
    "passed": <bool>,
    "notes": "<one concise sentence>"
  }},
  "copy_effectiveness": {{
    "score": <int 0-10>,
    "passed": <bool>,
    "notes": "<one concise sentence>"
  }},
  "brand_consistency": {{
    "score": <int 0-10>,
    "passed": <bool>,
    "notes": "<one concise sentence>"
  }},
  "platform_fit": {{
    "score": <int 0-10>,
    "passed": <bool>,
    "notes": "<one concise sentence>"
  }},
  "strengths": ["<point 1>", "<point 2>", "<point 3>"],
  "issues":    ["<issue 1>", "<issue 2>"],
  "suggestions": ["<actionable fix 1>", "<actionable fix 2>", "<actionable fix 3>"],
  "overall_verdict": "<approved|approved_with_notes|rejected>"
}}

overall_verdict rules:
  approved            → total score ≥ 40 AND compliance ≥ 8
  approved_with_notes → total score ≥ 30 AND compliance ≥ 6
  rejected            → anything else
""".strip()


# ─────────────────────────────────────────────────────────────────────────────
# Agent
# ─────────────────────────────────────────────────────────────────────────────

class PosterReviewAgent:
    """
    LLM-powered poster reviewer.

    Parameters
    ----------
    model : str
        Gemini model ID that supports image input.
    api_key : str, optional
        Overrides the GEMINI_API_KEY env variable.
    dry_run : bool
        If True, skips the Gemini call and returns a stub report
        (useful for testing layout / CI pipelines without spending tokens).
    """

    DEFAULT_MODEL = "gemini-2.5-flash"

    def __init__(
        self,
        model: str = DEFAULT_MODEL,
        api_key: Optional[str] = None,
        dry_run: bool = False,
    ) -> None:
        self.model = model
        self.dry_run = dry_run
        self._api_key = api_key or os.getenv("GEMINI_API_KEY", "")

        if not self.dry_run:
            if not self._api_key:
                raise EnvironmentError(
                    "GEMINI_API_KEY is not set. "
                    "Export it or pass api_key= to PosterReviewAgent()."
                )
            try:
                import google.generativeai as genai
                genai.configure(api_key=self._api_key)
                self._genai = genai
            except ImportError as exc:
                raise ImportError(
                    "google-generativeai is required. "
                    "Run: pip install google-generativeai"
                ) from exc

    # ── Public API ────────────────────────────────────────────────────────

    def review(
        self,
        image_path: str | Path,
        project: ProjectData,
        festival: str = "None",
        run_programmatic_checks: bool = True,
    ) -> ReviewReport:
        """
        Review a single poster image.

        Parameters
        ----------
        image_path : str | Path
            Path to the rendered PNG/JPEG poster.
        project : ProjectData
            Parsed project fact sheet (from poster_generator/project_data.py).
        festival : str
            Festival theme used when generating the poster.
        run_programmatic_checks : bool
            Whether to also run the pixel-level checks from checks.py.

        Returns
        -------
        ReviewReport
            Structured report with scores, verdict, and suggestions.
        """
        image_path = Path(image_path)
        if not image_path.exists():
            return ReviewReport(
                image_path=str(image_path),
                project_name=project.name,
                rera_number=project.rera_number,
                overall_verdict="rejected",
                error=f"Image file not found: {image_path}",
            )

        report = ReviewReport(
            image_path=str(image_path),
            project_name=project.name,
            rera_number=project.rera_number,
        )

        # 1. Programmatic pixel-level checks (fast, free)
        if run_programmatic_checks:
            report.programmatic_checks = self._run_programmatic_checks(
                image_path, project
            )

        # 2. LLM vision review
        if self.dry_run:
            self._apply_dry_run_stub(report)
        else:
            self._run_llm_review(image_path, project, festival, report)

        return report

    def review_batch(
        self,
        image_paths: List[str | Path],
        project: ProjectData,
        festival: str = "None",
    ) -> List[ReviewReport]:
        """Review multiple poster images for the same project."""
        return [
            self.review(p, project, festival=festival)
            for p in image_paths
        ]

    # ── Internal helpers ──────────────────────────────────────────────────

    def _run_programmatic_checks(
        self,
        image_path: Path,
        project: ProjectData,
    ) -> Dict[str, Any]:
        """Run checks.py verify_poster on the image."""
        try:
            from PIL import Image as PILImage
            img = PILImage.open(image_path)
            w, h = img.size
            return verify_poster(img, project, w, h)
        except Exception as exc:
            return {"error": str(exc), "all_passed": False, "details": []}

    def _build_prompt(self, project: ProjectData, festival: str) -> str:
        return _REVIEW_PROMPT_TEMPLATE.format(
            project_name=project.name,
            promoter=project.promoter,
            rera_number=project.rera_number,
            marketing_name=project.marketing_name,
            city=project.city,
            available_units=project.formatted_units_summary,
            formatted_price=project.formatted_lowest_price,
            travel_times=", ".join(project.travel_times) or "N/A",
            primary_colour=project.brand.primary_colour,
            secondary_colour=project.brand.secondary_colour,
            festival=festival,
        )

    def _encode_image(self, image_path: Path) -> Dict[str, Any]:
        """Encode image as base64 inline data for Gemini."""
        suffix = image_path.suffix.lower()
        mime_map = {".png": "image/png", ".jpg": "image/jpeg", ".jpeg": "image/jpeg"}
        mime = mime_map.get(suffix, "image/png")
        data = base64.standard_b64encode(image_path.read_bytes()).decode("utf-8")
        return {"mime_type": mime, "data": data}

    def _run_llm_review(
        self,
        image_path: Path,
        project: ProjectData,
        festival: str,
        report: ReviewReport,
    ) -> None:
        """Call Gemini with the poster image and parse the structured response."""
        prompt_text = self._build_prompt(project, festival)
        image_data = self._encode_image(image_path)

        try:
            model = self._genai.GenerativeModel(self.model)
            response = model.generate_content(
                [
                    prompt_text,
                    {"inline_data": image_data},
                ],
                generation_config={
                    "response_mime_type": "application/json",
                    "temperature": 0.2,
                    "max_output_tokens": 1024,
                },
            )
            raw = response.text.strip()
            report.raw_llm_response = raw
            self._parse_llm_response(raw, report)

        except Exception as exc:
            report.error = f"Gemini API error: {exc}"
            report.overall_verdict = "pending"

    def _parse_llm_response(self, raw: str, report: ReviewReport) -> None:
        """Parse Gemini JSON output into the ReviewReport fields."""
        # Strip accidental markdown fences
        if raw.startswith("```"):
            raw = raw.split("```")[1]
            if raw.startswith("json"):
                raw = raw[4:]
        raw = raw.strip()

        try:
            data: Dict[str, Any] = json.loads(raw)
        except json.JSONDecodeError as exc:
            report.error = f"Failed to parse LLM JSON: {exc}\nRaw: {raw[:300]}"
            return

        def _cat(key: str, display_name: str) -> CategoryScore:
            d = data.get(key, {})
            return CategoryScore(
                name=display_name,
                score=int(d.get("score", 0)),
                passed=bool(d.get("passed", False)),
                notes=str(d.get("notes", "")),
            )

        report.compliance         = _cat("compliance",         "Compliance & Legal")
        report.visual_quality     = _cat("visual_quality",     "Visual Quality")
        report.copy_effectiveness = _cat("copy_effectiveness", "Copy & Messaging")
        report.brand_consistency  = _cat("brand_consistency",  "Brand Consistency")
        report.platform_fit       = _cat("platform_fit",       "Platform Fit")

        report.strengths   = data.get("strengths",   [])
        report.issues      = data.get("issues",      [])
        report.suggestions = data.get("suggestions", [])
        report.overall_verdict = data.get("overall_verdict", "pending")

    def _apply_dry_run_stub(self, report: ReviewReport) -> None:
        """Fill the report with stub data for dry-run / testing mode."""
        report.compliance         = CategoryScore("Compliance & Legal", 9,  passed=True,  notes="[DRY RUN] RERA and disclaimers appear compliant.")
        report.visual_quality     = CategoryScore("Visual Quality",     8,  passed=True,  notes="[DRY RUN] Background quality looks premium.")
        report.copy_effectiveness = CategoryScore("Copy & Messaging",   7,  passed=True,  notes="[DRY RUN] Headline is festive; could add carpet area.")
        report.brand_consistency  = CategoryScore("Brand Consistency",  8,  passed=True,  notes="[DRY RUN] Brand colours and logo are consistent.")
        report.platform_fit       = CategoryScore("Platform Fit",       8,  passed=True,  notes="[DRY RUN] Layout fits selected format well.")
        report.strengths   = ["Strong RERA compliance", "Clear pricing callout", "Good visual hierarchy"]
        report.issues      = ["[DRY RUN] No live LLM call was made"]
        report.suggestions = ["Add carpet area (sq ft) to unit callout", "Consider unit-specific pricing instead of 'from' price"]
        report.overall_verdict = "approved_with_notes"


# ─────────────────────────────────────────────────────────────────────────────
# CLI Entry Point
# ─────────────────────────────────────────────────────────────────────────────

def _cli() -> None:
    parser = argparse.ArgumentParser(
        prog="poster_reviewer",
        description="AI Poster Review Agent — analyses a festive real-estate poster.",
    )
    parser.add_argument(
        "--image", "-i", required=True,
        help="Path to the poster PNG/JPEG file.",
    )
    parser.add_argument(
        "--project", "-p", required=True,
        help="Path to the project JSON data file.",
    )
    parser.add_argument(
        "--festival", "-f", default="None",
        help="Festival theme (e.g. Diwali, Ugadi). Default: None.",
    )
    parser.add_argument(
        "--model", "-m", default=PosterReviewAgent.DEFAULT_MODEL,
        help=f"Gemini model to use (default: {PosterReviewAgent.DEFAULT_MODEL}).",
    )
    parser.add_argument(
        "--dry-run", action="store_true",
        help="Skip the Gemini API call and return stub scores (for testing).",
    )
    parser.add_argument(
        "--json", action="store_true",
        help="Output review as JSON instead of the human-readable summary.",
    )
    args = parser.parse_args()

    # Parse project data
    project_path = Path(args.project)
    if not project_path.exists():
        print(f"ERROR: Project file not found: {project_path}", file=sys.stderr)
        sys.exit(1)

    try:
        from poster_generator.project_data import parse_project_json
    except ImportError:
        from project_data import parse_project_json  # type: ignore

    try:
        project = parse_project_json(project_path)
    except Exception as exc:
        print(f"ERROR parsing project JSON: {exc}", file=sys.stderr)
        sys.exit(1)

    # Run review
    agent = PosterReviewAgent(model=args.model, dry_run=args.dry_run)
    report = agent.review(
        image_path=args.image,
        project=project,
        festival=args.festival,
    )

    if args.json:
        print(json.dumps(report.to_dict(), indent=2, ensure_ascii=False))
    else:
        print(report.summary())

    # Exit code: 0 = approved/approved_with_notes, 1 = rejected/error
    sys.exit(0 if report.overall_verdict in ("approved", "approved_with_notes") else 1)


if __name__ == "__main__":
    _cli()

