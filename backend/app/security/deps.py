"""FastAPI dependencies for authentication and dataset access."""

from __future__ import annotations

import hmac

from fastapi import Header, Request

from app.config import settings
from app.core.errors import UnauthorizedError


def _constant_time_equals(a: str | None, b: str | None) -> bool:
    """Compare secrets without leaking length or content through timing."""
    if not a or not b:
        return False
    return hmac.compare_digest(a.encode("utf-8"), b.encode("utf-8"))


async def require_api_key(x_api_key: str | None = Header(default=None)) -> None:
    """Gate read endpoints when ``OCEANVIEW_REQUIRE_API_KEY`` is enabled.

    Disabled by default so the platform stays open for the public-outreach
    use case described in the problem statement.
    """
    if not settings.require_api_key:
        return
    if not _constant_time_equals(x_api_key, settings.api_key):
        raise UnauthorizedError("A valid 'X-API-Key' header is required.")


async def require_admin_key(x_admin_key: str | None = Header(default=None)) -> None:
    """Gate administrative endpoints (cache flush, limiter reset, reindex).

    Fails closed: if no admin key is configured, the routes are unusable
    rather than open.
    """
    if not settings.admin_api_key:
        raise UnauthorizedError(
            "Administrative endpoints are disabled because no admin key is configured. "
            "Set OCEANVIEW_ADMIN_API_KEY to enable them."
        )
    if not _constant_time_equals(x_admin_key, settings.admin_api_key):
        raise UnauthorizedError("A valid 'X-Admin-Key' header is required.")


def get_catalog(request: Request):
    """Return the dataset catalog attached to the app during startup."""
    catalog = getattr(request.app.state, "catalog", None)
    if catalog is None:  # pragma: no cover - defensive
        from app.core.errors import ServiceUnavailableError

        raise ServiceUnavailableError("The dataset catalog is not initialised.")
    return catalog
