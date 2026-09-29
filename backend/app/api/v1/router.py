"""Aggregate router for API version 1."""

from __future__ import annotations

from fastapi import APIRouter

from app.api.v1 import (
    admin,
    agent,
    collocation,
    colormaps,
    datasets,
    derived,
    fields,
    health,
    observations,
    wms,
)

api_router = APIRouter(prefix="/api/v1")

api_router.include_router(health.router, prefix="/health")
api_router.include_router(datasets.router, prefix="/datasets")
api_router.include_router(fields.router, prefix="/fields")
api_router.include_router(observations.router, prefix="/observations")
api_router.include_router(collocation.router, prefix="/collocation")
api_router.include_router(derived.router, prefix="/derived")
api_router.include_router(colormaps.router, prefix="/colormaps")
api_router.include_router(wms.router, prefix="/wms")
api_router.include_router(agent.router, prefix="/agent")
api_router.include_router(admin.router, prefix="/admin")

__all__ = ["api_router"]
