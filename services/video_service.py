"""
Unified Video Service
=====================
Modular abstraction layer supporting:
  1. Wan 2.6 Flash (fal.ai) - Fast 1080p B-roll and render animation
  2. Veo 3.1 Fast (Google Gemini Veo) - Cinematic 1080p clips with physics & audio
  3. HeyGen API (Avatar IV) - AI Presenter / Spokesperson with lip sync

Provides unified interface for generating video clips across providers with
consistent logging, fallback, API key checks, and output tracking.
"""

from __future__ import annotations

import abc
import base64
import json
import os
import time
import urllib.request
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple

import requests
import yaml
from dotenv import load_dotenv

load_dotenv()

OUTPUT_ROOT = Path(os.getenv("OUTPUT_ROOT", "outputs"))


# ─────────────────────────────────────────────
# Data Structures
# ─────────────────────────────────────────────

@dataclass
class VideoJobRequest:
    project_id: str
    aspect: str = "9:16"                     # e.g. "9:16", "16:9", "1:1"
    duration: int = 10                       # in seconds (e.g. 5, 8, 10, 15)
    quality: str = "1080p"                   # "720p", "1080p"
    prompt: Optional[str] = None             # Motion / cinematic prompt
    image_bytes: Optional[bytes] = None      # Conditioning image / render
    script_text: Optional[str] = None        # Script for voice / avatar
    options: Dict[str, Any] = field(default_factory=dict)


@dataclass
class VideoJobResponse:
    success: bool
    video_path: Optional[str] = None
    provider: str = ""
    model_used: str = ""
    duration: int = 0
    error: Optional[str] = None
    metadata: Dict[str, Any] = field(default_factory=dict)


@dataclass
class ProviderStatus:
    provider_id: str
    display_name: str
    api_key_env: str
    configured: bool
    description: str
    cost_info: str
    supported_durations: str


# ─────────────────────────────────────────────
# Base Engine
# ─────────────────────────────────────────────

class BaseVideoEngine(abc.ABC):
    def __init__(self, config: Dict[str, Any]):
        self.config = config

    @abc.abstractmethod
    def is_configured(self) -> bool:
        """Return True if required API keys / environment variables exist."""
        pass

    @abc.abstractmethod
    def generate(self, request: VideoJobRequest) -> VideoJobResponse:
        """Execute video generation and save to project output directory."""
        pass

    def _prepare_output_path(self, project_id: str, prefix: str, aspect: str, duration: int) -> Path:
        out_dir = OUTPUT_ROOT / project_id / "clips"
        out_dir.mkdir(parents=True, exist_ok=True)
        aspect_tag = aspect.replace(":", "_")
        return out_dir / f"{prefix}_{aspect_tag}_{duration}s.mp4"

    def _download_url(self, url: str, dest_path: Path) -> None:
        response = requests.get(url, stream=True, timeout=120)
        response.raise_for_status()
        with open(dest_path, "wb") as f:
            for chunk in response.iter_content(chunk_size=65536):
                f.write(chunk)


# ─────────────────────────────────────────────
# Engine 1: Wan 2.6 Flash (fal.ai)
# ─────────────────────────────────────────────

