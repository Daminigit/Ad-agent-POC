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


def normalize_point_o(text: str) -> str:
    """'two point zero' / 'two-point-zero' / 'point 0' -> 'two point o' (Indian way of saying 2.0)."""
    text = re.sub(r"\bpoint[\s-]+(zero|0)\b", "point o", text, flags=re.I)
    # also "point zero five" -> "point o five" (each digit after the point)
    while re.search(r"\bpoint((?:\s+(?:o|one|two|three|four|five|six|seven|eight|nine))+)\s+(zero|0)\b", text, re.I):
        text = re.sub(r"\bpoint((?:\s+(?:o|one|two|three|four|five|six|seven|eight|nine))+)\s+(zero|0)\b",
                      lambda m: f"point{m.group(1)} o", text, flags=re.I)
    return text


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

    # 3b. Decimals as spoken in India: "2.0" -> "two point o", "1.42" -> "one point four two"
    from planner import number_words
    # (a full stop right after the number – "Eternia 2.0." – must not block the match)
    text = re.sub(r"(?<![\d.])(\d+\.\d+)(?!\.?\d)", lambda m: number_words(m.group(1)), text)
    # 3c. Zero after "point" is always "o", however the script spelled it ("two point zero", "2 point 0")
    text = normalize_point_o(text)
    # 3d. The TTS engine reads a bare "o" after "point" as "zero" – spell it "oh" so it is said "two point oh"
    digit = r"(?:oh|one|two|three|four|five|six|seven|eight|nine)"
    pat = re.compile(rf"\bpoint((?:\s+{digit})*)\s+o\b", re.I)
    while pat.search(text):
        text = pat.sub(lambda m: f"point{m.group(1)} oh", text)

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
    max_seconds: Optional[float] = None,
) -> Path:
    """
    Generate an Indian-English voiceover from the approved script text.
    Supports 'en-IN-NeerjaNeural' (female) and 'en-IN-PrabhatNeural' (male).
    Applies phonetic tuning for authentic Indian pronunciation of terms like 'laakh'.
    max_seconds: the time available before the end card. Leading/trailing silence is trimmed and,
    if the voice is still too long, it is sped up slightly (at most 15%) so it ends in time.
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

    global LAST_ENGINE
    success = False

    # 1. Gemini voice on Vertex AI (natural, soft; checks "two point oh")
    success = _try_gemini_vertex_tts(spoken_text, temp_raw, voice_name)
    if success:
        LAST_ENGINE = f"Gemini {GEMINI_VOICES['male' if 'prabhat' in voice_name.lower() else 'female']}"

    # 2. Try Google Cloud Neural Text-to-Speech with Indian English (en-IN)
    if not success and key and not key.startswith("your_"):
        is_male = "prabhat" in voice_name.lower() or "male" in voice_name.lower()
        gc_voice = "en-IN-Neural2-B" if is_male else "en-IN-Neural2-D"
        success = _try_google_cloud_tts(spoken_text, temp_raw, key, voice_name=gc_voice)

    # 3. Studio-grade Neural Indian-English voice (edge-tts)
    if not success:
        success = _generate_neural_indian_voice(spoken_text, temp_raw, voice_name=voice_name)
        if success:
            LAST_ENGINE = f"edge-tts {voice_name}"

    # 4. Fallback to basic gTTS en-IN if neural unavailable
    if not success:
        success = _generate_gtts_indian(spoken_text, temp_raw)

    # 4. Final audio normalization via FFmpeg (+ silence trim and gentle speed fit)
    if success and temp_raw.exists():
        filters = [
            "silenceremove=start_periods=1:start_threshold=-45dB",
            "areverse", "silenceremove=start_periods=1:start_threshold=-45dB", "areverse",
        ]
        if max_seconds:
            trimmed_len = _probe_trimmed_seconds(temp_raw, ",".join(filters))
            if trimmed_len and trimmed_len > max_seconds:
                filters.append(f"atempo={min(1.15, trimmed_len / max_seconds):.3f}")
        # 0.3 s lead-in so the first word doesn't clip on the crossfade
        filters += ["adelay=300|300", "loudnorm=I=-16:TP=-1.5:LRA=11"]
        cmd = [
            "ffmpeg", "-y",
            "-i", str(temp_raw),
            "-filter:a", ",".join(filters),
            "-ar", "44100", "-ac", "2",
            "-c:a", "libmp3lame", "-b:a", "192k",
            str(output_path),
        ]
        subprocess.run(cmd, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL, check=True)
        temp_raw.unlink(missing_ok=True)
        return output_path

    raise RuntimeError("Failed to generate voiceover audio.")


def _probe_trimmed_seconds(path: Path, filters: str) -> Optional[float]:
    """Length of the audio after the silence-trim filters."""
    try:
        res = subprocess.run(
            ["ffmpeg", "-i", str(path), "-af", filters, "-f", "null", "-"],
            capture_output=True, text=True, check=True,
        )
        times = re.findall(r"time=(\d+):(\d+):(\d+\.\d+)", res.stderr)
        if times:
            h, m, sec = times[-1]
            return int(h) * 3600 + int(m) * 60 + float(sec)
    except Exception:
        pass
    return None


def voice_window_seconds(plan) -> float:
    """Seconds of scenes before the end card (what the voice has to fit into)."""
    veo = [s for s in plan.scenes if s.source_type != "end_card"]
    return max(3.0, sum(s.duration_seconds for s in veo) - len(veo) * plan.crossfade_seconds - 0.3)


GEMINI_TTS_MODEL = os.getenv("GEMINI_TTS_MODEL", "gemini-2.5-flash-tts")
# App voice choice -> Gemini prebuilt voice (picked by ear: Achernar = soft female, Charon = calm male)
GEMINI_VOICES = {"female": os.getenv("GEMINI_TTS_FEMALE", "Achernar"), "male": os.getenv("GEMINI_TTS_MALE", "Charon")}
# Tested: the brisk direction fits 10 s ads, and "two-point-O" was said "two point oh" in every take
GEMINI_STYLE = ("Read this as a soft, warm, elegant Indian-English voiceover for a premium real-estate ad, at a lively, "
                "slightly brisk commercial pace with no long pauses. Pronounce '2.0' as 'two point oh' (the letter O), "
                "never 'zero'. Say every word exactly as written: ")
LAST_ENGINE = ""   # which engine made the last voiceover (shown in the app)


def _gemini_tts_once(text: str, wav_path: Path, voice: str) -> bool:
    """One Gemini TTS call on Vertex AI (service account). Writes a WAV file."""
    from gemini_text import _vertex_token

    project = os.getenv("GCP_PROJECT_ID", "").strip()
    token = _vertex_token() if project else None
    if not (project and token):
        return False
    url = (f"https://aiplatform.googleapis.com/v1/projects/{project}/locations/global/publishers/google/"
           f"models/{GEMINI_TTS_MODEL}:generateContent")
    body = {"contents": [{"role": "user", "parts": [{"text": GEMINI_STYLE + text}]}],
            "generationConfig": {"responseModalities": ["AUDIO"],
                                 "speechConfig": {"voiceConfig": {"prebuiltVoiceConfig": {"voiceName": voice}}}}}
    try:
        r = requests.post(url, headers={"Authorization": f"Bearer {token}"}, json=body, timeout=120)
        if r.status_code != 200:
            print(f"[Voiceover] Gemini TTS HTTP {r.status_code}")
            return False
        inline = r.json()["candidates"][0]["content"]["parts"][0]["inlineData"]
        rate = 24000
        m = re.search(r"rate=(\d+)", inline.get("mimeType", ""))
        if m:
            rate = int(m.group(1))
        pcm = wav_path.with_suffix(".pcm")
        pcm.write_bytes(base64.b64decode(inline["data"]))
        subprocess.run(["ffmpeg", "-y", "-loglevel", "error", "-f", "s16le", "-ar", str(rate), "-ac", "1",
                        "-i", str(pcm), str(wav_path)], check=True)
        pcm.unlink(missing_ok=True)
        return wav_path.exists() and wav_path.stat().st_size > 1000
    except Exception as exc:
        print(f"[Voiceover] Gemini TTS note: {exc}")
        return False


def _heard_point_zero(wav_path: Path) -> bool:
    """Listen back (Gemini) and report whether the voice said 'point zero' instead of 'point oh'."""
    from gemini_text import _vertex_token

    project = os.getenv("GCP_PROJECT_ID", "").strip()
    token = _vertex_token()
    if not (project and token):
        return False
    small = wav_path.with_name(wav_path.stem + "_16k.wav")
    try:
        subprocess.run(["ffmpeg", "-y", "-loglevel", "error", "-i", str(wav_path), "-ac", "1", "-ar", "16000",
                        str(small)], check=True)
        url = (f"https://aiplatform.googleapis.com/v1/projects/{project}/locations/global/publishers/google/"
               "models/gemini-3-flash-preview:generateContent")
        body = {"contents": [{"role": "user", "parts": [
            {"inlineData": {"mimeType": "audio/wav", "data": base64.b64encode(small.read_bytes()).decode()}},
            {"text": "Transcribe exactly what is spoken, writing numbers as the words you hear "
                     "(e.g. 'two point zero' vs 'two point oh'). Output only the transcript."}]}],
            "generationConfig": {"maxOutputTokens": 1024, "temperature": 0}}
        r = requests.post(url, headers={"Authorization": f"Bearer {token}"}, json=body, timeout=60)
        parts = r.json()["candidates"][0]["content"]["parts"]
        heard = " ".join(x.get("text", "") for x in parts if not x.get("thought")).lower()
        return bool(re.search(r"point\s+zero|point\s+0\b|\b\d+\.0\b", heard))
    except Exception:
        return False
    finally:
        small.unlink(missing_ok=True)


def _try_gemini_vertex_tts(text: str, dest_path: Path, voice_name: str) -> bool:
    """Gemini voice; when the text says 'point oh', check it was said that way (up to 2 retries)."""
    gender = "male" if ("prabhat" in voice_name.lower() or "male" in voice_name.lower()
                        and "female" not in voice_name.lower()) else "female"
    voice = GEMINI_VOICES[gender]
    wav = dest_path.with_suffix(".wav")
    check = bool(re.search(r"point\s+oh", text, re.I))
    # Gemini says "two-point-O" as "two point oh" far more reliably than "two point oh"
    text = re.sub(r"\b(\w+)\s+point\s+oh\b", r"\1-point-O", text, flags=re.I)
    for attempt in range(3):
        if not _gemini_tts_once(text, wav, voice):
            return False
        if not check or not _heard_point_zero(wav):
            subprocess.run(["ffmpeg", "-y", "-loglevel", "error", "-i", str(wav), str(dest_path)], check=True)
            wav.unlink(missing_ok=True)
            return True
        print(f"[Voiceover] Gemini said 'point zero' – retrying ({attempt + 1}/2)")
    # Still 'zero' after retries: keep the last take rather than failing
    subprocess.run(["ffmpeg", "-y", "-loglevel", "error", "-i", str(wav), str(dest_path)], check=True)
    wav.unlink(missing_ok=True)
    return True


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
            # Slightly slower and lower for a softer, calmer read
            communicate = edge_tts.Communicate(text, voice_name, rate="-4%", pitch="-2Hz")
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
