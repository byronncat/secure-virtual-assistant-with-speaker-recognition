"""
Pydantic schemas for memory management.
"""

from __future__ import annotations

from pydantic import BaseModel, Field


class MemoryIn(BaseModel):
    content: str = Field(
        ...,
        min_length=1,
        description="Fact, preference, or useful personal note about the user",
    )
    category: str = Field(
        "general",
        description="Category of the memory (e.g. preference, personal_fact, work, habit)",
    )


class MemoryUpdate(BaseModel):
    content: str | None = Field(None, min_length=1, description="Updated memory text")
    category: str | None = Field(None, description="Updated memory category")


class MemoryOut(BaseModel):
    id: str
    username: str
    content: str
    category: str
    created_at: str
    updated_at: str


class MemoryListOut(BaseModel):
    memories: list[MemoryOut]
    total: int
