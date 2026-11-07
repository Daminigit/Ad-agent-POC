"""
Music Generation & Processing
=============================
Handles background score generation matching Section 7:
  - Length matches total video duration exactly
  - Fade-in 1s, fade-out 2s
  - Trims/loops user uploaded music if supplied
  - Generates instrumental using Google Lyria model via Gemini API
  - Provides acoustic Indian celebratory synthesizer fallback if Lyria is unavailable
"""

from __future__ import annotations

import math
import os
import struct
import subprocess
import wave
from pathlib import Path
from typing import Optional

import requests
from dotenv import load_dotenv

load_dotenv()


def build_music_track(
    duration: int,
    festival: str = "Diwali",
    uploaded_music_path: Optional[str] = None,
    output_path: Optional[Path] = None,
    api_key: Optional[str] = None,
    music_track: Optional[str] = None,
    music_prompt: Optional[str] = None,
) -> Path:
    """
    Produce a clean, continuous audio track for the video duration.
    Fades in 1 second, fades out 2 seconds.
    Supports music_track="sitar", "piano", or custom path.
    """
    clean_tag = (music_track or festival).replace("/", "_").lower()
    out_file = output_path or Path(f"./cache/music_{duration}s_{clean_tag}.mp3")
    out_file.parent.mkdir(parents=True, exist_ok=True)

    raw_audio_temp = out_file.parent / f"raw_temp_{out_file.stem}.wav"

    if uploaded_music_path and Path(uploaded_music_path).exists():
        # User uploaded music: Loop and trim
        _process_custom_audio(Path(uploaded_music_path), raw_audio_temp, duration)
    else:
        # Check for bundled studio acoustic tracks first
        studio_track = None
        assets_dir = Path("assets/music")

        if music_track == "sitar" or (not music_track and festival not in ("None", "Family")):
            candidate = assets_dir / "festive_indian.mp3"
            if candidate.exists():
                studio_track = candidate
        elif music_track == "piano" or (not music_track and festival in ("None", "Family")):
            candidate = assets_dir / "luxury_ambient.mp3"
            if candidate.exists():
                studio_track = candidate

        if studio_track and studio_track.exists():
            _process_custom_audio(studio_track, raw_audio_temp, duration)
        else:
            # Fallback to Lyria API or synthesis
            success = _try_generate_lyria(duration, festival, raw_audio_temp, api_key, music_prompt)
            if not success or not raw_audio_temp.exists():
                _synthesize_festive_acoustic_bed(duration, festival, raw_audio_temp)

    # Apply 1s fade-in and 2s fade-out via FFmpeg
    fade_out_start = max(0, duration - 2)
    cmd = [
        "ffmpeg", "-y",
        "-i", str(raw_audio_temp),
        "-t", str(duration),
        "-af", f"afade=t=in:ss=0:d=1,afade=t=out:st={fade_out_start}:d=2",
        "-c:a", "libmp3lame", "-b:a", "192k",
        str(out_file)
    ]
    subprocess.run(cmd, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL, check=True)

    if raw_audio_temp.exists():
        raw_audio_temp.unlink(missing_ok=True)

    return out_file


def _process_custom_audio(input_file: Path, output_file: Path, duration: int) -> None:
    """Loop or trim custom audio to required length."""
    cmd = [
        "ffmpeg", "-y",
        "-stream_loop", "-1",
        "-i", str(input_file),
        "-t", str(duration),
        "-vn",
        "-ac", "2", "-ar", "44100",
        str(output_file)
    ]
    subprocess.run(cmd, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL, check=True)


