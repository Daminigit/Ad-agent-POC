"""
Veo 3.1 Fast API Client
=======================
Handles Google Gemini Veo video generation for:
  - Image-to-video (render scenes)
  - Text-to-video (lifestyle scenes)
Includes:
  - Caching in ./cache keyed by hash(prompt + image + settings)
  - Retry logic (up to 2 retries on failure)
  - Strict GEMINI_API_KEY security (never prints or hardcodes)
  - Dry-run / mock simulation mode for testing without API charges
"""

from __future__ import annotations

import base64
import hashlib
import json
import os
import subprocess
import time
from pathlib import Path
from typing import Any, Dict, Optional, Tuple

import requests
from dotenv import load_dotenv

load_dotenv()

CACHE_DIR = Path("./cache")
CACHE_DIR.mkdir(parents=True, exist_ok=True)

# Model names available on Vertex AI for this project (checked Nov 2026). Fast first (cheaper).
VERTEX_VEO_MODELS = [m for m in [os.getenv("VEO_MODEL", "").strip(), "veo-3.1-fast-generate-001", "veo-3.1-generate-001"] if m]
GEMINI_API_VEO_MODELS = ["veo-3.1-fast-generate-preview", "veo-3.1-generate-preview"]
DEFAULT_VEO_MODELS = VERTEX_VEO_MODELS


def _prepare_image(image_bytes: bytes, max_side: int = 1920) -> bytes:
    """Re-encode the render as a JPEG no larger than 1920 px (keeps requests small)."""
    from io import BytesIO
    from PIL import Image

    img = Image.open(BytesIO(image_bytes)).convert("RGB")
    img.thumbnail((max_side, max_side), Image.LANCZOS)
    out = BytesIO()
    img.save(out, format="JPEG", quality=92)
    return out.getvalue()


def _error_message(resp: "requests.Response") -> str:
    try:
        return resp.json().get("error", {}).get("message", "")[:160]
    except Exception:
        return resp.text[:160]


