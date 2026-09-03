"""
Audio processing utilities: FFmpeg conversion, PCM decoding, and upload handling.
"""

from __future__ import annotations

import asyncio
import logging
import subprocess
import wave
from pathlib import Path

import numpy as np
from fastapi import HTTPException, UploadFile, status

from app.core.config import settings
from app.db.models import ConvertedAudio

logger = logging.getLogger(__name__)


class AudioConversionError(Exception):
    """Raised when ffmpeg fails to decode/convert the uploaded audio."""


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
            f"ffmpeg executable not found at '{settings.FFMPEG_BIN}'. Update FFMPEG_BIN "
            "in app/core/config.py to point to your ffmpeg.exe."
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
        str(settings.FFPROBE_BIN),
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
        str(settings.FFMPEG_BIN),
        "-y",  # overwrite output if it exists
        "-i",
        str(input_path),
        "-ar",
        str(settings.TARGET_SAMPLE_RATE),
        "-ac",
        str(settings.TARGET_CHANNELS),
        "-sample_fmt",
        settings.TARGET_SAMPLE_FORMAT,
        "-f",
        "wav",
        str(output_path),
    ]

    _run_ffmpeg(cmd)
    samples = _load_wav_as_float32_mono(output_path)

    return ConvertedAudio(
        path=output_path,
        sample_rate=settings.TARGET_SAMPLE_RATE,
        channels=settings.TARGET_CHANNELS,
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
        str(settings.FFMPEG_BIN),
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
        str(settings.TARGET_SAMPLE_RATE),
        "-ac",
        str(settings.TARGET_CHANNELS),
        "-sample_fmt",
        settings.TARGET_SAMPLE_FORMAT,
        "-f",
        "wav",
        str(output_path),
    ]

    _run_ffmpeg(cmd, input_bytes=pcm_bytes)
    samples = _load_wav_as_float32_mono(output_path)

    return ConvertedAudio(
        path=output_path,
        sample_rate=settings.TARGET_SAMPLE_RATE,
        channels=settings.TARGET_CHANNELS,
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


async def read_capped_upload(
    upload: UploadFile, max_bytes: int = settings.MAX_UPLOAD_BYTES
) -> bytes:
    chunks = []
    size = 0
    while chunk := await upload.read(1024 * 1024):
        size += len(chunk)
        if size > max_bytes:
            raise HTTPException(
                status_code=status.HTTP_413_REQUEST_ENTITY_TOO_LARGE,
                detail="Audio payload exceeds maximum allowed size.",
            )
        chunks.append(chunk)
    await upload.close()
    return b"".join(chunks)


async def pcm_upload_to_samples(
    audio: UploadFile, sample_rate: int, channels: int = 1
) -> ConvertedAudio:
    pcm_bytes = await read_capped_upload(audio)
    if not pcm_bytes:
        raise HTTPException(
            status.HTTP_400_BAD_REQUEST, "Received empty audio payload."
        )
    temp_wav_path = Path("temp.wav")
    try:
        return await convert_raw_pcm_to_16k_mono_wav_async(
            pcm_bytes,
            output_path=temp_wav_path,
            orig_sample_rate=sample_rate,
            channels=channels,
        )
    except AudioConversionError as exc:
        logger.exception("Failed to process raw PCM upload")
        raise HTTPException(
            status.HTTP_422_UNPROCESSABLE_ENTITY, f"Could not process audio: {exc}"
        ) from exc
    finally:
        if temp_wav_path.exists():
            try:
                temp_wav_path.unlink()
            except OSError as e:
                logger.warning(
                    "Could not delete temporary audio file %s: %s", temp_wav_path, e
                )
