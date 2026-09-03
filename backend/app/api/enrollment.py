"""
Voice enrollment endpoints.
"""

from __future__ import annotations

from fastapi import APIRouter, Depends, File, Form, HTTPException, UploadFile, status

from app.core.dependencies import get_current_user
from app.db.models import UserRecord
from app.repositories import enrollment_repository
from app.schemas.enrollment import EnrollmentStatus
from app.services import audio_processing, speaker_verification

router = APIRouter(prefix="/api/enroll", tags=["Enrollment"])


@router.get("/status", response_model=EnrollmentStatus)
async def enrollment_status(
    current_user: UserRecord = Depends(get_current_user),
) -> EnrollmentStatus:
    return EnrollmentStatus(
        **enrollment_repository.enrollment_status(current_user.username)
    )


@router.post(
    "/samples",
    response_model=EnrollmentStatus,
    status_code=status.HTTP_201_CREATED,
)
async def add_enrollment_sample(
    audio: UploadFile = File(..., description="Raw 16-bit PCM, little-endian"),
    sample_rate: int = Form(...),
    channels: int = Form(1),
    current_user: UserRecord = Depends(get_current_user),
) -> EnrollmentStatus:
    """
    Adds one enrollment sample: computes its embedding and stores it
    under the user's enrollment directory with the next never-reused
    index, then recalculates the centroid (recalculation is a no-op,
    clearing any stale centroid, if there are still fewer than
    `REQUIRED_ENROLLMENT_SAMPLES` samples).
    """
    processed = await audio_processing.pcm_upload_to_samples(
        audio, sample_rate, channels
    )
    embedding = speaker_verification.get_embedding(processed.samples)
    enrollment_repository.add_embedding(current_user.username, embedding)
    enrollment_repository.compute_and_store_centroid(current_user.username)
    return EnrollmentStatus(
        **enrollment_repository.enrollment_status(current_user.username)
    )


@router.delete("/samples/{index}", response_model=EnrollmentStatus)
async def delete_enrollment_sample(
    index: int, current_user: UserRecord = Depends(get_current_user)
) -> EnrollmentStatus:
    """
    Deletes one sample by index and recalculates the centroid. The user
    does NOT need to re-register: they can record a replacement via
    `POST /api/enroll/samples` afterward, which gets a fresh (never
    reused) index.
    """
    deleted = enrollment_repository.delete_embedding(current_user.username, index)
    if not deleted:
        raise HTTPException(status.HTTP_404_NOT_FOUND, f"Sample {index} not found.")
    enrollment_repository.compute_and_store_centroid(current_user.username)
    return EnrollmentStatus(
        **enrollment_repository.enrollment_status(current_user.username)
    )
