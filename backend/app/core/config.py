"""
Core application configuration and central constants.
"""

from __future__ import annotations

import logging
import os
from pathlib import Path

import torch

logger = logging.getLogger(__name__)


def resolve_device() -> str:
    """
    Resolve the compute device to use (e.g. 'cuda', 'cpu', 'mps').
    Supports 'DEVICE' environment variable with values like 'cuda', 'gpu', 'cpu', 'mps'.
    Falls back gracefully to 'cpu' if 'cuda' or 'gpu' is requested but unavailable.
    """
    env_device = os.getenv("DEVICE", "").lower().strip()
    if env_device in ("gpu", "cuda"):
        if torch.cuda.is_available():
            return "cuda"
        logger.warning(
            "CUDA/GPU requested via DEVICE environment variable but unavailable. Falling back to CPU."
        )
        return "cpu"
    if env_device:
        return env_device

    if torch.cuda.is_available():
        return "cuda"
    if hasattr(torch.backends, "mps") and torch.backends.mps.is_available():
        return "mps"
    return "cpu"


class Settings:
    # --- Compute Device ---
    DEVICE: str = resolve_device()

    # --- Project directories & files ---
    APP_DIR: Path = Path(__file__).resolve().parent.parent
    BACKEND_DIR: Path = APP_DIR.parent
    DATA_DIR: Path = BACKEND_DIR / "data"
    USERS_JSON: Path = DATA_DIR / "users.json"
    COMMANDS_JSON: Path = DATA_DIR / "commands.json"
    ENROLLMENT_DIR: Path = DATA_DIR / "enrollment"
    JWT_SECRET_PATH: Path = DATA_DIR / "jwt_secret.key"
    MODELS_DIR: Path = BACKEND_DIR / "models"
    SPEAKER_ENCODER_DIR: Path = MODELS_DIR / "speaker_encoder"
    SPEAKER_ENCODER_WEIGHTS: Path = SPEAKER_ENCODER_DIR / "speaker_encoder.pt"

    # --- Audio conversion & processing ---
    FFMPEG_BIN: Path = Path(
        r"D:\Programs\DEV\ffmpeg-9.0.1-full_build-shared\bin\ffmpeg.exe"
    )
    FFPROBE_BIN: Path = FFMPEG_BIN.with_name("ffprobe.exe")

    TARGET_SAMPLE_RATE: int = 16_000
    TARGET_CHANNELS: int = 1  # mono
    TARGET_SAMPLE_FORMAT: str = "s16"  # 16-bit PCM
    MAX_UPLOAD_BYTES: int = 15 * 1024 * 1024  # 15 MB

    # --- Security & Auth ---
    ALGORITHM: str = "HS256"
    ACCESS_TOKEN_TTL_SECONDS: int = 7 * 24 * 60 * 60  # 7 days
    PBKDF2_ITERATIONS: int = 200_000

    # --- Speaker Verification & Enrollment ---
    REQUIRED_ENROLLMENT_SAMPLES: int = 5
    DEFAULT_MATCH_THRESHOLD: float = 0.25  # cosine similarity

    # --- Models ---
    OLLAMA_MODEL: str = "llama3.1:8b"
    WHISPER_MODEL: str = "base"

    # --- CORS ---
    CORS_ORIGINS: list[str] = [
        "http://localhost:3000",
        "http://127.0.0.1:3000",
    ]


settings = Settings()
DEVICE: str = settings.DEVICE
