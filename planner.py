"""
Scene Planner for Festive Real-Estate Video Ads
===============================================
Calculates scene breakdowns, durations, prompts, and cost estimates matching
user constraints:
  - Video duration 10–60s (default 30s)
  - End card 3s (if <=15s) or 4s (if >15s)
  - Veo clip lengths only 4, 6, or 8 seconds
  - 0.5s crossfade between adjacent scenes
  - Order: Opening exterior -> other approved renders -> lifestyle scenes
"""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple

from project_data import ProjectData, RenderInfo


# Veo pricing (per second)
VEO_PRICING = {
    "1080p": 0.12,   # $1.20 per 10 seconds
    "720p": 0.09,    # $0.90 per 10 seconds
}

FESTIVAL_DETAILS = {
    "Diwali": "lit brass diyas, colourful floor rangolis, warm fairy lights, and gentle celebratory fireworks",
    "Ugadi": "fresh mango-leaf torans at doorways, traditional rangoli, and warm festive floral decor",
    "Dussehra": "vibrant marigold garlands, traditional brass lamps, and festive door torans",
    "Ganesh Chaturthi": "small eco-friendly Ganesha idol with fresh flowers, marigold garlands, and lit lamps",
    "Onam": "intricate pookalam flower carpet, traditional brass nilavilakku lamps, and festive banana-leaf decor",
    "Pongal/Sankranti": "traditional decorated earthen pots with sugarcane stalks and vibrant floor kolam rangoli",
    "Christmas": "tastefully decorated Christmas tree, warm fairy lights, and elegant holiday decor",
    "Eid": "intricate hanging lanterns, crescent-moon lights, and elegant celebratory decor",
    "New Year": "warm golden string lights, elegant party decor, and celebratory sparkles",
    "None": "warm ambient lighting, elegant indoor greenery, and soft architectural illumination",
}


@dataclass
class PlannedScene:
    index: int
    name: str
    source_type: str                   # "render_image" or "lifestyle_text" or "end_card"
    duration_seconds: int              # 4, 6, 8 for Veo; 3 or 4 for endcard
    render_path: Optional[str] = None
    render_type: Optional[str] = None  # "exterior", "interior", "amenity"
    prompt: str = ""
    estimated_cost_usd: float = 0.0
    is_opening: bool = False


@dataclass
class AdPlan:
    requested_duration: int
    final_duration: float
    endcard_duration: int
    festival: str
    aspect: str
    resolution: str
    scenes: List[PlannedScene]
    total_veo_seconds: int
    total_estimated_cost_usd: float
    crossfade_seconds: float = 0.5

    def to_table_data(self) -> List[Dict[str, Any]]:
        rows = []
        for s in self.scenes:
            src = "End Card (Pillow/FFmpeg)" if s.source_type == "end_card" else (
                f"Render ({Path(s.render_path).name})" if s.render_path else "Lifestyle (AI Prompt)"
            )
            rows.append({
                "Scene #": s.index,
                "Scene Name": s.name,
                "Source": src,
                "Duration": f"{s.duration_seconds}s",
                "Prompt Preview": s.prompt[:80] + "..." if len(s.prompt) > 80 else (s.prompt or "—"),
                "Est. Cost": f"${s.estimated_cost_usd:.2f}",
            })
        return rows


def _solve_clip_durations(target_veo_seconds: int) -> List[int]:
    """
    Find combination of clip durations from {4, 6, 8} that best matches
    target seconds after accounting for 0.5s crossfades.
    Constraint: Each clip must be 4, 6, or 8 seconds.
    """
    allowed = [8, 6, 4]
    best_combo = [8, 8, 8]
    best_diff = 999.0

    # Try 1 to 10 clips
    for count in range(1, 11):
        def search(depth: int, current: List[int]):
            nonlocal best_combo, best_diff
            if depth == count:
                # With 'count' clips and 1 endcard, there are 'count' transitions
                overlap = count * 0.5
                effective = sum(current) - overlap
                diff = abs(effective - target_veo_seconds)
                if diff < best_diff:
                    best_diff = diff
                    best_combo = list(current)
                return

            for dur in allowed:
                current.append(dur)
                search(depth + 1, current)
                current.pop()

        search(0, [])

    return best_combo


