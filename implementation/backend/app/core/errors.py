"""Canonical ApiError schema and FastAPI exception handlers."""

from fastapi import FastAPI, Request
from fastapi.exceptions import RequestValidationError
from fastapi.responses import JSONResponse
from pydantic import BaseModel, ConfigDict
from starlette.exceptions import HTTPException as StarletteHTTPException

from .logging import get_logger, get_request_id

_LOGGER = get_logger("vcc.errors")

_HTTP_STATUS_CODES = {
    400: "BAD_REQUEST",
    401: "UNAUTHORIZED",
    403: "FORBIDDEN",
    404: "NOT_FOUND",
    405: "METHOD_NOT_ALLOWED",
    409: "CONFLICT",
    413: "PAYLOAD_TOO_LARGE",
    422: "VALIDATION_ERROR",
    429: "RATE_LIMITED",
    503: "SERVICE_UNAVAILABLE",
}


class ApiErrorBody(BaseModel):
    """Canonical error response payload."""

    model_config = ConfigDict(extra="forbid")

    code: str
    message: str
    request_id: str
    retryable: bool = False
    turn_id: str | None = None
    job_id: str | None = None


class ApiAppException(Exception):
    """Application-level exception mapped to a canonical ApiError response."""

    def __init__(
        self,
        *,
        status_code: int,
        code: str,
        message: str,
        retryable: bool = False,
        turn_id: str | None = None,
        job_id: str | None = None,
    ) -> None:
        super().__init__(message)
        self.status_code = status_code
        self.code = code
        self.message = message
        self.retryable = retryable
        self.turn_id = turn_id
        self.job_id = job_id


def _error_response(status_code: int, body: ApiErrorBody) -> JSONResponse:
    return JSONResponse(
        status_code=status_code,
        content=body.model_dump(),
        headers={"X-Request-ID": body.request_id},
    )


def register_exception_handlers(app: FastAPI) -> None:
    """Attach canonical exception handlers to the FastAPI application."""

    @app.exception_handler(ApiAppException)
    async def handle_api_app_exception(_request: Request, exc: ApiAppException) -> JSONResponse:
        body = ApiErrorBody(
            code=exc.code,
            message=exc.message,
            request_id=get_request_id(),
            retryable=exc.retryable,
            turn_id=exc.turn_id,
            job_id=exc.job_id,
        )
        return _error_response(exc.status_code, body)

    @app.exception_handler(RequestValidationError)
    async def handle_validation_error(_request: Request, exc: RequestValidationError) -> JSONResponse:
        first_err = exc.errors()[0] if exc.errors() else {}
        loc = ".".join(str(part) for part in first_err.get("loc", ()))
        msg = first_err.get("msg", "Request validation failed")
        safe_message = f"{loc}: {msg}" if loc else str(msg)
        body = ApiErrorBody(
            code="VALIDATION_ERROR",
            message=safe_message,
            request_id=get_request_id(),
            retryable=False,
        )
        return _error_response(422, body)

    @app.exception_handler(StarletteHTTPException)
    async def handle_http_exception(_request: Request, exc: StarletteHTTPException) -> JSONResponse:
        code = _HTTP_STATUS_CODES.get(exc.status_code, f"HTTP_{exc.status_code}")
        message = exc.detail if isinstance(exc.detail, str) else "Request failed"
        body = ApiErrorBody(
            code=code,
            message=message,
            request_id=get_request_id(),
            retryable=exc.status_code in {429, 502, 503, 504},
        )
        return _error_response(exc.status_code, body)

    @app.exception_handler(Exception)
    async def handle_unexpected_exception(_request: Request, exc: Exception) -> JSONResponse:
        _LOGGER.exception("Unhandled exception during request processing: %s", type(exc).__name__)
        body = ApiErrorBody(
            code="INTERNAL_ERROR",
            message="An unexpected internal error occurred.",
            request_id=get_request_id(),
            retryable=False,
        )
        return _error_response(500, body)
