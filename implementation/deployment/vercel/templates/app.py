"""Deployment entrypoint; the complete coordinator owns API and WebSocket routes."""

from pathlib import Path

from backend.app.main import app
from deployment_spa import register_frontend_fallback

register_frontend_fallback(app, Path(__file__).with_name("frontend-index.html"))
