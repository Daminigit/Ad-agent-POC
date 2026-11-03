"""
Festive Real-Estate Video Ad Generator — CLI Interface
======================================================
Usage:
  python main.py --duration 30 --festival Diwali --aspect 16:9 --resolution 1080p \\
    --project inputs/project.json --logo inputs/logo.png --renders inputs/renders/ \\
    [--music inputs/music.mp3] [--dry-run]
"""

from __future__ import annotations

import argparse
import json
import os
import sys
from pathlib import Path
from typing import List

from dotenv import load_dotenv

from project_data import ProjectData, RenderInfo, filter_approved_renders, parse_project_json
from planner import AdPlan, plan_video_ad
from veo_client import VeoClient
from music import build_music_track
from endcard import create_endcard_clip
from overlays import assemble_final_video
from script_writer import generate_script_options
from voiceover import generate_indian_voiceover

load_dotenv()


def load_renders_from_dir(renders_dir: Path) -> List[RenderInfo]:
    """
    Load renders and annotations from directory or renders.json.
    """
    renders: List[RenderInfo] = []
    manifest_path = renders_dir / "renders.json"

    if manifest_path.exists():
        try:
            items = json.loads(manifest_path.read_text(encoding="utf-8"))
            for it in items:
                fpath = renders_dir / it.get("file", "")
                if fpath.exists():
                    renders.append(RenderInfo(
                        filepath=str(fpath),
                        render_type=it.get("type", "exterior"),
                        approved=it.get("approved", True),
                        needs_review=it.get("needs_review", False),
                    ))
            return renders
        except Exception as e:
            print(f"[Warning] Could not parse renders.json ({e}). Falling back to file scan.")

    # Fallback: Scan directory for common image extensions
    valid_exts = {".png", ".jpg", ".jpeg", ".webp"}
    for p in sorted(renders_dir.iterdir()):
        if p.suffix.lower() in valid_exts and p.name != "renders.json":
            stem_lower = p.stem.lower()
            rtype = "exterior"
            if "interior" in stem_lower or "bedroom" in stem_lower or "living" in stem_lower or "room" in stem_lower:
                rtype = "interior"
            elif "amenity" in stem_lower or "pool" in stem_lower or "gym" in stem_lower or "club" in stem_lower:
                rtype = "amenity"

            renders.append(RenderInfo(
                filepath=str(p),
                render_type=rtype,
                approved=True,
            ))

    return renders


