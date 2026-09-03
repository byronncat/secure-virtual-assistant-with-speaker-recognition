"""
Command database repository for managing registered intents in commands.json.
"""

from __future__ import annotations

import logging
import re
import uuid
from threading import RLock

from app.core.config import settings
from app.db.database import read_json_file, write_json_file
from app.db.models import CommandDefinition

logger = logging.getLogger(__name__)

_INTENT_RE = re.compile(r"^[a-z][a-z0-9_]{1,63}$")
_lock = RLock()
_cache: list[CommandDefinition] | None = None

DEFAULT_COMMANDS: list[dict] = []


class CommandDbError(Exception):
    """Raised for invalid/duplicate intents or unknown command lookups."""


def _read_raw() -> list[dict]:
    return read_json_file(settings.COMMANDS_JSON, default=[])


def _write_raw(entries: list[dict]) -> None:
    write_json_file(settings.COMMANDS_JSON, entries)


def _load() -> list[CommandDefinition]:
    global _cache
    with _lock:
        if _cache is not None:
            return _cache
        raw = _read_raw()
        _cache = [
            CommandDefinition(
                id=entry["id"],
                username=entry.get("username", ""),
                intent=entry["intent"],
                label=entry.get("label", entry["intent"]),
                icon=entry.get("icon", "Terminal"),
                description=entry.get("description", ""),
                important=bool(entry.get("important", False)),
            )
            for entry in raw
        ]
        return _cache


def reload() -> None:
    """Force the next lookup to re-read commands.json from disk."""
    global _cache
    with _lock:
        _cache = None


def get_by_intent(intent: str, username: str | None = None) -> CommandDefinition | None:
    for cmd in _load():
        if cmd.intent == intent:
            if username is None or cmd.username == username:
                return cmd
    return None


def list_intents(username: str | None = None) -> list[str]:
    return [c.intent for c in list_commands(username=username)]


def list_commands(username: str | None = None) -> list[CommandDefinition]:
    commands = _load()
    if username is not None:
        return [c for c in commands if c.username == username]
    return list(commands)


def create_command(
    username: str,
    intent: str,
    label: str,
    icon: str,
    description: str,
    important: bool,
) -> CommandDefinition:
    if not _INTENT_RE.match(intent):
        raise CommandDbError(
            "Intent must be lowercase snake_case, e.g. 'open_door' (2-64 chars)."
        )

    with _lock:
        entries = _read_raw()
        if any(
            e.get("username") == username and e["intent"] == intent for e in entries
        ):
            raise CommandDbError(f"Intent '{intent}' already exists.")

        new_entry = {
            "id": f"cmd_{uuid.uuid4().hex[:8]}",
            "username": username,
            "intent": intent,
            "label": label or intent,
            "icon": icon or "Terminal",
            "description": description,
            "important": important,
        }
        entries.append(new_entry)
        _write_raw(entries)
        reload()
        return CommandDefinition(**new_entry)


def update_command(
    username: str,
    intent: str,
    label: str | None = None,
    icon: str | None = None,
    description: str | None = None,
    important: bool | None = None,
) -> CommandDefinition:
    with _lock:
        entries = _read_raw()
        for entry in entries:
            if entry.get("username") == username and entry["intent"] == intent:
                if label is not None:
                    entry["label"] = label
                if icon is not None:
                    entry["icon"] = icon
                if description is not None:
                    entry["description"] = description
                if important is not None:
                    entry["important"] = important
                _write_raw(entries)
                reload()
                return CommandDefinition(
                    id=entry["id"],
                    username=entry.get("username", username),
                    intent=entry["intent"],
                    label=entry.get("label", entry["intent"]),
                    icon=entry.get("icon", "Terminal"),
                    description=entry["description"],
                    important=bool(entry["important"]),
                )
        raise CommandDbError(f"Intent '{intent}' not found.")


def delete_command(username: str, intent: str) -> None:
    with _lock:
        entries = _read_raw()
        remaining = [
            e
            for e in entries
            if not (e.get("username") == username and e["intent"] == intent)
        ]
        if len(remaining) == len(entries):
            raise CommandDbError(f"Intent '{intent}' not found.")
        _write_raw(remaining)
        reload()


def seed_default_commands(username: str) -> list[CommandDefinition]:
    """Seed the default set of commands for a new user if not already seeded."""
    with _lock:
        entries = _read_raw()
        existing_intents = {
            e["intent"] for e in entries if e.get("username") == username
        }
        created = []
        for def_cmd in DEFAULT_COMMANDS:
            if def_cmd["intent"] not in existing_intents:
                entry = {
                    "id": f"cmd_{uuid.uuid4().hex[:8]}",
                    "username": username,
                    "intent": def_cmd["intent"],
                    "label": def_cmd["label"],
                    "icon": def_cmd["icon"],
                    "description": def_cmd["description"],
                    "important": def_cmd["important"],
                }
                entries.append(entry)
                created.append(CommandDefinition(**entry))
        if created:
            _write_raw(entries)
            reload()
        return created
