"""
Central API router combining all route endpoints.
"""

from __future__ import annotations

from fastapi import APIRouter

from app.api.auth import router as auth_router
from app.api.chat import router as chat_router
from app.api.commands import router as commands_router
from app.api.enrollment import router as enrollment_router
from app.api.health import router as health_router
from app.api.memories import router as memories_router

api_router = APIRouter()

api_router.include_router(health_router)
api_router.include_router(auth_router)
api_router.include_router(enrollment_router)
api_router.include_router(commands_router)
api_router.include_router(chat_router)
api_router.include_router(memories_router)