class VeoClient:
    def __init__(self, api_key: Optional[str] = None, dry_run: bool = False):
        self.dry_run = dry_run
        self.credits_depleted = False
        self.api_error = ""
        self.fallbacks: list = []        # [(prompt start, reason)] for every scene that was NOT made by Veo
        self.live_clips = 0
        self.api_key = (
            api_key
            or os.getenv("GEMINI_API_KEY")
            or os.getenv("GOOGLE_API_KEY")
            or ""
        ).strip()

    def is_configured(self) -> bool:
        has_key = bool(self.api_key and not self.api_key.startswith("your_"))
        has_adc = bool(os.getenv("GOOGLE_APPLICATION_CREDENTIALS"))
        return has_key or has_adc

    def _get_request_headers(self) -> Dict[str, str]:
        headers = {"Content-Type": "application/json"}
        try:
            import google.auth
            from google.auth.transport.requests import Request
            creds, _ = google.auth.default(scopes=["https://www.googleapis.com/auth/cloud-platform"])
            creds.refresh(Request())
            if creds.token:
                headers["Authorization"] = f"Bearer {creds.token}"
        except Exception:
            pass
        return headers

    def _compute_cache_key(
        self,
        prompt: str,
        duration: int,
        aspect: str,
        resolution: str,
        image_bytes: Optional[bytes] = None,
    ) -> str:
        hasher = hashlib.sha256()
        hasher.update(prompt.encode("utf-8"))
        hasher.update(str(duration).encode("utf-8"))
        hasher.update(aspect.encode("utf-8"))
        hasher.update(resolution.encode("utf-8"))
        if image_bytes:
            hasher.update(image_bytes)
        return hasher.hexdigest()

    def generate_clip(
        self,
        prompt: str,
        duration: int,
        aspect: str = "16:9",
        resolution: str = "720p",
        image_path: Optional[str] = None,
        output_dest: Optional[Path] = None,
    ) -> Path:
        """
        Generate a video clip using Veo 3.1 Fast (or retrieve from cache).
        Retries up to 2 times on failure.
        """
        # Duration must be 4, 6, or 8 (Veo API constraints)
        dur = 4 if duration <= 4 else (6 if duration <= 6 else 8)

        # Aspect format for Veo
        aspect_ratio = "16:9" if aspect == "16:9" else "9:16"

        image_bytes = None
        if image_path and Path(image_path).exists():
            image_bytes = Path(image_path).read_bytes()

        # 1. Check Cache
        cache_key = self._compute_cache_key(prompt, dur, aspect_ratio, resolution, image_bytes)
        cached_file = CACHE_DIR / f"veo_{cache_key}.mp4"
        # Fallback animations live under a separate name so they are never mistaken for Veo clips
        mock_file = CACHE_DIR / f"mock_{cache_key}.mp4"

        if cached_file.exists() and cached_file.stat().st_size > 1000:
            if output_dest:
                output_dest.parent.mkdir(parents=True, exist_ok=True)
                output_dest.write_bytes(cached_file.read_bytes())
                return output_dest
            return cached_file

        # 2. Dry run / Mock simulation
        if self.dry_run or not self.is_configured():
            self.fallbacks.append((prompt[:60], "simulation mode" if self.dry_run else "no Veo credentials"))
            mock_clip = self._generate_mock_clip(
                mock_file, dur, aspect_ratio, resolution, image_path, prompt
            )
            if output_dest:
                output_dest.parent.mkdir(parents=True, exist_ok=True)
                output_dest.write_bytes(mock_clip.read_bytes())
                return output_dest
            return mock_clip

        # 3. Live API call (1 retry – every attempt is a paid Veo job)
        last_error = None
        for attempt in range(1, 3):
            try:
                clip_path = self._call_veo_api(
                    prompt=prompt,
                    duration=dur,
                    aspect_ratio=aspect_ratio,
                    resolution=resolution,
                    image_bytes=image_bytes,
                    dest_file=cached_file,
                )
                if clip_path.exists() and clip_path.stat().st_size > 1000:
                    self.live_clips += 1
                    if output_dest:
                        output_dest.parent.mkdir(parents=True, exist_ok=True)
                        output_dest.write_bytes(clip_path.read_bytes())
                        return output_dest
                    return clip_path
            except Exception as exc:
                last_error = exc
                err_str = str(exc)
                # If Google account has no prepaid Veo credits, don't waste time retrying
                if ("402" in err_str or "depleted" in err_str or "RESOURCE_EXHAUSTED" in err_str
                        or "billing" in err_str or "unavailable" in err_str or "safety filter" in err_str):
                    break
                time.sleep(2 * attempt)

        # 4. Graceful fallback on credit depletion (HTTP 402) or any API failure
        err_msg = str(last_error) if last_error else ""
        if "402" in err_msg or "depleted" in err_msg or "RESOURCE_EXHAUSTED" in err_msg or "billing" in err_msg:
            print("[VeoClient] ⚠️ Google API prepayment credits depleted (HTTP 402). Falling back to high-fidelity cinematic simulation.")
            self.credits_depleted = True
        else:
            print(f"[VeoClient] ⚠️ Live Veo API encountered error: {err_msg}. Falling back to high-fidelity cinematic simulation.")
            self.api_error = err_msg
        self.fallbacks.append((prompt[:60], err_msg or "unknown Veo error"))

        mock_clip = self._generate_mock_clip(
            mock_file, dur, aspect_ratio, resolution, image_path, prompt
        )
        if output_dest:
            output_dest.parent.mkdir(parents=True, exist_ok=True)
            output_dest.write_bytes(mock_clip.read_bytes())
            return output_dest
        return mock_clip

    def _call_veo_api(
        self,
        prompt: str,
        duration: int,
        aspect_ratio: str,
        resolution: str,
        image_bytes: Optional[bytes],
        dest_file: Path,
    ) -> Path:
        """Start a Veo job and wait for the video.
        Vertex AI (service account) when GCP_PROJECT_ID is set, otherwise the Gemini API key."""
        instance: Dict[str, Any] = {"prompt": prompt}
        if image_bytes:
            jpeg = _prepare_image(image_bytes)
            instance["image"] = {
                "bytesBase64Encoded": base64.b64encode(jpeg).decode("utf-8"),
                "mimeType": "image/jpeg",
            }

        gcp_project = os.getenv("GCP_PROJECT_ID", "").strip()
        gcp_location = os.getenv("GCP_LOCATION", "us-central1").strip() or "us-central1"
        headers = self._get_request_headers()
        use_vertex = bool(gcp_project and "Authorization" in headers)

        params: Dict[str, Any] = {
            "aspectRatio": aspect_ratio,
            "durationSeconds": duration,
            "sampleCount": 1,
        }
        if use_vertex:
            # Audio is OFF for every clip (the program adds music + voiceover); also cheaper.
            params.update({"generateAudio": False, "resolution": resolution, "personGeneration": "allow_adult"})
        else:
            params["personGeneration"] = "allow_adult"
        payload = {"instances": [instance], "parameters": params}

        errors = []
        for model in (VERTEX_VEO_MODELS if use_vertex else GEMINI_API_VEO_MODELS):
            if use_vertex:
                base = (f"https://{gcp_location}-aiplatform.googleapis.com/v1/projects/{gcp_project}"
                        f"/locations/{gcp_location}/publishers/google/models/{model}")
                url = f"{base}:predictLongRunning"
            else:
                url = f"https://generativelanguage.googleapis.com/v1beta/models/{model}:predictLongRunning?key={self.api_key}"
            resp = requests.post(url, headers=headers, json=payload, timeout=60)
            if resp.status_code != 200:
                errors.append(f"{model}: HTTP {resp.status_code} {_error_message(resp)}")
                if resp.status_code in (402, 429) or "billing" in resp.text.lower():
                    break
                continue
            operation_name = resp.json().get("name")
            if not operation_name:
                errors.append(f"{model}: no operation returned")
                continue
            print(f"[VeoClient] {model} job started ({'image' if image_bytes else 'text'}-to-video, {duration}s)")

            # Poll until done (up to ~6 minutes)
            for _ in range(72):
                time.sleep(5)
                if use_vertex:
                    poll = requests.post(f"{base}:fetchPredictOperation", headers=headers,
                                         json={"operationName": operation_name}, timeout=60)
                else:
                    poll = requests.get(f"https://generativelanguage.googleapis.com/v1beta/{operation_name}?key={self.api_key}",
                                        timeout=60)
                if poll.status_code != 200:
                    continue
                pj = poll.json()
                if not pj.get("done"):
                    continue
                if "error" in pj:
                    raise RuntimeError(f"Veo job failed: {pj['error'].get('message', pj['error'])}")
                data = pj.get("response", {})
                data = data.get("generateVideoResponse", data)
                videos = data.get("videos") or [s.get("video", {}) for s in data.get("generatedSamples", [])]
                if not videos:
                    filtered = data.get("raiMediaFilteredReasons") or data.get("raiMediaFilteredCount")
                    raise RuntimeError(f"Veo returned no video{f' (safety filter: {filtered})' if filtered else ''}")
                v = videos[0]
                if v.get("bytesBase64Encoded"):
                    dest_file.write_bytes(base64.b64decode(v["bytesBase64Encoded"]))
                elif v.get("uri"):
                    self._download_url(v["uri"], dest_file)
                elif v.get("gcsUri"):
                    raise RuntimeError("Veo saved the video to Cloud Storage; remove storageUri to get bytes back")
                else:
                    raise RuntimeError("Veo response had no video data")
                print(f"[VeoClient] {model} video ready ({dest_file.stat().st_size // 1024} KB)")
                return dest_file
            raise RuntimeError(f"{model}: timed out waiting for the video")

        raise RuntimeError("Veo unavailable – " + "; ".join(errors))

    def _download_url(self, url: str, dest: Path) -> None:
        r = requests.get(url, stream=True, timeout=120)
        r.raise_for_status()
        with open(dest, "wb") as f:
            for chunk in r.iter_content(chunk_size=65536):
                f.write(chunk)

    def _generate_mock_clip(
        self,
        dest_file: Path,
        duration: int,
        aspect_ratio: str,
        resolution: str,
        image_path: Optional[str],
        prompt: str,
    ) -> Path:
        """
        Produce a high-quality simulated clip using FFmpeg for dry-run testing.
        Applies subtle Ken Burns slow zoom so test pipelines evaluate realistic video files.
        """
        width, height = (1920, 1080) if aspect_ratio == "16:9" else (1080, 1920)
        if resolution == "720p":
            width, height = (1280, 720) if aspect_ratio == "16:9" else (720, 1280)

        dest_file.parent.mkdir(parents=True, exist_ok=True)

        if image_path and Path(image_path).exists():
            # Ken Burns slow drone zoom on input render image
            cmd = [
                "ffmpeg", "-y",
                "-loop", "1", "-i", str(image_path),
                "-filter_complex",
                f"[0:v]scale={width*2}:{height*2},zoompan=z='min(zoom+0.0012,1.25)':x='iw/2-(iw/zoom/2)':y='ih/2-(ih/zoom/2)':d={duration*25}:s={width}x{height}:fps=25[v]",
                "-map", "[v]",
                "-t", str(duration),
                "-pix_fmt", "yuv420p",
                "-c:v", "libx264", "-preset", "veryfast",
                str(dest_file)
            ]
        else:
            # Cinematic atmospheric color grade clip for lifestyle scene
            cmd = [
                "ffmpeg", "-y",
                "-f", "lavfi",
                "-i", f"color=c=0x1F2A44:s={width}x{height}:d={duration}:r=25",
                "-vf", f"drawbox=y=ih*0.2:color=0xD4AF37@0.15:width=iw:height=ih*0.6:t=fill",
                "-pix_fmt", "yuv420p",
                "-c:v", "libx264", "-preset", "veryfast",
                str(dest_file)
            ]

        subprocess.run(cmd, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL, check=True)
        return dest_file
