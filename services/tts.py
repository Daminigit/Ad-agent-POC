"""
Text-to-Speech Service
======================
Generates voiceover audio and an approximate .srt subtitle file from a voice
script using Kokoro (pip install kokoro soundfile).

Kokoro's KPipeline yields audio in multiple chunks; this module concatenates
them into a single .wav file and builds a word-aligned .srt from the result.

Dependencies:
    pip install kokoro soundfile numpy
"""

import os
from pathlib import Path

import numpy as np
import soundfile as sf
from kokoro import KPipeline


# ─────────────────────────────────────────────
# Internal helpers
# ─────────────────────────────────────────────

_pipeline_cache: dict[str, KPipeline] = {}


def _get_pipeline(lang_code: str = "a") -> KPipeline:
    """Return a cached KPipeline for the given language code.

    lang_code:
        "a" = American English (default)
        "b" = British English
    """
    if lang_code not in _pipeline_cache:
        _pipeline_cache[lang_code] = KPipeline(lang_code=lang_code)
    return _pipeline_cache[lang_code]


def format_timestamp(seconds: float) -> str:
    """Format seconds into SRT timestamp format: HH:MM:SS,mmm"""
    hours = int(seconds // 3600)
    minutes = int((seconds % 3600) // 60)
    secs = int(seconds % 60)
    millis = int((seconds - int(seconds)) * 1000)
    return f"{hours:02d}:{minutes:02d}:{secs:02d},{millis:03d}"


def _build_srt(text: str, duration: float, chunk_size: int = 5) -> str:
    """Build an SRT string by evenly distributing words across the audio duration."""
    words = text.split()
    chunks = [
        " ".join(words[i : i + chunk_size])
        for i in range(0, len(words), chunk_size)
    ]

    if not chunks:
        return ""

    time_per_chunk = duration / len(chunks)
    lines: list[str] = []

    for i, chunk in enumerate(chunks):
        start = i * time_per_chunk
        end = (i + 1) * time_per_chunk
        lines.append(str(i + 1))
        lines.append(f"{format_timestamp(start)} --> {format_timestamp(end)}")
        lines.append(chunk)
        lines.append("")  # blank line separates SRT blocks

    return "\n".join(lines)


# ─────────────────────────────────────────────
# Public API
# ─────────────────────────────────────────────

def generate_voiceover(
    text: str,
    output_dir: str,
    voice_name: str = "af_heart",
    lang_code: str = "a",
    speed: float = 1.0,
) -> tuple[str, str]:
    """
    Generate a .wav voiceover and a .srt subtitle file from ``text``.

    Kokoro's KPipeline streams audio in chunks; this function concatenates all
    chunks into a single WAV file so the rest of the pipeline can treat it as
    one audio asset.

    Args:
        text:        The voice script to speak.
        output_dir:  Directory where ``voiceover.wav`` and ``subtitles.srt``
                     will be written (created automatically if missing).
        voice_name:  Kokoro voice ID, e.g. ``"af_heart"``, ``"af_sky"``,
                     ``"bm_lewis"`` …
        lang_code:   ``"a"`` for American English, ``"b"`` for British English.
        speed:       Speaking speed multiplier (1.0 = normal).

    Returns:
        ``(wav_path, srt_path)`` — absolute paths to the generated files.

    Example::

        wav, srt = generate_voiceover(
            "Your own 3BHK, just 5 minutes from ITPL.",
            output_dir="outputs/my_project/audio",
        )
    """
    os.makedirs(output_dir, exist_ok=True)
    wav_path = os.path.join(output_dir, "voiceover.wav")
    srt_path = os.path.join(output_dir, "subtitles.srt")

    pipeline = _get_pipeline(lang_code)

    print(f"[tts] Generating audio for voice '{voice_name}' …")

    # Collect all audio chunks from the Kokoro pipeline
    audio_chunks: list[np.ndarray] = []
    sample_rate: int = 24000  # Kokoro always outputs 24 kHz

    for _gs, _ps, audio in pipeline(text, voice=voice_name, speed=speed):
        if audio is not None and len(audio) > 0:
            audio_chunks.append(audio)

    if not audio_chunks:
        raise RuntimeError("[tts] KPipeline returned no audio chunks.")

    # Concatenate all chunks into one contiguous array
    full_audio = np.concatenate(audio_chunks)

    # Write WAV
    sf.write(wav_path, full_audio, sample_rate)
    duration = len(full_audio) / sample_rate
    print(f"[tts] Audio generated: {duration:.1f}s → {wav_path}")

    # Write SRT
    srt_content = _build_srt(text, duration)
    with open(srt_path, "w", encoding="utf-8") as f:
        f.write(srt_content)
    print(f"[tts] Subtitles written → {srt_path}")

    return wav_path, srt_path