def build_render_prompt(
    render_type: str,
    festival: str,
    aspect: str,
) -> str:
    """
    Construct exact prompt for render image-to-video conforming to Section 4.
    """
    fest_detail = FESTIVAL_DETAILS.get(festival, FESTIVAL_DETAILS["None"])

    if festival == "None":
        if render_type == "exterior":
            base = (
                "Slow cinematic drone push-in toward the residential buildings in this image, "
                "in soft golden-hour evening light. Keep the buildings EXACTLY as in the image: "
                "same number of towers, same height, same shape, same facade and colours. "
                "Do not add, remove or reshape any building. No people."
            )
        elif render_type == "interior":
            base = (
                "Slow, smooth cinematic camera glide through this room exactly as shown in the image, "
                "illuminated by warm natural daylight and soft ambient evening lamps. "
                "Keep the room layout, furniture, windows and finishes exactly as in the image."
            )
        else:  # amenity
            base = (
                "Slow cinematic camera move across this amenity exactly as shown in the image, "
                "in soft golden-hour evening light. Keep the architecture exactly as in the image."
            )
    else:
        if render_type == "exterior":
            base = (
                f"Slow cinematic drone push-in toward the residential buildings in this image, at dusk "
                f"during {festival}. Warm golden fairy lights on the balconies, a few glowing lanterns and "
                f"gentle fireworks in the distant sky. Keep the buildings EXACTLY as in the image: "
                f"same number of towers, same height, same shape, same facade and colours. "
                f"Do not add, remove or reshape any building. No people."
            )
        elif render_type == "interior":
            base = (
                f"Slow, smooth cinematic camera glide through this room exactly as shown in the image, "
                f"decorated for {festival} with {fest_detail}. "
                f"Keep the room layout, furniture, windows and finishes exactly as in the image. "
                f"Warm evening light."
            )
        else:  # amenity
            base = (
                f"Slow cinematic camera move across this amenity exactly as shown in the image, "
                f"in the evening during {festival}, with warm string lights and diyas around it. "
                f"Keep the architecture exactly as in the image."
            )

    suffix = f" No text, no captions, no subtitles, no logos, no watermarks, no signage, no readable writing anywhere. Photorealistic, cinematic, {aspect} framing."
    return base + suffix


def build_lifestyle_prompt(
    scene_key: str,
    festival: str,
    city: str,
    aspect: str,
) -> str:
    """
    Construct exact prompt for lifestyle text-to-video conforming to Section 5.
    """
    if festival in ("Christmas", "New Year"):
        person = "a graceful Indian woman in her early 30s, long black hair in a low bun, wearing elegant modern festive attire"
    elif festival == "Eid":
        person = "a graceful Indian woman in her early 30s, long black hair in a low bun, wearing an elegant emerald green and gold embroidered silk anarkali"
    else:
        person = "a graceful Indian woman in her early 30s, long black hair in a low bun with jasmine flowers, wearing an elegant maroon and gold silk saree"

    fest_name = festival if festival != "None" else "a festive celebration"

    if scene_key == "living_room":
        if festival == "None":
            base = (
                f"In a bright, modern luxury apartment living room in the evening, {person} arranges fresh jasmine and marigold "
                f"flowers beside a decorative brass bowl on a polished marble floor. Beige sofa, large windows, warm golden lights. Slow dolly-in."
            )
        else:
            base = (
                f"In a bright, modern apartment living room in the evening during {fest_name}, {person} kneels and "
                f"lights a brass diya beside a colourful marigold rangoli on a polished marble floor. Beige sofa, large windows, warm golden lights. Slow dolly-in."
            )
    elif scene_key == "kitchen":
        base = (
            f"{person} arranges flowers and decorative festive sweets on a white marble island in a modern "
            f"modular kitchen with light wooden cabinets. She smiles softly. Slow tracking shot."
        )
    elif scene_key == "balcony":
        if festival == "None":
            base = (
                f"{person} stands at floor-to-ceiling glass doors in a modern bedroom balcony, enjoying the panoramic evening "
                f"{city} skyline with glowing city lights. Camera pushes in slowly from behind her."
            )
        else:
            base = (
                f"{person} stands at floor-to-ceiling glass doors in a modern bedroom, watching colourful {fest_name} "
                f"fireworks over the {city} skyline at night. Camera pushes in slowly from behind her."
            )
    elif scene_key == "family":
        base = (
            f"A happy Indian family of four in festive clothes shares sweets in a bright modern luxury apartment "
            f"living room decorated for {fest_name}. Warm, joyful atmosphere. Slow pan."
        )
    else:
        base = f"Cinematic scene in a luxury home during {fest_name} with {person}."

    suffix = f" No text, no captions, no subtitles, no logos, no watermarks, no signage, no readable writing anywhere. Photorealistic, cinematic, {aspect} framing."
    return base + suffix


