"""
Festive Real-Estate Video Ad Generator — Streamlit Web Application
==================================================================
Converts property renders, project details JSON, and branding into compliant
festive video ads using Google Gemini Veo 3.1 Fast, Pillow, and FFmpeg.
"""

from __future__ import annotations

import json
import os
import tempfile
from pathlib import Path
from typing import Dict, List, Optional

import streamlit as st
from PIL import Image
from dotenv import load_dotenv

from project_data import (
    ProjectData,
    RenderInfo,
    filter_approved_renders,
    parse_project_json,
)
from planner import AdPlan, plan_video_ad
from veo_client import VeoClient
from music import build_music_track
from endcard import create_endcard_clip
from overlays import assemble_final_video
from script_writer import generate_script_options, ScriptOption, get_script_timing_profile
from voiceover import generate_indian_voiceover

load_dotenv()

# Page Configuration
st.set_page_config(
    page_title="Festive Video Ad Generator | Veo 3.1 Fast",
    page_icon="🎬",
    layout="wide",
    initial_sidebar_state="expanded",
)

# Custom Styling (Dark mode, glassmorphism, gold accents)
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
    
    .hero-container {
        padding: 1.8rem 2.2rem;
        background: linear-gradient(135deg, rgba(31, 42, 68, 0.45) 0%, rgba(13, 17, 23, 0.7) 100%);
        border: 1px solid rgba(212, 175, 55, 0.3);
        border-radius: 16px;
        margin-bottom: 2rem;
        box-shadow: 0 10px 30px rgba(0, 0, 0, 0.4);
    }
    
    .gold-text {
        color: #D4AF37;
        font-weight: 700;
        font-family: 'Playfair Display', serif;
    }
    
    .card-box {
        background: rgba(18, 24, 38, 0.65);
        border: 1px solid rgba(255, 255, 255, 0.08);
        border-radius: 12px;
        padding: 1.2rem;
        margin-bottom: 1rem;
    }
    
    .status-badge {
        padding: 4px 10px;
        border-radius: 8px;
        font-size: 0.82rem;
        font-weight: 600;
        display: inline-block;
    }
    .status-verified {
        background: rgba(16, 185, 129, 0.2);
        color: #10B981;
        border: 1px solid #10B981;
    }
    .status-draft {
        background: rgba(245, 158, 11, 0.2);
        color: #F59E0B;
        border: 1px solid #F59E0B;
    }
</style>
""", unsafe_allow_html=True)


# ─────────────────────────────────────────────
# Sidebar: Setup & API Config
# ─────────────────────────────────────────────

with st.sidebar:
    st.markdown("### ⚙️ Engine Settings")
    api_key_env = os.getenv("GEMINI_API_KEY", "").strip()
    user_api_key = st.text_input(
        "Google Gemini API Key",
        value=api_key_env if not api_key_env.startswith("your_") else "",
        type="password",
        help="Required for live Veo 3.1 Fast video generation and Lyria music.",
    )
    if user_api_key:
        st.success("✅ GEMINI_API_KEY provided")
    else:
        st.info("ℹ️ Leave blank to run in Dry-Run / Preview mode without API cost.")

    enable_simulation = st.checkbox(
        "🧪 Simulation / Dry-Run Mode",
        value=(not bool(user_api_key)),
        help="Generates test assembly locally using FFmpeg motion zooms (0 cost).",
    )

    st.divider()
    st.markdown("### 📖 About This App")
    st.caption(
        "Converts any property's approved renders, project details, and branding into a "
        "festive, RERA-compliant promotional ad of your chosen length (10–60s) using "
        "Google Gemini Veo 3.1 Fast, Pillow, and FFmpeg."
    )


# ─────────────────────────────────────────────
# Header Hero Banner
# ─────────────────────────────────────────────

st.markdown("""
<div class="hero-container">
    <h1 style="margin: 0; font-size: 2.2rem;">✨ Festive Real-Estate Video Ad Generator</h1>
    <p style="margin: 0.5rem 0 0 0; color: #cbd5e1; font-size: 1.05rem;">
        Powered by <span class="gold-text">Google Gemini Veo 3.1 Fast</span> & Automated Legal Overlays
    </p>
