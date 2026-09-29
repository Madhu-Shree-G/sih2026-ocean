"""Liveness, readiness and service-info endpoints."""

from __future__ import annotations

import time
from typing import Any

from fastapi import APIRouter, Request

from app.config import settings
from app.db.session import healthcheck as db_healthcheck

router = APIRouter(tags=["health"])

_STARTED_AT = time.time()


@router.get("", summary="Liveness probe")
@router.get("/live", summary="Liveness probe")
async def live() -> dict[str, Any]:
    """Cheap check that the process is up. Never touches the database."""
    return {
        "status": "ok",
        "service": settings.app_name,
        "version": settings.version,
        "uptime_seconds": round(time.time() - _STARTED_AT, 1),
    }


@router.get("/ready", summary="Readiness probe")
async def ready(request: Request) -> dict[str, Any]:
    """Verify that dependencies are usable before accepting traffic."""
    catalog = getattr(request.app.state, "catalog", None)
    datasets = catalog.ids() if catalog is not None else []
    database_ok = db_healthcheck()

    checks = {
        "database": "ok" if database_ok else "unavailable",
        "catalog": "ok" if datasets else "empty",
        "datasets_loaded": len(datasets),
    }
    ready_state = database_ok and bool(datasets)

    return {
        "status": "ready" if ready_state else "degraded",
        "checks": checks,
        "datasets": datasets,
        "hint": (
            None if ready_state
            else "Run: python scripts/generate_sample_data.py to populate the demo dataset."
        ),
    }


@router.get("/info", summary="Service capabilities")
async def info(request: Request) -> dict[str, Any]:
    """Describe what this deployment can do - used by the frontend on boot."""
    catalog = getattr(request.app.state, "catalog", None)
    cache = getattr(request.app.state, "cache", None)
    limiter = getattr(request.app.state, "rate_limiter", None)

    return {
        "service": settings.app_name,
        "version": settings.version,
        "environment": settings.environment,
        "datasets": catalog.ids() if catalog else [],
        "plugins": catalog.plugin_manifest() if catalog else [],
        "capabilities": {
            "volume_rendering": True,
            "depth_slices": True,
            "transects": True,
            "time_animation": True,
            "collocation": True,
            "drift_simulation": True,
            "eddy_detection": True,
            "anomaly_detection": True,
            "ogc_wms": True,
        },
        "limits": {
            "max_volume_cells": settings.max_volume_cells,
            "max_volume_bytes": settings.max_volume_bytes,
            "max_timesteps_per_request": settings.max_timesteps_per_request,
            "max_drift_particles": settings.max_drift_particles,
            "max_transect_points": settings.max_transect_points,
            "rate_limit_per_minute": settings.rate_limit_default_per_minute,
            "rate_limit_heavy_per_minute": settings.rate_limit_heavy_per_minute,
        },
        "cache": cache.stats() if cache else None,
        "rate_limiter": limiter.stats() if limiter else None,
    }
