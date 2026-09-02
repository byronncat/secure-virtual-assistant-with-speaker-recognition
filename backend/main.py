"""
FastAPI backend implementing the revised architecture:

    Voice: Audio -> ASR -> Correction -> Intent Router
                -> LLM (streamed)  |  Command DB + Speaker Verification
    Chat:          Text -> Correction -> Intent Router
                -> LLM (streamed)  |  Command DB + Speaker Verification

Voice and chat share the same `pipeline.py` orchestration (doc section
13), so behavior stays consistent between the two input modes. Both are
exposed as Server-Sent Events so the LLM's answer can stream into the
frontend token by token (doc section 10) instead of waiting for the
whole response.

Every stream ends with one "done" event whose payload is the unified
response contract from doc section 9:

    {text, language, speaker_id, command, rejected, answer}

Run locally:
    uvicorn main:app --reload --port 8000
"""

from __future__ import annotations

import json
import logging
from collections.abc import AsyncIterator
from pathlib import Path

from fastapi import FastAPI, File, Form, HTTPException, UploadFile, status
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import StreamingResponse
from pydantic import BaseModel

from audio_processing import AudioConversionError, convert_raw_pcm_to_16k_mono_wav_async
from pipeline import PipelineEvent, run_text_pipeline, run_voice_pipeline
from speaker_verification import enroll_speaker

logger = logging.getLogger("voice_backend")
logging.basicConfig(level=logging.INFO)

app = FastAPI(title="Voice Backend", version="0.3.0")

app.add_middleware(
    CORSMiddleware,
    allow_origins=[
        "http://localhost:3000",
        "http://127.0.0.1:3000",
    ],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

# Raw 16-bit PCM, mono: ~96KB per second at 48kHz. Cap generously for a
# voice command clip (e.g. 60s -> ~5.8MB) while guarding against abuse.
MAX_UPLOAD_BYTES = 15 * 1024 * 1024


class ChatRequest(BaseModel):
    text: str
    speaker_id: str | None = None
    language: str | None = None


class EnrollResponse(BaseModel):
    speaker_id: str
    duration_seconds: float


async def _read_capped(upload: UploadFile) -> bytes:
    chunks = []
    size = 0
    while chunk := await upload.read(1024 * 1024):
        size += len(chunk)
        if size > MAX_UPLOAD_BYTES:
            raise HTTPException(
                status_code=status.HTTP_413_REQUEST_ENTITY_TOO_LARGE,
                detail="Audio payload exceeds maximum allowed size.",
            )
        chunks.append(chunk)
    await upload.close()
    return b"".join(chunks)


def _sse_frame(event_type: str, payload: dict) -> bytes:
    """Format one SSE frame. Naming the event lets the frontend dispatch
    on `event.type` without re-parsing the payload shape each time."""
    data = json.dumps(payload, ensure_ascii=False)
    return f"event: {event_type}\ndata: {data}\n\n".encode("utf-8")


async def _stream_pipeline_events(
    events: AsyncIterator[PipelineEvent],
) -> AsyncIterator[bytes]:
    async for event in events:
        yield _sse_frame(event.type, event.payload)


@app.get("/health")
async def health() -> dict:
    return {"status": "ok"}


@app.post("/api/voice")
async def voice(
    audio: UploadFile = File(..., description="Raw 16-bit PCM, little-endian"),
    sample_rate: int = Form(
        ..., description="Sample rate the browser captured at, e.g. 48000"
    ),
    channels: int = Form(
        1, description="Number of interleaved channels in the PCM payload"
    ),
    speaker_id: str | None = Form(
        None, description="Optional speaker to verify against"
    ),
    language: str | None = Form(
        None, description="Optional ISO language hint, e.g. 'vi'"
    ),
) -> StreamingResponse:
    """
    Accepts a raw PCM clip captured by the frontend's AudioWorklet,
    resamples it to 16kHz mono, then streams ASR -> correction -> intent
    routing -> (LLM answer | command execute/reject) as Server-Sent
    Events. See `pipeline.PipelineEvent` for the event shapes.
    """
    pcm_bytes = await _read_capped(audio)
    if not pcm_bytes:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Received empty audio payload.",
        )

    try:
        processed = await convert_raw_pcm_to_16k_mono_wav_async(
            pcm_bytes,
            output_path=Path("temp.wav"),
            orig_sample_rate=sample_rate,
            channels=channels,
        )
    except AudioConversionError as exc:
        logger.exception("Failed to process raw PCM upload")
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            detail=f"Could not process audio: {exc}",
        ) from exc

    events = run_voice_pipeline(
        processed.samples, speaker_id=speaker_id, language=language
    )
    return StreamingResponse(
        _stream_pipeline_events(events), media_type="text/event-stream"
    )


@app.post("/api/chat")
async def chat(request: ChatRequest) -> StreamingResponse:
    """
    Text-in chat entry point (doc section 13). Shares the same pipeline
    as `/api/voice` minus the ASR step, so voice and chat behave
    identically for the same corrected text. Important commands typed in
    chat have no audio to verify a speaker against, so they come back
    `rejected: true` rather than skipping the security gate.
    """
    if not request.text.strip():
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Received empty text.",
        )

    events = run_text_pipeline(
        request.text, speaker_id=request.speaker_id, language=request.language
    )
    return StreamingResponse(
        _stream_pipeline_events(events), media_type="text/event-stream"
    )


@app.post("/api/enroll", response_model=EnrollResponse)
async def enroll(
    audio: UploadFile = File(..., description="Raw 16-bit PCM, little-endian"),
    sample_rate: int = Form(...),
    channels: int = Form(1),
    speaker_id: str = Form(...),
    name: str | None = Form(None, description="Display name, e.g. 'Alice'"),
    password: str | None = Form(
        None, description="Optional password; stored only as a salted hash"
    ),
) -> EnrollResponse:
    """
    Registers a speaker's voice embedding (and, optionally, a
    name/password) from an enrollment clip, persisted via
    `enrollment_store` (doc section 7). Can be called multiple times per
    speaker_id to add more enrollment clips -- verification compares
    against the mean of all of them.
    """
    pcm_bytes = await _read_capped(audio)
    if not pcm_bytes:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Received empty audio payload.",
        )

    try:
        processed = await convert_raw_pcm_to_16k_mono_wav_async(
            pcm_bytes,
            output_path=Path("temp.wav"),
            orig_sample_rate=sample_rate,
            channels=channels,
        )
    except AudioConversionError as exc:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            detail=f"Could not process audio: {exc}",
        ) from exc

    enroll_speaker(speaker_id, processed.samples, name=name, password=password)

    return EnrollResponse(
        speaker_id=speaker_id,
        duration_seconds=processed.duration_seconds or 0.0,
    )
