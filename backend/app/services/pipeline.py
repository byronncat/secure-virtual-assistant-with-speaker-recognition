"""
Voice and text assistant pipeline orchestrator.
"""

from __future__ import annotations

import asyncio
import json
import queue as _queue
from collections.abc import AsyncIterator

import numpy as np

from app.db.models import PipelineEvent, RoutedIntent
from app.repositories import command_repository
from app.services import (
    asr,
    intent_router,
    llm,
    memory,
    speaker_verification,
    text_correction,
)


def sse_frame(event_type: str, payload: dict) -> bytes:
    data = json.dumps(payload, ensure_ascii=False)
    return f"event: {event_type}\ndata: {data}\n\n".encode("utf-8")


async def stream_pipeline_events(
    events: AsyncIterator[PipelineEvent],
) -> AsyncIterator[bytes]:
    async for event in events:
        yield sse_frame(event.type, event.payload)


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

    routed = await asyncio.to_thread(
        intent_router.route, corrected_text, username=speaker_id
    )

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
    # Retrieve user-specific memories for personalization if authenticated
    retrieved_memories: list[str] = []
    if speaker_id:
        retrieved_memories = await asyncio.to_thread(
            memory.retrieve_relevant_memories, speaker_id, corrected_text
        )

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

    # `llm.stream_answer` is a blocking generator (network calls under the
    # hood), so it has to run in a worker thread to avoid blocking the
    # event loop. asyncio.Queue is NOT thread-safe to write to from a
    # non-event-loop thread (its internal wakeup isn't guaranteed to fire
    # cross-thread), so we bridge with a plain thread-safe `queue.Queue`
    # instead and poll it via `asyncio.to_thread`.
    thread_safe_queue: _queue.Queue[str | None] = _queue.Queue()

    def _produce() -> None:
        try:
            for chunk in llm.stream_answer(
                corrected_text,
                language=language,
                memories=retrieved_memories,
            ):
                thread_safe_queue.put(chunk)
        finally:
            thread_safe_queue.put(None)  # sentinel: stream finished

    producer = asyncio.create_task(asyncio.to_thread(_produce))
    while True:
        chunk = await asyncio.to_thread(thread_safe_queue.get)
        if chunk is None:
            break
        full_answer.append(chunk)
        yield PipelineEvent(type="answer_chunk", payload={"chunk": chunk})
    await producer

    completed_answer = "".join(full_answer)

    # Schedule background memory extraction without delaying the 'done' event
    if speaker_id and completed_answer.strip():
        asyncio.create_task(
            memory.extract_and_save_async(speaker_id, corrected_text, completed_answer)
        )

    yield PipelineEvent(
        type="done",
        payload={
            "text": corrected_text,
            "language": language,
            "speaker_id": speaker_id,
            "command": None,
            "rejected": False,
            "answer": completed_answer,
        },
    )


async def _handle_command(
    corrected_text: str,
    language: str | None,
    speaker_id: str | None,
    samples: np.ndarray | None,
    routed: RoutedIntent,
) -> AsyncIterator[PipelineEvent]:
    """Command branch: important commands are gated by speaker
    verification, which the LLM/intent router never controls."""
    definition = command_repository.get_by_intent(
        routed.intent, username=speaker_id
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
