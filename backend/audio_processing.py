"""
Audio processing utilities.

The frontend captures audio via the Web Audio API (AudioWorklet), so what
arrives at the backend is raw 16-bit PCM plus the sample rate the browser
captured at (see `main.py`). This module converts that raw PCM into
16 kHz, mono, 16-bit PCM WAV using ffmpeg (via subprocess), and decodes
the result into a float32 numpy array ready for ASR / speaker
verification.

A file-based conversion path (`convert_to_16k_mono_wav`) is also kept for
inputs that are already containerized/encoded audio (e.g. WebM/Opus from
MediaRecorder), in case that ingestion path is used elsewhere.

ffmpeg is NOT assumed to be on PATH -- the absolute path to the ffmpeg(.exe)
/ ffprobe(.exe) binaries is configured below via FFMPEG_BIN / FFPROBE_BIN.
"""

from __future__ import annotations

import asyncio
import logging
import subprocess
import wave
from dataclasses import dataclass
from pathlib import Path

import numpy as np

logger = logging.getLogger(__name__)

# --- Explicit ffmpeg/ffprobe location (do NOT rely on PATH) ---
FFMPEG_BIN = Path(r"D:\Programs\DEV\ffmpeg-9.0.1-full_build-shared\bin\ffmpeg.exe")
FFPROBE_BIN = FFMPEG_BIN.with_name("ffprobe.exe")

TARGET_SAMPLE_RATE = 16_000
TARGET_CHANNELS = 1  # mono
TARGET_SAMPLE_FORMAT = "s16"  # 16-bit PCM


class AudioConversionError(Exception):
    """Raised when ffmpeg fails to decode/convert the uploaded audio."""


@dataclass
class ConvertedAudio:
    path: Path
    sample_rate: int
    channels: int
    duration_seconds: float | None = None
    samples: np.ndarray | None = None  # float32 mono, range [-1, 1], at sample_rate


def _run_ffmpeg(
    cmd: list[str], input_bytes: bytes | None = None
) -> subprocess.CompletedProcess:
    try:
        return subprocess.run(
            cmd,
            input=input_bytes,
            check=True,
            capture_output=True,
        )
    except FileNotFoundError as exc:
        raise AudioConversionError(
            f"ffmpeg executable not found at '{FFMPEG_BIN}'. Update FFMPEG_BIN "
            "in audio_processing.py to point to your ffmpeg.exe."
        ) from exc
    except subprocess.CalledProcessError as exc:
        stderr = exc.stderr.decode("utf-8", errors="replace") if exc.stderr else ""
        logger.error("ffmpeg failed: %s", stderr)
        raise AudioConversionError(f"ffmpeg failed to convert audio: {stderr}") from exc


def _load_wav_as_float32_mono(path: Path) -> np.ndarray:
    """Decode a 16-bit PCM mono WAV file into a float32 array in [-1, 1]."""
    try:
        with wave.open(str(path), "rb") as wf:
            sampwidth = wf.getsampwidth()
            n_frames = wf.getnframes()
            raw = wf.readframes(n_frames)
    except wave.Error as exc:
        raise AudioConversionError(f"Could not read converted WAV file: {exc}") from exc

    if sampwidth != 2:
        raise AudioConversionError(
            f"Expected 16-bit PCM WAV output, got sample width {sampwidth} bytes."
        )

    samples_int16 = np.frombuffer(raw, dtype="<i2")
    return samples_int16.astype(np.float32) / 32768.0


def probe_duration_seconds(path: Path) -> float | None:
    """Best-effort duration probe via ffprobe. Returns None if unavailable."""
    cmd = [
        str(FFPROBE_BIN),
        "-v",
        "error",
        "-show_entries",
        "format=duration",
        "-of",
        "default=noprint_wrappers=1:nokey=1",
        str(path),
    ]
    try:
        result = subprocess.run(cmd, check=True, capture_output=True, text=True)
        return float(result.stdout.strip())
    except (FileNotFoundError, subprocess.CalledProcessError, ValueError):
        return None


def convert_to_16k_mono_wav(input_path: Path, output_path: Path) -> ConvertedAudio:
    """
    Decode any input audio file (e.g. WebM/Opus from MediaRecorder) and
    convert it to a 16 kHz, mono, 16-bit PCM WAV file, suitable as input
    for ASR (e.g. Whisper) and speaker verification models.

    Runs synchronously -- call via `asyncio.to_thread` from async request
    handlers so it doesn't block the event loop.
    """
    output_path.parent.mkdir(parents=True, exist_ok=True)

    cmd = [
        str(FFMPEG_BIN),
        "-y",  # overwrite output if it exists
        "-i",
        str(input_path),
        "-ar",
        str(TARGET_SAMPLE_RATE),
        "-ac",
        str(TARGET_CHANNELS),
        "-sample_fmt",
        TARGET_SAMPLE_FORMAT,
        "-f",
        "wav",
        str(output_path),
    ]

    _run_ffmpeg(cmd)
    samples = _load_wav_as_float32_mono(output_path)

    return ConvertedAudio(
        path=output_path,
        sample_rate=TARGET_SAMPLE_RATE,
        channels=TARGET_CHANNELS,
        duration_seconds=probe_duration_seconds(output_path),
        samples=samples,
    )


async def convert_to_16k_mono_wav_async(
    input_path: Path, output_path: Path
) -> ConvertedAudio:
    """Async wrapper so FastAPI's event loop isn't blocked by the subprocess call."""
    return await asyncio.to_thread(convert_to_16k_mono_wav, input_path, output_path)


def convert_raw_pcm_to_16k_mono_wav(
    pcm_bytes: bytes,
    output_path: Path,
    orig_sample_rate: int,
    channels: int = 1,
) -> ConvertedAudio:
    """
    Convert raw 16-bit little-endian PCM bytes (as uploaded by the
    frontend's AudioWorklet) into a 16 kHz, mono, 16-bit PCM WAV file, and
    decode that WAV into a float32 numpy array.

    The PCM bytes are piped directly to ffmpeg's stdin -- no intermediate
    input file is written.
    """
    output_path.parent.mkdir(parents=True, exist_ok=True)

    cmd = [
        str(FFMPEG_BIN),
        "-y",
        "-f",
        "s16le",
        "-ar",
        str(orig_sample_rate),
        "-ac",
        str(channels),
        "-i",
        "pipe:0",
        "-ar",
        str(TARGET_SAMPLE_RATE),
        "-ac",
        str(TARGET_CHANNELS),
        "-sample_fmt",
        TARGET_SAMPLE_FORMAT,
        "-f",
        "wav",
        str(output_path),
    ]

    _run_ffmpeg(cmd, input_bytes=pcm_bytes)
    samples = _load_wav_as_float32_mono(output_path)

    return ConvertedAudio(
        path=output_path,
        sample_rate=TARGET_SAMPLE_RATE,
        channels=TARGET_CHANNELS,
        duration_seconds=probe_duration_seconds(output_path),
        samples=samples,
    )


async def convert_raw_pcm_to_16k_mono_wav_async(
    pcm_bytes: bytes,
    output_path: Path,
    orig_sample_rate: int,
    channels: int = 1,
) -> ConvertedAudio:
    """Async wrapper so FastAPI's event loop isn't blocked by the subprocess call."""
    return await asyncio.to_thread(
        convert_raw_pcm_to_16k_mono_wav,
        pcm_bytes,
        output_path,
        orig_sample_rate,
        channels,
    )
