"""HTTP middleware stack: request context, hardening, and throttling.

Ordering matters.  Starlette runs middleware in reverse registration order
for the request path, so ``main.py`` adds these outermost-last:

    RequestContext -> SecurityHeaders -> BodyLimit -> RateLimit -> Concurrency
"""

from __future__ import annotations

import re
import time
import uuid

from starlette.middleware.base import BaseHTTPMiddleware, RequestResponseEndpoint
from starlette.requests import Request
from starlette.responses import JSONResponse, Response
from starlette.types import ASGIApp

from app.core.logging import get_logger, request_id_ctx

logger = get_logger(__name__)

#: Route prefixes that trigger expensive I/O or array maths.  These are held
#: to the stricter rate-limit bucket and the concurrency gate.
HEAVY_PATH_PATTERN = re.compile(
    r"^/api/v1/(fields/(volume|slice|transect)|wms|derived/(drift|eddies|anomaly)|collocation/bias-map)"
)

#: Paths exempt from throttling so orchestrators can always probe the service.
EXEMPT_PATHS = frozenset({"/api/v1/health", "/api/v1/health/live", "/api/v1/health/ready"})

_REQUEST_ID_RE = re.compile(r"^[A-Za-z0-9._\-]{1,64}$")


def client_key(request: Request) -> str:
    """Derive a stable throttling key for the caller.

    ``X-Forwarded-For`` is honoured only when the application is explicitly
    configured to sit behind a trusted proxy, otherwise a client could spoof
    the header and bypass rate limiting entirely.
    """
    if getattr(request.app.state, "trust_proxy_headers", False):
        forwarded = request.headers.get("x-forwarded-for", "")
        if forwarded:
            first = forwarded.split(",")[0].strip()
            if first:
                return first
    if request.client and request.client.host:
        return request.client.host
    return "unknown"


def is_heavy(path: str) -> bool:
    return bool(HEAVY_PATH_PATTERN.match(path))


class RequestContextMiddleware(BaseHTTPMiddleware):
    """Assign a request ID, time the request, and emit one access log line."""

    async def dispatch(self, request: Request, call_next: RequestResponseEndpoint) -> Response:
        incoming = request.headers.get("x-request-id", "")
        rid = incoming if _REQUEST_ID_RE.match(incoming) else uuid.uuid4().hex
        token = request_id_ctx.set(rid)
        request.state.request_id = rid
        started = time.perf_counter()

        try:
            response = await call_next(request)
        except Exception:
            elapsed_ms = (time.perf_counter() - started) * 1000
            logger.exception(
                "request_failed",
                extra={
                    "method": request.method,
                    "path": request.url.path,
                    "duration_ms": round(elapsed_ms, 2),
                    "client": client_key(request),
                },
            )
            request_id_ctx.reset(token)
            raise

        elapsed_ms = (time.perf_counter() - started) * 1000
        response.headers["X-Request-ID"] = rid
        response.headers["X-Response-Time-ms"] = f"{elapsed_ms:.1f}"

        if request.url.path not in EXEMPT_PATHS:
            logger.info(
                "request",
                extra={
                    "method": request.method,
                    "path": request.url.path,
                    "status": response.status_code,
                    "duration_ms": round(elapsed_ms, 2),
                    "client": client_key(request),
                },
            )
        request_id_ctx.reset(token)
        return response


class SecurityHeadersMiddleware(BaseHTTPMiddleware):
    """Attach a conservative set of browser-hardening response headers."""

    def __init__(self, app: ASGIApp, *, enable_hsts: bool = False) -> None:
        super().__init__(app)
        self.enable_hsts = enable_hsts

    async def dispatch(self, request: Request, call_next: RequestResponseEndpoint) -> Response:
        response = await call_next(request)
        headers = response.headers

        headers.setdefault("X-Content-Type-Options", "nosniff")
        headers.setdefault("X-Frame-Options", "DENY")
        headers.setdefault("Referrer-Policy", "strict-origin-when-cross-origin")
        headers.setdefault("Cross-Origin-Opener-Policy", "same-origin")
        headers.setdefault("Cross-Origin-Resource-Policy", "cross-origin")
        headers.setdefault(
            "Permissions-Policy",
            "geolocation=(), microphone=(), camera=(), payment=(), usb=()",
        )

        # The API serves JSON and binary blobs; interactive docs need a looser
        # policy so Swagger UI can load its bundled assets.
        if request.url.path.startswith(("/docs", "/redoc", "/openapi.json")):
            headers.setdefault(
                "Content-Security-Policy",
                "default-src 'self'; img-src 'self' data: https://fastapi.tiangolo.com; "
                "script-src 'self' https://cdn.jsdelivr.net 'unsafe-inline'; "
                "style-src 'self' https://cdn.jsdelivr.net 'unsafe-inline'; "
                "worker-src 'self' blob:; frame-ancestors 'none'",
            )
        else:
            headers.setdefault(
                "Content-Security-Policy",
                "default-src 'none'; frame-ancestors 'none'; base-uri 'none'; form-action 'none'",
            )

        if self.enable_hsts:
            headers.setdefault(
                "Strict-Transport-Security", "max-age=31536000; includeSubDomains"
            )
        return response


