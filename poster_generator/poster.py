"""
Poster Generator — Command Line Interface
=========================================
Usage:
  python poster.py --project inputs/project.json --logo inputs/logo.png \
    --render inputs/renders/tower_exterior.png --festival Diwali \
    [--headline "..."] [--dry-run]
"""

from __future__ import annotations

import argparse
import sys
from pathlib import Path

from config import IMAGE_PRICE_USD, SIZES
from project_data import parse_project_json
from background import generate_festive_background, build_background_prompt
from headlines import generate_headlines
from layout import render_poster
from checks import verify_poster


def main():
    parser = argparse.ArgumentParser(
        description="Festive Real-Estate Poster Generator using Google Gemini Nano Banana & Pillow."
    )
    parser.add_argument("--project", type=str, required=True, help="Path to project JSON details file")
    parser.add_argument("--logo", type=str, required=True, help="Path to brand logo PNG")
    parser.add_argument("--render", type=str, required=True, help="Path to chosen architectural render image")
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
    parser.add_argument("--headline", type=str, default=None, help="Custom headline (max 8 words)")
    parser.add_argument("--dry-run", action="store_true", help="Preview prompts and estimated cost without paid API calls")
    parser.add_argument("--output-dir", type=str, default="output/posters", help="Directory to save final posters")

    args = parser.parse_args()

    print("\n" + "=" * 65)
    print("🎨 FESTIVE POSTER GENERATOR (Nano Banana + Pillow Engine)")
    print("=" * 65)

    # 1. Parse Project Data & Validate Strict RERA
    print(f"\n[1/5] Loading and validating project: {args.project}...")
    try:
        project = parse_project_json(args.project)
        print(f"  ✓ Project:      {project.name}")
        print(f"  ✓ Promoter:     {project.promoter}")
        print(f"  ✓ Location:     {project.marketing_name}, {project.city}")
        print(f"  ✓ RERA No:      {project.rera_number}")
        print(f"  ✓ Units/Price:  {project.formatted_units_summary} from {project.formatted_lowest_price}")
        if not project.is_verified:
            print("  ⚠️ Project is UNVERIFIED — confirm the facts before publishing.")
        else:
            print("  ✓ Status:       VERIFIED (Clean broadcast output)")
    except Exception as exc:
        print(f"\n❌ Error validating project: {exc}")
        sys.exit(1)

    # 2. Preview Cost
    print("\n[2/5] Cost & Generation Preview:")
    enabled_sizes = [s for s in SIZES.values() if s["enabled"]]
    total_images = len(enabled_sizes)
    est_cost = total_images * IMAGE_PRICE_USD

    print(f"  • Formats to Generate: {len(enabled_sizes)} sizes")
    for s in enabled_sizes:
        print(f"    - {s['name']}: {s['width']}x{s['height']} ({s['aspect_ratio']})")
    print(f"  • AI Image Model:      Google Gemini Nano Banana (gemini-2.5-flash-image)")
    print(f"  • Estimated Cost:      ${est_cost:.2f} USD ({total_images} images @ ${IMAGE_PRICE_USD:.2f})")

    if args.dry_run:
        print("\n🧪 [DRY RUN ACTIVE] Simulation mode — no paid API calls will be made.")
        print("\nGenerated Prompt for Nano Banana:")
        print(f'"{build_background_prompt(args.festival)}"')

    # 3. Headlines
    print("\n[3/5] Generating headline ideas...")
    if args.headline:
        chosen_headline = args.headline.strip()
        print(f"  ✓ Using custom headline: \"{chosen_headline}\"")
    else:
        ideas = generate_headlines(project, args.festival)
        print("  Gemini Headline Options:")
        for idx, h in enumerate(ideas, 1):
            print(f"    [{idx}] \"{h}\"")
        chosen_headline = ideas[0]
        print(f"  ✓ Selected Option 1: \"{chosen_headline}\"")

    # 4. Generate Backgrounds
    print("\n[4/5] Generating festive backgrounds via Nano Banana...")
    cache_dir = Path("cache")
    cache_dir.mkdir(parents=True, exist_ok=True)
    generated_backgrounds = {}

    for s in enabled_sizes:
        sid = s["id"]
        bg_dest = cache_dir / f"bg_{sid}_{args.festival.lower()}.png"
        print(f"  → Generating background for {s['name']} ({s['width']}x{s['height']})...")
        bg_path = generate_festive_background(
            render_path=args.render,
            festival=args.festival,
            width=s["width"],
            height=s["height"],
            aspect_ratio=s["aspect_ratio"],
            output_path=bg_dest,
            cache_dir=cache_dir,
            dry_run=args.dry_run,
        )
        generated_backgrounds[sid] = bg_path
        print(f"    ✓ Ready: {bg_path.resolve()}")

    # Step 2 Approval Check in CLI
    print("\n" + "-" * 65)
    print("🔍 STEP 2: BACKGROUND APPROVAL CHECK")
    print("⚠️  WARNING: Check the building is unchanged (number of towers, shape, facade) before approving.")
    print("-" * 65)
    for idx, (sid, p) in enumerate(generated_backgrounds.items(), 1):
        print(f"  [{idx}] {SIZES[sid]['name']} Background: {p.name}")

    if not args.dry_run and sys.stdin.isatty():
        try:
            choice = input("\nType 'yes' or press Enter to approve and continue [Y/n]: ").strip().lower()
            if choice in ("n", "no"):
                print("Generation cancelled by user.")
                sys.exit(0)
        except (EOFError, KeyboardInterrupt):
            pass

    # 5. Composite Text & Logo (Pillow)
    print("\n[5/5] Compositing layout, typography & RERA disclosure (Pillow)...")
    out_dir = Path(args.output_dir)
    out_dir.mkdir(parents=True, exist_ok=True)

    clean_pname = project.name.replace(" ", "_").lower()
    clean_fest = args.festival.replace("/", "_").lower()

    output_files = []

    for sid in ("instagram_post", "story"):
        s_cfg = SIZES[sid]
        bg_file = generated_backgrounds[sid]
        out_filename = f"{clean_pname}_{clean_fest}_{'instagram' if sid == 'instagram_post' else 'story'}.png"
        final_dest = out_dir / out_filename

        rendered_img = render_poster(
            background_path=bg_file,
            project=project,
            logo_path=args.logo,
            headline=chosen_headline,
            festival=args.festival,
            size_id=sid,
            output_path=final_dest,
        )

        checks = verify_poster(rendered_img, project, s_cfg["width"], s_cfg["height"])
        output_files.append((final_dest, s_cfg, checks))
        print(f"  ✓ {s_cfg['name']} created: {final_dest.name}")

    print("\n" + "=" * 65)
    print("🎉 POSTER GENERATION COMPLETE & VERIFIED!")
    print("=" * 65)
    for p_path, s_cfg, checks in output_files:
        status_icon = "✓ PASS" if checks["all_passed"] else "⚠️ FLAGGED"
        print(f"  • {s_cfg['name']} ({s_cfg['width']}x{s_cfg['height']}):")
        print(f"    - Path:        {p_path.resolve()}")
        print(f"    - RERA Status: {'✓ Valid on poster' if checks['rera_present'] else '❌ Missing'}")
        print(f"    - WCAG AA:     {'✓ Passed' if checks['wcag_aa_passed'] else '⚠️ Review contrast'}")
        print(f"    - Overall:     {status_icon}")
    print("=" * 65 + "\n")


if __name__ == "__main__":
    main()
