"""
FastAPI backend entry point.

Run locally:
    uvicorn app.main:app --reload --port 8000
    # or
    uvicorn main:app --reload --port 8000
"""

from app.main import app

__all__ = ["app"]
