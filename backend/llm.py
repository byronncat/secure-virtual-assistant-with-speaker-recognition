"""
Conversation LLM: free-form streaming answers for anything routed as
"conversation" by `intent_router.py`.

`stream_answer` is a generator so `main.py` can forward tokens straight
onto an SSE connection as they're produced, instead of waiting for the
full response before replying.

(Intent/command extraction now lives in `intent_router.py` + a
`command_db` lookup rather than here -- this module is conversation-only.)
"""

from __future__ import annotations

from collections.abc import Iterator

from ollama import chat

MODEL = "llama3.1:8b"

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
        model=MODEL,
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


if __name__ == "__main__":
    # Quick manual test: python -m llm
    for piece in stream_answer("Hôm nay thứ mấy?", language="vi"):
        print(piece, end="", flush=True)
    print()
