"""
Simple JSON-backed command database (see doc section 4).

Each command entry:

    {
      "id": "cmd_001",
      "intent": "open_door",
      "description": "Open the main door",
      "important": true
    }

In production, swap this module's internals for a real database -- the
read API (`get_by_intent`, `list_intents`) is what the rest of the
pipeline depends on, so callers don't need to change.
"""

from __future__ import annotations

import json
import logging
from dataclasses import dataclass
from pathlib import Path
from threading import Lock

logger = logging.getLogger(__name__)

DB_PATH = Path(__file__).parent / "data" / "commands.json"

_lock = Lock()
_cache: dict[str, "CommandDefinition"] | None = None


@dataclass
class CommandDefinition:
    id: str
    intent: str
    description: str
    important: bool


def _load() -> dict[str, CommandDefinition]:
    global _cache
    with _lock:
        if _cache is not None:
            return _cache

        if not DB_PATH.exists():
            logger.warning("Command DB not found at %s; starting empty.", DB_PATH)
            _cache = {}
            return _cache

        raw = json.loads(DB_PATH.read_text(encoding="utf-8"))
        _cache = {
            entry["intent"]: CommandDefinition(
                id=entry["id"],
                intent=entry["intent"],
                description=entry.get("description", ""),
                important=bool(entry.get("important", False)),
            )
            for entry in raw
        }
        return _cache


def reload() -> None:
    """Force the next lookup to re-read commands.json from disk."""
    global _cache
    with _lock:
        _cache = None


def get_by_intent(intent: str) -> CommandDefinition | None:
    return _load().get(intent)


def list_intents() -> list[str]:
    return list(_load().keys())


def list_commands() -> list[CommandDefinition]:
    return list(_load().values())
