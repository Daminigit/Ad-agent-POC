"""
Ad Agent POC — Streamlit UI
=============================
Wires up all services into a 4-stage State Machine:
  1. Intake: Chat-based document ingestion
  2. Confirm: Fact confirmation & correction
  3. Generate: Copy + Creative Pipeline + Validation
  4. Results: Display generated assets
"""

import streamlit as st
import uuid
import time
import os
from pathlib import Path
from dotenv import load_dotenv

from models.db import load_project, get_documents
from models.fact_sheet import Project
from services.intake import (
    get_next_required_doc, ingest_document, mark_document_skipped
)
from services.extraction import (
    process_document, confirm_fact, reject_fact,
    get_unconfirmed_fields, build_confirmation_prompts
)
from services.copy_writer import generate_copy, copy_to_display
from services.creative import run_creative_pipeline
from services.validation import validate_project_creatives

load_dotenv()

st.set_page_config(page_title="Property Ad Agent", layout="wide")

# ─────────────────────────────────────────────
# Session State Initialization
# ─────────────────────────────────────────────

if "project_id" not in st.session_state:
    st.session_state.project_id = str(uuid.uuid4())
if "stage" not in st.session_state:
    st.session_state.stage = "intake"

with st.sidebar:
    st.caption(f"Current Project: `{st.session_state.project_id}`")
    
    # Project list dropdown
    from models.db import list_projects
    try:
        all_projs = list_projects()
        proj_options = {f"{p.get('name') or 'Unnamed'} ({p['id'][:8]}...)": p['id'] for p in all_projs}
        selected_label = st.selectbox("Select Existing Project:", ["-- Choose Project --"] + list(proj_options.keys()))
        if selected_label != "-- Choose Project --":
            chosen_id = proj_options[selected_label]
            if chosen_id != st.session_state.project_id:
                st.session_state.project_id = chosen_id
                st.session_state.stage = "results"
                st.session_state.pipeline_results = {}
                st.rerun()
    except Exception:
        pass

    load_id = st.text_input("Or enter Project ID:")
    col_l1, col_l2 = st.columns(2)
    with col_l1:
        if st.button("Load Intake"):
            if load_id:
                st.session_state.project_id = load_id
                st.session_state.stage = "intake"
                st.session_state.pipeline_results = {}
                st.rerun()
    with col_l2:
        if st.button("Load Creatives"):
            if load_id:
                st.session_state.project_id = load_id
                st.session_state.stage = "results"
                st.session_state.pipeline_results = {}
                st.rerun()

    st.divider()
    st.write("**Quick Switch Stage:**")
    col_nav1, col_nav2 = st.columns(2)
    with col_nav1:
        if st.button("Review Creatives", use_container_width=True):
            st.session_state.stage = "results"
            st.rerun()
    with col_nav2:
        if st.button("Intake", use_container_width=True):
            st.session_state.stage = "intake"
            st.rerun()


# Helper to reload the project from SQLite
def get_project() -> Project:
    raw = load_project(st.session_state.project_id)
    return Project(**raw) if raw else Project(id=st.session_state.project_id)


# ─────────────────────────────────────────────
# STAGE 1: INTAKE
# ─────────────────────────────────────────────

def render_intake():
    st.header("Step 1: Document Intake")
    
    project_id = st.session_state.project_id
    next_doc = get_next_required_doc(project_id)
    
    if not next_doc:
        st.success("All documents uploaded successfully!")
        if st.button("Proceed to Fact Confirmation", type="primary"):
            st.session_state.stage = "confirm"
            st.rerun()
        return

    req_label = "*(Required)*" if next_doc["required"] else "*(Optional)*"
    st.chat_message("assistant").write(
        f"Please upload your **{next_doc['label']}** {req_label}."
    )
    if next_doc["hint"]:
        st.caption(next_doc["hint"])

    is_render = "render" in next_doc["key"]
    uploaded_file = st.file_uploader(
        f"Upload {next_doc['key']}",
        key=f"upload_{next_doc['key']}",
        label_visibility="collapsed",
        accept_multiple_files=is_render
    )

    col1, col2 = st.columns([1, 4])
    with col1:
        if uploaded_file:
            if st.button("Submit Document"):
                with st.spinner("Processing document..."):
                    files = uploaded_file if isinstance(uploaded_file, list) else [uploaded_file]
                    all_ok = True
                    all_errors = []
                    
                    for f in files:
                        bytes_data = f.getvalue()
                        res = ingest_document(
                            project_id=project_id,
                            doc_type=next_doc["key"],
                            filename=f.name,
                            file_bytes=bytes_data
                        )
                        
                        if not res["ok"]:
                            all_ok = False
                            all_errors.extend(res["errors"])
                        else:
                            # Extract facts in the background
                            if res["text"]:
                                process_document(
                                    project_id=project_id,
                                    doc_type=next_doc["key"],
                                    document_text=res["text"],
                                    source_doc=f.name
                                )
                                
                    if not all_ok:
                        st.error("\n".join(all_errors))
                    else:
                        st.success(f"{next_doc['label']} submitted successfully!")
                        st.rerun()

    with col2:
        if not next_doc["required"]:
            if st.button("Skip this document"):
                mark_document_skipped(project_id, next_doc["key"])
                st.rerun()

    # Show uploaded documents
    docs = get_documents(project_id)
    if docs:
        st.divider()
        st.subheader("Uploaded Documents")
        for d in docs:
            if d["status"] != "missing":
                st.text(f"✅ {d['doc_type']}: {d['filename']}")