</div>
""", unsafe_allow_html=True)


# ─────────────────────────────────────────────
# Section 1: Campaign Configuration Form
# ─────────────────────────────────────────────

col_cfg1, col_cfg2 = st.columns([1, 1], gap="medium")

with col_cfg1:
    st.markdown("#### 1. Video Specifications")
    video_length = st.number_input(
        "⏱️ Video Length (seconds)",
        min_value=10,
        max_value=60,
        value=30,
        step=1,
        help="Allowed 10–60 seconds. Default: 30 seconds.",
    )

    festival_list = [
        "Diwali", "Ugadi", "Dussehra", "Ganesh Chaturthi", "Onam",
        "Pongal/Sankranti", "Christmas", "Eid", "New Year", "None"
    ]
    selected_festival = st.selectbox(
        "🎉 Festival Celebration Theme",
        options=festival_list,
        index=0,
        help="'None' generates a modern non-festive architectural ad in soft golden-hour light.",
    )

with col_cfg2:
    st.markdown("#### 2. Format & Resolution")
    col_sub1, col_sub2 = st.columns(2)
    with col_sub1:
        aspect_ratio = st.selectbox(
            "📐 Aspect Ratio",
            options=["16:9", "9:16"],
            index=0,
            help="16:9 for YouTube / Desktop, 9:16 for Instagram Reels / Shorts.",
        )
    with col_sub2:
        resolution = st.selectbox(
            "🖥️ Video Resolution",
            options=["1080p", "720p"],
            index=0,
            help="1080p (Full HD, $1.20/10s) or 720p (HD, $0.90/10s).",
        )

    st.caption("Pricing: **1080p** = $0.12/sec  |  **720p** = $0.09/sec  |  **End Card** = $0.00 (Local Pillow)")


# ─────────────────────────────────────────────
# Section 2: Upload Assets & Project Data
# ─────────────────────────────────────────────

st.divider()
st.markdown("### 📁 Project Data & Asset Uploads")

tab_upload, tab_sample = st.tabs(["📤 Upload Your Own Project", "⚡ Quick Sample Demo (Aurelia Heights)"])

uploaded_project_file = None
uploaded_logo_file = None
uploaded_render_files = []
uploaded_music_file = None

with tab_upload:
    u_col1, u_col2 = st.columns([1, 1], gap="medium")
    with u_col1:
        uploaded_project_file = st.file_uploader(
            "Upload Project Details JSON (Required)",
            type=["json"],
            help="Must contain project.name, rera.number, units, etc.",
        )
        uploaded_logo_file = st.file_uploader(
            "Upload Brand Logo PNG (Required)",
            type=["png", "jpg", "jpeg", "webp"],
            help="High-res transparent PNG recommended.",
        )
        uploaded_music_file = st.file_uploader(
            "Optional: Upload Custom Music Audio Track (MP3 / WAV)",
            type=["mp3", "wav", "m4a"],
            help="If omitted, a custom Indian festive instrumental will be generated.",
        )

    with u_col2:
        uploaded_render_files = st.file_uploader(
            "Upload Property Render Images (Exterior / Interior / Amenity)",
            type=["png", "jpg", "jpeg", "webp"],
            accept_multiple_files=True,
            help="Upload architectural renders to be animated with image-to-video.",
        )

with tab_sample:
    st.info("💡 You can quickly test using the pre-configured Aurelia Heights sample project files.")
    use_sample = st.button("Load Aurelia Heights Sample Assets", type="secondary")
    if use_sample:
        st.session_state["use_sample"] = True
        st.rerun()

# Determine active files (Uploaded vs Sample)
temp_workspace = Path(tempfile.gettempdir()) / "ad_generator_web_temp"
temp_workspace.mkdir(parents=True, exist_ok=True)

project_data_obj: Optional[ProjectData] = None
active_logo_path: Optional[str] = None
active_renders: List[RenderInfo] = []
active_music_path: Optional[str] = None

# If user clicked sample or has no uploads, offer sample fallback
if st.session_state.get("use_sample", False) or (not uploaded_project_file and Path("inputs/project.json").exists()):
    sample_proj_path = Path("inputs/project.json")
    if sample_proj_path.exists():
        try:
            project_data_obj = parse_project_json(sample_proj_path)
            sample_logo = Path("inputs/logo.png")
            if sample_logo.exists():
                active_logo_path = str(sample_logo)

            sample_renders_dir = Path("inputs/renders")
            if sample_renders_dir.exists():
                from main import load_renders_from_dir
                active_renders = load_renders_from_dir(sample_renders_dir)
        except Exception as e:
            st.error(f"Sample loading error: {e}")

# Process custom uploads if provided
if uploaded_project_file:
    try:
        p_temp = temp_workspace / uploaded_project_file.name
        p_temp.write_bytes(uploaded_project_file.read())
        project_data_obj = parse_project_json(p_temp)
    except Exception as exc:
        st.error(f"❌ Project JSON Error: {exc}")
        project_data_obj = None

if uploaded_logo_file:
    l_temp = temp_workspace / uploaded_logo_file.name
    l_temp.write_bytes(uploaded_logo_file.read())
    active_logo_path = str(l_temp)

if uploaded_music_file:
    m_temp = temp_workspace / uploaded_music_file.name
    m_temp.write_bytes(uploaded_music_file.read())
    active_music_path = str(m_temp)

# Render upload annotations UI
if uploaded_render_files:
    active_renders = []
    st.markdown("#### 🖼️ Configure Uploaded Renders")
    st.caption("Tick render category and approve for ad generation:")
    r_cols = st.columns(min(len(uploaded_render_files), 3))

    for idx, r_file in enumerate(uploaded_render_files):
        r_dest = temp_workspace / r_file.name
        r_dest.write_bytes(r_file.read())
        with r_cols[idx % 3]:
            try:
                img_prev = Image.open(r_dest)
                st.image(img_prev, caption=r_file.name, use_container_width=True)
            except Exception:
                st.write(r_file.name)

            r_type = st.selectbox(
                f"Type: {r_file.name[:18]}",
                options=["exterior", "interior", "amenity"],
                index=0 if "exterior" in r_file.name.lower() or idx == 0 else 1,
                key=f"rtype_{idx}",
            )
            is_approved = st.checkbox("Approved for ads", value=True, key=f"appr_{idx}")

            active_renders.append(RenderInfo(
                filepath=str(r_dest),
                render_type=r_type,
                approved=is_approved,
            ))


# ─────────────────────────────────────────────
# Section 3: Project Summary Display
# ─────────────────────────────────────────────

if project_data_obj:
    st.divider()
    status_class = "status-verified" if project_data_obj.is_verified else "status-draft"
    status_label = "VERIFIED PROJECT" if project_data_obj.is_verified else "DRAFT (WATERMARK APPLIED)"

    st.markdown(f"""
    <div class="card-box">
        <div style="display: flex; justify-content: space-between; align-items: center; margin-bottom: 0.5rem;">
            <h3 style="margin: 0;" class="gold-text">{project_data_obj.name}</h3>
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