class WanFlashEngine(BaseVideoEngine):
    """
    Wan 2.6 Flash via fal.ai.
    Cheapest 1080p video clip generator, great for animating architectural
    renders, B-roll, and product shots.
    """

    def is_configured(self) -> bool:
        key = os.getenv("FAL_KEY", "").strip()
        return bool(key and key != "your_fal_api_key_here")

    def generate(self, request: VideoJobRequest) -> VideoJobResponse:
        if not self.is_configured():
            return VideoJobResponse(
                success=False,
                provider="wan_flash",
                error="FAL_KEY is not set or invalid in .env",
            )

        try:
            import fal_client
        except ImportError:
            return VideoJobResponse(
                success=False,
                provider="wan_flash",
                error="fal_client is not installed. Run `pip install fal-client`.",
            )

        model = self.config.get("model", "fal-ai/wan-2.6/image-to-video")
        fallback_models = self.config.get(
            "fallback_models",
            ["fal-ai/wan-2.6-flash", "fal-ai/wan/v2.2/image-to-video", "fal-ai/wan/v2.1/image-to-video"]
        )

        prompt = request.prompt or self.config.get(
            "prompt",
            "gentle slow zoom, drifting clouds, cinematic real estate, smooth motion, 1080p"
        )
        motion_strength = float(request.options.get("motion_strength", self.config.get("motion_strength", 0.4)))
        resolution = request.quality if request.quality in ("720p", "1080p") else "1080p"

        # Image conditioning
        if not request.image_bytes:
            return VideoJobResponse(
                success=False,
                provider="wan_flash",
                error="Wan 2.6 Flash image-to-video requires render/image bytes.",
            )

        b64 = base64.b64encode(request.image_bytes).decode("utf-8")
        data_uri = f"data:image/jpeg;base64,{b64}"

        out_path = self._prepare_output_path(
            project_id=request.project_id,
            prefix="wan_flash",
            aspect=request.aspect,
            duration=request.duration,
        )

        models_to_try = [model] + [m for m in fallback_models if m != model]
        last_error = None
        used_model = model

        for target_model in models_to_try:
            try:
                result = fal_client.subscribe(
                    target_model,
                    arguments={
                        "image_url": data_uri,
                        "prompt": prompt,
                        "duration": min(request.duration, 10),
                        "motion_strength": motion_strength,
                        "aspect_ratio": request.aspect,
                        "resolution": resolution,
                    },
                )
                video_url = (
                    result.get("video", {}).get("url")
                    or result.get("video_url")
                    or result.get("url")
                )
                if not video_url:
                    raise RuntimeError(f"No video URL in fal.ai result: {result}")

                self._download_url(video_url, out_path)
                used_model = target_model
                return VideoJobResponse(
                    success=True,
                    video_path=str(out_path),
                    provider="wan_flash",
                    model_used=used_model,
                    duration=min(request.duration, 10),
                    metadata={"result": result, "resolution": resolution},
                )
            except Exception as e:
                last_error = str(e)
                # If model is unavailable or 404, continue to next fallback model
                continue

        return VideoJobResponse(
            success=False,
            provider="wan_flash",
            model_used=model,
            error=f"Wan 2.6 Flash execution failed across candidates {models_to_try}: {last_error}",
        )


# ─────────────────────────────────────────────
# Engine 2: Veo 3.1 Fast (Google Gemini Veo)
# ─────────────────────────────────────────────

