"""
Poster Review Agent — Streamlit UI Component
=============================================
A self-contained Streamlit page / section that runs the PosterReviewAgent
on generated posters and displays results as an interactive review panel.

Can be used in two ways:
  1. As a standalone Streamlit app:
        streamlit run agents/poster_review_ui.py

  2. Imported and called from within another Streamlit app
     (e.g. poster_generator/app.py):
        from agents.poster_review_ui import render_review_section
        render_review_section(poster_paths, project_data, festival)
"""

from __future__ import annotations

import os
import sys
from pathlib import Path
from typing import Dict, Optional

import streamlit as st

# ── path resolution ────────────────────────────────────────────────────────
_ROOT = Path(__file__).resolve().parent.parent
if str(_ROOT) not in sys.path:
    sys.path.insert(0, str(_ROOT))
_PG_DIR = _ROOT / "poster_generator"
if str(_PG_DIR) not in sys.path:
    sys.path.insert(0, str(_PG_DIR))

from agents.poster_reviewer import PosterReviewAgent, ReviewReport

try:
    from poster_generator.project_data import ProjectData, parse_project_json
except ImportError:
    from project_data import ProjectData, parse_project_json  # type: ignore


# ─────────────────────────────────────────────────────────────────────────────
# Shared CSS
# ─────────────────────────────────────────────────────────────────────────────

_CSS = """
<style>
.review-card {
    background: linear-gradient(135deg, rgba(20, 27, 45, 0.9) 0%, rgba(10, 14, 22, 0.95) 100%);
    border: 1px solid rgba(201, 162, 39, 0.25);
    border-radius: 12px;
    padding: 1.4rem 1.6rem;
    margin-bottom: 1rem;
}
.verdict-badge {
    display: inline-block;
    padding: 6px 14px;
    border-radius: 20px;
    font-weight: 700;
    font-size: 0.95rem;
    letter-spacing: 0.03em;
}
.verdict-approved      { background: rgba(16,185,129,0.2); color:#10B981; border:1px solid #10B981; }
.verdict-notes         { background: rgba(245,158,11,0.2);  color:#F59E0B; border:1px solid #F59E0B; }
.verdict-rejected      { background: rgba(239,68,68,0.2);   color:#EF4444; border:1px solid #EF4444; }
.score-bar-wrap        { margin: 6px 0; }
.score-label           { font-size: 0.82rem; color: #9CA3AF; margin-bottom: 2px; }
.check-pass            { color: #10B981; }
.check-fail            { color: #EF4444; }
.suggestion-item       { color: #FDE68A; font-size: 0.88rem; margin: 3px 0; }
</style>
"""


# ─────────────────────────────────────────────────────────────────────────────
# Helpers
# ─────────────────────────────────────────────────────────────────────────────

def _verdict_badge(verdict: str) -> str:
    cls_map = {
        "approved":            ("verdict-approved", "✅ APPROVED"),
        "approved_with_notes": ("verdict-notes",    "⚠️ APPROVED WITH NOTES"),
        "rejected":            ("verdict-rejected",  "❌ REJECTED"),
    }
    css_cls, label = cls_map.get(verdict, ("verdict-notes", "⏳ PENDING"))
    return f'<span class="verdict-badge {css_cls}">{label}</span>'


def _score_bar(score: int, max_score: int, label: str, passed: bool) -> str:
    pct = int((score / max_score) * 100) if max_score else 0
    colour = "#10B981" if passed else "#EF4444"
    icon = "✓" if passed else "✗"
    icon_cls = "check-pass" if passed else "check-fail"
    return f"""
    <div class="score-bar-wrap">
        <div class="score-label">
            <span class="{icon_cls}">{icon}</span> {label}
            &nbsp;<strong style="color:#F0F3F6">{score}/{max_score}</strong>
        </div>
        <div style="background:#1F2937; border-radius:4px; height:8px; width:100%">
            <div style="background:{colour}; width:{pct}%; height:8px; border-radius:4px;"></div>
        </div>
    </div>"""


def _run_review(
    image_path: Path,
    project: ProjectData,
    festival: str,
    dry_run: bool,
    model: str,
) -> ReviewReport:
    """Cached review runner (keyed by image path + project RERA)."""
    cache_key = f"review_{image_path}_{project.rera_number}_{festival}"
    if cache_key in st.session_state:
        return st.session_state[cache_key]

    agent = PosterReviewAgent(model=model, dry_run=dry_run)
    report = agent.review(image_path=image_path, project=project, festival=festival)
    st.session_state[cache_key] = report
    return report


# ─────────────────────────────────────────────────────────────────────────────
# Main UI Component
# ─────────────────────────────────────────────────────────────────────────────

