"""
Indian-English Voiceover Generator
==================================
Converts approved real-estate scripts into professional Indian-English voiceover:
  1. Google Cloud / Gemini Text-to-Speech (en-IN neural voice) if API key active
  2. Google Indian-English TTS (gTTS en-IN) as seamless fallback
  3. Applies volume normalization and clean audio headers
"""

from __future__ import annotations

import base64
import os
import subprocess
from pathlib import Path
from typing import Optional

import requests
from dotenv import load_dotenv

load_dotenv()


def generate_indian_voiceover(
    script_text: str,
    output_path: Path,
    api_key: Optional[str] = None,
) -> Path:
    """
    Generate an Indian-English voiceover from the approved script text.
    """
    output_path.parent.mkdir(parents=True, exist_ok=True)
    temp_raw = output_path.parent / f"raw_voice_{output_path.stem}.mp3"

    key = (
        api_key
        or os.getenv("GEMINI_API_KEY")
        or os.getenv("GOOGLE_API_KEY")
        or ""
    ).strip()

    success = False

    # 1. Try Gemini Native Audio Model (gemini-2.5-flash-preview-tts / gemini-3.8-flash-tts)
    if key and not key.startswith("your_"):
        success = _try_gemini_native_tts(script_text, temp_raw, key)

    # 2. Try Google Cloud Neural Text-to-Speech with Indian English (en-IN)
    if not success and key and not key.startswith("your_"):
        success = _try_google_cloud_tts(script_text, temp_raw, key)

    # 3. High-quality Google Indian-English TTS fallback (gTTS en-IN)
    if not success:
        success = _generate_gtts_indian(script_text, temp_raw)

    # 4. Final audio normalization via FFmpeg
    if success and temp_raw.exists():
        cmd = [
            "ffmpeg", "-y",
            "-i", str(temp_raw),
            "-filter:a", "loudnorm=I=-16:TP=-1.5:LRA=11",
            "-ar", "44100", "-ac", "2",
            "-c:a", "libmp3lame", "-b:a", "192k",
            str(output_path),
        ]
        subprocess.run(cmd, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL, check=True)
        temp_raw.unlink(missing_ok=True)
        return output_path

    raise RuntimeError("Failed to generate voiceover audio.")


def _try_gemini_native_tts(text: str, dest_path: Path, api_key: str) -> bool:
    """Invoke Google Gemini Native Audio generation (gemini-2.5-flash-preview-tts / gemini-3.8-flash-tts)."""
    models = ["gemini-2.5-flash-preview-tts", "gemini-3.8-flash-tts", "gemini-3.1-flash-tts-preview"]
    for model in models:
        url = f"https://generativelanguage.googleapis.com/v1beta/models/{model}:generateContent?key={api_key}"
        payload = {
            "contents": [{
                "parts": [{
                    "text": f"Read this luxury real-estate advertisement voiceover in a warm, welcoming, and elegant Indian English accent: {text}"
                }]
            }],
            "generationConfig": {
                "responseModalities": ["AUDIO"],
                "speechConfig": {
                    "voiceConfig": {
                        "prebuiltVoiceConfig": {
                            "voiceName": "Puck"
                        }
                    }
                }
            }
        }
        try:
            resp = requests.post(url, json=payload, headers={"Content-Type": "application/json"}, timeout=15)
            if resp.status_code == 200:
                data = resp.json()
                part = data.get("candidates", [{}])[0].get("content", {}).get("parts", [{}])[0]
                inline = part.get("inlineData", {})
                b64_audio = inline.get("data")
                if b64_audio:
                    dest_path.write_bytes(base64.b64decode(b64_audio))
                    return True
        except Exception:
            continue
    return False


def _try_google_cloud_tts(text: str, dest_path: Path, api_key: str) -> bool:
    """Invoke Google TTS REST endpoint with en-IN voice."""
    url = f"https://texttospeech.googleapis.com/v1/text:synthesize?key={api_key}"
    payload = {
        "input": {"text": text},
        "voice": {
            "languageCode": "en-IN",
            "name": "en-IN-Wavenet-D",
            "ssmlGender": "MALE",
        },
        "audioConfig": {
            "audioEncoding": "MP3",
            "speakingRate": 1.04,
            "pitch": 0.0,
        },
    }

    try:
        resp = requests.post(url, json=payload, timeout=12)
        if resp.status_code == 200:
            data = resp.json()
            audio_b64 = data.get("audioContent")
            if audio_b64:
                dest_path.write_bytes(base64.b64decode(audio_b64))
                return True
    except Exception:
        pass
    return False


def _generate_gtts_indian(text: str, dest_path: Path) -> bool:
    """Generate Indian-accented English speech via gTTS (co.in TLD)."""
    try:
        from gtts import gTTS
        tts = gTTS(text=text, lang="en", tld="co.in", slow=False)
        tts.save(str(dest_path))
        return True
    except Exception as e:
        print(f"[Voiceover] gTTS generation note: {e}")
        return False
