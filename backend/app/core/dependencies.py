"""
FastAPI dependency functions.
"""

from __future__ import annotations

from fastapi import Depends, HTTPException, status
from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer

from app.core.security import decode_access_token
from app.db.models import UserRecord
from app.repositories.user_repository import get_user

_bearer_scheme = HTTPBearer(auto_error=False)


async def get_current_user(
    credentials: HTTPAuthorizationCredentials | None = Depends(_bearer_scheme),
) -> UserRecord:
    """FastAPI dependency: resolves the bearer token to a persisted user
    record, or raises 401. This is the ONLY source of `speaker_id` used
    for security-sensitive operations (important-command verification) --
    it is never taken from request bodies, so a client can't claim to be
    someone else."""
    if credentials is None:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Not authenticated.",
            headers={"WWW-Authenticate": "Bearer"},
        )
    username = decode_access_token(credentials.credentials)
    user = get_user(username)
    if user is None:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED, detail="User no longer exists."
        )
    return user
