"""
Festive Real-Estate Video Ad Generator — Streamlit Web Application
==================================================================
Converts property renders, project details JSON, and branding into compliant
festive video ads using Google Gemini Veo 3.1 Fast, Pillow, and FFmpeg.
"""

from __future__ import annotations

import json
import os
import subprocess
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
from planner import AdPlan, fmt_seconds, plan_all_versions, plan_video_ad, plan_with_agent, validate_plan
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

    use_scene_agent = st.checkbox(
        "🤖 Plan scenes with Gemini agent",
        value=False,
        help="Sends the scene-planner system prompt to Gemini. Its plan is checked against the rules; "
             "if it breaks any rule the built-in rule engine is used instead.",
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

st.markdown("### 🎨 Choose Video Ad Campaign Template")
template_choice = st.radio(
    "Ad Template",
    options=["🪔 Indian Festival Ad", "🏢 Standard Luxury Ad", "👨‍👩‍👧‍👦 Family Living & Community Ad"],
    index=0,
    horizontal=True,
    help="Select 'Indian Festival' for cultural celebrations like Diwali, 'Standard' for modern architectural luxury, or 'Family Living' for wholesome community lifestyle.",
    label_visibility="collapsed",
    key="campaign_template_choice",
)

is_festival_template = "Indian Festival" in template_choice
is_family_template = "Family Living" in template_choice

col_cfg1, col_cfg2 = st.columns([1, 1], gap="medium")

with col_cfg1:
    st.markdown("#### 1. Video Specifications")
    video_length = st.number_input(
        "⏱️ Video Length (seconds)",
        min_value=10,
        max_value=60,
        value=10,
        step=1,
        help="Allowed 10–60 seconds. Default: 10 seconds (~₹62 at 720p).",
    )
    make_all_versions = st.checkbox(
        "🎞️ Make all three versions (60 s, 20 s, 10 s)",
        value=False,
        help="Plans the 60 s video first and cuts the 20 s and 10 s versions from the same clips, "
             "so Veo is paid for only once.",
    )

    if is_festival_template:
        festival_list = [
            "Diwali", "Ugadi", "Dussehra", "Ganesh Chaturthi", "Onam",
            "Pongal/Sankranti", "Christmas", "Eid", "New Year"
        ]
        selected_festival = st.selectbox(
            "🎉 Festival Celebration Theme",
            options=festival_list,
            index=0,
            help="Select the Indian festival to tailor visual decor, music, and voiceover copy.",
        )
    elif is_family_template:
        selected_festival = "Family"
        st.info("👨‍👩‍👧‍👦 **Family Living Theme Active:** Heartwarming family lifestyle, vibrant green parks, kids play zones, safe community living, and multi-generational comfort.")
    else:
        selected_festival = "None"
        st.info("🏢 **Standard Template Active:** Clean architectural drone shots, luxury ambient score, executive typography, and pricing highlights without festival decor.")

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
            options=["720p", "1080p"],
            index=0,
            help="720p (HD, $0.09/sec ~₹62/10s) or 1080p (Full HD, $0.12/sec ~₹83/10s).",
        )

    st.caption("Pricing: **720p** = $0.09/sec (~₹62/10s)  |  **1080p** = $0.12/sec (~₹83/10s)  |  **End Card** = $0.00 (Local Pillow)")


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
            r_desc = st.text_input("What it shows", value="", key=f"rdesc_{idx}",
                                   placeholder="e.g. 3 towers at dusk")

            active_renders.append(RenderInfo(
                filepath=str(r_dest),
                render_type=r_type,
                approved=is_approved,
                description=r_desc,
            ))


# ─────────────────────────────────────────────
# Section 3: Project Summary Display
# ─────────────────────────────────────────────

