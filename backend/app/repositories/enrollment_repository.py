"""
Speaker enrollment repository for embedding numpy files and centroid persistence.
"""

from __future__ import annotations

import logging
import re
import time
from pathlib import Path
from threading import Lock

import numpy as np

from app.core.config import settings
from app.db.database import read_json_file, write_json_file
from app.db.models import EmbeddingSample
from app.repositories.user_repository import EnrollmentError, get_user

logger = logging.getLogger(__name__)

_lock = Lock()


def _now_iso() -> str:
    return time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime())


def _load_users() -> dict:
    return read_json_file(settings.USERS_JSON, default={})


def _save_users(data: dict) -> None:
    write_json_file(settings.USERS_JSON, data)


def _embedding_dir(speaker_id: str) -> Path:
    return settings.ENROLLMENT_DIR / speaker_id


def _centroid_path(speaker_id: str) -> Path:
    return _embedding_dir(speaker_id) / "centroid.npy"


def add_embedding(username: str, embedding: np.ndarray) -> EmbeddingSample:
    """Save one enrollment-clip embedding, using a monotonically
    increasing, never-reused index for this user."""
    with _lock:
        users = _load_users()
        entry = users.get(username)
        if entry is None:
            raise EnrollmentError(f"Unknown user '{username}'.")

        speaker_id = entry["speaker_id"]
        embedding_dir = _embedding_dir(speaker_id)
        embedding_dir.mkdir(parents=True, exist_ok=True)

        next_index = entry.get("next_embedding_index", 0) + 1
        out_path = embedding_dir / f"embedding_{next_index:02d}.npy"
        np.save(out_path, embedding)

        entry["next_embedding_index"] = next_index
        users[username] = entry
        _save_users(users)

        return EmbeddingSample(
            index=next_index,
            filename=out_path.name,
            recorded_at=_now_iso(),
        )


def list_embeddings(username: str) -> list[EmbeddingSample]:
    record = get_user(username)
    if record is None:
        raise EnrollmentError(f"Unknown user '{username}'.")

    embedding_dir = _embedding_dir(record.speaker_id)
    if not embedding_dir.exists():
        return []

    samples = []
    for path in sorted(embedding_dir.glob("embedding_*.npy")):
        match = re.search(r"embedding_(\d+)\.npy$", path.name)
        if not match:
            continue
        samples.append(
            EmbeddingSample(
                index=int(match.group(1)),
                filename=path.name,
                recorded_at=time.strftime(
                    "%Y-%m-%dT%H:%M:%SZ", time.gmtime(path.stat().st_mtime)
                ),
            )
        )
    return samples


def delete_embedding(username: str, index: int) -> bool:
    """Deletes one embedding sample by its index. Returns False if it
    didn't exist. Does NOT recalculate the centroid -- call
    `compute_and_store_centroid` afterward."""
    record = get_user(username)
    if record is None:
        raise EnrollmentError(f"Unknown user '{username}'.")

    path = _embedding_dir(record.speaker_id) / f"embedding_{index:02d}.npy"
    if not path.exists():
        return False
    path.unlink()
    return True


def load_raw_embeddings(username: str) -> list[np.ndarray]:
    record = get_user(username)
    if record is None:
        raise EnrollmentError(f"Unknown user '{username}'.")
    embedding_dir = _embedding_dir(record.speaker_id)
    if not embedding_dir.exists():
        return []
    return [np.load(p) for p in sorted(embedding_dir.glob("embedding_*.npy"))]


def compute_and_store_centroid(
    username: str, min_required: int = settings.REQUIRED_ENROLLMENT_SAMPLES
) -> np.ndarray | None:
    """
    Recomputes the centroid from whatever embeddings currently exist on
    disk: L2-normalize(mean(embeddings)). If there are fewer than
    `min_required` embeddings, any stale centroid.npy is removed and
    None is returned instead of computing one from an insufficient set.
    """
    record = get_user(username)
    if record is None:
        raise EnrollmentError(f"Unknown user '{username}'.")

    embeddings = load_raw_embeddings(username)
    centroid_path = _centroid_path(record.speaker_id)

    if len(embeddings) < min_required:
        if centroid_path.exists():
            centroid_path.unlink()
        return None

    stacked = np.stack(embeddings, axis=0)
    mean = stacked.mean(axis=0)
    norm = np.linalg.norm(mean)
    centroid = mean / norm if norm > 0 else mean

    np.save(centroid_path, centroid)
    return centroid


def load_centroid(username: str) -> np.ndarray | None:
    record = get_user(username)
    if record is None:
        return None
    centroid_path = _centroid_path(record.speaker_id)
    if not centroid_path.exists():
        return None
    return np.load(centroid_path)


def enrollment_status(username: str) -> dict:
    """Summary used by the enrollment-management UI."""
    samples = list_embeddings(username)
    centroid = load_centroid(username)
    return {
        "samples": [
            {"index": s.index, "filename": s.filename, "recorded_at": s.recorded_at}
            for s in samples
        ],
        "sample_count": len(samples),
        "required_samples": settings.REQUIRED_ENROLLMENT_SAMPLES,
        "centroid_ready": centroid is not None,
    }
