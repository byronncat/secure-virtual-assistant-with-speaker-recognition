"""
Orchestrates the full assistant pipeline:

    Audio -> ASR -> raw transcript
    (raw transcript | typed text) -> Text Correction -> corrected text
    corrected text -> Intent Router -> conversation | command
        conversation -> LLM (streamed token by token)
        command      -> Command DB lookup
                            important=False -> execute
                            important=True  -> Speaker Verification
                                                    passed -> execute
                                                    failed -> reject

Two entry points converge on the same routing logic so voice and chat
get identical behavior:

    - `run_voice_pipeline`: audio in, runs ASR first, has samples
      available for speaker verification.
    - `run_text_pipeline`: text in (chat), skips ASR. Important commands
      typed in chat have no audio to verify against, so they're rejected
      rather than silently skipping the security gate (see
      `_handle_command`).

Both are async generators yielding `PipelineEvent`s, so `main.py` can
forward LLM tokens straight onto an SSE connection as they're produced
instead of buffering the whole response.
"""

from __future__ import annotations

import asyncio
from collections.abc import AsyncIterator
from dataclasses import dataclass, field
from typing import Any

import numpy as np

import asr
import command_db
import intent_router
import llm
import speaker_verification
import text_correction


@dataclass
class PipelineEvent:
    """One increment of the pipeline's response.

    type:
        "meta"         -- sent once, as soon as text/language/intent are
                           known, before any answer text.
        "answer_chunk" -- one streamed token/piece of a conversation
                           answer. payload: {"chunk": str}
        "done"         -- terminal event. payload matches the unified
                           response contract:
                           {text, language, speaker_id, command,
                            rejected, answer}
    """

    type: str
    payload: dict[str, Any] = field(default_factory=dict)


async def run_voice_pipeline(
    samples: np.ndarray,
    speaker_id: str | None = None,
    language: str | None = None,
) -> AsyncIterator[PipelineEvent]:
    """Audio in: ASR first, then the shared routing pipeline."""
    transcription = await asyncio.to_thread(asr.audio_to_text, samples, language)
    async for event in _route_and_respond(
        raw_text=transcription["text"],
        language=language or transcription["language"],
        speaker_id=speaker_id,
        samples=samples,
    ):
        yield event


async def run_text_pipeline(
    text: str,
    speaker_id: str | None = None,
    language: str | None = None,
) -> AsyncIterator[PipelineEvent]:
    """Typed chat text in: skips ASR, otherwise identical pipeline."""
    async for event in _route_and_respond(
        raw_text=text,
        language=language,
        speaker_id=speaker_id,
        samples=None,
    ):
        yield event


async def _route_and_respond(
    raw_text: str,
    language: str | None,
    speaker_id: str | None,
    samples: np.ndarray | None,
) -> AsyncIterator[PipelineEvent]:
    corrected_text = await asyncio.to_thread(
        text_correction.correct_text, raw_text, language
    )

    if not corrected_text.strip():
        yield PipelineEvent(
            type="done",
            payload={
                "text": corrected_text,
                "language": language,
                "speaker_id": speaker_id,
                "command": None,
                "rejected": False,
                "answer": "",
            },
        )
        return

    routed = await asyncio.to_thread(intent_router.route, corrected_text)

    if routed.kind == "command":
        async for event in _handle_command(
            corrected_text, language, speaker_id, samples, routed
        ):
            yield event
        return

    async for event in _handle_conversation(corrected_text, language, speaker_id):
        yield event


async def _handle_conversation(
    corrected_text: str,
    language: str | None,
    speaker_id: str | None,
) -> AsyncIterator[PipelineEvent]:
    """Conversation branch: stream the LLM's answer token by token."""
    yield PipelineEvent(
        type="meta",
        payload={
            "text": corrected_text,
            "language": language,
            "speaker_id": speaker_id,
            "command": None,
            "rejected": False,
        },
    )

    full_answer: list[str] = []
    queue: asyncio.Queue[str | None] = asyncio.Queue()

    def _produce() -> None:
        try:
            for chunk in llm.stream_answer(corrected_text, language=language):
                queue.put_nowait(chunk)
        finally:
            queue.put_nowait(None)  # sentinel: stream finished

    producer = asyncio.create_task(asyncio.to_thread(_produce))
    while True:
        chunk = await queue.get()
        if chunk is None:
            break
        full_answer.append(chunk)
        yield PipelineEvent(type="answer_chunk", payload={"chunk": chunk})
    await producer

    yield PipelineEvent(
        type="done",
        payload={
            "text": corrected_text,
            "language": language,
            "speaker_id": speaker_id,
            "command": None,
            "rejected": False,
            "answer": "".join(full_answer),
        },
    )


async def _handle_command(
    corrected_text: str,
    language: str | None,
    speaker_id: str | None,
    samples: np.ndarray | None,
    routed: intent_router.RoutedIntent,
) -> AsyncIterator[PipelineEvent]:
    """Command branch: important commands are gated by speaker
    verification, which the LLM/intent router never controls."""
    definition = command_db.get_by_intent(
        routed.intent
    )  # guaranteed non-None by router

    base_payload = {
        "text": corrected_text,
        "language": language,
        "command": definition.intent,
    }

    yield PipelineEvent(
        type="meta",
        payload={**base_payload, "speaker_id": speaker_id, "rejected": False},
    )

    if not definition.important:
        yield PipelineEvent(
            type="done",
            payload={
                **base_payload,
                "speaker_id": speaker_id,
                "rejected": False,
                "answer": f"Đã thực hiện: {definition.description}",
            },
        )
        return

    if samples is None:
        # Chat has no audio to verify against -- an important command
        # typed in chat can't be authenticated, so it's rejected rather
        # than silently skipping the security gate.
        yield PipelineEvent(
            type="done",
            payload={
                **base_payload,
                "speaker_id": speaker_id,
                "rejected": True,
                "answer": "Lệnh này yêu cầu xác minh giọng nói qua voice, không thể thực hiện qua chat.",
            },
        )
        return

    verification = await asyncio.to_thread(
        speaker_verification.verify_speaker, samples, speaker_id
    )

    if verification.is_match:
        yield PipelineEvent(
            type="done",
            payload={
                **base_payload,
                "speaker_id": verification.speaker_id,
                "rejected": False,
                "answer": f"Đã thực hiện: {definition.description}",
            },
        )
    else:
        yield PipelineEvent(
            type="done",
            payload={
                **base_payload,
                "speaker_id": verification.speaker_id or speaker_id or "unknown",
                "rejected": True,
                "answer": "Tôi không thể xác minh người nói cho command này.",
            },
        )
