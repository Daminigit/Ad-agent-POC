"""
Festive Real-Estate Poster Generator — Streamlit Web Application
================================================================
Transforms property renders, project details JSON, and brand logo into compliant
festive real-estate posters across Instagram Post (4:5) and Story (9:16) formats.
"""

from __future__ import annotations

import io
import os
import sys
import tempfile
import zipfile
from pathlib import Path
from typing import Dict, List, Optional

_pg_dir = str(Path(__file__).resolve().parent)
if _pg_dir in sys.path:
    sys.path.remove(_pg_dir)
sys.path.insert(0, _pg_dir)

import streamlit as st
from PIL import Image
from dotenv import load_dotenv

from config import FESTIVALS, IMAGE_PRICE_USD, SIZES
from project_data import (
    ProjectData,
    RenderInfo,
    filter_approved_renders,
    parse_project_json,
)
from background import generate_festive_background, build_background_prompt
from headlines import generate_headlines
from layout import render_poster
from layout_templates import render_poster_with_template, TEMPLATES
from checks import verify_poster

load_dotenv()

# Page Setup
st.set_page_config(
    page_title="Festive Poster Generator | Nano Banana",
    page_icon="🎨",
    layout="wide",
    initial_sidebar_state="expanded",
)

# Custom Styling (Dark elegance, gold accents, polished cards)
st.markdown("""
<style>
    @import url('https://fonts.googleapis.com/css2?family=Plus+Jakarta+Sans:wght@400;500;600;700&family=Playfair+Display:wght@600;700&display=swap');
    
    html, body, [class*="css"] {
        font-family: 'Plus Jakarta Sans', sans-serif;
    }
    
    .stApp {
        background: radial-gradient(circle at 10% 20%, #0d1117 0%, #080a0e 100%);
        color: #f0f3f6;
    }
    
    .hero-card {
        padding: 1.6rem 2rem;
        background: linear-gradient(135deg, rgba(31, 42, 68, 0.45) 0%, rgba(13, 17, 23, 0.7) 100%);
        border: 1px solid rgba(201, 162, 39, 0.3);
        border-radius: 14px;
        margin-bottom: 1.5rem;
        box-shadow: 0 10px 30px rgba(0, 0, 0, 0.4);
    }
    
    .gold-title {
        color: #D4AF37;
        font-family: 'Playfair Display', serif;
        font-weight: 700;
        margin: 0;
    }
    
    .status-badge {
        padding: 4px 10px;
        border-radius: 8px;
        font-size: 0.8rem;
        font-weight: 600;
        display: inline-block;
    }
    .badge-verified {
        background: rgba(16, 185, 129, 0.2);
        color: #10B981;
        border: 1px solid #10B981;
    }
    .badge-draft {
        background: rgba(239, 68, 68, 0.2);
        color: #EF4444;
        border: 1px solid #EF4444;
    }
    .warning-box {
        padding: 12px 16px;
        background: rgba(245, 158, 11, 0.15);
        border: 1px solid #F59E0B;
        border-radius: 8px;
        color: #FDE68A;
        font-size: 0.9rem;
        margin: 12px 0;
    }
</style>
""", unsafe_allow_html=True)

# ─────────────────────────────────────────────
# Sidebar: Setup & Configuration
# ─────────────────────────────────────────────

