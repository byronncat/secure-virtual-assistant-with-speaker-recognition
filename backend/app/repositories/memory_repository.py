"""
Memory database repository for storing and managing user-specific memories in memories.json.
"""

from __future__ import annotations

import logging
import time
import uuid
from threading import RLock

from app.core.config import settings
from app.db.database import read_json_file, write_json_file
from app.db.models import MemoryRecord

logger = logging.getLogger(__name__)

_lock = RLock()
_cache: list[MemoryRecord] | None = None


def _now_iso() -> str:
    return time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime())


def _read_raw() -> list[dict]:
    return read_json_file(settings.MEMORIES_JSON, default=[])


def _write_raw(entries: list[dict]) -> None:
    write_json_file(settings.MEMORIES_JSON, entries)


def _load() -> list[MemoryRecord]:
    global _cache
    with _lock:
        if _cache is not None:
            return _cache
        raw = _read_raw()
        _cache = [
            MemoryRecord(
                id=entry["id"],
                username=entry["username"],
                content=entry["content"],
                category=entry.get("category", "general"),
                created_at=entry.get("created_at", ""),
                updated_at=entry.get("updated_at", ""),
            )
            for entry in raw
        ]
        return _cache


def reload() -> None:
    """Force the next lookup to re-read memories.json from disk."""
    global _cache
    with _lock:
        _cache = None


def list_memories(username: str) -> list[MemoryRecord]:
    """Return all stored memories for the given user."""
    return [m for m in _load() if m.username == username]


def get_memory(memory_id: str, username: str | None = None) -> MemoryRecord | None:
    """Retrieve a single memory by ID (optionally scoped to a username)."""
    for m in _load():
        if m.id == memory_id:
            if username is None or m.username == username:
                return m
    return None


def add_memory(
    username: str,
    content: str,
    category: str = "general",
) -> MemoryRecord:
    """Add a new memory for a user."""
    clean_content = content.strip()
    if not clean_content:
        raise ValueError("Memory content cannot be empty.")

    now = _now_iso()
    new_entry = {
        "id": f"mem_{uuid.uuid4().hex[:10]}",
        "username": username,
        "content": clean_content,
        "category": category or "general",
        "created_at": now,
        "updated_at": now,
    }

    with _lock:
        entries = _read_raw()
        entries.append(new_entry)
        _write_raw(entries)
        reload()
        return MemoryRecord(**new_entry)


def add_memories_batch(
    username: str,
    items: list[dict],
) -> list[MemoryRecord]:
    """Add multiple memories in a single disk write."""
    valid_entries: list[dict] = []
    now = _now_iso()

    for it in items:
        text = it.get("content", "").strip()
        if not text:
            continue
        valid_entries.append(
            {
                "id": f"mem_{uuid.uuid4().hex[:10]}",
                "username": username,
                "content": text,
                "category": it.get("category", "general") or "general",
                "created_at": now,
                "updated_at": now,
            }
        )

    if not valid_entries:
        return []

    with _lock:
        entries = _read_raw()
        entries.extend(valid_entries)
        _write_raw(entries)
        reload()
        return [MemoryRecord(**entry) for entry in valid_entries]


def update_memory(
    memory_id: str,
    username: str,
    content: str | None = None,
    category: str | None = None,
) -> MemoryRecord | None:
    """Update an existing memory's content or category."""
    with _lock:
        entries = _read_raw()
        for entry in entries:
            if entry["id"] == memory_id and entry.get("username") == username:
                if content is not None:
                    entry["content"] = content.strip()
                if category is not None:
                    entry["category"] = category
                entry["updated_at"] = _now_iso()
                _write_raw(entries)
                reload()
                return MemoryRecord(**entry)
        return None


def delete_memory(memory_id: str, username: str) -> bool:
    """Delete a specific memory belonging to the user."""
    with _lock:
        entries = _read_raw()
        remaining = [
            e
            for e in entries
            if not (e["id"] == memory_id and e.get("username") == username)
        ]
        if len(remaining) == len(entries):
            return False
        _write_raw(remaining)
        reload()
        return True


def delete_all_memories(username: str) -> int:
    """Clear all memories for a user, returning the count of deleted items."""
    with _lock:
        entries = _read_raw()
        remaining = [e for e in entries if e.get("username") != username]
        deleted_count = len(entries) - len(remaining)
        if deleted_count > 0:
            _write_raw(remaining)
            reload()
        return deleted_count


def search_memories(username: str, query: str, limit: int = 5) -> list[MemoryRecord]:
    """Simple substring/keyword memory lookup."""
    terms = [t.lower() for t in query.split() if len(t) > 1]
    memories = list_memories(username)
    if not terms:
        return memories[:limit]

    scored: list[tuple[int, MemoryRecord]] = []
    for m in memories:
        text_lower = m.content.lower()
        score = sum(1 for t in terms if t in text_lower)
        if score > 0:
            scored.append((score, m))

    scored.sort(key=lambda x: x[0], reverse=True)
    return [m for _, m in scored[:limit]]