def render_review_section(
    poster_paths: Dict[str, Path],
    project: ProjectData,
    festival: str = "None",
    dry_run: bool = False,
    model: str = PosterReviewAgent.DEFAULT_MODEL,
) -> None:
    """
    Render the Poster Review Agent section inside a Streamlit app.

    Parameters
    ----------
    poster_paths : dict
        Mapping of size_id → Path, e.g. {"instagram_post": Path(...), "story": Path(...)}.
    project : ProjectData
        Parsed project fact sheet.
    festival : str
        Festival name used when generating the posters.
    dry_run : bool
        True → skip Gemini API call (use stub scores). Useful when no API key.
    model : str
        Gemini model ID.
    """
    st.markdown(_CSS, unsafe_allow_html=True)
    st.divider()
    st.markdown("### 🤖 AI Poster Review Agent")
    st.caption(
        "Uses Gemini vision to score each poster on Compliance, Visual Quality, "
        "Copy Effectiveness, Brand Consistency and Platform Fit."
    )

    if dry_run:
        st.warning(
            "**Simulation Mode** — Gemini API call is skipped. "
            "Scores shown are illustrative stubs. "
            "Disable Simulation Mode in the sidebar to get a real review.",
            icon="⚠️",
        )

    if not poster_paths:
        st.info("No posters to review yet. Generate posters first.")
        return

    # ── Trigger button ─────────────────────────────────────────────────────
    col_btn, col_clear = st.columns([3, 1])
    with col_btn:
        run_review = st.button(
            "🔍 Run Poster Review",
            type="primary",
            use_container_width=True,
        )
    with col_clear:
        if st.button("🗑️ Clear Results", use_container_width=True):
            for key in list(st.session_state.keys()):
                if key.startswith("review_"):
                    del st.session_state[key]
            st.rerun()

    if not run_review and not any(
        f"review_{p}_{project.rera_number}_{festival}" in st.session_state
        for p in poster_paths.values()
    ):
        return

    # ── Run reviews ────────────────────────────────────────────────────────
    reports: Dict[str, ReviewReport] = {}
    with st.spinner("Reviewing posters with Gemini vision…"):
        for size_id, image_path in poster_paths.items():
            reports[size_id] = _run_review(
                image_path=image_path,
                project=project,
                festival=festival,
                dry_run=dry_run,
                model=model,
            )

    # ── Display results per poster ─────────────────────────────────────────
    cols = st.columns(len(reports), gap="large")
    size_labels = {
        "instagram_post": "📱 Instagram Post (4:5)",
        "story":          "📲 Story / WhatsApp (9:16)",
    }

    for col, (size_id, report) in zip(cols, reports.items()):
        with col:
            label = size_labels.get(size_id, size_id)
            st.markdown(f"#### {label}")

            # Overall score ring + verdict
            pct = report.overall_percentage
            st.markdown(
                f"""
                <div class="review-card">
                    <div style="display:flex; justify-content:space-between; align-items:center; margin-bottom:0.8rem">
                        <div>
                            <span style="font-size:2rem; font-weight:700; color:#F0F3F6">{report.total_score}</span>
                            <span style="color:#6B7280">/{report.max_total_score}</span>
                            <span style="color:#9CA3AF; font-size:0.85rem; margin-left:6px">({pct:.0f}%)</span>
                        </div>
                        {_verdict_badge(report.overall_verdict)}
                    </div>
                </div>
                """,
                unsafe_allow_html=True,
            )

            # Category score bars
            with st.expander("📊 Category Scores", expanded=True):
                for cat in [
                    report.compliance,
                    report.visual_quality,
                    report.copy_effectiveness,
                    report.brand_consistency,
                    report.platform_fit,
                ]:
                    st.markdown(
                        _score_bar(cat.score, cat.max_score, cat.name, cat.passed),
                        unsafe_allow_html=True,
                    )
                    if cat.notes:
                        st.caption(cat.notes)

            # Strengths / Issues / Suggestions
            if report.strengths:
                with st.expander("✅ Strengths"):
                    for s in report.strengths:
                        st.markdown(f"- {s}")

            if report.issues:
                with st.expander("⚠️ Issues", expanded=bool(report.issues)):
                    for i in report.issues:
                        st.markdown(f"- {i}")

            if report.suggestions:
                with st.expander("💡 Suggestions"):
                    for sug in report.suggestions:
                        st.markdown(
                            f'<p class="suggestion-item">→ {sug}</p>',
                            unsafe_allow_html=True,
                        )

            # Programmatic checks accordion
            pc = report.programmatic_checks
            if pc:
                with st.expander("🔬 Programmatic Checks"):
                    all_ok = pc.get("all_passed", False)
                    st.markdown(
                        f"**Status:** {'✅ All Passed' if all_ok else '❌ Some Failed'}"
                    )
                    for detail in pc.get("details", []):
                        st.markdown(f"- {detail}")
                    cr = pc.get("contrast_ratios", {})
                    if cr:
                        st.markdown(
                            f"**WCAG Contrast** — RERA Strip: `{cr.get('rera_strip', 'N/A')}:1` "
                            f"| Panel: `{cr.get('panel_text', 'N/A')}:1`"
                        )

            if report.error:
                st.error(f"Review error: {report.error}")

    # ── Aggregate summary ──────────────────────────────────────────────────
    if len(reports) > 1:
        verdicts = [r.overall_verdict for r in reports.values()]
        avg_score = sum(r.total_score for r in reports.values()) / len(reports)
        if all(v == "approved" for v in verdicts):
            st.success(f"🎉 All {len(reports)} posters **Approved** — Avg score: {avg_score:.0f}/50")
        elif "rejected" in verdicts:
            st.error(
                f"❌ {verdicts.count('rejected')} poster(s) **Rejected** — "
                "Fix issues before uploading to ad platforms."
            )
        else:
            st.warning(
                f"⚠️ Posters approved with notes — review suggestions above. "
                f"Avg score: {avg_score:.0f}/50"
            )