class VeoFastEngine(BaseVideoEngine):
    """
    Veo 3.1 Fast via Google Gemini Video Generation API.
    Produces high-fidelity 1080p clips (4, 6, or 8s) with native lighting,
    physics, sound effects, voice, and background music in one go.
    """

    def is_configured(self) -> bool:
        key = (
            os.getenv("GEMINI_API_KEY")
            or os.getenv("GOOGLE_API_KEY")
            or os.getenv("GOOGLE_GENAI_API_KEY")
            or ""
        ).strip()
        return bool(key and not key.startswith("your_"))

    def _get_api_key(self) -> str:
        return (
            os.getenv("GEMINI_API_KEY")
            or os.getenv("GOOGLE_API_KEY")
            or os.getenv("GOOGLE_GENAI_API_KEY")
            or ""
        ).strip()

    def generate(self, request: VideoJobRequest) -> VideoJobResponse:
        if not self.is_configured():
            return VideoJobResponse(
                success=False,
                provider="veo_fast",
                error="GEMINI_API_KEY or GOOGLE_API_KEY is not set in .env",
            )

        api_key = self._get_api_key()
        model = self.config.get("model", "veo-3.1-fast")
        fallback_models = self.config.get(
            "fallback_models",
            ["veo-2.0-generate-001", "veo-3.1-generate-preview"]
        )

        # Veo supports 4, 6, 8 second clips
        duration = 8
        if request.duration in (4, 6, 8):
            duration = request.duration
        elif request.duration < 6:
            duration = 4
        elif request.duration <= 7:
            duration = 6
        else:
            duration = 8

        prompt = request.prompt or self.config.get(
            "prompt",
            "Cinematic real estate advertisement, photorealistic architectural details, smooth camera glide, natural lighting, high dynamic range 1080p"
        )
        if request.script_text:
            prompt = f"{prompt}. Accompanying narration context: {request.script_text[:180]}"

        # Map aspect ratios to Veo formats
        aspect_ratio = "9:16"
        if request.aspect in ("16:9", "9:16", "1:1"):
            aspect_ratio = request.aspect
        elif request.aspect == "4:5":
            aspect_ratio = "9:16"  # Veo standard

        out_path = self._prepare_output_path(
            project_id=request.project_id,
            prefix="veo_fast",
            aspect=aspect_ratio,
            duration=duration,
        )

        models_to_try = [model] + [m for m in fallback_models if m != model]
        last_error = None

        for target_model in models_to_try:
            try:
                # Prepare payload
                instance: Dict[str, Any] = {"prompt": prompt}
                if request.image_bytes:
                    instance["image"] = {
                        "bytesBase64Encoded": base64.b64encode(request.image_bytes).decode("utf-8"),
                        "mimeType": "image/jpeg",
                    }

                payload = {
                    "instances": [instance],
                    "parameters": {
                        "aspectRatio": aspect_ratio,
                        "durationSeconds": duration,
                        "sampleCount": 1,
                        "personGeneration": "ALLOW_ADULT",
                    },
                }

                url = f"https://generativelanguage.googleapis.com/v1beta/models/{target_model}:predictLongRunning?key={api_key}"
                resp = requests.post(
                    url,
                    headers={"Content-Type": "application/json"},
                    json=payload,
                    timeout=30,
                )

                if resp.status_code != 200:
                    last_error = f"HTTP {resp.status_code}: {resp.text}"
                    continue

                res_json = resp.json()
                operation_name = res_json.get("name")
                if not operation_name:
                    last_error = f"No operation name returned: {res_json}"
                    continue

                # Poll operation until done
                poll_url = f"https://generativelanguage.googleapis.com/v1beta/{operation_name}?key={api_key}"
                max_polls = 60
                video_found = False

                for _ in range(max_polls):
                    time.sleep(5)
                    poll_resp = requests.get(poll_url, timeout=30)
                    if poll_resp.status_code != 200:
                        continue
                    poll_json = poll_resp.json()

                    if poll_json.get("done"):
                        if "error" in poll_json:
                            raise RuntimeError(f"Veo operation failed: {poll_json['error']}")

                        # Extract video
                        response_data = poll_json.get("response", {})
                        gen_response = (
                            response_data.get("generateVideoResponse", {})
                            or response_data.get("videoResponse", {})
                            or response_data
                        )
                        samples = gen_response.get("generatedSamples", [])
                        if not samples and "videos" in gen_response:
                            samples = [{"video": v} for v in gen_response["videos"]]

                        if not samples:
                            raise RuntimeError(f"No generated samples found in response: {poll_json}")

                        video_info = samples[0].get("video", {})
                        if "bytesBase64Encoded" in video_info:
                            raw_bytes = base64.b64decode(video_info["bytesBase64Encoded"])
                            out_path.write_bytes(raw_bytes)
                            video_found = True
                            break
                        elif "uri" in video_info:
                            self._download_url(video_info["uri"], out_path)
                            video_found = True
                            break
                        else:
                            raise RuntimeError(f"Unknown video payload format: {video_info}")

                if video_found and out_path.exists() and out_path.stat().st_size > 1000:
                    return VideoJobResponse(
                        success=True,
                        video_path=str(out_path),
                        provider="veo_fast",
                        model_used=target_model,
                        duration=duration,
                        metadata={"operation": operation_name, "aspectRatio": aspect_ratio},
                    )

            except Exception as exc:
                last_error = str(exc)
                continue

        return VideoJobResponse(
            success=False,
            provider="veo_fast",
            model_used=model,
            error=f"Veo 3.1 Fast failed: {last_error}",
        )


