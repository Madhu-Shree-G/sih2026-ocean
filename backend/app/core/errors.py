"""Typed application errors and the handlers that render them.

Every failure leaves the service in the same JSON envelope, and internal
exception detail is never echoed to the client outside debug mode.
"""

from __future__ import annotations

from typing import Any

from fastapi import FastAPI, Request
from fastapi.exceptions import RequestValidationError
from fastapi.responses import JSONResponse
from starlette.exceptions import HTTPException as StarletteHTTPException

from app.core.logging import get_logger, request_id_ctx

logger = get_logger(__name__)


class AppError(Exception):
    """Base class for all deliberately raised service errors."""

    status_code: int = 500
    code: str = "internal_error"
    message: str = "An unexpected error occurred."

    def __init__(self, message: str | None = None, **details: Any) -> None:
        self.message = message or self.message
        self.details = details
        super().__init__(self.message)

    def to_payload(self) -> dict[str, Any]:
        body: dict[str, Any] = {
            "error": {
                "code": self.code,
                "message": self.message,
                "request_id": request_id_ctx.get(),
            }
        }
        if self.details:
            body["error"]["details"] = _jsonable(self.details)
        return body


class NotFoundError(AppError):
    status_code = 404
    code = "not_found"
    message = "The requested resource does not exist."


class ValidationError(AppError):
    status_code = 422
    code = "validation_error"
    message = "The request parameters are invalid."


class PayloadTooLargeError(AppError):
    status_code = 413
    code = "payload_too_large"
    message = "The request would produce a response larger than the configured limit."


class RateLimitError(AppError):
    status_code = 429
    code = "rate_limited"
    message = "Too many requests. Please slow down."


class UnauthorizedError(AppError):
    status_code = 401
    code = "unauthorized"
    message = "Valid credentials are required for this endpoint."


class ServiceUnavailableError(AppError):
    status_code = 503
    code = "service_unavailable"
    message = "The service is temporarily unable to handle the request."


class DataUnavailableError(AppError):
    status_code = 503
    code = "data_unavailable"
    message = (
        "No dataset is loaded. Run 'python scripts/generate_sample_data.py' "
        "to build the demo dataset."
    )


def _jsonable(value: Any) -> Any:
    """Coerce detail payloads into something ``json.dumps`` accepts."""
    if isinstance(value, dict):
        return {str(k): _jsonable(v) for k, v in value.items()}
    if isinstance(value, (list, tuple, set)):
        return [_jsonable(v) for v in value]
    if isinstance(value, (str, int, float, bool)) or value is None:
        return value
    return str(value)


def register_exception_handlers(app: FastAPI, *, debug: bool = False) -> None:
    """Attach handlers so no exception escapes as an unformatted 500."""

    @app.exception_handler(AppError)
    async def _app_error(_: Request, exc: AppError) -> JSONResponse:
        if exc.status_code >= 500:
            logger.error("app_error", extra={"code": exc.code, "detail": exc.message})
        return JSONResponse(status_code=exc.status_code, content=exc.to_payload())

    @app.exception_handler(RequestValidationError)
    async def _validation(_: Request, exc: RequestValidationError) -> JSONResponse:
        fields = [
            {
                "field": ".".join(str(p) for p in err.get("loc", ()) if p != "body"),
                "issue": err.get("msg", "invalid"),
            }
            for err in exc.errors()
        ]
        return JSONResponse(
            status_code=422,
            content={
                "error": {
                    "code": "validation_error",
                    "message": "One or more request parameters are invalid.",
                    "request_id": request_id_ctx.get(),
                    "details": {"fields": fields},
                }
            },
        )

    @app.exception_handler(StarletteHTTPException)
    async def _http(_: Request, exc: StarletteHTTPException) -> JSONResponse:
        code_map = {
            400: "bad_request", 401: "unauthorized", 403: "forbidden",
            404: "not_found", 405: "method_not_allowed", 413: "payload_too_large",
            414: "uri_too_long", 429: "rate_limited", 503: "service_unavailable",
        }
        return JSONResponse(
            status_code=exc.status_code,
            content={
                "error": {
                    "code": code_map.get(exc.status_code, "http_error"),
                    "message": str(exc.detail),
                    "request_id": request_id_ctx.get(),
                }
            },
            headers=getattr(exc, "headers", None),
        )

    @app.exception_handler(Exception)
    async def _unhandled(_: Request, exc: Exception) -> JSONResponse:
        # Log the full trace server-side; return an opaque message to the client
        # so internals are never disclosed in production.
        logger.exception("unhandled_exception", extra={"exception_type": type(exc).__name__})
        message = f"{type(exc).__name__}: {exc}" if debug else "An internal error occurred."
        return JSONResponse(
            status_code=500,
            content={
                "error": {
                    "code": "internal_error",
                    "message": message,
                    "request_id": request_id_ctx.get(),
                }
            },
        )
