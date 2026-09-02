"""
Assistant voice and chat streaming (SSE) endpoints.
"""

from __future__ import annotations

from fastapi import APIRouter, Depends, File, Form, HTTPException, UploadFile, status
from fastapi.responses import StreamingResponse

from app.core.dependencies import get_current_user
from app.db.models import UserRecord
from app.schemas.chat import ChatRequest
from app.services import audio_processing
from app.services.pipeline import (
    run_text_pipeline,
    run_voice_pipeline,
    stream_pipeline_events,
)

router = APIRouter(prefix="/api", tags=["Assistant"])


@router.post("/voice")
async def voice(
    audio: UploadFile = File(..., description="Raw 16-bit PCM, little-endian"),
    sample_rate: int = Form(
        ..., description="Sample rate the browser captured at, e.g. 48000"
    ),
    channels: int = Form(
        1, description="Number of interleaved channels in the PCM payload"
    ),
    language: str | None = Form(
        None, description="Optional ISO language hint, e.g. 'vi'"
    ),
    current_user: UserRecord = Depends(get_current_user),
) -> StreamingResponse:
    """
    Accepts a raw PCM clip, resamples it to 16kHz mono, then streams
    ASR -> correction -> intent routing -> (LLM answer | command
    execute/reject) as Server-Sent Events. `speaker_id` for verification
    is always the authenticated user, never a request field.
    """
    processed = await audio_processing.pcm_upload_to_samples(
        audio, sample_rate, channels
    )
    events = run_voice_pipeline(
        processed.samples, speaker_id=current_user.username, language=language
    )
    return StreamingResponse(
        stream_pipeline_events(events), media_type="text/event-stream"
    )


@router.post("/chat")
async def chat(
    request: ChatRequest, current_user: UserRecord = Depends(get_current_user)
) -> StreamingResponse:
    """
    Text-in chat entry point, sharing the same pipeline as `/api/voice`
    minus the ASR step. Important commands typed in chat
    have no audio to verify a speaker against, so they come back
    `rejected: true` rather than skipping the security gate -- being
    logged in is not sufficient to run an important command by text.
    """
    if not request.text.strip():
        raise HTTPException(status.HTTP_400_BAD_REQUEST, "Received empty text.")

    events = run_text_pipeline(
        request.text, speaker_id=current_user.username, language=request.language
    )
    return StreamingResponse(
        stream_pipeline_events(events), media_type="text/event-stream"
    )
