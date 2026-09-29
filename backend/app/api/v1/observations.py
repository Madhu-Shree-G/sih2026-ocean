"""In-situ observation endpoints: platforms, trajectories and profiles."""

from __future__ import annotations

from typing import Any

from fastapi import APIRouter, Depends, Path, Query
from sqlalchemy.orm import Session

from app.config import settings
from app.db import repository
from app.db.session import get_session
from app.security.deps import require_api_key
from app.security.validation import parse_bbox, parse_iso_time

router = APIRouter(tags=["observations"], dependencies=[Depends(require_api_key)])

PLATFORM_TYPES = ("argo_float", "glider", "ctd", "mooring", "adcp", "drifter")


def _domain_bbox() -> tuple[float, float, float, float]:
    return (
        settings.domain_lon_min, settings.domain_lat_min,
        settings.domain_lon_max, settings.domain_lat_max,
    )


@router.get("/platforms", summary="List observing platforms")
async def list_platforms(
    bbox: str | None = Query(None, description="min_lon,min_lat,max_lon,max_lat"),
    platform_type: list[str] | None = Query(None, description="Filter by platform type"),
    active_since: str | None = Query(None, description="ISO-8601 timestamp"),
    include_trajectory: bool = Query(False, description="Include the full track"),
    limit: int = Query(500, ge=1, le=2000),
    offset: int = Query(0, ge=0),
    session: Session = Depends(get_session),
) -> dict[str, Any]:
    """Argo floats, gliders, CTDs and moorings, filtered to the current view.

    ``include_trajectory`` returns each platform's full track, which the
    client draws as a 3-D polyline through the volume.
    """
    box = parse_bbox(bbox, default=_domain_bbox()) if bbox else None
    platforms = repository.list_platforms(
        session,
        bbox=box,
        platform_types=platform_type,
        active_since=parse_iso_time(active_since, field="active_since"),
        limit=limit,
        offset=offset,
        include_trajectory=include_trajectory,
    )
    return {
        "count": len(platforms),
        "limit": limit,
        "offset": offset,
        "platform_types": list(PLATFORM_TYPES),
        "platforms": platforms,
    }


@router.get("/platforms/{platform_id}", summary="Describe one platform")
async def get_platform(
    platform_id: str = Path(..., max_length=64),
    session: Session = Depends(get_session),
) -> dict[str, Any]:
    """Platform metadata plus its full trajectory."""
    platform = repository.get_platform(session, platform_id)
    return platform.to_dict(include_trajectory=True)


@router.get("/platforms/{platform_id}/profiles", summary="List a platform's profiles")
async def platform_profiles(
    platform_id: str = Path(..., max_length=64),
    limit: int = Query(200, ge=1, le=2000),
    offset: int = Query(0, ge=0),
    session: Session = Depends(get_session),
) -> dict[str, Any]:
    repository.get_platform(session, platform_id)  # 404s if unknown
    profiles = repository.list_profiles(
        session, platform_id=platform_id, limit=limit, offset=offset
    )
    return {
        "platform_id": platform_id,
        "count": len(profiles),
        "profiles": [p.to_summary() for p in profiles],
    }


@router.get("/profiles", summary="Query profiles")
async def list_profiles(
    bbox: str | None = Query(None),
    start_time: str | None = Query(None),
    end_time: str | None = Query(None),
    platform_type: list[str] | None = Query(None),
    limit: int = Query(500, ge=1, le=2000),
    offset: int = Query(0, ge=0),
    session: Session = Depends(get_session),
) -> dict[str, Any]:
    """Spatial and temporal search across every platform.

    Returns summaries only; fetch one profile by id for its measurements.
    """
    profiles = repository.list_profiles(
        session,
        bbox=parse_bbox(bbox, default=_domain_bbox()) if bbox else None,
        start_time=parse_iso_time(start_time, field="start_time"),
        end_time=parse_iso_time(end_time, field="end_time"),
        platform_types=platform_type,
        limit=limit,
        offset=offset,
    )
    return {
        "count": len(profiles),
        "limit": limit,
        "offset": offset,
        "profiles": [p.to_summary() for p in profiles],
    }


@router.get("/profiles/{profile_id}", summary="Full profile with measurements")
async def get_profile(
    profile_id: int = Path(..., ge=1),
    session: Session = Depends(get_session),
) -> dict[str, Any]:
    """Every measured level for one cast - the observed line in the UI chart."""
    return repository.get_profile(session, profile_id).to_dict()


@router.get("/statistics", summary="Observation holdings summary")
async def observation_statistics(session: Session = Depends(get_session)) -> dict[str, Any]:
    """Counts and coverage - drives the dashboard header."""
    return repository.statistics(session)
