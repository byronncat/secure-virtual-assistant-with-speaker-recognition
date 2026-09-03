"""
API endpoints for user memory and personalization management.
"""

from __future__ import annotations

from fastapi import APIRouter, Depends, HTTPException, status

from app.core.dependencies import get_current_user
from app.db.models import UserRecord
from app.repositories import memory_repository
from app.schemas.memory import MemoryIn, MemoryListOut, MemoryOut, MemoryUpdate

router = APIRouter(prefix="/api/memories", tags=["Memories"])


def _to_schema(m) -> MemoryOut:
    return MemoryOut(
        id=m.id,
        username=m.username,
        content=m.content,
        category=m.category,
        created_at=m.created_at,
        updated_at=m.updated_at,
    )


@router.get("", response_model=MemoryListOut)
async def list_user_memories(
    current_user: UserRecord = Depends(get_current_user),
) -> MemoryListOut:
    """List all stored memories and preferences for the current user."""
    memories = memory_repository.list_memories(current_user.username)
    return MemoryListOut(
        memories=[_to_schema(m) for m in memories],
        total=len(memories),
    )


@router.post("", response_model=MemoryOut, status_code=status.HTTP_201_CREATED)
async def create_user_memory(
    payload: MemoryIn,
    current_user: UserRecord = Depends(get_current_user),
) -> MemoryOut:
    """Manually add a memory or preference for the current user."""
    try:
        record = memory_repository.add_memory(
            username=current_user.username,
            content=payload.content,
            category=payload.category,
        )
        return _to_schema(record)
    except ValueError as exc:
        raise HTTPException(status.HTTP_400_BAD_REQUEST, str(exc)) from exc


@router.put("/{memory_id}", response_model=MemoryOut)
async def update_user_memory(
    memory_id: str,
    payload: MemoryUpdate,
    current_user: UserRecord = Depends(get_current_user),
) -> MemoryOut:
    """Update an existing memory's content or category."""
    updated = memory_repository.update_memory(
        memory_id=memory_id,
        username=current_user.username,
        content=payload.content,
        category=payload.category,
    )
    if not updated:
        raise HTTPException(
            status.HTTP_404_NOT_FOUND,
            f"Memory '{memory_id}' not found.",
        )
    return _to_schema(updated)


@router.delete("/{memory_id}", status_code=status.HTTP_204_NO_CONTENT)
async def delete_user_memory(
    memory_id: str,
    current_user: UserRecord = Depends(get_current_user),
) -> None:
    """Delete a specific memory belonging to the current user."""
    deleted = memory_repository.delete_memory(memory_id, current_user.username)
    if not deleted:
        raise HTTPException(
            status.HTTP_404_NOT_FOUND,
            f"Memory '{memory_id}' not found.",
        )


@router.delete("", response_model=dict[str, int])
async def clear_all_user_memories(
    current_user: UserRecord = Depends(get_current_user),
) -> dict[str, int]:
    """Clear all memories belonging to the current user."""
    count = memory_repository.delete_all_memories(current_user.username)
    return {"deleted": count}