with st.sidebar:
    st.markdown("### ⚙️ Poster Engine")
    api_key_input = st.text_input(
        "Google Gemini API Key",
        value=os.getenv("GEMINI_API_KEY", ""),
        type="password",
        help="Reads from GEMINI_API_KEY in .env automatically.",
    )
    if api_key_input:
        os.environ["GEMINI_API_KEY"] = api_key_input.strip()

    enable_simulation = st.checkbox(
        "Simulation Mode (--dry-run)",
        value=(not bool(api_key_input)),
        help="Preview layout, prompts, and Pillow typography without calling paid image models.",
    )

    st.divider()
    st.markdown("#### 🎨 Poster Template")
    template_options = {k: v[0] for k, v in TEMPLATES.items()}
    selected_template = st.selectbox(
        "Choose a layout style",
        options=list(template_options.keys()),
        format_func=lambda k: template_options[k],
        index=0,
        help="Each template has a distinct visual style. All are RERA-compliant.",
    )
    st.caption(TEMPLATES[selected_template][1])

    st.divider()
    st.markdown("#### 🎯 Active Poster Sizes (V1)")
    enabled_sizes = [s for s in SIZES.values() if s["enabled"]]
    for s in enabled_sizes:
        st.markdown(f"• **{s['name']}** `{s['width']}x{s['height']}` ({s['aspect_ratio']})")

    st.caption("ℹ️ Square (1080x1080), LinkedIn (1200x628) and A4 Print are configured in `config.py` and switched OFF for V1.")

    st.divider()
    if st.button("📁 Load Aurelia Heights Sample Assets", use_container_width=True):
        st.session_state["use_sample"] = True
        st.rerun()


# ─────────────────────────────────────────────
# Header
# ─────────────────────────────────────────────

st.markdown("""
<div class="hero-card">
    <div style="display: flex; justify-content: space-between; align-items: center;">
        <h2 class="gold-title">🎨 Festive Real-Estate Poster Generator</h2>
        <span class="status-badge" style="background: rgba(201, 162, 39, 0.2); color: #D4AF37; border: 1px solid #D4AF37;">
            Nano Banana + Pillow Engine
        </span>
    </div>
    <p style="color: #cbd5e1; margin-top: 6px; font-size: 0.95rem; line-height: 1.5;">
        Converts architectural renders into festive print and social posters in <strong>Instagram Post (4:5)</strong> and <strong>Story (9:16)</strong> formats.
        Backgrounds are generated with Google Gemini <em>Nano Banana</em>. <strong>ALL typography, brand logo, and RERA disclosures are composited with Pillow—never by AI.</strong>
    </p>
</div>
""", unsafe_allow_html=True)


# ─────────────────────────────────────────────
# Step 1: Uploads & Project Specifications
# ─────────────────────────────────────────────

st.markdown("### 1. Upload Project Assets & Configuration")

col_u1, col_u2 = st.columns(2, gap="medium")

with col_u1:
    uploaded_project_file = st.file_uploader("Upload Project Details JSON", type=["json"])
    uploaded_logo_file = st.file_uploader("Upload Brand Logo (PNG, transparent)", type=["png"])

with col_u2:
    selected_festival = st.selectbox("Celebration / Festival Theme", options=FESTIVALS, index=0)
    uploaded_render_files = st.file_uploader(
        "Upload Architectural Render Images",
        type=["png", "jpg", "jpeg", "webp"],
        accept_multiple_files=True,
    )

# Manage state & sample files
sample_active = st.session_state.get("use_sample", False) or (
    not uploaded_project_file and Path("inputs/project.json").exists()
)

temp_workspace = Path(tempfile.gettempdir()) / "poster_gen_workspace"
temp_workspace.mkdir(parents=True, exist_ok=True)

project_data_obj: Optional[ProjectData] = None
active_logo_path: Optional[str] = None
active_renders: List[RenderInfo] = []

# Load sample fallback
if sample_active and not uploaded_project_file:
    try:
        p_path = Path("inputs/project.json")
        if p_path.exists():
            project_data_obj = parse_project_json(p_path)
            logo_cand = Path("inputs/logo_full.png") if Path("inputs/logo_full.png").exists() else Path("inputs/logo.png")
            if logo_cand.exists():
                active_logo_path = str(logo_cand)
            renders_dir = Path("inputs/renders")
            if renders_dir.exists():
                # Load from renders.json
                r_json = renders_dir / "renders.json"
                if r_json.exists():
                    import json
                    r_items = json.loads(r_json.read_text(encoding="utf-8"))
                    for it in r_items:
                        rf = renders_dir / it.get("file", "")
                        if rf.exists():
                            active_renders.append(RenderInfo(
                                filepath=str(rf),
                                render_type=it.get("type", "exterior"),
                                approved=it.get("approved", True),
                            ))
    except Exception as exc:
        st.error(f"Sample load warning: {exc}")

