"""
Domain entities and data structures.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

import numpy as np


@dataclass
class UserRecord:
    username: str
    name: str
    speaker_id: str
    password_hash: str
    password_salt: str
    embedding_path: str
    created_at: str
    next_embedding_index: int


@dataclass
class CommandDefinition:
    id: str
    username: str
    intent: str
    label: str
    icon: str
    description: str
    important: bool



@dataclass
class EmbeddingSample:
    index: int
    filename: str
    recorded_at: str


@dataclass
class ConvertedAudio:
    path: Path
    sample_rate: int
    channels: int
    duration_seconds: float | None = None
    samples: np.ndarray | None = None  # float32 mono, range [-1, 1], at sample_rate


@dataclass
class PipelineEvent:
    type: str
    payload: dict[str, Any] = field(default_factory=dict)


@dataclass
class RoutedIntent:
    kind: str  # "conversation" | "command"
    intent: str | None  # matched intent name, only set when kind == "command"
    entities: dict[str, Any]


@dataclass
class SpeakerVerificationResult:
    speaker_id: str | None
    is_match: bool | None
    similarity_score: float | None
