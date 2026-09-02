"""
Authentication endpoints.
"""

from __future__ import annotations

from fastapi import APIRouter, Depends, HTTPException, status

from app.core.dependencies import get_current_user
from app.core.security import create_access_token
from app.db.models import UserRecord
from app.repositories import user_repository
from app.repositories.user_repository import EnrollmentError
from app.schemas.auth import AuthResponse, LoginRequest, RegisterRequest, UserPublic

router = APIRouter(prefix="/api/auth", tags=["Auth"])


def _user_public(user: UserRecord) -> UserPublic:
    return UserPublic(
        username=user.username,
        name=user.name,
        speaker_id=user.speaker_id,
        created_at=user.created_at,
    )


@router.post(
    "/register",
    response_model=AuthResponse,
    status_code=status.HTTP_201_CREATED,
)
async def register(request: RegisterRequest) -> AuthResponse:
    """Creates the account (username/name/password) only -- no voice
    samples yet. The frontend follows this immediately with the
    enrollment wizard using the returned token, so registration and
    voice enrollment are two steps of one flow but two separate calls
    (you can also finish enrollment later)."""
    try:
        user = user_repository.create_user(
            username=request.username, name=request.name, password=request.password
        )
    except EnrollmentError as exc:
        raise HTTPException(status.HTTP_400_BAD_REQUEST, str(exc)) from exc

    token = create_access_token(user.username)
    return AuthResponse(access_token=token, user=_user_public(user))


@router.post("/login", response_model=AuthResponse)
async def login(request: LoginRequest) -> AuthResponse:
    user = user_repository.authenticate(request.username, request.password)
    if user is None:
        raise HTTPException(
            status.HTTP_401_UNAUTHORIZED, "Invalid username or password."
        )
    token = create_access_token(user.username)
    return AuthResponse(access_token=token, user=_user_public(user))


@router.get("/me", response_model=UserPublic)
async def me(current_user: UserRecord = Depends(get_current_user)) -> UserPublic:
    """Frontend calls this on load to validate a persisted token and
    restore the session, rather than trusting an unverified local copy."""
    return _user_public(current_user)


@router.post("/logout", status_code=status.HTTP_204_NO_CONTENT)
async def logout(current_user: UserRecord = Depends(get_current_user)) -> None:
    return None