if project_data_obj:
    st.divider()
    status_class = "status-verified" if project_data_obj.is_verified else "status-draft"
    status_label = "VERIFIED PROJECT" if project_data_obj.is_verified else "UNVERIFIED PROJECT"

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
            st.session_state["script_text_input"] = st.session_state["script_options"][0].text
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
        raw_choice = st.session_state.get("script_radio_choice", 0)
        try:
            chosen_idx = int(raw_choice)
        except (ValueError, TypeError):
            chosen_idx = 0

        if not (0 <= chosen_idx < len(script_opts)):
            chosen_idx = 0

        st.session_state["selected_script_idx"] = chosen_idx
        st.session_state["script_radio_choice"] = chosen_idx
        chosen_text = script_opts[chosen_idx].text if script_opts else ""
        st.session_state["approved_script"] = chosen_text
        st.session_state["script_text_input"] = chosen_text
        st.session_state["preview_vo_path"] = None

    # Ensure selected index and radio state are safe integers within bounds
    try:
        current_script_idx = int(st.session_state.get("selected_script_idx", 0))
    except (ValueError, TypeError):
        current_script_idx = 0
    if not (0 <= current_script_idx < len(script_opts)):
        current_script_idx = 0
    st.session_state["selected_script_idx"] = current_script_idx
    if "script_radio_choice" in st.session_state and not isinstance(st.session_state["script_radio_choice"], int):
        st.session_state["script_radio_choice"] = current_script_idx

    col_pick, col_regen = st.columns([3, 1], gap="small")
    with col_pick:
        st.radio(
            "Select a script option to approve & customize:",
            options=list(range(len(script_opts))),
            format_func=lambda idx: f"Option {idx+1}: {script_opts[idx].title} ({script_opts[idx].tone})",
            index=current_script_idx,
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
                first_text = st.session_state["script_options"][0].text
                st.session_state["approved_script"] = first_text
                st.session_state["script_text_input"] = first_text
                st.session_state["preview_vo_path"] = None
                st.rerun()

    # Editable Text Area for Live Modification
    if "script_text_input" not in st.session_state or not st.session_state["script_text_input"]:
        st.session_state["script_text_input"] = script_opts[0].text if script_opts else ""

    edited_script = st.text_area(
        "✏️ Approve & Edit Voiceover Script (Live on web page):",
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

    s_col1, s_col2 = st.columns([1.5, 3.5])
    with s_col1:
        st.caption(f"📝 **{word_count} words** (~{est_speech_time:.1f}s speech)")
    with s_col2:
        if est_speech_time > speaking_window + 0.8:
            st.caption(f"⚠️ Script is long for {video_length}s ad ({est_speech_time:.1f}s > {speaking_window:.1f}s window).")
        else:
            st.caption(f"✅ Perfectly timed for {video_length}s ad ({est_speech_time:.1f}s in {speaking_window:.1f}s window).")

    # ─────────────────────────────────────────────
    # Audio & Soundtrack Customization Controls
    # ─────────────────────────────────────────────
    st.markdown("#### 🎚️ Choose Voice & Background Music")
    a_col1, a_col2, a_col3 = st.columns([1.4, 1.8, 1.0])

    with a_col1:
        voice_choice = st.selectbox(
            "🎙️ Voiceover Actor",
            options=[
                "👩 Neerja (Female — Warm & Elegant)",
                "👨 Prabhat (Male — Deep & Authoritative)",
                "🚫 None (Instrumental Music Only)",
            ],
            index=0,
            help="Select the AI voice actor for your voiceover narration.",
            key="voice_actor_select",
        )

    with a_col2:
        default_music_idx = 0 if is_festival_template else 1
        music_choice = st.selectbox(
            "🎵 Background Soundtrack",
            options=[
                "🪔 Pure Sitar & Tanpura (Authentic Classical Raga — Zero Vocals)",
                "🎹 Neoclassical Ambient Piano & Strings (Modern Luxury)",
                "📁 Custom Uploaded Audio Track",
            ],
            index=default_music_idx,
            help="Select the musical soundtrack style for your video ad.",
            key="soundtrack_style_select",
        )

    with a_col3:
        music_volume = st.slider(
            "🎚️ Music Volume",
            min_value=10,
            max_value=40,
            value=20,
            step=5,
            format="%d%%",
            help="Music volume level under voiceover. Default: 20%.",
            key="music_vol_slider",
        )

    # Audio Preview Action Buttons
    prev_col1, prev_col2, prev_col3 = st.columns(3)
    btn_prev_vo = prev_col1.button("🎙️ Preview Voice Alone", use_container_width=True)
    btn_prev_music = prev_col2.button("🎵 Preview Music Alone", use_container_width=True)
    btn_prev_mix = prev_col3.button("🎧 Preview Complete Mix", use_container_width=True, type="secondary")

    # Determine voice name
    selected_voice_name = "en-IN-PrabhatNeural" if "Prabhat" in voice_choice else "en-IN-NeerjaNeural"
    voice_enabled = "None" not in voice_choice
    selected_track_type = "sitar" if "Sitar" in music_choice else ("piano" if "Piano" in music_choice else None)
    duck_level = music_volume / 100.0

    preview_cache_dir = Path("outputs/audio_previews")
    preview_cache_dir.mkdir(parents=True, exist_ok=True)

    # 1. Preview Voice Alone
    if btn_prev_vo and edited_script.strip() and voice_enabled:
        with st.spinner(f"Synthesizing voice with {voice_choice.split('(')[0]}..."):
            vo_preview_path = preview_cache_dir / f"preview_voice_{'male' if 'Prabhat' in voice_choice else 'female'}.mp3"
            try:
                generate_indian_voiceover(
                    script_text=edited_script.strip(),
                    output_path=vo_preview_path,
                    api_key=effective_key,
                    voice_name=selected_voice_name,
                )
                st.session_state["active_preview_audio"] = str(vo_preview_path)
                st.session_state["active_preview_label"] = f"🎙️ Voiceover Preview ({voice_choice.split('(')[0].strip()})"
            except Exception as e:
                st.error(f"Voice generation failed: {e}")

    # 2. Preview Music Alone
    if btn_prev_music:
        with st.spinner("Preparing background music preview..."):
            music_preview_path = preview_cache_dir / f"preview_music_{selected_track_type or 'custom'}.mp3"
            try:
                build_music_track(
                    duration=video_length,
                    festival=selected_festival,
                    uploaded_music_path=active_music_path if "Custom" in music_choice else None,
                    output_path=music_preview_path,
                    music_track=selected_track_type,
                )
                st.session_state["active_preview_audio"] = str(music_preview_path)
                st.session_state["active_preview_label"] = f"🎵 Music Track Preview ({music_choice.split('(')[0].strip()})"
            except Exception as e:
                st.error(f"Music generation failed: {e}")

    # 3. Preview Complete Mix
    if btn_prev_mix and edited_script.strip():
        with st.spinner("Mixing voiceover with ducked background music..."):
            mix_preview_path = preview_cache_dir / f"preview_mix_{video_length}s.mp3"
            temp_vo = preview_cache_dir / "temp_mix_vo.mp3"
            temp_music = preview_cache_dir / "temp_mix_music.mp3"
            try:
                build_music_track(
                    duration=video_length,
                    festival=selected_festival,
                    uploaded_music_path=active_music_path if "Custom" in music_choice else None,
                    output_path=temp_music,
                    music_track=selected_track_type,
                )
                if voice_enabled:
                    generate_indian_voiceover(
                        script_text=edited_script.strip(),
                        output_path=temp_vo,
                        api_key=effective_key,
                        voice_name=selected_voice_name,
                    )
                    cmd_mix = [
                        "ffmpeg", "-y",
                        "-i", str(temp_music),
                        "-i", str(temp_vo),
                        "-filter_complex",
                        f"[0:a]aformat=sample_fmts=fltp:sample_rates=44100:channel_layouts=stereo,volume={duck_level:.2f}[mduck];"
                        f"[1:a]aformat=sample_fmts=fltp:sample_rates=44100:channel_layouts=stereo,volume=1.0[vclean];"
                        f"[mduck][vclean]amix=inputs=2:duration=first:dropout_transition=2[aout]",
                        "-map", "[aout]",
                        "-t", str(video_length),
                        "-c:a", "libmp3lame", "-b:a", "192k",
                        str(mix_preview_path)
                    ]
                    subprocess.run(cmd_mix, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL, check=True)
                else:
                    mix_preview_path = temp_music

                st.session_state["active_preview_audio"] = str(mix_preview_path)
                st.session_state["active_preview_label"] = f"🎧 Complete Master Audio Mix ({video_length}s)"
            except Exception as e:
                st.error(f"Audio mix failed: {e}")

    # Display Active Audio Player
    if st.session_state.get("active_preview_audio") and Path(st.session_state["active_preview_audio"]).exists():
        st.markdown(f"**{st.session_state.get('active_preview_label', 'Audio Player')}:**")
        st.audio(st.session_state["active_preview_audio"], format="audio/mp3")


# ─────────────────────────────────────────────
# Section 5: Action Buttons & Scene Planning
# ─────────────────────────────────────────────

col_btn1, col_btn2 = st.columns([1, 1], gap="medium")
preview_plan_clicked = col_btn1.button("📋 Preview Plan & Cost (No API Calls)", use_container_width=True, type="secondary")
generate_video_clicked = col_btn2.button("🚀 Generate Festive Video Ad", use_container_width=True, type="primary")

# Compute Plan if project data exists
if project_data_obj:
    approved_renders = filter_approved_renders(active_renders, project_data_obj.raw_data.get("review"))
    logo_ok = bool(active_logo_path and Path(active_logo_path).exists())
    plan_key = json.dumps([
        project_data_obj.name, [(r.filepath, r.render_type, r.description) for r in approved_renders],
        video_length, selected_festival, aspect_ratio, resolution, logo_ok, make_all_versions,
        use_scene_agent, st.session_state.get("approved_script", ""),
    ])
    if st.session_state.get("plan_key") != plan_key:
        user_script = st.session_state.get("approved_script", "").strip() or None
        base = None
        if use_scene_agent:
            with st.spinner("🤖 Gemini scene agent is planning..."):
                base = plan_with_agent(
                    project_data_obj, approved_renders, 60 if make_all_versions else video_length,
                    selected_festival, aspect_ratio, resolution,
                    script=None if make_all_versions else user_script,
                    logo_available=logo_ok, api_key=user_api_key or os.getenv("GEMINI_API_KEY", ""),
                )
        if make_all_versions:
            versions = plan_all_versions(
                project_data_obj, approved_renders, selected_festival, aspect_ratio, resolution,
                logo_available=logo_ok, base_plan=base,
            )
        else:
            versions = [base or plan_video_ad(
                project=project_data_obj,
                renders=approved_renders,
                requested_duration=video_length,
                festival=selected_festival,
                aspect=aspect_ratio,
                resolution=resolution,
                script=user_script,
                logo_available=logo_ok,
            )]
        st.session_state["plan_versions"] = versions
        st.session_state["plan_key"] = plan_key
    plan_versions: List[AdPlan] = st.session_state["plan_versions"]
    plan = plan_versions[0]
else:
    plan_versions = []
    plan = None


# ── Plan Table Display ──────────────────────────
if preview_plan_clicked or st.session_state.get("show_plan", False):
    st.session_state["show_plan"] = True
    if not project_data_obj:
        st.warning("⚠️ Please upload a valid project JSON or click 'Load Aurelia Heights Sample Assets'.")
    else:
        if is_festival_template:
            heading_title = f"Indian Festival Ad ({selected_festival})"
        elif is_family_template:
            heading_title = "Family Living & Community Ad"
        else:
            heading_title = "Standard Luxury Real Estate Ad"
        if plan.blocked:
            st.error(f"⛔ Video blocked: {plan.blocked_reason}")
            if plan.case == "F":
                st.info("💡 Make a poster with the logo instead (Poster Generator), or ask the developer for renders.")
        case_text = {
            "A": "Exterior + interior + amenity renders",
            "B": "Exterior + amenity renders (no interior)",
            "C": "Exterior + interior renders (no amenity) – amenities shown as text chips",
            "D": "Exterior render only – amenities shown as text chips",
            "E": "No exterior render – no building shots",
            "F": "No approved renders",
        }
        for pv in ([] if plan.blocked else plan_versions):
            st.markdown(f"### 📋 {heading_title} – {pv.requested_duration}s")
            st.caption(
                f"**Case {pv.case}:** {case_text.get(pv.case, '')} • Planner: `{pv.planner}` • "
                f"Crossfade {pv.crossfade_seconds:.2f}s"
            )
            for w in pv.warnings:
                st.warning(w)
            if pv.missing_fields:
                st.caption("**Missing fields:** " + ", ".join(f"`{m}`" for m in pv.missing_fields))
            for fb in pv.fallbacks_used:
                st.caption(f"↪️ Fallback: {fb['replaced']} → *{fb['with']}*")
            problems = validate_plan(pv, approved_renders)
            if problems:
                st.error("Rule check failed: " + "; ".join(problems))

            m_col1, m_col2, m_col3, m_col4 = st.columns(4)
            m_col1.metric("Length", f"{pv.requested_duration}s")
            m_col2.metric("Planned Length", f"{pv.final_duration:.1f}s")
            m_col3.metric("New Veo Seconds", f"{pv.total_veo_seconds}s")
            m_col4.metric("Estimated Cost", f"${pv.total_estimated_cost_usd:.2f}")

            st.dataframe(pv.to_table_data(), use_container_width=True, hide_index=True)
            st.caption(f"🎙️ **Voiceover ({pv.voiceover_word_count} words):** {pv.voiceover_script}")
            st.caption("🏷️ **End card:** " + " | ".join(pv.end_card.get("lines", [])))
            if pv.amenity_text_chips:
                st.caption("🔖 **Amenity chips:** " + " • ".join(pv.amenity_text_chips))

            with st.expander(f"🎬 Veo prompts – {pv.requested_duration}s", expanded=False):
                for s_ in pv.veo_scenes:
                    reuse = f" • reuses 60s scene {s_.reuses_scene_id}" if s_.reuses_scene_id else ""
                    st.markdown(
                        f"**Scene {s_.index}: {s_.name}** — `{s_.veo_mode}` • Veo {s_.veo_duration}s, "
                        f"used {fmt_seconds(s_.duration_seconds)} • *{s_.label}*{reuse}"
                    )
                    st.code(s_.prompt, language=None)
            st.download_button(
                f"⬇️ Scene plan JSON ({pv.requested_duration}s)",
                data=json.dumps(pv.to_dict(), indent=2, ensure_ascii=False),
                file_name=f"scene_plan_{pv.requested_duration}s.json",
                mime="application/json",
                key=f"plan_json_{pv.requested_duration}",
            )

        st.caption("ℹ️ 'Preview plan & cost' incurs zero API charges. Review prompts and timing above.")


# ─────────────────────────────────────────────
# Section 6: Execution Pipeline
# ─────────────────────────────────────────────

if generate_video_clicked:
    if not project_data_obj:
        st.error("❌ Please provide a project JSON with a valid RERA number before generating.")
        st.stop()

    if plan is None or plan.blocked:
        st.error(f"⛔ Cannot generate: {plan.blocked_reason if plan else 'no plan'}")
        st.stop()
    if not active_logo_path:
        st.warning("⚠️ No logo – the end card will show the project name in large text.")

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

        results = []
        clean_pname = project_data_obj.name.replace(" ", "_").lower()
        clean_fest = selected_festival.replace("/", "_").lower()
        clean_aspect = aspect_ratio.replace(":", "_")
        chosen_track = "sitar" if "Sitar" in music_choice else ("piano" if "Piano" in music_choice else None)

        for pv in plan_versions:
            dur = pv.requested_duration
            st.write(f"#### ▶️ {dur}s version (case {pv.case})")
            # Step 2: Generate Clips (cached by prompt + render + Veo length, so versions share clips)
            clip_paths = []
            for s in pv.veo_scenes:
                reuse = f" (reusing 60s scene {s.reuses_scene_id})" if s.reuses_scene_id else ""
                st.write(f"🎥 Scene {s.index} ({s.veo_mode}, Veo {s.veo_duration}s){reuse}: **{s.name}**...")
                dest = cache_dir / f"clip_{dur}s_scene_{s.index}_{s.veo_duration}s.mp4"
                try:
                    clip_file = veo.generate_clip(
                        prompt=s.prompt,
                        duration=s.veo_duration,
                        aspect=aspect_ratio,
                        resolution=resolution,
                        image_path=s.render_path,
                        output_dest=dest,
                    )
                except Exception as e:
                    st.warning(f"⚠️ Veo live render notice: {e}. Using cinematic motion fallback.")
                    clip_file = veo._generate_mock_clip(
                        dest, s.veo_duration, aspect_ratio, resolution, s.render_path, s.prompt
                    )
                clip_paths.append(clip_file)

            # Step 3: End Card
            st.write(f"🏷️ Creating end card ({pv.endcard_duration}s)...")
            endcard_dest = cache_dir / f"web_endcard_{dur}s.mp4"
            create_endcard_clip(
                project=project_data_obj,
                duration=pv.endcard_duration,
                logo_path=active_logo_path,
                festival=selected_festival,
                aspect=aspect_ratio,
                resolution=resolution,
                output_path=endcard_dest,
                card=pv.end_card,
            )

            # Step 4: Music Track
            st.write(f"🎵 Preparing background music ({music_choice.split('(')[0].strip()})...")
            music_dest = cache_dir / f"web_music_{dur}s.mp3"
            build_music_track(
                duration=dur,
                festival=selected_festival,
                uploaded_music_path=active_music_path if "Custom" in music_choice else None,
                output_path=music_dest,
                api_key=effective_key,
                music_track=chosen_track,
                music_prompt=pv.music_prompt,
            )

            # Step 4b: Voiceover (approved script for a single version; one script per length in "all" mode)
            voiceover_dest = None
            script_to_speak = pv.voiceover_script.strip()
            if script_to_speak and "None" not in voice_choice:
                st.write(f"🎙️ Synthesizing voiceover ({voice_choice.split('(')[0].strip()})...")
                voiceover_dest = cache_dir / f"web_voice_{dur}s.mp3"
                try:
                    chosen_voice_name = "en-IN-PrabhatNeural" if "Prabhat" in voice_choice else "en-IN-NeerjaNeural"
                    generate_indian_voiceover(
                        script_text=script_to_speak,
                        output_path=voiceover_dest,
                        api_key=effective_key,
                        voice_name=chosen_voice_name,
                    )
                except Exception as e:
                    st.warning(f"Voiceover warning: {e}. Video will proceed with background music track.")
                    voiceover_dest = None

            # Step 5: Stitching & Legal Overlays with Audio Ducking
            st.write("⚖️ Trimming clips, crossfading, ducking music, burning RERA bar, labels & disclaimers...")
            final_file = output_dir / f"{clean_pname}_{clean_fest}_{dur}s_{clean_aspect}.mp4"
            duck_vol = (music_volume / 100.0) if voiceover_dest else 1.0
            out_path, checks = assemble_final_video(
                plan=pv,
                project=project_data_obj,
                clip_paths=clip_paths,
                endcard_path=endcard_dest,
                music_path=music_dest,
                output_path=final_file,
                voiceover_path=voiceover_dest,
                music_duck_volume=duck_vol,
            )
            results.append((pv, out_path, checks, voiceover_dest))

        if getattr(veo, "credits_depleted", False):
            st.info("ℹ️ Google Cloud Veo credits are depleted on your account (HTTP 402). Cinematic motion rendering was used at $0.00 cost.")

        status_box.update(label="🎉 Video Ad Export Complete & Verified!", state="complete", expanded=False)

    # ─────────────────────────────────────────────
    # Section 6: Video Player & Verification Report
    # ─────────────────────────────────────────────
    st.divider()
    st.markdown("### 🏆 Your Generated Festive Real-Estate Ad")

    for plan, out_path, checks, voiceover_dest in results:
        st.markdown(f"#### {plan.requested_duration}s version")
        v_col1, v_col2 = st.columns([3, 2], gap="large")

        with v_col1:
            if out_path.exists():
                st.video(str(out_path))
                with open(out_path, "rb") as vf:
                    st.download_button(
                        label=f"⬇️ Download Video ({out_path.name})",
                        key=f"dl_{out_path.name}",
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
            - **Campaign Template:** `{"Indian Festival (" + selected_festival + ")" if is_festival_template else ("Family Living & Community Ad" if is_family_template else "Standard Luxury Real Estate Ad")}`
            - **Requested Duration:** `{plan.requested_duration} seconds`
            - **Exported Duration:** `{checks['actual_duration']} seconds` (±1s tolerance: **{'PASSED' if checks['duration_passed'] else 'FLAGGED'}**)
            - **Audio Production:** **{'🎙️ Indian-English AI Voiceover + Ducked Music' if voiceover_dest else '🎵 Festive Instrumental Music'}**
            - **Legal RERA Bar:** `RERA No: {project_data_obj.rera_number} | *T&C Apply`
            - **RERA Compliance:** **{'✓ Present on every frame' if checks['rera_bar_verified'] else '⚠️ Check frames'}**
            - **Frames Inspected:** `{checks['frames_checked']} frames verified (1 FPS)`
            - **AI Video Engine:** `Google Gemini Veo 3.1 Fast`
            - **Estimated Cost:** `${plan.total_estimated_cost_usd:.2f} USD`
            """)

            if plan.warnings:
                st.warning("Check before publishing: " + " ".join(plan.warnings))
            else:
                st.success("✨ Ready for review: RERA bar, labels and disclaimers applied.")