# ─────────────────────────────────────────────────────────────────────────────
# Standalone Streamlit App
# ─────────────────────────────────────────────────────────────────────────────

def _standalone_app() -> None:
    """Full standalone Streamlit page for the Poster Review Agent."""
    st.set_page_config(
        page_title="Poster Review Agent | Ad Agent POC",
        page_icon="🤖",
        layout="wide",
    )

    st.markdown(_CSS, unsafe_allow_html=True)
    st.markdown("## 🤖 Poster Review Agent")
    st.caption("Upload poster images + a project JSON to get an AI quality review.")

    with st.sidebar:
        st.markdown("### ⚙️ Configuration")
        api_key_input = st.text_input(
            "Gemini API Key",
            value=os.getenv("GEMINI_API_KEY", ""),
            type="password",
        )
        if api_key_input:
            os.environ["GEMINI_API_KEY"] = api_key_input.strip()

        dry_run = st.checkbox(
            "Simulation Mode (no API call)",
            value=not bool(api_key_input),
        )
        model = st.selectbox(
            "Gemini Model",
            ["gemini-2.5-flash", "gemini-2.5-pro", "gemini-2.0-flash"],
            index=0,
        )
        festival = st.selectbox(
            "Festival theme",
            ["None", "Diwali", "Ugadi", "Dussehra", "Ganesh Chaturthi",
             "Onam", "Pongal/Sankranti", "Christmas", "Eid", "New Year"],
            index=1,
        )

    col1, col2 = st.columns([1, 2])

    with col1:
        st.markdown("#### Upload Project JSON")
        json_file = st.file_uploader("Project JSON", type=["json"])
        st.markdown("#### Upload Poster Images")
        image_files = st.file_uploader(
            "Poster PNG/JPG files",
            type=["png", "jpg", "jpeg"],
            accept_multiple_files=True,
        )

        # Quick-load sample
        sample_json = _ROOT / "poster_generator" / "sample_assets" / "aurelia_heights.json"
        sample_posters_dir = _ROOT / "output" / "posters"
        if st.button("📂 Load Aurelia Heights Sample") and sample_json.exists():
            st.session_state["sample_mode"] = True

    # ── Resolve project + images ───────────────────────────────────────────
    project: Optional[ProjectData] = None
    poster_paths: Dict[str, Path] = {}

    if st.session_state.get("sample_mode") and sample_json.exists():
        try:
            project = parse_project_json(sample_json)
            for png in sorted(sample_posters_dir.glob("*.png")):
                poster_paths[png.stem] = png
            st.success(f"Loaded sample: {project.name} | {len(poster_paths)} poster(s)")
        except Exception as exc:
            st.error(f"Could not load sample: {exc}")

    elif json_file and image_files:
        import tempfile
        tmp_dir = Path(tempfile.mkdtemp())
        json_path = tmp_dir / "project.json"
        json_path.write_bytes(json_file.read())
        try:
            project = parse_project_json(json_path)
        except Exception as exc:
            st.error(f"Project JSON error: {exc}")

        for uf in image_files:
            img_path = tmp_dir / uf.name
            img_path.write_bytes(uf.read())
            poster_paths[img_path.stem] = img_path

    # ── Display + Review ───────────────────────────────────────────────────
    if project and poster_paths:
        with col2:
            st.markdown("#### Poster Previews")
            preview_cols = st.columns(min(len(poster_paths), 3))
            for pc, (sid, pp) in zip(preview_cols, poster_paths.items()):
                with pc:
                    st.image(str(pp), use_container_width=True, caption=sid)

        render_review_section(
            poster_paths=poster_paths,
            project=project,
            festival=festival,
            dry_run=dry_run,
            model=model,
        )
    elif not project:
        st.info("Upload a project JSON file (or load the sample) to get started.")
    elif not poster_paths:
        st.info("Upload at least one poster image to review.")


if __name__ == "__main__":
    _standalone_app()

