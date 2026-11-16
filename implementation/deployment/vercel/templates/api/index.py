"""ASGI entrypoint for Vercel's file-based Python function layout."""

from pathlib import Path

from backend.app.main import app
from deployment_spa import register_frontend_fallback

register_frontend_fallback(app, Path(__file__).resolve().parents[1] / "frontend-index.html")
