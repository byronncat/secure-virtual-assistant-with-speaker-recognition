"""
Conversation LLM service for streaming free-form responses.
"""

from __future__ import annotations

from collections.abc import Iterator

from ollama import chat

from app.core.config import settings

_BASE_SYSTEM_PROMPT = """
You are a helpful, concise voice assistant. Answer naturally in the same
language the user wrote in. Keep answers short and conversational unless
the user asks for more detail.
"""


def _build_system_prompt(memories: list[str] | None = None) -> str:
    if not memories:
        return _BASE_SYSTEM_PROMPT.strip()

    mem_bullets = "\n".join(f"- {m}" for m in memories)
    return (
        f"{_BASE_SYSTEM_PROMPT.strip()}\n\n"
        "Relevant user profile & persistent memories:\n"
        f"{mem_bullets}\n\n"
        "Guidelines for personalization:\n"
        "- Use the above user memories naturally to tailor your answers.\n"
        "- Do not explicitly announce 'According to my memory' or 'You told me earlier' unless the user asks."
    )


def stream_answer(
    text: str,
    language: str | None = None,
    memories: list[str] | None = None,
) -> Iterator[str]:
    """Yield response text chunks as they arrive from the model."""
    user_prompt = text
    if language:
        user_prompt = f"[respond in language={language}]\n{text}"

    system_prompt = _build_system_prompt(memories)

    stream = chat(
        model=settings.OLLAMA_MODEL,
        messages=[
            {"role": "system", "content": system_prompt},
            {"role": "user", "content": user_prompt},
        ],
        stream=True,
    )
    for chunk in stream:
        piece = chunk.message.content
        if piece:
            yield piece


def answer(
    text: str,
    language: str | None = None,
    memories: list[str] | None = None,
) -> str:
    """Non-streaming convenience wrapper (e.g. for quick tests)."""
    return "".join(stream_answer(text, language=language, memories=memories))
