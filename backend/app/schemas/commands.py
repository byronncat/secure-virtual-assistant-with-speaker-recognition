"""
Command request and response schemas.
"""

from __future__ import annotations

from pydantic import BaseModel


class CommandIn(BaseModel):
    intent: str
    label: str
    icon: str = "Terminal"
    description: str
    important: bool = False


class CommandUpdate(BaseModel):
    label: str | None = None
    icon: str | None = None
    description: str | None = None
    important: bool | None = None


class CommandOut(BaseModel):
    id: str
    intent: str
    label: str
    icon: str
    description: str
    important: bool
