"""
Voice enrollment workflow service coordinating embeddings and centroid calculation.
"""

from __future__ import annotations

import numpy as np

from app.repositories.enrollment_repository import (
    add_embedding,
    compute_and_store_centroid,
    delete_embedding,
    enrollment_status,
)
from app.services.speaker_verification import get_embedding


def add_sample_and_update_centroid(username: str, samples: np.ndarray) -> dict:
    """Computes embedding from audio samples, saves it, and updates centroid."""
    embedding = get_embedding(samples)
    add_embedding(username, embedding)
    compute_and_store_centroid(username)
    return enrollment_status(username)


def delete_sample_and_update_centroid(username: str, index: int) -> dict | None:
    """Deletes sample at index and updates centroid. Returns None if sample wasn't found."""
    deleted = delete_embedding(username, index)
    if not deleted:
        return None
    compute_and_store_centroid(username)
    return enrollment_status(username)


def get_enrollment_status(username: str) -> dict:
    """Retrieves current enrollment progress for user."""
    return enrollment_status(username)