class BodyLimitMiddleware(BaseHTTPMiddleware):
    """Reject oversized request bodies and absurdly long query strings.

    The ``Content-Length`` check short-circuits obvious cases; the streaming
    check below it defends against a chunked upload that omits the header.
    """

    def __init__(self, app: ASGIApp, *, max_body_bytes: int, max_query_bytes: int) -> None:
        super().__init__(app)
        self.max_body_bytes = max_body_bytes
        self.max_query_bytes = max_query_bytes

    async def dispatch(self, request: Request, call_next: RequestResponseEndpoint) -> Response:
        query = request.url.query or ""
        if len(query.encode("utf-8", errors="ignore")) > self.max_query_bytes:
            return _error(414, "uri_too_long", "The query string exceeds the permitted length.")

        raw_length = request.headers.get("content-length")
        if raw_length:
            try:
                declared = int(raw_length)
            except ValueError:
                return _error(400, "bad_request", "Malformed Content-Length header.")
            if declared > self.max_body_bytes:
                return _error(
                    413, "payload_too_large",
                    f"Request body exceeds the {self.max_body_bytes} byte limit.",
                )

        if request.method in {"POST", "PUT", "PATCH"} and not raw_length:
            body = await request.body()
            if len(body) > self.max_body_bytes:
                return _error(
                    413, "payload_too_large",
                    f"Request body exceeds the {self.max_body_bytes} byte limit.",
                )

        return await call_next(request)


class RateLimitMiddleware(BaseHTTPMiddleware):
    """Apply the token-bucket limiter and publish standard rate-limit headers."""

    async def dispatch(self, request: Request, call_next: RequestResponseEndpoint) -> Response:
        limiter = getattr(request.app.state, "rate_limiter", None)
        path = request.url.path

        if limiter is None or not limiter.enabled or path in EXEMPT_PATHS:
            return await call_next(request)

        kind = "heavy" if is_heavy(path) else "default"
        decision = limiter.check(client_key(request), kind)

        if not decision.allowed:
            logger.warning(
                "rate_limited",
                extra={"path": path, "client": client_key(request), "reason": decision.reason},
            )
            response = _error(
                429, "rate_limited",
                "Too many requests. Retry after {0:.0f}s.".format(decision.retry_after),
            )
            response.headers["Retry-After"] = str(max(1, int(decision.retry_after)))
            response.headers["X-RateLimit-Limit"] = str(decision.limit)
            response.headers["X-RateLimit-Remaining"] = "0"
            return response

        response = await call_next(request)
        response.headers["X-RateLimit-Limit"] = str(decision.limit)
        response.headers["X-RateLimit-Remaining"] = str(decision.remaining)
        return response


class ConcurrencyLimitMiddleware(BaseHTTPMiddleware):
    """Cap simultaneous in-flight heavy requests.

    Without this, a handful of concurrent full-volume extractions can exhaust
    memory even though every individual request is within its size budget.
    """

    def __init__(self, app: ASGIApp, *, max_concurrent: int) -> None:
        super().__init__(app)
        self.max_concurrent = max(1, max_concurrent)
        self._in_flight = 0
        import asyncio

        self._lock = asyncio.Lock()

    async def dispatch(self, request: Request, call_next: RequestResponseEndpoint) -> Response:
        if not is_heavy(request.url.path):
            return await call_next(request)

        async with self._lock:
            if self._in_flight >= self.max_concurrent:
                logger.warning("concurrency_rejected", extra={"path": request.url.path})
                response = _error(
                    503, "service_unavailable",
                    "The server is at capacity for heavy requests. Please retry shortly.",
                )
                response.headers["Retry-After"] = "2"
                return response
            self._in_flight += 1

        try:
            return await call_next(request)
        finally:
            async with self._lock:
                self._in_flight -= 1


def _error(status_code: int, code: str, message: str) -> JSONResponse:
    return JSONResponse(
        status_code=status_code,
        content={
            "error": {
                "code": code,
                "message": message,
                "request_id": request_id_ctx.get(),
            }
        },
    )