# ─────────────────────────────────────────────
# Engine 3: HeyGen API (Avatar IV)
# ─────────────────────────────────────────────

class HeyGenAvatarEngine(BaseVideoEngine):
    """
    HeyGen API (Avatar IV) via HeyGen v2 Video Generation API.
    Renders an AI presenter / spokesperson speaking the exact promotional
    script with accurate lip sync and natural gestures.
    """

    def is_configured(self) -> bool:
        key = os.getenv("HEYGEN_API_KEY", "").strip()
        return bool(key and not key.startswith("your_"))

    def generate(self, request: VideoJobRequest) -> VideoJobResponse:
        if not self.is_configured():
            return VideoJobResponse(
                success=False,
                provider="heygen_avatar",
                error="HEYGEN_API_KEY is not set in .env",
            )

        api_key = os.getenv("HEYGEN_API_KEY", "").strip()
        avatar_id = request.options.get(
            "avatar_id",
            self.config.get("default_avatar_id", "Daisy-inskirt-20220818")
        )
        voice_id = request.options.get(
            "voice_id",
            self.config.get("default_voice_id", "1bd001e7e50f421d891986aad5158bc8")
        )
        avatar_type = request.options.get("avatar_type", self.config.get("avatar_type", "avatar"))

        script = request.script_text
        if not script:
            return VideoJobResponse(
                success=False,
                provider="heygen_avatar",
                error="HeyGen Avatar IV requires a script/narration text for the avatar to speak.",
            )

        # Dimension mapping
        dim_w, dim_h = 1080, 1920
        if request.aspect == "16:9":
            dim_w, dim_h = 1920, 1080
        elif request.aspect == "1:1":
            dim_w, dim_h = 1080, 1080
        elif request.aspect == "4:5":
            dim_w, dim_h = 1080, 1350

        out_path = self._prepare_output_path(
            project_id=request.project_id,
            prefix="heygen_avatar",
            aspect=request.aspect,
            duration=request.duration,
        )

        headers = {
            "X-Api-Key": api_key,
            "Content-Type": "application/json",
        }

        # Build character payload
        character_payload: Dict[str, Any] = {
            "type": avatar_type,
            "avatar_id": avatar_id,
            "avatar_style": self.config.get("avatar_style", "normal"),
        }
        if avatar_type == "talking_photo":
            character_payload = {
                "type": "talking_photo",
                "talking_photo_id": avatar_id,
            }

        payload = {
            "video_inputs": [
                {
                    "character": character_payload,
                    "voice": {
                        "type": "text",
                        "input_text": script,
                        "voice_id": voice_id,
                    },
                    "background": {
                        "type": "color",
                        "value": "#0A0D14",
                    },
                }
            ],
            "dimension": {
                "width": dim_w,
                "height": dim_h,
            },
            "test": request.options.get("test_mode", False),
        }

        try:
            # 1. Submit video generation
            submit_resp = requests.post(
                "https://api.heygen.com/v2/video/generate",
                headers=headers,
                json=payload,
                timeout=30,
            )
            submit_resp.raise_for_status()
            submit_json = submit_resp.json()

            video_id = submit_json.get("data", {}).get("video_id")
            if not video_id:
                return VideoJobResponse(
                    success=False,
                    provider="heygen_avatar",
                    error=f"HeyGen did not return a video_id: {submit_json}",
                )

            # 2. Poll for completion
            status_url = f"https://api.heygen.com/v1/video_status.get?video_id={video_id}"
            max_polls = 60
            video_url = None

            for _ in range(max_polls):
                time.sleep(5)
                stat_resp = requests.get(status_url, headers=headers, timeout=30)
                if stat_resp.status_code != 200:
                    continue
                stat_json = stat_resp.json()
                data = stat_json.get("data", {})
                current_status = data.get("status")

                if current_status == "completed":
                    video_url = data.get("video_url")
                    break
                elif current_status == "failed":
                    error_msg = data.get("error", "HeyGen video generation failed.")
                    return VideoJobResponse(
                        success=False,
                        provider="heygen_avatar",
                        error=f"HeyGen generation failed: {error_msg}",
                    )

            if not video_url:
                return VideoJobResponse(
                    success=False,
                    provider="heygen_avatar",
                    error=f"HeyGen video generation timed out (video_id: {video_id})",
                )

            # 3. Download the finished video
            self._download_url(video_url, out_path)

            return VideoJobResponse(
                success=True,
                video_path=str(out_path),
                provider="heygen_avatar",
                model_used="Avatar IV",
                duration=request.duration,
                metadata={"video_id": video_id, "avatar_id": avatar_id, "video_url": video_url},
            )

        except Exception as e:
            return VideoJobResponse(
                success=False,
                provider="heygen_avatar",
                error=f"HeyGen API request error: {e}",
            )


