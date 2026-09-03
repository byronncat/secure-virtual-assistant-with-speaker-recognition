"""
Automatic Speech Recognition (ASR) service using OpenAI Whisper.
"""

from __future__ import annotations

import numpy as np
import whisper

from app.core.config import DEVICE, settings

model = whisper.load_model(settings.WHISPER_MODEL, device=DEVICE)


def audio_to_text(samples: np.ndarray, language: str | None = None) -> dict:
    """
    Transcribe a 16 kHz mono float32 PCM array into text.

    Whisper accepts a numpy array directly, so no intermediate WAV file
    is needed -- the whole pipeline stays in memory from the browser's
    raw PCM upload through to the transcript.

    Args:
        samples: mono float32 array, sample rate 16000, range [-1, 1].
        language: optional ISO language hint (e.g. "vi"). If omitted,
            Whisper auto-detects.

    Returns:
        dict with "text" and "language" keys.
    """
    if samples.dtype != np.float32:
        samples = samples.astype(np.float32)

    result = whisper.transcribe(
        model,
        samples,
        task="transcribe",
        language=language,
        fp16=(DEVICE.startswith("cuda")),
    )

    return {
        "text": result["text"].strip(),
        "language": result.get("language"),
    }