def plan_video_ad(
    project: ProjectData,
    renders: List[RenderInfo],
    requested_duration: int = 30,
    festival: str = "Diwali",
    aspect: str = "16:9",
    resolution: str = "1080p",
) -> AdPlan:
    """
    Generate an optimal scene-by-scene plan for the video ad.
    """
    # Enforce duration bounds [10, 60]
    total_dur = max(10, min(60, int(requested_duration)))

    # Endcard: 3s if <=15s, 4s if >15s
    endcard_dur = 3 if total_dur <= 15 else 4
    crossfade = 0.5

    # Target duration needed from Veo clips:
    # Final = sum(clips) + endcard - (num_clips * crossfade)
    # Target sum(clips) - (num_clips * crossfade) = total_dur - endcard
    target_veo_time = total_dur - endcard_dur

    clip_durations = _solve_clip_durations(target_veo_time)
    num_clips = len(clip_durations)

    # Filter approved renders
    approved = [r for r in renders if r.approved]

    # Prioritize exterior for opening
    exteriors = [r for r in approved if r.render_type == "exterior"]
    interiors = [r for r in approved if r.render_type == "interior"]
    amenities = [r for r in approved if r.render_type == "amenity"]
    others = [r for r in approved if r.render_type not in ("exterior", "interior", "amenity")]

    ordered_renders: List[RenderInfo] = []
    if exteriors:
        ordered_renders.append(exteriors[0])
        ordered_renders.extend(interiors)
        ordered_renders.extend(amenities)
        ordered_renders.extend(exteriors[1:])
        ordered_renders.extend(others)
    else:
        ordered_renders.extend(approved)

    lifestyle_keys = ["living_room", "kitchen", "balcony", "family"]
    lifestyle_idx = 0

    scenes: List[PlannedScene] = []
    price_per_sec = VEO_PRICING.get(resolution, 0.12)
    total_veo_secs = sum(clip_durations)

    for i, dur in enumerate(clip_durations, 1):
        if i <= len(ordered_renders):
            # Render scene (image-to-video)
            r = ordered_renders[i - 1]
            p_text = build_render_prompt(r.render_type, festival, aspect)
            s_name = f"Opening: {r.render_type.title()} Drone Shot" if i == 1 else f"Property Tour: {r.render_type.title()} View"
            scenes.append(PlannedScene(
                index=i,
                name=s_name,
                source_type="render_image",
                duration_seconds=dur,
                render_path=r.filepath,
                render_type=r.render_type,
                prompt=p_text,
                estimated_cost_usd=dur * price_per_sec,
                is_opening=(i == 1),
            ))
        else:
            # Lifestyle scene (text-to-video)
            l_key = lifestyle_keys[lifestyle_idx % len(lifestyle_keys)]
            lifestyle_idx += 1
            p_text = build_lifestyle_prompt(l_key, festival, project.city, aspect)
            scenes.append(PlannedScene(
                index=i,
                name=f"Lifestyle: {l_key.replace('_', ' ').title()}",
                source_type="lifestyle_text",
                duration_seconds=dur,
                render_path=None,
                render_type=None,
                prompt=p_text,
                estimated_cost_usd=dur * price_per_sec,
                is_opening=False,
            ))

    # Add End Card
    end_idx = len(scenes) + 1
    scenes.append(PlannedScene(
        index=end_idx,
        name=f"End Card: Brand & Offer ({project.name})",
        source_type="end_card",
        duration_seconds=endcard_dur,
        render_path=None,
        render_type=None,
        prompt="Static brand card with logo, pricing, project details, and festive wishes",
        estimated_cost_usd=0.0,
        is_opening=False,
    ))

    # Final length after crossfades:
    # num_clips transitions between clips + 1 transition into end card = num_clips total transitions
    final_length = sum(clip_durations) + endcard_dur - (len(clip_durations) * crossfade)
    total_cost = sum(s.estimated_cost_usd for s in scenes)

    return AdPlan(
        requested_duration=total_dur,
        final_duration=final_length,
        endcard_duration=endcard_dur,
        festival=festival,
        aspect=aspect,
        resolution=resolution,
        scenes=scenes,
        total_veo_seconds=total_veo_secs,
        total_estimated_cost_usd=total_cost,
        crossfade_seconds=crossfade,
    )