# Process custom project upload
if uploaded_project_file:
    p_dest = temp_workspace / uploaded_project_file.name
    p_dest.write_bytes(uploaded_project_file.read())
    try:
        project_data_obj = parse_project_json(p_dest)
    except Exception as exc:
        st.error(f"❌ Project Validation Error: {exc}")
        project_data_obj = None

# Process custom logo upload
if uploaded_logo_file:
    l_dest = temp_workspace / uploaded_logo_file.name
    l_dest.write_bytes(uploaded_logo_file.read())
    active_logo_path = str(l_dest)

# Process custom render uploads
if uploaded_render_files:
    active_renders = []
    st.markdown("#### 🖼️ Configure Uploaded Renders")
    st.caption("Categorize and approve renders (only approved renders can be selected for poster creation):")
    r_cols = st.columns(min(len(uploaded_render_files), 4))
    for idx, r_file in enumerate(uploaded_render_files):
        r_dest = temp_workspace / r_file.name
        r_dest.write_bytes(r_file.read())
        with r_cols[idx % 4]:
            try:
                st.image(Image.open(r_dest), caption=r_file.name[:20], use_container_width=True)
            except Exception:
                st.write(r_file.name)
            rtype = st.selectbox(
                f"Type {idx+1}",
                options=["exterior", "interior", "amenity"],
                index=0 if "exterior" in r_file.name.lower() or idx == 0 else 1,
                key=f"p_rtype_{idx}",
            )
            is_appr = st.checkbox("Approved for ads", value=True, key=f"p_appr_{idx}")
            active_renders.append(RenderInfo(
                filepath=str(r_dest),
                render_type=rtype,
                approved=is_appr,
            ))


# ─────────────────────────────────────────────
# Step 2: Render Selection & Project Summary
# ─────────────────────────────────────────────

if project_data_obj:
    st.divider()
    status_label = "VERIFIED PROJECT" if project_data_obj.is_verified else "UNVERIFIED PROJECT"
    status_class = "badge-verified" if project_data_obj.is_verified else "badge-draft"

    st.markdown(f"""
    <div style="background: rgba(18, 24, 38, 0.65); border: 1px solid rgba(255, 255, 255, 0.08); border-radius: 12px; padding: 1.2rem; margin-bottom: 1rem;">
        <div style="display: flex; justify-content: space-between; align-items: center; margin-bottom: 0.4rem;">
            <h3 style="margin: 0;" class="gold-title">{project_data_obj.name}</h3>
            <span class="status-badge {status_class}">{status_label}</span>
        </div>
        <div style="color: #cbd5e1; font-size: 0.95rem; line-height: 1.6;">
            <strong>Promoter:</strong> {project_data_obj.promoter} &nbsp;|&nbsp;
            <strong>Location:</strong> {project_data_obj.marketing_name}, {project_data_obj.city} &nbsp;|&nbsp;
            <strong>RERA No:</strong> <code style="color: #10B981;">{project_data_obj.rera_number}</code>
            <br>
            <strong>Configurations:</strong> {project_data_obj.formatted_units_summary} from <strong>{project_data_obj.formatted_lowest_price}</strong>
        </div>
    </div>
    """, unsafe_allow_html=True)

    # Filter approved renders
    approved_renders = filter_approved_renders(active_renders, project_data_obj.raw_data.get("review"))
    if not approved_renders:
        st.warning("⚠️ No approved renders found. Please upload or approve at least one render.")
        st.stop()

    def _r_name(r):
        return getattr(r, "filename", Path(r.filepath).name)

    # Dropdown of approved renders (default = first exterior)
    render_options = [_r_name(r) for r in approved_renders]
    default_idx = 0
    for idx, r in enumerate(approved_renders):
        if r.render_type == "exterior":
            default_idx = idx
            break

    col_r1, col_r2 = st.columns([2, 1])
    with col_r1:
        chosen_render_name = st.selectbox(
            "Render to use (dropdown of approved renders; default = first exterior):",
            options=render_options,
            index=default_idx,
        )
    chosen_render = next(r for r in approved_renders if _r_name(r) == chosen_render_name)

    with col_r2:
        st.caption(f"Category: **{chosen_render.render_type.upper()}**")
        st.image(Image.open(chosen_render.filepath), width=180)


