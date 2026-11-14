"""FastAPI application factory for the coordinator service (`backend/app/main.py`).

Mounts both:
- `/api/v1/meta/*` (`routes_meta.router`, preserving 100% of P0 health, branding, exercises, and demo-presets contracts)
- `/api/v1/*` (`routes_sessions.router`, providing P3–P7 sessions, CAS code updates, spec ack, challenges, turns, confirm-claim, hints, playback-ack, cancel, traces, export, delete, and capacity endpoints)
"""

from contextlib import asynccontextmanager, closing
from typing import AsyncIterator
import uuid

from fastapi import FastAPI, Request, Response
from fastapi.middleware.cors import CORSMiddleware

from backend.app.api.routes_meta import router as meta_router
from backend.app.core.branding import get_branding
from backend.app.core.config import Settings, get_settings, request_settings
from backend.app.core.errors import register_exception_handlers
from backend.app.core.logging import configure_logging, get_logger, reset_request_id, set_request_id

from backend.app.api.routes_sessions import router as sessions_router
from backend.app.api.session_security import install_session_security

_LOGGER = get_logger("vcc.main")


def create_app(settings: Settings | None = None, *, include_session_routes: bool = True) -> FastAPI:
    """Create and configure the FastAPI coordinator application."""
    active_settings = settings or get_settings()
    configure_logging(active_settings.log_level)

    @asynccontextmanager
    async def lifespan(_app: FastAPI) -> AsyncIterator[None]:
        branding = get_branding(active_settings.branding_config_path)
        _LOGGER.info(
            "Coordinator starting",
            extra={
                "env": active_settings.env,
                "phase": "P0-P9",
                "product_name": branding.productName,
                "custom_code_execution_enabled": active_settings.allow_public_custom_code,
            },
        )
        from backend.app.speech.service import SpeechService
        from backend.app.db.repository import SQLiteRepository
        from backend.app.operations.retention import RetentionService
        from backend.app.orchestration.worker_client import WorkerClient
        repository = SQLiteRepository(active_settings.database_path)
        repository.initialize()
        from backend.app.repo_learning.service import recover_incomplete
        recover_incomplete(active_settings.database_path)
        from backend.app.db.migrations import open_connection
        with closing(open_connection(active_settings.database_path)) as db:
            db.execute('BEGIN IMMEDIATE')
            db.execute("UPDATE studio_speech_usage SET status='UNCERTAIN' WHERE status='RESERVED'")
            from backend.app.studio.model_budget import recover
            recover(db)
            db.commit()
        _app.state.speech = SpeechService(db_path=active_settings.database_path, cache_dir=active_settings.tts_cache_dir,
            api_key=active_settings.gnani_api_key.get_secret_value() if active_settings.gnani_api_key else None, settings=active_settings)
        cancellation_worker = None
        if active_settings.internal_worker_secret:
            cancellation_worker = WorkerClient(
                base_url=active_settings.exec_worker_url,
                internal_worker_secret=active_settings.internal_worker_secret.get_secret_value(),
                allow_public_custom_code=False, session_repository=repository,
            )
        _app.state.retention = RetentionService(
            repository, _app.state.speech, worker_client=cancellation_worker,
            interval_seconds=active_settings.retention_interval_seconds,
            batch_size=active_settings.retention_batch_size,
        )
        _app.state.retention.start()
        from backend.app.studio.retention import StudioRetention
        studio_retention = StudioRetention(active_settings.database_path, active_settings.retention_interval_seconds)
        studio_retention.start()
        try:
            yield
        finally:
            await studio_retention.aclose()
            await _app.state.retention.aclose()
            await _app.state.speech.aclose()
        _LOGGER.info("Coordinator shutting down")

    application = FastAPI(
        title="VCC Coordinator API",
        version=active_settings.api_version,
        lifespan=lifespan,
    )

    @application.middleware("http")
    async def request_context_middleware(request: Request, call_next) -> Response:
        incoming_id = request.headers.get("X-Request-ID", "").strip()
        request_id = incoming_id[:128] if incoming_id else str(uuid.uuid4())
        token = set_request_id(request_id)
        settings_token = request_settings.set(active_settings)
        try:
            response = await call_next(request)
            response.headers["X-Request-ID"] = request_id
            if request.url.path.startswith(("/api/v1/studio", "/api/v1/repos")):
                response.headers["Cache-Control"] = "no-store"
                response.headers["Pragma"] = "no-cache"
                response.headers["X-Content-Type-Options"] = "nosniff"
                response.headers["Referrer-Policy"] = "no-referrer"
            _LOGGER.info(
                "HTTP request completed",
                extra={
                    "method": request.method,
                    "path": request.url.path,
                    "status_code": response.status_code,
                },
            )
            return response
        finally:
            reset_request_id(token)
            request_settings.reset(settings_token)

    application.add_middleware(
        CORSMiddleware,
        allow_origins=active_settings.cors_origins_list,
        allow_credentials=True,
        allow_methods=["*"],
        allow_headers=["*"],
    )

    application.state.settings = active_settings
    install_session_security(application, active_settings)
    from backend.app.operations.admission import AdmissionController, AdmissionMiddleware
    admission = AdmissionController(
        active_settings.database_path, window_seconds=active_settings.request_window_seconds,
        per_ip_limit=active_settings.per_ip_request_limit,
        per_session_limit=active_settings.per_session_request_limit,
        global_limit=active_settings.global_request_limit,
        session_creation_limit=active_settings.session_creation_limit,
        max_inflight=active_settings.max_inflight_requests,
    )
    application.state.admission = admission
    from backend.app.studio.body_limit import StudioBodyLimit
    application.add_middleware(StudioBodyLimit)
    application.add_middleware(AdmissionMiddleware, controller=admission)
    register_exception_handlers(application)
    from backend.app.studio.routes import router as studio_router
    application.include_router(studio_router, prefix="/api/v1")
    from backend.app.studio.speech import router as studio_speech_router
    application.include_router(studio_speech_router, prefix="/api/v1")
    from backend.app.studio.feedback import router as studio_feedback_router
    application.include_router(studio_feedback_router, prefix="/api/v1")
    from backend.app.studio.turns import router as studio_turns_router
    application.include_router(studio_turns_router, prefix="/api/v1")
    from backend.app.repo_learning.routes import router as repo_learning_router
    application.include_router(repo_learning_router, prefix="/api/v1")
    application.include_router(meta_router, prefix="/api/v1")
    from backend.app.operations.readiness import router as operations_router
    application.include_router(operations_router, prefix="/api/v1")
    from backend.app.api.routes_gamification import router as gamification_router
    application.include_router(gamification_router, prefix="/api/v1")
    if include_session_routes and sessions_router is not None:
        application.include_router(sessions_router, prefix="/api/v1")
        from backend.app.speech.routes import router as speech_router
        application.include_router(speech_router, prefix="/api/v1")

    return application


app = create_app()