# ─────────────────────────────────────────────
# Service Registry & Facade
# ─────────────────────────────────────────────

class UnifiedVideoService:
    """
    Unified manager for all video engines.
    """

    def __init__(self, config_path: str = "config/platforms.yaml"):
        self.config_path = Path(config_path)
        self.config: Dict[str, Any] = {}
        if self.config_path.exists():
            self.config = yaml.safe_load(self.config_path.read_text()) or {}

        video_cfg = self.config.get("video_generation", {}).get("providers", {})

        # Default fallback configs
        wan_cfg = video_cfg.get("wan_flash") or self.config.get("wan", {})
        veo_cfg = video_cfg.get("veo_fast", {})
        heygen_cfg = video_cfg.get("heygen_avatar", {})

        self.engines: Dict[str, BaseVideoEngine] = {
            "wan_flash": WanFlashEngine(wan_cfg),
            "veo_fast": VeoFastEngine(veo_cfg),
            "heygen_avatar": HeyGenAvatarEngine(heygen_cfg),
        }

    def get_statuses(self) -> List[ProviderStatus]:
        return [
            ProviderStatus(
                provider_id="wan_flash",
                display_name="Wan 2.6 Flash (fal.ai)",
                api_key_env="FAL_KEY",
                configured=self.engines["wan_flash"].is_configured(),
                description="Fastest & cheapest ($0.75 / 10s) 1080p B-roll and render animation.",
                cost_info="$0.75 / 10s",
                supported_durations="5s, 10s clips",
            ),
            ProviderStatus(
                provider_id="veo_fast",
                display_name="Veo 3.1 Fast (Google Veo)",
                api_key_env="GEMINI_API_KEY",
                configured=self.engines["veo_fast"].is_configured(),
                description="Cinematic lighting, camera physics, voice, and audio effects in one go.",
                cost_info="$1.20 / 10s",
                supported_durations="4s, 6s, 8s clips",
            ),
            ProviderStatus(
                provider_id="heygen_avatar",
                display_name="HeyGen API (Avatar IV)",
                api_key_env="HEYGEN_API_KEY",
                configured=self.engines["heygen_avatar"].is_configured(),
                description="Photorealistic AI presenter/spokesperson speaking your exact script with lip-sync.",
                cost_info="$0.39 - $0.81 / 10s",
                supported_durations="Up to 30 min per video",
            ),
        ]

    def generate(self, provider_id: str, request: VideoJobRequest) -> VideoJobResponse:
        engine = self.engines.get(provider_id)
        if not engine:
            return VideoJobResponse(
                success=False,
                provider=provider_id,
                error=f"Unknown video provider: '{provider_id}'. Available: {list(self.engines.keys())}",
            )
        return engine.generate(request)


# Singleton instance
_SERVICE = UnifiedVideoService()

def get_video_service() -> UnifiedVideoService:
    return _SERVICE
