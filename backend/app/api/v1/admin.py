"""Administrative endpoints.

Every route here is gated behind ``X-Admin-Key`` and fails closed: if no
admin key is configured the routes are unusable rather than open.
"""

from __future__ import annotations

from typing import Any

from fastapi import APIRouter, Depends, Request

from app.core.logging import get_logger
from app.db import repository
from app.db.session import get_session
from app.security.deps import require_admin_key
from sqlalchemy.orm import Session

logger = get_logger(__name__)

router = APIRouter(tags=["admin"], dependencies=[Depends(require_admin_key)])


@router.post("/cache/clear", summary="Flush the response cache")
async def clear_cache(request: Request) -> dict[str, Any]:
    cleared = request.app.state.cache.clear()
    logger.info("cache_cleared", extra={"entries": cleared})
    return {"status": "ok", "entries_cleared": cleared}


@router.post("/catalog/reload", summary="Rescan the data directory")
async def reload_catalog(request: Request) -> dict[str, Any]:
    """Pick up newly ingested Zarr stores without restarting the service."""
    catalog = request.app.state.catalog
    catalog.load()
    request.app.state.cache.clear()
    logger.info("catalog_reloaded", extra={"datasets": len(catalog.ids())})
    return {"status": "ok", "datasets": catalog.ids()}


@router.post("/ratelimit/reset", summary="Clear rate-limiter state")
async def reset_rate_limiter(request: Request) -> dict[str, Any]:
    limiter = request.app.state.rate_limiter
    limiter.reset()
    return {"status": "ok", "limiter": limiter.stats()}


@router.get("/stats", summary="Runtime statistics")
async def stats(request: Request, session: Session = Depends(get_session)) -> dict[str, Any]:
    return {
        "cache": request.app.state.cache.stats(),
        "rate_limiter": request.app.state.rate_limiter.stats(),
        "catalog": {
            "datasets": request.app.state.catalog.ids(),
            "plugins": request.app.state.catalog.plugin_manifest(),
        },
        "observations": repository.statistics(session),
    }