# ─────────────────────────────────────────────
# Step 3: Headlines & Cost Preview
# ─────────────────────────────────────────────

if project_data_obj:
    st.divider()
    st.markdown("### 2. Headline & Cost Estimation")

    # Headline Generation
    cache_head_key = f"{project_data_obj.name}_{selected_festival}_headlines"
    if cache_head_key not in st.session_state:
        st.session_state[cache_head_key] = generate_headlines(project_data_obj, selected_festival)

    ai_headlines = st.session_state[cache_head_key]
    headline_choices = ai_headlines + ["Write my own"]

    h_pick = st.radio(
        "Headline Ideas (Gemini text model - max 8 words, strictly fact-based):",
        options=headline_choices,
        index=0,
    )

    if h_pick == "Write my own":
        custom_headline = st.text_input("Enter your custom headline:", value=ai_headlines[0])
        final_headline = custom_headline.strip()
    else:
        final_headline = h_pick

    words_in_h = len(final_headline.split()) if final_headline else 0
    if words_in_h > 8:
        st.warning(f"⚠️ Headline has {words_in_h} words (max recommended: 8 words).")
    else:
        st.caption(f"✓ {words_in_h} words.")

    # Action Buttons: Preview Cost & Generate Backgrounds
    st.markdown("<div style='height: 10px;'></div>", unsafe_allow_html=True)
    b_col1, b_col2 = st.columns([1, 1], gap="medium")
    preview_cost_clicked = b_col1.button("💰 Preview Cost (No API Calls)", use_container_width=True)
    gen_bg_clicked = b_col2.button("✨ Generate Backgrounds (Nano Banana)", use_container_width=True, type="primary")

    if preview_cost_clicked:
        st.session_state["cost_previewed"] = True
        st.markdown(f"""
        <div style="background: rgba(31, 42, 68, 0.4); border: 1px solid #10B981; border-radius: 10px; padding: 14px; margin-top: 10px;">
            <h4 style="margin: 0; color: #10B981;">💵 Cost Estimation Breakdown</h4>
            <div style="color: #cbd5e1; font-size: 0.95rem; margin-top: 6px;">
                • <strong>Nano Banana Image Variations:</strong> 2 images (Instagram 4:5 + Story 9:16) @ ${IMAGE_PRICE_USD:.2f} = <strong>${IMAGE_PRICE_USD * 2:.2f} USD</strong><br>
                • <strong>Gemini Text Headlines:</strong> 3 ideas @ $0.0001 = <strong>~$0.0001 USD</strong><br>
                • <strong>Total Billed Cost:</strong> <strong>${IMAGE_PRICE_USD * 2:.2f} USD (~₹5.00 INR)</strong><br>
                <em>Waiting for your confirmation: Click 'Generate Backgrounds' to proceed.</em>
            </div>
        </div>
        """, unsafe_allow_html=True)


# ─────────────────────────────────────────────
# Step 4: Background Generation & Approval
# ─────────────────────────────────────────────

cache_dir = Path("cache")
cache_dir.mkdir(parents=True, exist_ok=True)

