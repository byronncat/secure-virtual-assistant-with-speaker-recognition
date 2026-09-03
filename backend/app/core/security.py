"""
Security utilities: password hashing and JWT token operations.
"""

from __future__ import annotations

import hashlib
import os
import secrets
import time

import jwt
from fastapi import HTTPException, status

from app.core.config import settings


def _get_or_create_secret() -> str:
    settings.JWT_SECRET_PATH.parent.mkdir(parents=True, exist_ok=True)
    if settings.JWT_SECRET_PATH.exists():
        return settings.JWT_SECRET_PATH.read_text(encoding="utf-8").strip()

    secret = secrets.token_hex(32)
    settings.JWT_SECRET_PATH.write_text(secret, encoding="utf-8")
    return secret


_SECRET = _get_or_create_secret()


def hash_password(password: str, salt: bytes | None = None) -> tuple[str, str]:
    """Returns (hash_hex, salt_hex). Generates a fresh salt if none is given."""
    if salt is None:
        salt = os.urandom(16)
    digest = hashlib.pbkdf2_hmac(
        "sha256", password.encode("utf-8"), salt, settings.PBKDF2_ITERATIONS
    )
    return digest.hex(), salt.hex()


def verify_password(password: str, password_hash: str, password_salt: str) -> bool:
    digest, _ = hash_password(password, bytes.fromhex(password_salt))
    return digest == password_hash


def create_access_token(username: str) -> str:
    now = int(time.time())
    payload = {
        "sub": username,
        "iat": now,
        "exp": now + settings.ACCESS_TOKEN_TTL_SECONDS,
    }
    return jwt.encode(payload, _SECRET, algorithm=settings.ALGORITHM)


def decode_access_token(token: str) -> str:
    """Returns the username from a valid token, or raises HTTPException(401)."""
    try:
        payload = jwt.decode(token, _SECRET, algorithms=[settings.ALGORITHM])
    except jwt.ExpiredSignatureError:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Session expired, please log in again.",
        )
    except jwt.InvalidTokenError:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Invalid authentication token.",
        )
    username = payload.get("sub")
    if not username:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED, detail="Invalid token payload."
        )
    return username
