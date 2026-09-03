"""
FastAPI Voice Assistant backend application.
"""

from __future__ import annotations

import logging

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from app.api.router import api_router
from app.core.config import settings

logger = logging.getLogger("voice_backend")
logging.basicConfig(level=logging.INFO)
logger.info("Initializing voice backend on device: %s", settings.DEVICE)

app = FastAPI(title="Voice Backend", version="0.4.0")

app.add_middleware(
    CORSMiddleware,
    allow_origins=settings.CORS_ORIGINS,
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

app.include_router(api_router)
