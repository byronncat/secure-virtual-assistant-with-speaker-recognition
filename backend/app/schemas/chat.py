"""
Chat and assistant request schemas.
"""

from __future__ import annotations

from pydantic import BaseModel


class ChatRequest(BaseModel):
    text: str
    language: str | None = None