# ─────────────────────────────────────────────
# STAGE 2: CONFIRM
# ─────────────────────────────────────────────

def render_confirm():
    st.header("Step 2: Fact Confirmation")
    st.write("Review and confirm the facts extracted from your documents.")
    
    project = get_project()
    unconfirmed = get_unconfirmed_fields(project)
    
    if not unconfirmed:
        st.success("All extracted facts have been reviewed.")
        
        gate_ok = project.is_ready_for_generation()
        if not gate_ok:
            st.error("Cannot proceed: Both RERA number and Price List MUST be confirmed.")
            st.warning("Some required information wasn't found in your documents. Please enter it manually below:")
            
            with st.form("manual_gate_form"):
                missing_rera = "rera_number" not in project.confirmed_facts
                missing_price = "unit_types" not in project.confirmed_facts and "price_range" not in project.confirmed_facts
                
                manual_rera = st.text_input("RERA Number:") if missing_rera else None
                manual_price = st.text_input("Price Range (e.g. ₹1.5 Cr onwards):") if missing_price else None
                
                if st.form_submit_button("Confirm Missing Details"):
                    if missing_rera and manual_rera:
                        confirm_fact(project.id, "rera_number", manual_rera, "Manual Entry", "Developer")
                    if missing_price and manual_price:
                        confirm_fact(project.id, "price_range", manual_price, "Manual Entry", "Developer")
                    st.rerun()
        else:
            if st.button("Generate Ad Creatives & Copy", type="primary"):
                st.session_state.stage = "generate"
                st.rerun()
        return

    # Just show the first unconfirmed field to keep it chat-like
    field_to_confirm = unconfirmed[0]
    
    # We need the extraction prompts logic (we saved facts in project, but prompts need the raw dict)
    # Rebuild a dummy facts dict from the project for the prompt builder
    dummy_facts = project.model_dump(mode="json")
    # Rename project attributes to fact keys where different
    dummy_facts["project_name"] = dummy_facts.pop("name", None)
    dummy_facts["unit_types"] = dummy_facts.pop("units", [])
    
    prompts = build_confirmation_prompts(dummy_facts, project)
    prompt = next((p for p in prompts if p["field"] == field_to_confirm), None)
    
    if not prompt:
        # Fallback if something goes wrong
        st.error(f"Cannot build prompt for {field_to_confirm}")
        return
        
    st.chat_message("assistant").write(prompt["display_text"])
    st.write(f"Does this look correct for **{prompt['label']}**?")
    
    col1, col2 = st.columns([1, 1])
    with col1:
        if st.button("Yes, confirm", key=f"conf_{field_to_confirm}"):
            confirm_fact(
                project_id=project.id,
                field=field_to_confirm,
                value=prompt["extracted_value"],
                source_doc="extracted_doc",
                confirmed_by="Developer"
            )
            st.rerun()
    with col2:
        new_val = st.text_input("No, correct it:", key=f"corr_{field_to_confirm}")
        if st.button("Save Correction"):
            if new_val:
                reject_fact(
                    project_id=project.id,
                    field=field_to_confirm,
                    correct_value=new_val,
                    source_doc="developer_correction",
                    confirmed_by="Developer"
                )
                st.rerun()
            else:
                st.error("Please enter a corrected value.")