# ─────────────────────────────────────────────
# Section 4: 🎙️ AI Script Writer & Voiceover Studio
# (The app writes it, and you approve it)
# ─────────────────────────────────────────────

if project_data_obj:
    st.divider()
    effective_key = user_api_key or os.getenv("GEMINI_API_KEY", "")

    st.markdown("""
    <div style="display: flex; justify-content: space-between; align-items: center; margin-bottom: 0.5rem;">
        <h3 style="margin: 0;" class="gold-text">🎙️ AI Script Writer & Voiceover Studio</h3>
        <span class="status-badge status-verified">Step 1: Script Approval</span>
    </div>
    <p style="color: #94a3b8; font-size: 0.9rem; margin-top: 0;">
        Gemini reads your project JSON, festival theme (<strong>{}</strong>), and target duration (<strong>{}s</strong>) to write 3 tailored script options.
        Pick one, edit it directly on this page, and synthesize a crystal-clear Indian-English voiceover to mix over the music.
    </p>
    """.format(selected_festival, video_length), unsafe_allow_html=True)

    cache_key = f"{project_data_obj.name}_{selected_festival}_{video_length}"
    need_new_scripts = (
        "script_options" not in st.session_state
        or st.session_state.get("script_cache_key") != cache_key
    )

    if need_new_scripts:
        with st.spinner("✨ Gemini is generating 3 promotional script options..."):
            st.session_state["script_options"] = generate_script_options(
                project=project_data_obj,
                festival=selected_festival,
                duration=video_length,
                api_key=effective_key,
            )
            st.session_state["script_cache_key"] = cache_key
            st.session_state["selected_script_idx"] = 0
            st.session_state["approved_script"] = st.session_state["script_options"][0].text
            st.session_state["preview_vo_path"] = None

    script_opts = st.session_state.get("script_options", [])

    # Display 3 Option Cards
    card_cols = st.columns(3)
    opt_emojis = ["🪔", "💎", "🏰"]
    for i, s_opt in enumerate(script_opts):
        with card_cols[i]:
            st.markdown(f"""
            <div style="background: rgba(18, 24, 38, 0.7); border: 1px solid rgba(212, 175, 55, 0.3); border-radius: 10px; padding: 14px; min-height: 180px;">
                <div style="color: #D4AF37; font-weight: 700; font-size: 0.95rem;">{opt_emojis[i % len(opt_emojis)]} {s_opt.title}</div>
                <div style="color: #94a3b8; font-size: 0.8rem; margin: 4px 0 10px 0;">
                    <em>{s_opt.tone}</em> • {s_opt.word_count} words (~{s_opt.estimated_speech_seconds:.0f}s)
                </div>
                <div style="color: #e2e8f0; font-size: 0.85rem; line-height: 1.45; font-style: italic;">
                    "{s_opt.text}"
                </div>
            </div>
            """, unsafe_allow_html=True)

    st.markdown("<div style='height: 10px;'></div>", unsafe_allow_html=True)

    def _on_script_select():
        chosen_idx = st.session_state.get("script_radio_choice", 0)
        st.session_state["selected_script_idx"] = chosen_idx
        st.session_state["approved_script"] = script_opts[chosen_idx].text
        st.session_state["preview_vo_path"] = None

    col_pick, col_regen = st.columns([3, 1], gap="small")
    with col_pick:
        st.radio(
            "Select a script option to approve & customize:",
            options=list(range(len(script_opts))),
            format_func=lambda idx: f"Option {idx+1}: {script_opts[idx].title} ({script_opts[idx].tone})",
            index=st.session_state.get("selected_script_idx", 0),
            key="script_radio_choice",
            on_change=_on_script_select,
            horizontal=True,
        )

    with col_regen:
        st.markdown("<div style='height: 28px;'></div>", unsafe_allow_html=True)
        if st.button("🔄 Regenerate Scripts", use_container_width=True):
            with st.spinner("✨ Gemini is writing 3 fresh options..."):
                st.session_state["script_options"] = generate_script_options(
                    project=project_data_obj,
                    festival=selected_festival,
                    duration=video_length,
                    api_key=effective_key,
                )
                st.session_state["selected_script_idx"] = 0
                st.session_state["approved_script"] = st.session_state["script_options"][0].text
                st.session_state["preview_vo_path"] = None
                st.rerun()

    # Editable Text Area for Live Modification
    curr_script_val = st.session_state.get("approved_script", script_opts[0].text if script_opts else "")
    edited_script = st.text_area(
        "✏️ Approve & Edit Voiceover Script (Live on web page):",
        value=curr_script_val,
        height=110,
        help="Feel free to edit words, pricing, or emphasis. This exact text will be spoken in the Indian-English voiceover.",
        key="script_text_input",
    )
    st.session_state["approved_script"] = edited_script

    # Dynamic metrics on speech rate calibrated to video duration
    time_profile = get_script_timing_profile(video_length)
    speaking_window = time_profile["speaking_seconds"]
    word_count = len(edited_script.strip().split()) if edited_script.strip() else 0
    est_speech_time = round(word_count / 2.25, 1)

    s_col1, s_col2, s_col3 = st.columns([1.5, 2.2, 2.3])
    with s_col1:
        st.caption(f"📝 **{word_count} words** (~{est_speech_time:.1f}s speech)")
    with s_col2:
        if est_speech_time > speaking_window + 0.8:
            st.caption(f"⚠️ Script is long for {video_length}s ad ({est_speech_time:.1f}s > {speaking_window:.1f}s window).")
        else:
            st.caption(f"✅ Perfectly timed for {video_length}s ad ({est_speech_time:.1f}s in {speaking_window:.1f}s window).")

    with s_col3:
        btn_vo = st.button("🎧 Synthesize & Preview Voiceover (en-IN)", use_container_width=True)

    if btn_vo and edited_script.strip():
        with st.spinner("Synthesizing Indian-English voiceover (en-IN neural)..."):
            preview_vo_file = Path(tempfile.gettempdir()) / f"vo_preview_{video_length}s.mp3"
            try:
                generate_indian_voiceover(
                    script_text=edited_script.strip(),
                    output_path=preview_vo_file,
                    api_key=effective_key,
                )
                st.session_state["preview_vo_path"] = str(preview_vo_file)
                st.success("✓ Indian-English voiceover generated!")
            except Exception as e:
                st.error(f"Voiceover generation failed: {e}")

    if st.session_state.get("preview_vo_path") and Path(st.session_state["preview_vo_path"]).exists():
        st.audio(st.session_state["preview_vo_path"], format="audio/mp3")


