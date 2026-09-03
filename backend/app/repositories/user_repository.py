"""
User account repository handling users.json persistence and authentication.
"""

from __future__ import annotations

import logging
import re
import time
from threading import Lock

from app.core.config import settings
from app.core.security import hash_password, verify_password
from app.db.database import read_json_file, write_json_file
from app.db.models import UserRecord

logger = logging.getLogger(__name__)

_USERNAME_RE = re.compile(r"^[a-zA-Z0-9_.-]{3,64}$")
_lock = Lock()


class EnrollmentError(Exception):
    """Raised for invalid usernames, duplicate accounts, unknown users, etc."""


UserError = EnrollmentError


def _now_iso() -> str:
    return time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime())


def _load_users() -> dict:
    return read_json_file(settings.USERS_JSON, default={})


def _save_users(data: dict) -> None:
    write_json_file(settings.USERS_JSON, data)


def _to_record(username: str, entry: dict) -> UserRecord:
    return UserRecord(
        username=username,
        name=entry["name"],
        speaker_id=entry["speaker_id"],
        password_hash=entry["password_hash"],
        password_salt=entry["password_salt"],
        embedding_path=entry["embedding_path"],
        created_at=entry["created_at"],
        next_embedding_index=entry.get("next_embedding_index", 0),
    )


def create_user(username: str, name: str, password: str) -> UserRecord:
    """Creates a new account (no embeddings yet). Raises EnrollmentError if
    the username is invalid or already taken."""
    if not _USERNAME_RE.match(username):
        raise EnrollmentError(
            "Username must be 3-64 characters: letters, numbers, '.', '_', '-'."
        )
    if not password or len(password) < 6:
        raise EnrollmentError("Password must be at least 6 characters.")

    with _lock:
        users = _load_users()
        if username in users:
            raise EnrollmentError(f"Username '{username}' is already taken.")

        password_hash, password_salt = hash_password(password)
        speaker_id = username  # one user == one speaker in this app
        embedding_dir = settings.ENROLLMENT_DIR / speaker_id
        embedding_dir.mkdir(parents=True, exist_ok=True)

        entry = {
            "name": name,
            "speaker_id": speaker_id,
            "password_hash": password_hash,
            "password_salt": password_salt,
            "embedding_path": str(embedding_dir.relative_to(settings.DATA_DIR)),
            "created_at": _now_iso(),
            "next_embedding_index": 0,
        }
        users[username] = entry
        _save_users(users)

        # Seed default commands for the new user
        from app.repositories import command_repository

        command_repository.seed_default_commands(username)

        return _to_record(username, entry)


def get_user(username: str) -> UserRecord | None:
    entry = _load_users().get(username)
    return _to_record(username, entry) if entry else None


def authenticate(username: str, password: str) -> UserRecord | None:
    record = get_user(username)
    if record is None:
        return None
    if not verify_password(password, record.password_hash, record.password_salt):
        return None
    return record
