"""Model / observation collocation endpoints.

The centrepiece of the platform.  ``/collocation/profile/{id}`` is the call
behind the single most important interaction in the UI: click a float, see
its measured profile and the model's prediction on the same axes, with the
divergence quantified.
"""

from __future__ import annotations

from typing import Any

import numpy as np
from fastapi import APIRouter, Depends, Path, Query
from sqlalchemy.orm import Session

from app.config import settings
from app.core.errors import ValidationError
from app.data.catalog import Catalog
from app.data.collocation import (
    ObservationInput,
    collocate_many,
    collocate_profile,
    summarise_bias,
)
from app.db import repository
from app.db.session import get_session
from app.security.deps import get_catalog, require_api_key
from app.security.validation import parse_bbox, parse_iso_time, safe_identifier

router = APIRouter(tags=["collocation"], dependencies=[Depends(require_api_key)])

#: Variables that exist in both the model and the observation schema.
COMPARABLE = ("temperature", "salinity", "chlorophyll", "oxygen")


def _domain_bbox() -> tuple[float, float, float, float]:
    return (
        settings.domain_lon_min, settings.domain_lat_min,
        settings.domain_lon_max, settings.domain_lat_max,
    )


@router.get(
    "/profile/{profile_id}",
    summary="Compare one observed profile against the model",
)
async def collocate_one(
    profile_id: int = Path(..., ge=1),
    variable: str = Query("temperature"),
    dataset: str | None = Query(None),
    session: Session = Depends(get_session),
    catalog: Catalog = Depends(get_catalog),
) -> dict[str, Any]:
    """Pair an in-situ profile with the model field at the same point in space-time.

    Returns both series on the observation's depth axis plus verification
    metrics (bias, RMSD, MAE, correlation) - everything needed to draw the
    comparison chart and state how far apart the two are.
    """
    safe_identifier(variable, field="variable")
    if variable not in COMPARABLE:
        raise ValidationError(
            f"'{variable}' cannot be collocated; observations carry {list(COMPARABLE)}.",
            field="variable",
        )

    profile = repository.get_profile(session, profile_id)
    handle = catalog.resolve(dataset)

    depths, values = profile.series(variable)
    if not depths:
        raise ValidationError(
            f"Profile {profile_id} contains no '{variable}' measurements.", field="variable"
        )

    result = collocate_profile(
        handle,
        variable=variable,
        platform_id=profile.platform.platform_id if profile.platform else str(profile_id),
        latitude=profile.latitude,
        longitude=profile.longitude,
        observation_time=profile.time,
        depths=depths,
        values=values,
    )
    payload = result.to_dict()
    payload["profile_id"] = profile_id
    payload["cycle"] = profile.cycle_number
    return payload


@router.get("/bias-map", summary="Fleet-wide model bias across the current view")
async def bias_map(
    variable: str = Query("temperature"),
    dataset: str | None = Query(None),
    bbox: str | None = Query(None),
    start_time: str | None = Query(None),
    end_time: str | None = Query(None),
    depth_max: float = Query(500.0, ge=0, le=11000, description="Restrict the comparison depth"),
    limit: int = Query(200, ge=1, le=500),
    session: Session = Depends(get_session),
    catalog: Catalog = Depends(get_catalog),
) -> dict[str, Any]:
    """Colour every platform in view by its model-observation bias.

    Turns the viewer into a verification tool: a forecaster sees at a glance
    where today's model is drifting away from reality.
    """
    safe_identifier(variable, field="variable")
    if variable not in COMPARABLE:
        raise ValidationError(
            f"'{variable}' cannot be collocated; observations carry {list(COMPARABLE)}.",
            field="variable",
        )

    handle = catalog.resolve(dataset)
    profiles = repository.latest_profile_per_platform(
        session,
        bbox=parse_bbox(bbox, default=_domain_bbox()) if bbox else None,
        start_time=parse_iso_time(start_time, field="start_time"),
        end_time=parse_iso_time(end_time, field="end_time"),
        limit=limit,
    )

    observations: list[ObservationInput] = []
    for profile in profiles:
        depths, values = profile.series(variable)
        if not depths:
            continue

        kept = [(d, v) for d, v in zip(depths, values) if d <= depth_max]
        if len(kept) < 2:
            continue

        observations.append(
            ObservationInput(
                platform_id=profile.platform.platform_id if profile.platform else "unknown",
                latitude=profile.latitude,
                longitude=profile.longitude,
                observation_time=profile.time,
                depths=[d for d, _ in kept],
                values=[v for _, v in kept],
                reference=profile,
            )
        )

    results = []
    markers: list[dict[str, Any]] = []

    for observation, result in collocate_many(
        handle, variable=variable, observations=observations
    ):
        if result.statistics is None:
            continue

        profile = observation.reference
        statistics = result.statistics.to_dict()
        results.append(result)
        markers.append(
            {
                "profile_id": profile.id,
                "platform_id": result.platform_id,
                "platform_type": profile.platform.platform_type if profile.platform else None,
                "lat": result.latitude,
                "lon": result.longitude,
                "time": result.observation_time,
                "bias": statistics["bias"],
                "rmsd": statistics["rmsd"],
                "n_levels": result.statistics.count,
            }
        )

    biases = [m["bias"] for m in markers if m["bias"] is not None]
    spread = float(np.nanmax(np.abs(biases))) if biases else 1.0

    return {
        "dataset": handle.id,
        "variable": variable,
        "units": handle.variable_specs[variable].units if handle.has_variable(variable) else "",
        "depth_max_m": depth_max,
        "count": len(markers),
        "markers": markers,
        "summary": summarise_bias(results),
        "suggested_scale": {
            "colormap": "balance",
            "vmin": -round(spread, 3),
            "vmax": round(spread, 3),
        },
    }


@router.get("/variables", summary="Variables available for collocation")
async def comparable_variables(catalog: Catalog = Depends(get_catalog)) -> dict[str, Any]:
    """Intersection of what the model carries and what instruments measure."""
    handle = catalog.default()
    available = [name for name in COMPARABLE if handle.has_variable(name)]
    return {
        "dataset": handle.id,
        "comparable": available,
        "observation_variables": list(COMPARABLE),
        "model_variables": sorted(handle.variable_specs),
    }
