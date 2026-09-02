"""
Persistent speaker enrollment storage (doc section 7).

Replaces the original `speaker_verification.py`'s in-memory dict with a
filesystem-backed store matching the doc's layout:

    data/
    ├── speakers.json
    └── enrollment/
        ├── speaker_001/
        │   ├── embedding_01.npy
        │   ├── embedding_02.npy
        │   └── ...
        └── speaker_002/
            └── ...

`speakers.json` never stores a plaintext password -- only a salted
PBKDF2 hash, per the doc's own revision of its section-7 example.
"""

from __future__ import annotations

import hashlib
import json
import logging
import os
import time
from dataclasses import dataclass
from pathlib import Path
from threading import Lock

import numpy as np

logger = logging.getLogger(__name__)

DATA_DIR = Path(__file__).parent / "data"
SPEAKERS_JSON = DATA_DIR / "speakers.json"
ENROLLMENT_DIR = DATA_DIR / "enrollment"

_PBKDF2_ITERATIONS = 200_000
_lock = Lock()


@dataclass
class SpeakerRecord:
    speaker_id: str
    name: str
    password_hash: str | None
    password_salt: str | None
    embedding_dir: Path
    created_at: str


def _now_iso() -> str:
    return time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime())


def hash_password(password: str, salt: bytes | None = None) -> tuple[str, str]:
    """Returns (hash_hex, salt_hex). Generates a fresh salt if none is given."""
    if salt is None:
        salt = os.urandom(16)
    digest = hashlib.pbkdf2_hmac(
        "sha256", password.encode("utf-8"), salt, _PBKDF2_ITERATIONS
    )
    return digest.hex(), salt.hex()


def verify_password(password: str, password_hash: str, password_salt: str) -> bool:
    digest, _ = hash_password(password, bytes.fromhex(password_salt))
    return digest == password_hash


def _load_speakers() -> dict:
    if not SPEAKERS_JSON.exists():
        return {}
    return json.loads(SPEAKERS_JSON.read_text(encoding="utf-8"))


def _save_speakers(data: dict) -> None:
    DATA_DIR.mkdir(parents=True, exist_ok=True)
    SPEAKERS_JSON.write_text(
        json.dumps(data, indent=2, ensure_ascii=False), encoding="utf-8"
    )


def register_speaker(
    speaker_id: str, name: str, password: str | None = None
) -> SpeakerRecord:
    """Create or update a speaker's metadata entry. Does not touch embeddings."""
    with _lock:
        speakers = _load_speakers()
        entry = speakers.get(speaker_id, {})

        password_hash = entry.get("password_hash")
        password_salt = entry.get("password_salt")
        if password:
            password_hash, password_salt = hash_password(password)

        embedding_dir = ENROLLMENT_DIR / speaker_id
        embedding_dir.mkdir(parents=True, exist_ok=True)

        entry.update(
            {
                "name": name,
                "password_hash": password_hash,
                "password_salt": password_salt,
                "embedding_path": str(embedding_dir.relative_to(DATA_DIR)),
                "created_at": entry.get("created_at", _now_iso()),
            }
        )
        speakers[speaker_id] = entry
        _save_speakers(speakers)

        return SpeakerRecord(
            speaker_id=speaker_id,
            name=name,
            password_hash=password_hash,
            password_salt=password_salt,
            embedding_dir=embedding_dir,
            created_at=entry["created_at"],
        )


def add_embedding(speaker_id: str, embedding: np.ndarray) -> Path:
    """Save one enrollment-clip embedding for a speaker. Supports multiple
    clips per speaker -- verification averages across all of them."""
    with _lock:
        speakers = _load_speakers()
        if speaker_id not in speakers:
            register_speaker(speaker_id, name=speaker_id)

        embedding_dir = ENROLLMENT_DIR / speaker_id
        embedding_dir.mkdir(parents=True, exist_ok=True)

        existing = sorted(embedding_dir.glob("embedding_*.npy"))
        next_index = len(existing) + 1
        out_path = embedding_dir / f"embedding_{next_index:02d}.npy"
        np.save(out_path, embedding)
        return out_path


def load_embeddings(speaker_id: str) -> list[np.ndarray]:
    """Load all enrolled embedding clips for a speaker. Averaging is left
    to the caller (see `speaker_verification._enrolled_embedding`)."""
    embedding_dir = ENROLLMENT_DIR / speaker_id
    if not embedding_dir.exists():
        return []
    return [np.load(p) for p in sorted(embedding_dir.glob("embedding_*.npy"))]


def is_enrolled(speaker_id: str) -> bool:
    return len(load_embeddings(speaker_id)) > 0


def get_speaker_record(speaker_id: str) -> dict | None:
    return _load_speakers().get(speaker_id)