if gen_bg_clicked and project_data_obj:
    with st.spinner("🎨 Nano Banana is editing your render into festive backgrounds..."):
        st.session_state["generated_bgs"] = {}
        for sid in ("instagram_post", "story"):
            sc = SIZES[sid]
            out_bg = cache_dir / f"bg_{sid}_{selected_festival.lower()}.png"
            bg_path = generate_festive_background(
                render_path=chosen_render.filepath,
                festival=selected_festival,
                width=sc["width"],
                height=sc["height"],
                aspect_ratio=sc["aspect_ratio"],
                output_path=out_bg,
                cache_dir=cache_dir,
                dry_run=enable_simulation,
                force_refresh=True,
            )
            st.session_state["generated_bgs"][sid] = str(bg_path)
        st.session_state["backgrounds_ready"] = True
        st.session_state["approved_bgs"] = False

# Display Backgrounds for Approval (Step 2)
if st.session_state.get("backgrounds_ready", False) and "generated_bgs" in st.session_state:
    st.divider()
    st.markdown("### 3. Step 2 – User Approves Backgrounds")

    st.markdown("""
    <div class="warning-box">
        ⚠️ <strong>CRITICAL ARCHITECTURAL CHECK:</strong> Please check that the building is completely unchanged
        (number of towers, shape, facade, colors, and windows) before approving.
    </div>
    """, unsafe_allow_html=True)

    bgs = st.session_state["generated_bgs"]
    col_orig, col_ig, col_st = st.columns([1, 1, 1], gap="medium")

    with col_orig:
        st.markdown("**Original Render (Reference):**")
        st.image(Image.open(chosen_render.filepath), caption=_r_name(chosen_render), use_container_width=True)

    with col_ig:
        st.markdown("**Instagram Post Background (4:5):**")
        st.image(Image.open(bgs["instagram_post"]), caption="1080x1350", use_container_width=True)
        if st.button("🔄 Regenerate Instagram Background", key="regen_ig"):
            with st.spinner("Regenerating Instagram background..."):
                sc = SIZES["instagram_post"]
                out_bg = cache_dir / f"bg_instagram_post_{selected_festival.lower()}_regen.png"
                new_bg = generate_festive_background(
                    render_path=chosen_render.filepath,
                    festival=selected_festival,
                    width=sc["width"],
                    height=sc["height"],
                    aspect_ratio=sc["aspect_ratio"],
                    output_path=out_bg,
                    cache_dir=cache_dir,
                    dry_run=enable_simulation,
                    force_refresh=True,
                )
                st.session_state["generated_bgs"]["instagram_post"] = str(new_bg)
                st.rerun()

    with col_st:
        st.markdown("**Story / WhatsApp Background (9:16):**")
        st.image(Image.open(bgs["story"]), caption="1080x1920", use_container_width=True)
        if st.button("🔄 Regenerate Story Background", key="regen_st"):
            with st.spinner("Regenerating Story background..."):
                sc = SIZES["story"]
                out_bg = cache_dir / f"bg_story_{selected_festival.lower()}_regen.png"
                new_bg = generate_festive_background(
                    render_path=chosen_render.filepath,
                    festival=selected_festival,
                    width=sc["width"],
                    height=sc["height"],
                    aspect_ratio=sc["aspect_ratio"],
                    output_path=out_bg,
                    cache_dir=cache_dir,
                    dry_run=enable_simulation,
                    force_refresh=True,
                )
                st.session_state["generated_bgs"]["story"] = str(new_bg)
                st.rerun()

    st.markdown("<div style='height: 10px;'></div>", unsafe_allow_html=True)
    if st.button("✅ Approve Backgrounds & Proceed to Poster Creation", type="primary", use_container_width=True):
        st.session_state["approved_bgs"] = True
        st.success("✓ Backgrounds approved! Ready to render final posters with Pillow.")


# ─────────────────────────────────────────────
# Step 5: Render Posters & Download
# ─────────────────────────────────────────────