# ─────────────────────────────────────────────
# STAGE 3: GENERATE
# ─────────────────────────────────────────────

def render_generate():
    st.header("Step 3: Generating Creatives")
    
    project = get_project()
    docs = get_documents(project.id)
    
    # Find render paths
    render_paths = [
        d["filepath"] for d in docs 
        if d["doc_type"] in ("exterior_renders", "interior_renders") and Path(d["filepath"]).exists()
    ]
    
    if not render_paths:
        st.error("No exterior or interior renders uploaded. Cannot generate creatives.")
        if st.button("Go back to Intake"):
            st.session_state.stage = "intake"
            st.rerun()
        return

    st.write("### Generation Settings")
    motion_type = st.radio(
        "Motion Engine",
        ["Motion by Hyperframes (Ken Burns zoom - Free & Fast)", "Motion by Wan 2.2 (Cinematic AI via fal.ai)"]
    )

    if st.button("Start Pipeline", type="primary"):
        with st.status("Running Generation Pipeline...", expanded=True) as status:
            # 1. Ad Copy
            st.write("✍️ Generating Ad Copy...")
            copy = generate_copy(project)
            
            # 2. Creatives
            st.write("🎨 Preparing images and animating (this may take a minute)...")
            
            # We don't have a specific price_text field in the fact sheet models exactly formatted for overlay.
            # We'll use the price_range confirmed fact.
            price_fact = project.confirmed_facts.get("price_range")
            price_text = price_fact.value if price_fact else "Price on request"
            
            # Find logo if uploaded
            logo_doc = next((d for d in docs if d["doc_type"] == "logo" and d["status"] == "ok"), None)
            logo_path = logo_doc["filepath"] if logo_doc else None
            
            res = run_creative_pipeline(
                project_id=project.id,
                render_paths=render_paths,
                rera_number=project.rera_number,
                price_text=price_text,
                logo_path=logo_path,
                voice_script=copy.voice_script,
                animate=(motion_type == "Motion by Wan 2.2 (Cinematic AI via fal.ai)"),
                quality="draft" # Use draft 480p by default to save money
            )
            
            if res["errors"]:
                for e in res["errors"]:
                    st.error(e)
            
            # 3. Validation
            st.write("✅ Validating outputs...")
            all_images = []
            for paths in res.get("static_images", {}).values():
                all_images.extend(paths)
                
            val_results = validate_project_creatives(project, all_images)
            
            status.update(label="Pipeline Complete!", state="complete", expanded=False)
            st.session_state.pipeline_results = res
            st.session_state.val_results = val_results
            st.session_state.stage = "results"
            st.rerun()


# ─────────────────────────────────────────────
# STAGE 4: RESULTS
# ─────────────────────────────────────────────

