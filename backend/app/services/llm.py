"""
Conversation LLM service for streaming free-form responses.
"""

from __future__ import annotations

from collections.abc import Iterator

from ollama import chat

from app.core.config import settings

_SYSTEM_PROMPT = """
You are a helpful, concise voice assistant. Answer naturally in the same
language the user wrote in. Keep answers short and conversational unless
the user asks for more detail.
"""


def stream_answer(text: str, language: str | None = None) -> Iterator[str]:
    """Yield response text chunks as they arrive from the model."""
    user_prompt = text
    if language:
        user_prompt = f"[respond in language={language}]\n{text}"

    stream = chat(
        model=settings.OLLAMA_MODEL,
        messages=[
            {"role": "system", "content": _SYSTEM_PROMPT},
            {"role": "user", "content": user_prompt},
        ],
        stream=True,
    )
    for chunk in stream:
        piece = chunk.message.content
        if piece:
            yield piece


def answer(text: str, language: str | None = None) -> str:
    """Non-streaming convenience wrapper (e.g. for quick tests)."""
    return "".join(stream_answer(text, language=language))