if st.session_state.get("approved_bgs", False) and project_data_obj:
    st.divider()
    st.markdown("### 4. Step 3 – Final Posters (Pillow Typography & RERA)")

    out_posters_dir = Path("output/posters")
    out_posters_dir.mkdir(parents=True, exist_ok=True)

    clean_pname = project_data_obj.name.replace(" ", "_").lower()
    clean_fest = selected_festival.replace("/", "_").lower()

    poster_paths = {}
    poster_checks = {}

    with st.spinner("Rendering typography, brand logo, and RERA disclosures with Pillow..."):
        for sid in ("instagram_post", "story"):
            sc = SIZES[sid]
            bg_f = st.session_state["generated_bgs"][sid]
            out_filename = f"{clean_pname}_{clean_fest}_{'instagram' if sid == 'instagram_post' else 'story'}.png"
            dest_file = out_posters_dir / out_filename

            rendered_poster = render_poster_with_template(
                template=selected_template,
                background_path=bg_f,
                project=project_data_obj,
                logo_path=active_logo_path,
                headline=final_headline,
                festival=selected_festival,
                size_id=sid,
                output_path=dest_file,
            )

            p_checks = verify_poster(rendered_poster, project_data_obj, sc["width"], sc["height"])
            poster_paths[sid] = dest_file
            poster_checks[sid] = p_checks

    st.success("🎉 Posters Created Successfully!")

    # Display Final Posters Side by Side
    p_col1, p_col2 = st.columns(2, gap="large")

    with p_col1:
        st.markdown("#### 📱 Instagram Post (4:5 • 1080x1350)")
        ig_path = poster_paths["instagram_post"]
        st.image(Image.open(ig_path), use_container_width=True)
        with open(ig_path, "rb") as f:
            st.download_button(
                label="⬇️ Download Instagram Post (PNG)",
                data=f.read(),
                file_name=ig_path.name,
                mime="image/png",
                use_container_width=True,
                type="primary",
            )
        st.caption(f"WCAG Contrast: **{poster_checks['instagram_post']['contrast_ratios']['rera_strip']}:1** | RERA: **Verified**")

    with p_col2:
        st.markdown("#### 📲 Story / WhatsApp (9:16 • 1080x1920)")
        st_path = poster_paths["story"]
        st.image(Image.open(st_path), use_container_width=True)
        with open(st_path, "rb") as f:
            st.download_button(
                label="⬇️ Download Story / WhatsApp (PNG)",
                data=f.read(),
                file_name=st_path.name,
                mime="image/png",
                use_container_width=True,
                type="primary",
            )
        st.caption(f"WCAG Contrast: **{poster_checks['story']['contrast_ratios']['rera_strip']}:1** | RERA: **Verified**")

    # ZIP Download Option
    st.markdown("<div style='height: 12px;'></div>", unsafe_allow_html=True)
    zip_buffer = io.BytesIO()
    with zipfile.ZipFile(zip_buffer, "w", zipfile.ZIP_DEFLATED) as zip_file:
        for sid, p_file in poster_paths.items():
            zip_file.write(p_file, arcname=p_file.name)

    st.download_button(
        label="📦 Download Both Posters (ZIP Archive)",
        data=zip_buffer.getvalue(),
        file_name=f"{clean_pname}_{clean_fest}_posters.zip",
        mime="application/zip",
        use_container_width=True,
    )

    # ─────────────────────────────────────────────
    # Step 6: AI Poster Review Agent
    # ─────────────────────────────────────────────
    try:
        import sys as _sys
        from pathlib import Path as _Path
        _repo_root = _Path(__file__).resolve().parent.parent
        if str(_repo_root) not in _sys.path:
            _sys.path.insert(0, str(_repo_root))
        from agents.poster_review_ui import render_review_section
        render_review_section(
            poster_paths=poster_paths,
            project=project_data_obj,
            festival=selected_festival,
            dry_run=enable_simulation,
        )
    except ImportError as _e:
        st.warning(f"Poster Review Agent not available: {_e}")