def render_results():
    st.header("Step 4: Review Ad Creatives")
    project = get_project()
    
    tab_google, tab_meta, tab_voice, tab_creatives, tab_validation = st.tabs([
        "Google Search", "Meta Ads", "Voice Script", "Images & Reels", "Validation"
    ])
    
    # Ad Copy (Google)
    with tab_google:
        from services.copy_writer import get_copy, copy_to_display
        copy = get_copy(project.id)
        if copy:
            disp = copy_to_display(copy)
            st.subheader("Headlines")
            for h in disp["google_search"]["headlines"]:
                color = "green" if h["ok"] else "red"
                st.markdown(f"- {h['text']} `:{color}[{h['chars']}/{h['limit']}]`")
            st.subheader("Descriptions")
            for d in disp["google_search"]["descriptions"]:
                color = "green" if d["ok"] else "red"
                st.markdown(f"- {d['text']} `:{color}[{d['chars']}/{d['limit']}]`")
                
    # Ad Copy (Meta)
    with tab_meta:
        if copy:
            disp = copy_to_display(copy)
            meta = disp["meta"]
            st.subheader("Primary Text")
            st.write(meta["primary_text"])
            
            h = meta["headline"]
            color_h = "green" if h["ok"] else "red"
            st.markdown(f"**Headline:** {h['text']} `:{color_h}[{h['chars']}/{h['limit']}]`")
            
            l = meta["link_description"]
            color_l = "green" if l["ok"] else "red"
            st.markdown(f"**Link:** {l['text']} `:{color_l}[{l['chars']}/{l['limit']}]`")
            
    # Voice Script
    with tab_voice:
        if copy:
            st.info("🎙️ **Video Voiceover Script**")
            st.write(copy.voice_script)
            
    # Creatives
    with tab_creatives:
        res = st.session_state.get("pipeline_results", {})
        
        # If res is empty (e.g. user loaded a project), try to find existing files
        if not res and (Path("outputs") / project.id).exists():
            out_dir = Path("outputs") / project.id
            res = {"static_images": {"reloaded": []}, "reels": []}
            
            img_dir = out_dir / "images"
            if img_dir.exists():
                for p in sorted(img_dir.glob("*.jpg")):
                    res["static_images"]["reloaded"].append(str(p))
                    
            reel_dir = out_dir / "reels"
            if reel_dir.exists():
                for p in sorted(reel_dir.glob("*.mp4")):
                    res["reels"].append(str(p))
            st.session_state.pipeline_results = res
                    
        st.subheader("Generated Images")
        
        for platform, paths in res.get("static_images", {}).items():
            st.write(f"**{platform.title()}**")
            cols = st.columns(min(len(paths), 4))
            for i, p in enumerate(paths):
                if Path(p).exists():
                    cols[i % 4].image(p, caption=Path(p).name, use_container_width=True)
                    
        reels = res.get("reels", [])
        if reels:
            st.subheader("Generated Reels & Video Ads")
            for r in reels:
                reel_path = Path(r)
                if reel_path.exists():
                    col_v, col_btn = st.columns([3, 1])
                    with col_v:
                        st.markdown(f"🎬 **{reel_path.name}**")
                        st.video(str(reel_path))
                    with col_btn:
                        st.write("")
                        st.write("")
                        with open(reel_path, "rb") as f:
                            st.download_button(
                                label=f"⬇️ Download {reel_path.name}",
                                data=f.read(),
                                file_name=reel_path.name,
                                mime="video/mp4",
                                key=f"dl_{reel_path.name}"
                            )
        else:
            st.info("No reels generated. Check if FFmpeg is installed and log errors.")

    # Validation
    with tab_validation:
        val = st.session_state.get("val_results", {})
        st.metric("Images Passed Validation", f"{val.get('passed', 0)} / {val.get('total', 0)}")
        if val.get("failed", 0) > 0:
            st.error(f"{val.get('failed')} images failed validation.")
            
        for res in val.get("results", []):
            color = "green" if res["status"] == "passed" else "red"
            st.markdown(f"**{Path(res['creative_path']).name}** — :{color}[{res['status'].upper()}]")
            for reason in res["reasons"]:
                st.markdown(f"- ⚠️ {reason}")

    st.divider()
    
    st.subheader("🚀 Automated Publishing")
    if st.button("Publish to Google Ads Test Account", type="primary"):
        from services.publisher import publish_to_google_ads
        
        with st.status("Connecting to Google Ads API...") as pub_status:
            copy = get_copy(project.id)
            # Create a basic dictionary payload of the generated copy and creative paths
            copy_data = copy.dict() if copy else {}
            res = st.session_state.get("pipeline_results", {})
            creative_data = {"reels": res.get("reels", []), "images": res.get("static_images", {})}
            
            pub_result = publish_to_google_ads(project.id, creative_data, copy_data)
            
            if pub_result.get("status") == "success":
                pub_status.update(label="Successfully Published!", state="complete")
                if pub_result.get("is_simulation") == "true":
                    st.warning("⚠️ **Simulation Mode**: No API Token found in `.env`.")
                st.success(f"Ad published successfully! View it here: [Google Ads Preview]({pub_result.get('preview_url')})")
            else:
                pub_status.update(label="Publishing Failed", state="error")
                st.error(pub_result.get("message"))

    st.divider()
    if st.button("Re-run Generation Pipeline", type="secondary"):
        st.session_state.stage = "generate"
        st.rerun()

    if st.button("Start Over (New Project)"):
        st.session_state.clear()
        st.rerun()


# ─────────────────────────────────────────────
# Router
# ─────────────────────────────────────────────

def main():
    st.sidebar.title("Ad Agent POC")
    st.sidebar.write(f"**Stage:** {st.session_state.stage.title()}")
    st.sidebar.write(f"**Project:** {st.session_state.project_id[:8]}")
    
    if st.session_state.stage == "intake":
        render_intake()
    elif st.session_state.stage == "confirm":
        render_confirm()
    elif st.session_state.stage == "generate":
        render_generate()
    elif st.session_state.stage == "results":
        render_results()


if __name__ == "__main__":
    main()
