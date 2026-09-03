"""
Command management endpoints.
"""

from __future__ import annotations

from fastapi import APIRouter, Depends, HTTPException, status

from app.core.dependencies import get_current_user
from app.db.models import UserRecord
from app.repositories import command_repository
from app.repositories.command_repository import CommandDbError
from app.schemas.commands import CommandIn, CommandOut, CommandUpdate

router = APIRouter(prefix="/api/commands", tags=["Commands"])


@router.get("", response_model=list[CommandOut])
async def list_commands(
    current_user: UserRecord = Depends(get_current_user),
) -> list[CommandOut]:
    return [
        CommandOut(**vars(c))
        for c in command_repository.list_commands(username=current_user.username)
    ]


@router.post("", response_model=CommandOut, status_code=status.HTTP_201_CREATED)
async def create_command(
    request: CommandIn, current_user: UserRecord = Depends(get_current_user)
) -> CommandOut:
    try:
        created = command_repository.create_command(
            username=current_user.username,
            intent=request.intent,
            label=request.label,
            icon=request.icon,
            description=request.description,
            important=request.important,
        )
    except CommandDbError as exc:
        raise HTTPException(status.HTTP_400_BAD_REQUEST, str(exc)) from exc
    return CommandOut(**vars(created))


@router.put("/{intent}", response_model=CommandOut)
async def update_command(
    intent: str,
    request: CommandUpdate,
    current_user: UserRecord = Depends(get_current_user),
) -> CommandOut:
    try:
        updated = command_repository.update_command(
            username=current_user.username,
            intent=intent,
            label=request.label,
            icon=request.icon,
            description=request.description,
            important=request.important,
        )
    except CommandDbError as exc:
        raise HTTPException(status.HTTP_404_NOT_FOUND, str(exc)) from exc
    return CommandOut(**vars(updated))


@router.delete("/{intent}", status_code=status.HTTP_204_NO_CONTENT)
async def delete_command(
    intent: str, current_user: UserRecord = Depends(get_current_user)
) -> None:
    try:
        command_repository.delete_command(username=current_user.username, intent=intent)
    except CommandDbError as exc:
        raise HTTPException(status.HTTP_404_NOT_FOUND, str(exc)) from exc