def _try_generate_lyria(
    duration: int,
    festival: str,
    output_file: Path,
    api_key: Optional[str] = None,
    music_prompt: Optional[str] = None,
) -> bool:
    """Attempt Google Gemini Lyria model call if available."""
    key = api_key or os.getenv("GEMINI_API_KEY") or os.getenv("GOOGLE_API_KEY")
    if not key or key.startswith("your_"):
        return False

    prompt = music_prompt or (
        f"Joyful Indian festive instrumental for {festival}: shehnai and sitar melody, "
        f"tabla and soft dholak rhythm, light temple bells, warm and celebratory, no vocals, "
        f"{duration} seconds, gentle ending."
    )

    # Check Lyria audio generation endpoints
    endpoints = [
        "https://generativelanguage.googleapis.com/v1beta/models/sound-generation:predict",
        "https://generativelanguage.googleapis.com/v1beta/models/lyria:generateAudio",
    ]

    for ep in endpoints:
        try:
            resp = requests.post(
                f"{ep}?key={key}",
                headers={"Content-Type": "application/json"},
                json={"prompt": prompt, "duration_seconds": duration},
                timeout=10,
            )
            if resp.status_code == 200:
                audio_bytes = resp.content
                if len(audio_bytes) > 5000:
                    output_file.write_bytes(audio_bytes)
                    return True
        except Exception:
            continue

    return False


def _synthesize_festive_acoustic_bed(duration: int, festival: str, output_file: Path) -> None:
    """
    High-quality procedural Indian acoustic festive generator.
    Synthesizes rich sitar harmonic overtones, tanpura drone, rhythmic tabla
    accents, and resonant temple chime harmonics.
    """
    sample_rate = 44100
    total_samples = int(sample_rate * duration)

    # Tanpura drone base frequency (C# / D: ~146.83 Hz)
    f_root = 146.83
    f_fifth = f_root * 1.5   # Pa (220.25 Hz)
    f_octave = f_root * 2.0  # Sa (293.66 Hz)

    # Tempo / rhythm: 96 BPM
    beat_samples = int(sample_rate * (60.0 / 96.0))

    audio_frames = []

    for i in range(total_samples):
        t = i / sample_rate

        # 1. Tanpura drone with gentle chorusing
        tanpura = (
            0.18 * math.sin(2 * math.pi * f_root * t)
            + 0.12 * math.sin(2 * math.pi * f_fifth * t + 0.2)
            + 0.08 * math.sin(2 * math.pi * f_octave * t + 0.4)
            + 0.04 * math.sin(2 * math.pi * (f_octave * 1.5) * t)
        )

        # 2. Sitar melodic overtones (pentatonic Raga Bhupali notes: Sa, Re, Ga, Pa, Dha)
        melody_step = int(t / (60.0 / 96.0)) % 8
        scale_ratios = [1.0, 1.125, 1.25, 1.5, 1.667, 1.5, 1.25, 1.125]
        note_freq = f_octave * scale_ratios[melody_step]
        sitar_env = math.exp(-3.5 * ((t % (60.0 / 96.0))))
        sitar = 0.22 * math.sin(2 * math.pi * note_freq * t) * sitar_env

        # 3. Soft rhythmic percussion (Dholak / Tabla Bayan)
        percussion = 0.0
        sample_in_beat = i % beat_samples
        if sample_in_beat < int(0.2 * sample_rate):
            drum_t = sample_in_beat / sample_rate
            drum_decay = math.exp(-22.0 * drum_t)
            drum_freq = 85.0 * math.exp(-15.0 * drum_t)
            percussion = 0.25 * math.sin(2 * math.pi * drum_freq * drum_t) * drum_decay

        # 4. Temple Chime bells every 4 beats
        chime = 0.0
        four_beat = beat_samples * 4
        sample_in_chime = i % four_beat
        if sample_in_chime < int(1.5 * sample_rate):
            ch_t = sample_in_chime / sample_rate
            ch_decay = math.exp(-2.2 * ch_t)
            chime = (
                0.08 * math.sin(2 * math.pi * 1760.0 * ch_t)
                + 0.06 * math.sin(2 * math.pi * 2637.0 * ch_t)
            ) * ch_decay

        # Sum and soft clip
        sample = tanpura + sitar + percussion + chime
        sample = max(-0.95, min(0.95, sample))
        int_sample = int(sample * 32767.0)

        # Stereo (left, right)
        audio_frames.append(struct.pack("<hh", int_sample, int_sample))

    with wave.open(str(output_file), "w") as wav_out:
        wav_out.setnchannels(2)
        wav_out.setsampwidth(2)
        wav_out.setframerate(sample_rate)
        wav_out.writeframes(b"".join(audio_frames))