def main():
    parser = argparse.ArgumentParser(
        description="Generate festive real-estate video ads using Google Gemini Veo 3.1 Fast, Pillow, and FFmpeg."
    )
    parser.add_argument("--duration", type=int, default=30, help="Video length in seconds (10–60, default 30)")
    parser.add_argument(
        "--festival",
        type=str,
        default="Diwali",
        choices=[
            "Diwali", "Ugadi", "Dussehra", "Ganesh Chaturthi", "Onam",
            "Pongal/Sankranti", "Christmas", "Eid", "New Year", "None"
        ],
        help="Festival celebration theme (None for regular ad)"
    )
    parser.add_argument("--aspect", type=str, default="16:9", choices=["16:9", "9:16"], help="Aspect ratio")
    parser.add_argument("--resolution", type=str, default="1080p", choices=["720p", "1080p"], help="Video resolution")
    parser.add_argument("--project", type=str, required=True, help="Path to project details JSON")
    parser.add_argument("--logo", type=str, required=True, help="Path to developer logo PNG")
    parser.add_argument("--renders", type=str, required=True, help="Directory containing render images")
    parser.add_argument("--music", type=str, default=None, help="Optional user-supplied background music audio file")
    parser.add_argument("--script", type=str, default=None, help="Custom voiceover script text or path to a .txt file")
    parser.add_argument("--no-voiceover", action="store_true", help="Disable voiceover and generate music-only ad")
    parser.add_argument("--dry-run", action="store_true", help="Preview plan and test assembly without making paid API calls")
    parser.add_argument("--output", type=str, default=None, help="Custom output filepath")

    args = parser.parse_args()

    print("\n" + "=" * 65)
    print("🎬 FESTIVE REAL-ESTATE VIDEO AD GENERATOR (Veo 3.1 Fast)")
    print("=" * 65)

    # 1. Parse Project Data & Validate RERA
    print(f"\n[1/6] Loading project details: {args.project}...")
    try:
        project = parse_project_json(args.project)
        print(f"  ✓ Project Name:   {project.name}")
        print(f"  ✓ Promoter:       {project.promoter}")
        print(f"  ✓ Location:       {project.marketing_name}, {project.city}")
        print(f"  ✓ RERA Number:    {project.rera_number}")
        print(f"  ✓ Units & Price:  {project.formatted_units_summary} from {project.formatted_lowest_price}")
        if not project.is_verified:
            print("  ⚠️ Notice: Project status is unverified. 'DRAFT - NOT FOR PUBLICATION' watermark will be applied.")
    except Exception as e:
        print(f"\n❌ Validation Error: {e}")
        sys.exit(1)

    # 2. Load Renders
    renders_dir = Path(args.renders)
    if not renders_dir.exists():
        print(f"\n❌ Error: Renders directory '{renders_dir}' does not exist.")
        sys.exit(1)

    all_renders = load_renders_from_dir(renders_dir)
    approved_renders = filter_approved_renders(all_renders, project.raw_data.get("review"))
    print(f"\n[2/6] Found {len(all_renders)} render(s), {len(approved_renders)} approved for ad production.")
    for r in approved_renders:
        print(f"  - [{r.render_type.upper()}] {Path(r.filepath).name}")

    # 3. Build Scene Plan & Cost Preview
    print(f"\n[3/6] Generating scene plan for {args.duration}s ({args.festival}, {args.aspect}, {args.resolution})...")
    plan = plan_video_ad(
        project=project,
        renders=approved_renders,
        requested_duration=args.duration,
        festival=args.festival,
        aspect=args.aspect,
        resolution=args.resolution,
    )

    print("\n" + "-" * 75)
    print(f"{'Scene':<8} {'Type':<18} {'Sec':<6} {'Est. Cost':<12} {'Prompt Summary'}")
    print("-" * 75)
    for s in plan.scenes:
        stype = "End Card" if s.source_type == "end_card" else ("Render (I2V)" if s.render_path else "Lifestyle (T2V)")
        print(f"{s.index:<8} {stype:<18} {str(s.duration_seconds)+'s':<6} {f'${s.estimated_cost_usd:.2f}':<12} {s.prompt[:35]}...")
    print("-" * 75)
    print(f"Total AI Video Seconds: {plan.total_veo_seconds}s  |  Total Estimated Cost: ${plan.total_estimated_cost_usd:.2f}")
    print(f"End Card Duration:      {plan.endcard_duration}s  |  Target Final Length:   {plan.final_duration:.1f}s")
    print("-" * 75)

    if args.dry_run:
        print("\n🧪 [DRY RUN ACTIVE] Running assembly with simulation mode (no API charges)...")

    # 4. Generate Veo Clips
    print("\n[4/6] Producing video scenes (Veo 3.1 Fast / Simulation)...")
    veo = VeoClient(dry_run=args.dry_run)
    clip_files = []
    cache_dir = Path("./cache")
    cache_dir.mkdir(parents=True, exist_ok=True)

    for s in plan.scenes:
        if s.source_type == "end_card":
            continue
        print(f"  → Generating Scene {s.index} ({s.duration_seconds}s) [{s.name}]...")
        dest = cache_dir / f"scene_{s.index}_{s.duration_seconds}s_{args.aspect.replace(':', '_')}.mp4"
        clip_path = veo.generate_clip(
            prompt=s.prompt,
            duration=s.duration_seconds,
            aspect=args.aspect,
            resolution=args.resolution,
            image_path=s.render_path,
            output_dest=dest,
        )
        clip_files.append(clip_path)
        print(f"    ✓ Scene {s.index} ready: {clip_path.name}")

    # 5. Build End Card, Voiceover, and Music
    print("\n[5/6] Building brand End Card, Indian-English voiceover, and background music...")
    endcard_dest = cache_dir / f"endcard_{args.duration}s.mp4"
    create_endcard_clip(
        project=project,
        duration=plan.endcard_duration,
        logo_path=args.logo,
        festival=args.festival,
        aspect=args.aspect,
        resolution=args.resolution,
        output_path=endcard_dest,
    )
    print(f"  ✓ End Card rendered ({plan.endcard_duration}s)")

    # Voiceover handling
    voiceover_dest = None
    if not args.no_voiceover:
        if args.script:
            if Path(args.script).is_file():
                chosen_script = Path(args.script).read_text(encoding="utf-8").strip()
            else:
                chosen_script = args.script.strip()
            print(f"  ✓ Using provided custom script ({len(chosen_script.split())} words)")
        else:
            print("  ✨ Generating 3 script options with Gemini...")
            options = generate_script_options(
                project=project,
                festival=args.festival,
                duration=args.duration,
            )
            for idx, opt in enumerate(options):
                print(f"    [{idx+1}] {opt.title} ({opt.tone}) — {opt.word_count} words")
            chosen_script = options[0].text
            print(f"  ✓ Selected Option 1 (Recommended): \"{chosen_script}\"")

        voiceover_dest = cache_dir / f"voiceover_{args.duration}s.mp3"
        print("  🎙️ Synthesizing Indian-English voiceover (en-IN)...")
        try:
            generate_indian_voiceover(
                script_text=chosen_script,
                output_path=voiceover_dest,
            )
            print(f"  ✓ Voiceover audio track ready ({voiceover_dest.name})")
        except Exception as e:
            print(f"  ⚠️ Voiceover generation warning: {e}. Falling back to instrumental music only.")
            voiceover_dest = None

    music_dest = cache_dir / f"music_{args.duration}s.mp3"
    build_music_track(
        duration=args.duration,
        festival=args.festival,
        uploaded_music_path=args.music,
        output_path=music_dest,
    )
    print(f"  ✓ Music track composed ({args.duration}s, 1s fade-in, 2s fade-out)")

    # 6. Final Video Stitching & Overlays
    clean_pname = project.name.replace(" ", "_").lower()
    clean_fest = args.festival.replace("/", "_").lower()
    clean_aspect = args.aspect.replace(":", "_")
    final_output = Path(args.output or f"output/{clean_pname}_{clean_fest}_{args.duration}s_{clean_aspect}.mp4")

    print(f"\n[6/6] Stitching crossfades, ducking music under voiceover, burning RERA bar -> {final_output}...")
    out_file, checks = assemble_final_video(
        plan=plan,
        project=project,
        clip_paths=clip_files,
        endcard_path=endcard_dest,
        music_path=music_dest,
        output_path=final_output,
        voiceover_path=voiceover_dest,
    )

    print("\n" + "=" * 65)
    print("🎉 VIDEO EXPORT COMPLETE & VERIFIED!")
    print("=" * 65)
    print(f"  • Output File:       {out_file.resolve()}")
    print(f"  • Video Duration:    {checks['actual_duration']}s (Requested: {args.duration}s | Status: {'✓ PASS' if checks['duration_passed'] else '⚠️'})")
    print(f"  • Audio Track:       {'Indian-English Voiceover + Ducked Festive Music' if voiceover_dest else 'Festive Instrumental Music'}")
    print(f"  • RERA Bar Check:    {'✓ Present on every frame' if checks['rera_bar_verified'] else '⚠️ Verification warning'}")
    print(f"  • Frames Inspected:  {checks['frames_checked']} frames verified")
    print(f"  • Estimated Cost:    ${plan.total_estimated_cost_usd:.2f}")
    print("=" * 65 + "\n")


if __name__ == "__main__":
    main()