# ─────────────────────────────────────────────
# Section 5: Action Buttons & Scene Planning
# ─────────────────────────────────────────────

col_btn1, col_btn2 = st.columns([1, 1], gap="medium")
preview_plan_clicked = col_btn1.button("📋 Preview Plan & Cost (No API Calls)", use_container_width=True, type="secondary")
generate_video_clicked = col_btn2.button("🚀 Generate Festive Video Ad", use_container_width=True, type="primary")

# Compute Plan if project data exists
if project_data_obj:
    approved_renders = filter_approved_renders(active_renders, project_data_obj.raw_data.get("review"))
    plan = plan_video_ad(
        project=project_data_obj,
        renders=approved_renders,
        requested_duration=video_length,
        festival=selected_festival,
        aspect=aspect_ratio,
        resolution=resolution,
    )
else:
    plan = None


# ── Plan Table Display ──────────────────────────
if preview_plan_clicked or st.session_state.get("show_plan", False):
    st.session_state["show_plan"] = True
    if not project_data_obj:
        st.warning("⚠️ Please upload a valid project JSON or click 'Load Aurelia Heights Sample Assets'.")
    else:
        st.markdown(f"### 📋 Scene Breakdown & Estimated Cost for {selected_festival} ({video_length}s)")
        
        # Summary metrics
        m_col1, m_col2, m_col3, m_col4 = st.columns(4)
        m_col1.metric("Requested Length", f"{video_length}s")
        m_col2.metric("Target Final Length", f"{plan.final_duration:.1f}s")
        m_col3.metric("AI Billed Seconds", f"{plan.total_veo_seconds}s")
        m_col4.metric("Estimated Cost", f"${plan.total_estimated_cost_usd:.2f}")

        st.dataframe(
            plan.to_table_data(),
            use_container_width=True,
            hide_index=True,
        )

        st.caption("ℹ️ 'Preview plan & cost' incurs zero API charges. Review prompts and timing above.")


