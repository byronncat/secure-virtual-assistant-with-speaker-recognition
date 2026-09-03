"""
Enrollment request and response schemas.
"""

from __future__ import annotations

from pydantic import BaseModel


class EnrollmentSampleOut(BaseModel):
    index: int
    filename: str
    recorded_at: str


class EnrollmentStatus(BaseModel):
    samples: list[EnrollmentSampleOut]
    sample_count: int
    required_samples: int
    centroid_ready: bool
