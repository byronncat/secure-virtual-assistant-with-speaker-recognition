"""
Speaker verification via trained ECAPA-TDNN embedding model.
"""

from __future__ import annotations

import logging
from pathlib import Path

import numpy as np
import torch
import torch.nn.functional as F
import torchaudio

from app.core.config import DEVICE, settings
from app.db.models import SpeakerVerificationResult
from app.repositories.enrollment_repository import load_centroid
from models.model import ECAPAModel

logger = logging.getLogger(__name__)

_encoder: ECAPAModel | None = None
_mel_spectrogram: torchaudio.transforms.MelSpectrogram | None = None
_amplitude_to_db: torchaudio.transforms.AmplitudeToDB | None = None


def _get_feature_extractors() -> (
    tuple[torchaudio.transforms.MelSpectrogram, torchaudio.transforms.AmplitudeToDB]
):
    global _mel_spectrogram, _amplitude_to_db
    if _mel_spectrogram is None or _amplitude_to_db is None:
        _mel_spectrogram = torchaudio.transforms.MelSpectrogram(
            sample_rate=settings.TARGET_SAMPLE_RATE,
            n_fft=400,
            win_length=400,
            hop_length=160,
            n_mels=80,
        ).to(DEVICE)
        _amplitude_to_db = torchaudio.transforms.AmplitudeToDB().to(DEVICE)
    return _mel_spectrogram, _amplitude_to_db


def _find_checkpoint_path() -> Path:
    """Find the trained model checkpoint in settings.SPEAKER_ENCODER_DIR."""
    candidates = [
        settings.SPEAKER_ENCODER_WEIGHTS,
        settings.SPEAKER_ENCODER_DIR / "best_model.pt",
        settings.SPEAKER_ENCODER_DIR / "speaker_encoder.pt",
        settings.SPEAKER_ENCODER_DIR / "model.pt",
        settings.MODELS_DIR / "speaker_encoder.pt",
    ]
    for p in candidates:
        if p.exists():
            return p
    if settings.SPEAKER_ENCODER_DIR.exists():
        for p in settings.SPEAKER_ENCODER_DIR.glob("*.pt"):
            return p
    raise FileNotFoundError(
        f"No trained speaker encoder model found in '{settings.SPEAKER_ENCODER_DIR}'"
    )


def _get_encoder() -> ECAPAModel:
    """Lazily load the trained ECAPA-TDNN model from the models/speaker_encoder/ folder."""
    global _encoder
    if _encoder is None:
        ckpt_path = _find_checkpoint_path()
        logger.info(
            "Loading trained ECAPA-TDNN speaker encoder from %s on device=%s...",
            ckpt_path,
            DEVICE,
        )
        encoder = ECAPAModel()
        ckpt = torch.load(str(ckpt_path), map_location=DEVICE, weights_only=False)
        if isinstance(ckpt, dict) and "encoder" in ckpt:
            encoder.load_state_dict(ckpt["encoder"])
        elif isinstance(ckpt, dict):
            encoder.load_state_dict(ckpt)
        encoder.to(DEVICE)
        encoder.eval()
        _encoder = encoder
    return _encoder


def get_embedding(samples: np.ndarray) -> np.ndarray:
    """
    Extract a normalized speaker embedding from a 16 kHz mono float32 array.
    Returns a 1D numpy array of shape (192,).
    """
    encoder = _get_encoder()
    mel, to_db = _get_feature_extractors()

    signal = torch.from_numpy(samples).float().to(DEVICE)
    if signal.dim() == 1:
        signal = signal.unsqueeze(0)  # shape (1, n_samples)

    # Feature extraction matching training/dataset.py: (1, n_mels, T) -> (1, T, n_mels)
    feat = to_db(mel(signal)).transpose(1, 2)
    with torch.no_grad():
        emb = encoder(feat)
        norm_emb = F.normalize(emb, dim=-1)
    return norm_emb.squeeze(0).detach().cpu().numpy()


def cosine_similarity(a: np.ndarray, b: np.ndarray) -> float:
    a, b = a.flatten(), b.flatten()
    denom = (np.linalg.norm(a) * np.linalg.norm(b)) or 1e-8
    return float(np.dot(a, b) / denom)


def verify_speaker(
    samples: np.ndarray,
    username: str | None,
    threshold: float = settings.DEFAULT_MATCH_THRESHOLD,
) -> SpeakerVerificationResult:
    """
    Compare the embedding of `samples` against `username`'s stored
    centroid. Returns is_match=None (never True) if there's no username
    or no centroid yet -- callers must treat that as "cannot verify",
    which for important commands means reject.
    """
    if not username:
        return SpeakerVerificationResult(
            speaker_id=None, is_match=None, similarity_score=None
        )

    centroid = load_centroid(username)
    if centroid is None:
        logger.warning(
            "No centroid available for user=%s (incomplete enrollment).", username
        )
        return SpeakerVerificationResult(
            speaker_id=username, is_match=None, similarity_score=None
        )

    embedding = get_embedding(samples)
    score = cosine_similarity(embedding, centroid)

    return SpeakerVerificationResult(
        speaker_id=username,
        is_match=score >= threshold,
        similarity_score=score,
    )