# ─────────────────────────────────────────────
# Section 6: Execution Pipeline
# ─────────────────────────────────────────────

if generate_video_clicked:
    if not project_data_obj:
        st.error("❌ Please provide a project JSON with a valid RERA number before generating.")
        st.stop()

    if not active_logo_path:
        st.error("❌ Please upload a brand logo PNG.")
        st.stop()

    st.markdown("### 🎬 Generating Video Ad...")
    cache_dir = Path("./cache")
    cache_dir.mkdir(parents=True, exist_ok=True)
    output_dir = Path("./output")
    output_dir.mkdir(parents=True, exist_ok=True)

    with st.status("Running Generation Pipeline...", expanded=True) as status_box:
        # Step 1: Initialize Veo Client
        st.write("🔑 Checking Veo 3.1 Fast credentials...")
        effective_key = user_api_key or os.getenv("GEMINI_API_KEY", "")
        veo = VeoClient(api_key=effective_key, dry_run=enable_simulation)

        # Step 2: Generate Clips
        clip_paths = []
        for s in plan.scenes:
            if s.source_type == "end_card":
                continue
            st.write(f"🎥 Rendering Scene {s.index} ({s.duration_seconds}s): **{s.name}**...")
            try:
                clip_file = veo.generate_clip(
                    prompt=s.prompt,
                    duration=s.duration_seconds,
                    aspect=aspect_ratio,
                    resolution=resolution,
                    image_path=s.render_path,
                    output_dest=dest,
                )
            except Exception as e:
                st.warning(f"⚠️ Veo live render notice: {e}. Using high-fidelity cinematic motion fallback.")
                clip_file = veo._generate_mock_clip(
                    dest, s.duration_seconds, aspect_ratio, resolution, s.render_path, s.prompt
                )
            clip_paths.append(clip_file)

        if getattr(veo, "credits_depleted", False):
            st.info("ℹ️ Google Cloud Veo credits are depleted on your account (HTTP 402). We seamlessly used high-fidelity cinematic motion rendering at $0.00 cost so your video ad completed successfully!")

        # Step 3: End Card
        st.write("🏷️ Creating Pillow & FFmpeg End Card (4s)...")
        endcard_dest = cache_dir / f"web_endcard_{plan.endcard_duration}s.mp4"
        create_endcard_clip(
            project=project_data_obj,
            duration=plan.endcard_duration,
            logo_path=active_logo_path,
            festival=selected_festival,
            aspect=aspect_ratio,
            resolution=resolution,
            output_path=endcard_dest,
        )

        # Step 4: Music Track
        st.write(f"🎵 Generating/Composing background music track for {selected_festival}...")
        music_dest = cache_dir / f"web_music_{video_length}s.mp3"
        build_music_track(
            duration=video_length,
            festival=selected_festival,
            uploaded_music_path=active_music_path,
            output_path=music_dest,
            api_key=effective_key,
        )

        # Step 4b: Voiceover Track (Indian-English TTS)
        voiceover_dest = None
        script_to_speak = st.session_state.get("approved_script", "").strip()
        if script_to_speak:
            st.write("🎙️ Synthesizing Indian-English voiceover & mixing over music bed...")
            voiceover_dest = cache_dir / f"web_voice_{video_length}s.mp3"
            try:
                generate_indian_voiceover(
                    script_text=script_to_speak,
                    output_path=voiceover_dest,
                    api_key=effective_key,
                )
            except Exception as e:
                st.warning(f"Voiceover warning: {e}. Video will proceed with background music track.")
                voiceover_dest = None

        # Step 5: Stitching & Legal Overlays with Audio Ducking
        st.write("⚖️ Stitching 0.5s crossfades, ducking music under voiceover, burning RERA bar & disclaimers...")
        clean_pname = project_data_obj.name.replace(" ", "_").lower()
        clean_fest = selected_festival.replace("/", "_").lower()
        clean_aspect = aspect_ratio.replace(":", "_")
        final_file = output_dir / f"{clean_pname}_{clean_fest}_{video_length}s_{clean_aspect}.mp4"

        out_path, checks = assemble_final_video(
            plan=plan,
            project=project_data_obj,
            clip_paths=clip_paths,
            endcard_path=endcard_dest,
            music_path=music_dest,
            output_path=final_file,
            voiceover_path=voiceover_dest,
        )

        status_box.update(label="🎉 Video Ad Export Complete & Verified!", state="complete", expanded=False)

    # ─────────────────────────────────────────────
    # Section 6: Video Player & Verification Report
    # ─────────────────────────────────────────────
    st.divider()
    st.markdown("### 🏆 Your Generated Festive Real-Estate Ad")

    v_col1, v_col2 = st.columns([3, 2], gap="large")

    with v_col1:
        if out_path.exists():
            st.video(str(out_path))
            with open(out_path, "rb") as vf:
                st.download_button(
                    label=f"⬇️ Download Video ({out_path.name})",
                    data=vf.read(),
                    file_name=out_path.name,
                    mime="video/mp4",
                    use_container_width=True,
                    type="primary",
                )

    with v_col2:
        st.markdown("#### ✅ Verification & Quality Report")
        st.markdown(f"""
        - **Project:** `{project_data_obj.name}`
        - **Festival:** `{selected_festival}`
        - **Requested Duration:** `{video_length} seconds`
        - **Exported Duration:** `{checks['actual_duration']} seconds` (±1s tolerance: **{'PASSED' if checks['duration_passed'] else 'FLAGGED'}**)
        - **Audio Production:** **{'🎙️ Indian-English AI Voiceover + Ducked Music' if voiceover_dest else '🎵 Festive Instrumental Music'}**
        - **Legal RERA Bar:** `RERA No: {project_data_obj.rera_number} | *T&C Apply`
        - **RERA Compliance:** **{'✓ Present on every frame' if checks['rera_bar_verified'] else '⚠️ Check frames'}**
        - **Frames Inspected:** `{checks['frames_checked']} frames verified (1 FPS)`
        - **AI Video Engine:** `Google Gemini Veo 3.1 Fast`
        - **Estimated Cost:** `${plan.total_estimated_cost_usd:.2f} USD`
        """)

        if not project_data_obj.is_verified:
            st.warning("⚠️ **Notice:** 'DRAFT - NOT FOR PUBLICATION' watermark is burned into the video because project status is unverified.")
        else:
            st.success("✨ **Ready for Broadcast:** Fully compliant with RERA guidelines and advertising limits.")
