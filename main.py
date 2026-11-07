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
from planner import AdPlan, fmt_seconds, plan_all_versions, plan_video_ad, plan_with_agent, validate_plan
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
                        description=it.get("description", ""),
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
    parser.add_argument("--duration", type=str, default="30",
                        help="Video length in seconds (10–60, default 30), or 'all' for 60 s + 20 s + 10 s from shared clips")
    parser.add_argument("--agent", action="store_true",
                        help="Plan scenes with the Gemini scene agent (validated; falls back to the rule engine)")
    parser.add_argument("--plan-json", type=str, default=None, help="Write the scene plan JSON to this path")
    parser.add_argument(
        "--festival",
        type=str,
        default="Diwali",
        choices=[
            "Diwali", "Ugadi", "Dussehra", "Ganesh Chaturthi", "Onam",
            "Pongal/Sankranti", "Christmas", "Eid", "New Year", "None", "Family"
        ],
        help="Festival celebration theme (None for regular ad)"
    )
    parser.add_argument("--aspect", type=str, default="16:9", choices=["16:9", "9:16"], help="Aspect ratio")
    parser.add_argument("--resolution", type=str, default="1080p", choices=["720p", "1080p"], help="Video resolution")
    parser.add_argument("--project", type=str, required=True, help="Path to project details JSON")
    parser.add_argument("--logo", type=str, default=None, help="Path to developer logo PNG (optional; name is shown instead)")
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
            print("  ⚠️ Notice: Project status is unverified – confirm the facts before publishing.")
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
    all_mode = str(args.duration).lower() == "all"
    duration = 60 if all_mode else int(args.duration)
    logo_ok = bool(args.logo and Path(args.logo).exists())
    user_script = None
    if args.script:
        user_script = Path(args.script).read_text(encoding="utf-8").strip() if Path(args.script).is_file() else args.script.strip()
        if all_mode:
            print("  ⚠️ --script is ignored in 'all' mode (each length gets its own voiceover).")
            user_script = None

    print(f"\n[3/6] Planning scenes for {'60 s + 20 s + 10 s' if all_mode else f'{duration}s'} "
          f"({args.festival}, {args.aspect}, {args.resolution})...")
    base = None
    if args.agent:
        base = plan_with_agent(project, approved_renders, duration, args.festival, args.aspect, args.resolution,
                               script=user_script, logo_available=logo_ok)
    if all_mode:
        versions = plan_all_versions(project, approved_renders, args.festival, args.aspect, args.resolution,
                                     logo_available=logo_ok, base_plan=base)
    else:
        versions = [base or plan_video_ad(project, approved_renders, duration, args.festival, args.aspect,
                                          args.resolution, script=user_script, logo_available=logo_ok)]

    if versions[0].blocked:
        print(f"\n⛔ BLOCKED: {versions[0].blocked_reason}")
        sys.exit(2)

    for plan in versions:
        print("\n" + "-" * 90)
        print(f"{plan.requested_duration}s version – case {plan.case} – planner: {plan.planner}")
        print("-" * 90)
        for s in plan.scenes:
            reuse = f" ↺60s#{s.reuses_scene_id}" if s.reuses_scene_id else ""
            print(f"  {s.index:<3} {s.name[:52]:<52} {fmt_seconds(s.duration_seconds):<6} {s.label or '':<22}{reuse}")
            if s.voiceover:
                print(f"        🎙️ {s.voiceover}")
        print(f"  End card: {' | '.join(plan.end_card.get('lines', []))}")
        print(f"  New Veo seconds: {plan.total_veo_seconds}s | Est. cost: ${plan.total_estimated_cost_usd:.2f} "
              f"| Voiceover: {plan.voiceover_word_count} words")
        for w in plan.warnings:
            print(f"  ⚠️ {w}")
        for e in validate_plan(plan, approved_renders):
            print(f"  ❌ Rule check: {e}")
    if args.plan_json:
        out = [v.to_dict() for v in versions]
        Path(args.plan_json).write_text(json.dumps({"versions": out} if all_mode else out[0], indent=2, ensure_ascii=False))
        print(f"\n  ✓ Scene plan JSON written to {args.plan_json}")

    if args.dry_run:
        print("\n🧪 [DRY RUN ACTIVE] Running assembly with simulation mode (no API charges)...")

    veo = VeoClient(dry_run=args.dry_run)
    cache_dir = Path("./cache")
    cache_dir.mkdir(parents=True, exist_ok=True)
    clean_pname = project.name.replace(" ", "_").lower()
    clean_fest = args.festival.replace("/", "_").lower()
    clean_aspect = args.aspect.replace(":", "_")

    for plan in versions:
        dur = plan.requested_duration
        # 4. Veo clips (cached by prompt + render + length, so shorter versions reuse the 60 s clips)
        print(f"\n[4/6] {dur}s: producing video scenes (Veo 3.1 Fast / Simulation)...")
        clip_files = []
        for s in plan.veo_scenes:
            dest = cache_dir / f"scene_{dur}s_{s.index}_{s.veo_duration}s_{clean_aspect}.mp4"
            clip_files.append(veo.generate_clip(
                prompt=s.prompt, duration=s.veo_duration, aspect=args.aspect,
                resolution=args.resolution, image_path=s.render_path, output_dest=dest,
            ))
            print(f"    ✓ Scene {s.index} ({s.veo_mode}) ready")

        # 5. End card, voiceover, music
        print(f"[5/6] {dur}s: end card, voiceover and music...")
        endcard_dest = cache_dir / f"endcard_{dur}s.mp4"
        create_endcard_clip(project=project, duration=plan.endcard_duration, logo_path=args.logo,
                            festival=args.festival, aspect=args.aspect, resolution=args.resolution,
                            output_path=endcard_dest, card=plan.end_card)
        voiceover_dest = None
        if not args.no_voiceover and plan.voiceover_script:
            voiceover_dest = cache_dir / f"voiceover_{dur}s.mp3"
            try:
                generate_indian_voiceover(script_text=plan.voiceover_script, output_path=voiceover_dest)
            except Exception as e:
                print(f"  ⚠️ Voiceover generation warning: {e}. Falling back to music only.")
                voiceover_dest = None
        music_dest = cache_dir / f"music_{dur}s.mp3"
        build_music_track(duration=dur, festival=args.festival, uploaded_music_path=args.music,
                          output_path=music_dest, music_prompt=plan.music_prompt)

        # 6. Stitch & overlays
        if args.output and not all_mode:
            final_output = Path(args.output)
        else:
            final_output = Path(f"output/{clean_pname}_{clean_fest}_{dur}s_{clean_aspect}.mp4")
        print(f"[6/6] {dur}s: stitching, labels, RERA bar -> {final_output}...")
        out_file, checks = assemble_final_video(
            plan=plan, project=project, clip_paths=clip_files, endcard_path=endcard_dest,
            music_path=music_dest, output_path=final_output, voiceover_path=voiceover_dest,
        )
        print(f"  🎉 {out_file.resolve()}")
        print(f"     Duration {checks['actual_duration']}s (requested {dur}s: "
              f"{'✓ PASS' if checks['duration_passed'] else '⚠️'}) | RERA frames: {checks['frames_checked']} "
              f"| Est. cost ${plan.total_estimated_cost_usd:.2f}")


if __name__ == "__main__":
    main()
