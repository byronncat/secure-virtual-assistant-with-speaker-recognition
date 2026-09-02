"""
Speaker verification via SpeechBrain's ECAPA-TDNN embedding model.

This is the security gate for "important" commands -- it is the only
module allowed to authenticate a speaker. `intent_router.py` and `llm.py`
may decide *what* the user wants, but never *whether they're allowed to
do it*.

A speaker's reference embedding is the mean of all their enrolled clips,
so `/api/enroll` can be called more than once per speaker to improve robustness.
"""

from __future__ import annotations

import logging
from dataclasses import dataclass

import numpy as np
import torch
from speechbrain.inference.speaker import EncoderClassifier

import enrollment_store

logger = logging.getLogger(__name__)

SAMPLE_RATE = 16_000
DEFAULT_MATCH_THRESHOLD = 0.25  # cosine similarity; tune against your enrollment data

_classifier: EncoderClassifier | None = None


def _get_classifier() -> EncoderClassifier:
    """Lazily load the ECAPA-TDNN model (downloads weights on first call)."""
    global _classifier
    if _classifier is None:
        logger.info("Loading ECAPA-TDNN speaker embedding model...")
        _classifier = EncoderClassifier.from_hparams(
            source="speechbrain/spkrec-ecapa-voxceleb",
            savedir="pretrained_models/spkrec-ecapa-voxceleb",
        )
    return _classifier


@dataclass
class SpeakerVerificationResult:
    speaker_id: str | None
    is_match: bool | None
    similarity_score: float | None


def get_embedding(samples: np.ndarray) -> torch.Tensor:
    """
    Extract a speaker embedding from a 16 kHz mono float32 array.
    Returns a 1D torch tensor.
    """
    classifier = _get_classifier()
    signal = torch.from_numpy(samples).float().unsqueeze(0)  # shape (1, n_samples)
    with torch.no_grad():
        embedding = classifier.encode_batch(signal)
    return embedding.squeeze()


def cosine_similarity(a: torch.Tensor, b: torch.Tensor) -> float:
    return torch.nn.functional.cosine_similarity(a.flatten(), b.flatten(), dim=0).item()


def enroll_speaker(
    speaker_id: str,
    samples: np.ndarray,
    name: str | None = None,
    password: str | None = None,
) -> None:
    """
    Compute the embedding for a speaker_id from an enrollment clip and
    persist it. If `name`/`password` are given, also (re)registers the
    speaker's metadata record.
    """
    if name or password:
        enrollment_store.register_speaker(speaker_id, name=name or speaker_id, password=password)
    embedding = get_embedding(samples)
    enrollment_store.add_embedding(speaker_id, embedding.cpu().numpy())


def _enrolled_embedding(speaker_id: str) -> torch.Tensor | None:
    """Mean embedding across all enrolled clips for this speaker, or None
    if the speaker has no enrollment on disk."""
    clips = enrollment_store.load_embeddings(speaker_id)
    if not clips:
        return None
    stacked = torch.stack([torch.from_numpy(c) for c in clips])
    return stacked.mean(dim=0)


def verify_speaker(
    samples: np.ndarray,
    claimed_speaker_id: str | None = None,
    threshold: float = DEFAULT_MATCH_THRESHOLD,
) -> SpeakerVerificationResult:
    """
    Compare the embedding of `samples` against the enrolled (mean)
    embedding for `claimed_speaker_id`. Returns is_match=None if the
    speaker isn't enrolled (nothing to compare against) or no
    speaker_id was given.
    """
    if claimed_speaker_id is None:
        return SpeakerVerificationResult(
            speaker_id=None, is_match=None, similarity_score=None
        )

    enrolled_embedding = _enrolled_embedding(claimed_speaker_id)
    if enrolled_embedding is None:
        logger.warning("No enrollment found for speaker_id=%s", claimed_speaker_id)
        return SpeakerVerificationResult(
            speaker_id=claimed_speaker_id, is_match=None, similarity_score=None
        )

    embedding = get_embedding(samples)
    score = cosine_similarity(embedding, enrolled_embedding)

    return SpeakerVerificationResult(
        speaker_id=claimed_speaker_id,
        is_match=score >= threshold,
        similarity_score=score,
    )