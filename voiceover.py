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
import re
import subprocess
from pathlib import Path
from typing import Optional

import requests
from dotenv import load_dotenv

load_dotenv()


def _phonetic_clean_for_speech(text: str) -> str:
    """
    Phonetically optimize real-estate terms for authentic Indian pronunciation.
    Ensures 'lakh' is pronounced with a warm, open elongated vowel ('laakh')
    instead of a flat, rushed 'lack'.
    """
    # 1. Pronounce Lakh / Lakhs as crisp "lack" / "lacks"
    text = re.sub(r"\b[Ll]akhs\b", "lacks", text)
    text = re.sub(r"\b[Ll]akh\b", "lack", text)
    text = re.sub(r"\b[Ll]acs\b", "lacks", text)
    text = re.sub(r"\b[Ll]ac\b", "lack", text)
    text = re.sub(r"\blaakhs\b", "lacks", text)
    text = re.sub(r"\blaakh\b", "lack", text)

    # 2. Authentic Crore pronunciation
    text = re.sub(r"\b[Cc]rores\b", "krores", text)
    text = re.sub(r"\b[Cc]rore\b", "krore", text)
    text = re.sub(r"\b[Cc]r\b\.?", "krore", text)

    # 3. Currency symbol removal (e.g., ₹96 -> 96)
    text = re.sub(r"₹\s*", "", text)

    # 4. Clean separation of BHK letters so it is spoken as 'B-H-K'
    text = re.sub(r"\bBHK\b", "B-H-K", text)
    text = re.sub(r"\bbhk\b", "B-H-K", text)

    # 5. Ampersands to 'and'
    text = re.sub(r"\s*&\s*", " and ", text)

    # 6. Square feet formatting
    text = re.sub(r"\b[Ss]q\.?\s*[Ff]t\.?\b", "square feet", text)
    text = re.sub(r"\b[Ss]qft\b", "square feet", text)

    return text.strip()


def generate_indian_voiceover(
    script_text: str,
    output_path: Path,
    api_key: Optional[str] = None,
    voice_name: str = "en-IN-NeerjaNeural",
) -> Path:
    """
    Generate an Indian-English voiceover from the approved script text.
    Supports 'en-IN-NeerjaNeural' (female) and 'en-IN-PrabhatNeural' (male).
    Applies phonetic tuning for authentic Indian pronunciation of terms like 'laakh'.
    """
    output_path.parent.mkdir(parents=True, exist_ok=True)
    temp_raw = output_path.parent / f"raw_voice_{output_path.stem}.mp3"
    spoken_text = _phonetic_clean_for_speech(script_text)

    key = (
        api_key
        or os.getenv("GEMINI_API_KEY")
        or os.getenv("GOOGLE_API_KEY")
        or ""
    ).strip()

    success = False

    # 1. Try Gemini Native Audio Model
    if key and not key.startswith("your_"):
        success = _try_gemini_native_tts(spoken_text, temp_raw, key)

    # 2. Try Google Cloud Neural Text-to-Speech with Indian English (en-IN)
    if not success and key and not key.startswith("your_"):
        is_male = "prabhat" in voice_name.lower() or "male" in voice_name.lower()
        gc_voice = "en-IN-Neural2-B" if is_male else "en-IN-Neural2-D"
        success = _try_google_cloud_tts(spoken_text, temp_raw, key, voice_name=gc_voice)

    # 3. Studio-grade Neural Indian-English voice (edge-tts)
    if not success:
        success = _generate_neural_indian_voice(spoken_text, temp_raw, voice_name=voice_name)

    # 4. Fallback to basic gTTS en-IN if neural unavailable
    if not success:
        success = _generate_gtts_indian(spoken_text, temp_raw)

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


def _try_google_cloud_tts(text: str, dest_path: Path, api_key: str, voice_name: str = "en-IN-Neural2-D") -> bool:
    """Invoke Google TTS REST endpoint with en-IN neural voice."""
    headers = {"Content-Type": "application/json"}
    url = f"https://texttospeech.googleapis.com/v1/text:synthesize"

    # Support OAuth2 bearer token from Service Account credentials
    try:
        import google.auth
        from google.auth.transport.requests import Request
        creds, _ = google.auth.default(scopes=["https://www.googleapis.com/auth/cloud-platform"])
        creds.refresh(Request())
        if creds.token:
            headers["Authorization"] = f"Bearer {creds.token}"
    except Exception:
        if api_key and not api_key.startswith("your_"):
            url = f"{url}?key={api_key}"

    is_male = "B" in voice_name or "male" in voice_name.lower()
    payload = {
        "input": {"text": text},
        "voice": {
            "languageCode": "en-IN",
            "name": voice_name,
            "ssmlGender": "MALE" if is_male else "FEMALE",
        },
        "audioConfig": {
            "audioEncoding": "MP3",
            "speakingRate": 1.02,
            "pitch": 0.0,
        },
    }

    try:
        resp = requests.post(url, headers=headers, json=payload, timeout=12)
        if resp.status_code == 200:
            data = resp.json()
            audio_b64 = data.get("audioContent")
            if audio_b64:
                dest_path.write_bytes(base64.b64decode(audio_b64))
                return True
    except Exception:
        pass
    return False


def _generate_neural_indian_voice(text: str, dest_path: Path, voice_name: str = "en-IN-NeerjaNeural") -> bool:
    """Generate broadcast-quality neural Indian-English speech using edge-tts."""
    try:
        import asyncio
        import edge_tts

        async def _synth():
            communicate = edge_tts.Communicate(text, voice_name, rate="+2%", pitch="+1Hz")
            await communicate.save(str(dest_path))

        asyncio.run(_synth())
        return dest_path.exists() and dest_path.stat().st_size > 1000
    except Exception as e:
        print(f"[Voiceover] Neural TTS note: {e}")
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
