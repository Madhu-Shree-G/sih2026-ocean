"""Derived-product endpoints.

Every route here is computed from fields the service has already read for
rendering, which is why an "analysis layer" costs so little: mixed-layer
depth, eddy census, anomalies and drift are all small amounts of extra
arithmetic on arrays that are already in memory.
"""

from __future__ import annotations

from typing import Any

import numpy as np
from fastapi import APIRouter, Depends, Query, Request

from app.config import settings
from app.core.cache import cache_key
from app.core.errors import NotFoundError, ValidationError
from app.data.catalog import Catalog, DatasetHandle
from app.data.derived import (
    VelocityField,
    anomaly,
    detect_eddies,
    heatwave_mask,
    mixed_layer_depth,
    simulate_drift,
    thermocline_depth,
)
from app.schemas.requests import DriftRequest
from app.security.deps import get_catalog, require_api_key
from app.security.validation import (
    guard_cell_budget,
    parse_bbox,
    parse_iso_time,
    safe_identifier,
)

router = APIRouter(tags=["derived"], dependencies=[Depends(require_api_key)])

#: Dataset id suffix used for a matching climatology store, if one exists.
CLIMATOLOGY_SUFFIX = "_climatology"


def _resolve_time_index(handle: DatasetHandle, time: str | None, time_index: int | None) -> int:
    if time_index is not None:
        return max(0, min(int(time_index), max(0, int(handle.times.size) - 1)))
    if time:
        return handle.time_index(parse_iso_time(time, field="time"))
    return 0


def _grid(values: np.ndarray, lats: np.ndarray, lons: np.ndarray, *, precision: int = 3) -> dict[str, Any]:
    """Serialise a 2-D field with its axes, converting NaN to null."""
    return {
        "shape": [int(values.shape[0]), int(values.shape[1])],
        "lats": [round(float(v), 5) for v in lats],
        "lons": [round(float(v), 5) for v in lons],
        "values": [
            [None if not np.isfinite(v) else round(float(v), precision) for v in row]
            for row in values
        ],
    }


# ---------------------------------------------------------------------------
# Mixed layer / thermocline
# ---------------------------------------------------------------------------
@router.get("/mixed-layer-depth", summary="Mixed layer depth")
async def get_mixed_layer_depth(
    dataset: str | None = Query(None),
    bbox: str | None = Query(None),
    time: str | None = Query(None),
    time_index: int | None = Query(None, ge=0),
    threshold: float = Query(0.2, gt=0, le=5, description="Temperature criterion in degC"),
    stride: int = Query(1, ge=1, le=32),
    catalog: Catalog = Depends(get_catalog),
) -> dict[str, Any]:
    """Mixed layer depth using the de Boyer Montegut 0.2 degC criterion.

    MLD controls how much heat a cyclone can draw on and how deep nutrients
    mix, so it underpins both hazard assessment and fishery advisories.
    """
    handle = catalog.resolve(dataset)
    handle.require_variable("temperature")

    box = parse_bbox(bbox, default=handle.bounds())
    idx = _resolve_time_index(handle, time, time_index)

    subset = handle.subset(
        "temperature", bbox=box, time_indices=[idx], stride=stride
    )
    guard_cell_budget(
        n_lat=subset.values.shape[2], n_lon=subset.values.shape[3],
        n_depth=subset.values.shape[1],
        max_cells=settings.max_volume_cells, max_bytes=settings.max_volume_bytes,
    )

    block = subset.values[0]  # (depth, lat, lon)
    mld = mixed_layer_depth(block, subset.depths, threshold=threshold)
    finite = mld[np.isfinite(mld)]

    return {
        "dataset": handle.id,
        "product": "mixed_layer_depth",
        "units": "m",
        "method": "de Boyer Montegut (2004), dT = {0} degC from 10 m".format(threshold),
        "time": subset.times[0],
        "bbox": list(box),
        "value_range": (
            [round(float(finite.min()), 2), round(float(finite.max()), 2)]
            if finite.size else [None, None]
        ),
        "colormap": "deep",
        "grid": _grid(mld, subset.lats, subset.lons, precision=2),
    }


@router.get("/thermocline", summary="Thermocline depth")
async def get_thermocline(
    dataset: str | None = Query(None),
    bbox: str | None = Query(None),
    time: str | None = Query(None),
    time_index: int | None = Query(None, ge=0),
    stride: int = Query(1, ge=1, le=32),
    catalog: Catalog = Depends(get_catalog),
) -> dict[str, Any]:
    """Depth of the strongest vertical temperature gradient."""
    handle = catalog.resolve(dataset)
    handle.require_variable("temperature")

    box = parse_bbox(bbox, default=handle.bounds())
    idx = _resolve_time_index(handle, time, time_index)
    subset = handle.subset("temperature", bbox=box, time_indices=[idx], stride=stride)

    depth_field = thermocline_depth(subset.values[0], subset.depths)
    finite = depth_field[np.isfinite(depth_field)]

    return {
        "dataset": handle.id,
        "product": "thermocline_depth",
        "units": "m",
        "method": "Depth of maximum |dT/dz|",
        "time": subset.times[0],
        "bbox": list(box),
        "value_range": (
            [round(float(finite.min()), 2), round(float(finite.max()), 2)]
            if finite.size else [None, None]
        ),
        "colormap": "deep",
        "grid": _grid(depth_field, subset.lats, subset.lons, precision=2),
    }


# ---------------------------------------------------------------------------
# Anomaly and marine heatwave
# ---------------------------------------------------------------------------
@router.get("/anomaly", summary="Anomaly against climatology")
async def get_anomaly(
    request: Request,
    dataset: str | None = Query(None),
    variable: str = Query("temperature"),
    bbox: str | None = Query(None),
    depth: float = Query(0.0, ge=0, le=11000),
    time: str | None = Query(None),
    time_index: int | None = Query(None, ge=0),
    stride: int = Query(1, ge=1, le=32),
    heatwave_threshold: float = Query(1.0, gt=0, le=10),
    catalog: Catalog = Depends(get_catalog),
) -> dict[str, Any]:
    """Field minus climatology, with marine-heatwave cells flagged.

    A companion ``<dataset>_climatology`` store is used when present.  If it
    is absent the dataset's own temporal mean is used instead, and the
    ``reference`` field in the response says so - an anomaly against a short
    record is not the same product as one against a 30-year climatology, and
    the API should never blur that distinction.
    """
    safe_identifier(variable, field="variable")
    handle = catalog.resolve(dataset)
    handle.require_variable(variable)

    box = parse_bbox(bbox, default=handle.bounds())
    idx = _resolve_time_index(handle, time, time_index)
    depth_value = float(handle.depths[handle.depth_index(depth)])

    subset = handle.subset(
        variable, bbox=box, depth_min=depth_value, depth_max=depth_value,
        time_indices=[idx], stride=stride,
    )
    field = subset.values[0, 0]

    climatology_id = f"{handle.id}{CLIMATOLOGY_SUFFIX}"
    reference = "dataset_time_mean"
    climatology: np.ndarray

    if climatology_id in catalog.ids():
        clim_handle = catalog.get(climatology_id)
        if clim_handle.has_variable(variable):
            clim_subset = clim_handle.subset(
                variable, bbox=box, depth_min=depth_value, depth_max=depth_value,
                time_indices=[min(idx, max(0, int(clim_handle.times.size) - 1))],
                stride=stride,
            )
            climatology = clim_subset.values[0, 0]
            reference = climatology_id
        else:
            climatology = _temporal_mean(handle, variable, box, depth_value, stride)
    else:
        climatology = _temporal_mean(handle, variable, box, depth_value, stride)

    if climatology.shape != field.shape:
        raise ValidationError(
            "Climatology grid does not align with the requested field; "
            "regenerate the climatology at the same resolution."
        )

    anomaly_field = anomaly(field, climatology)
    heatwave = heatwave_mask(anomaly_field, threshold=heatwave_threshold)
    finite = anomaly_field[np.isfinite(anomaly_field)]
    extreme = float(np.nanmax(np.abs(finite))) if finite.size else 1.0

    return {
        "dataset": handle.id,
        "product": "anomaly",
        "variable": variable,
        "units": subset.units,
        "reference": reference,
        "reference_note": (
            "Anomaly computed against the dataset's own temporal mean, not a "
            "long-term climatology. Load a <dataset>_climatology store for "
            "operational-grade anomalies."
            if reference == "dataset_time_mean" else None
        ),
        "time": subset.times[0],
        "depth_m": depth_value,
        "bbox": list(box),
        "colormap": "balance",
        "suggested_scale": {"vmin": -round(extreme, 3), "vmax": round(extreme, 3)},
        "heatwave": {
            "threshold": heatwave["threshold"],
            "cells_flagged": heatwave["cells_flagged"],
            "cells_valid": heatwave["cells_valid"],
            "area_fraction": heatwave["fraction"],
            "max_anomaly": round(heatwave["max_anomaly"], 3),
            "min_anomaly": round(heatwave["min_anomaly"], 3),
            "mean_anomaly_in_event": round(heatwave["mean_anomaly_in_event"], 3),
            "mask": [[bool(v) for v in row] for row in heatwave["mask"]],
        },
        "grid": _grid(anomaly_field, subset.lats, subset.lons),
    }


def _temporal_mean(
    handle: DatasetHandle,
    variable: str,
    box: tuple[float, float, float, float],
    depth_value: float,
    stride: int,
) -> np.ndarray:
    """Mean over every available timestep - the climatology fallback."""
    n_times = int(handle.times.size) or 1
    indices = list(range(min(n_times, settings.max_timesteps_per_request)))
    subset = handle.subset(
        variable, bbox=box, depth_min=depth_value, depth_max=depth_value,
        time_indices=indices, stride=stride,
    )
    with np.errstate(invalid="ignore"):
        return np.nanmean(subset.values[:, 0], axis=0)


# ---------------------------------------------------------------------------
# Eddies
# ---------------------------------------------------------------------------
@router.get("/eddies", summary="Detect mesoscale eddies")
async def get_eddies(
    dataset: str | None = Query(None),
    bbox: str | None = Query(None),
    depth: float = Query(0.0, ge=0, le=11000),
    time: str | None = Query(None),
    time_index: int | None = Query(None, ge=0),
    threshold_factor: float = Query(0.2, gt=0, le=2),
    min_cells: int = Query(6, ge=3, le=500),
    stride: int = Query(1, ge=1, le=16),
    include_field: bool = Query(False, description="Also return the Okubo-Weiss field"),
    catalog: Catalog = Depends(get_catalog),
) -> dict[str, Any]:
    """Identify eddy cores with the Okubo-Weiss parameter.

    Mesoscale eddies concentrate nutrients and drive fish aggregation, so an
    eddy census feeds directly into potential-fishing-zone advisories.
    """
    handle = catalog.resolve(dataset)
    for component in ("u", "v"):
        if not handle.has_variable(component):
            raise NotFoundError(
                f"Dataset '{handle.id}' has no '{component}' velocity component; "
                "eddy detection requires both 'u' and 'v'."
            )

    box = parse_bbox(bbox, default=handle.bounds())
    idx = _resolve_time_index(handle, time, time_index)
    depth_value = float(handle.depths[handle.depth_index(depth)])

    u_subset = handle.subset(
        "u", bbox=box, depth_min=depth_value, depth_max=depth_value,
        time_indices=[idx], stride=stride,
    )
    v_subset = handle.subset(
        "v", bbox=box, depth_min=depth_value, depth_max=depth_value,
        time_indices=[idx], stride=stride,
    )

    u_plane = u_subset.values[0, 0]
    v_plane = v_subset.values[0, 0]
    if u_plane.shape != v_plane.shape:
        raise ValidationError("Velocity components have mismatched grids.")
    if min(u_plane.shape) < 3:
        raise ValidationError(
            "The selected region is too small for eddy detection; "
            "widen the bbox or reduce 'stride'."
        )

    eddies, w_field = detect_eddies(
        u_plane, v_plane, u_subset.lats, u_subset.lons,
        threshold_factor=threshold_factor, min_cells=min_cells,
    )

    payload: dict[str, Any] = {
        "dataset": handle.id,
        "product": "eddy_census",
        "method": "Okubo-Weiss, cores at W < -{0} * std(W)".format(threshold_factor),
        "time": u_subset.times[0],
        "depth_m": depth_value,
        "bbox": list(box),
        "count": len(eddies),
        "cyclonic": sum(1 for e in eddies if e.polarity == "cyclonic"),
        "anticyclonic": sum(1 for e in eddies if e.polarity == "anticyclonic"),
        "eddies": [e.to_dict() for e in eddies],
    }
    if include_field:
        payload["okubo_weiss"] = _grid(w_field, u_subset.lats, u_subset.lons, precision=12)
        payload["okubo_weiss"]["units"] = "s-2"
    return payload


# ---------------------------------------------------------------------------
# Drift / search and rescue
# ---------------------------------------------------------------------------
@router.post("/drift", summary="Simulate particle drift (search-and-rescue)")
async def post_drift(
    body: DriftRequest,
    catalog: Catalog = Depends(get_catalog),
) -> dict[str, Any]:
    """Advect a particle cloud through the modelled current field.

    Seeded on a last known position, spread by an initial position
    uncertainty and sub-grid diffusion, and optionally pushed by windage.
    The 95th-percentile radius of the resulting cloud is the search area a
    rescue coordinator actually needs.

    Note: this is a demonstration model, not a certified SAR planning tool.
    """
    handle = catalog.resolve(body.dataset)
    for component in ("u", "v"):
        if not handle.has_variable(component):
            raise NotFoundError(
                f"Dataset '{handle.id}' has no '{component}' velocity component; "
                "drift simulation requires both 'u' and 'v'."
            )

    min_lon, min_lat, max_lon, max_lat = handle.bounds()
    if not (min_lat <= body.lat <= max_lat and min_lon <= body.lon <= max_lon):
        raise ValidationError(
            "The origin lies outside the model domain "
            f"[{min_lon}, {min_lat}, {max_lon}, {max_lat}].",
            field="lat",
        )

    idx = body.time_index if body.time_index is not None else 0
    idx = max(0, min(idx, max(0, int(handle.times.size) - 1)))
    depth_value = float(handle.depths[handle.depth_index(body.depth)])
    box = handle.bounds()

    u_subset = handle.subset(
        "u", bbox=box, depth_min=depth_value, depth_max=depth_value, time_indices=[idx]
    )
    v_subset = handle.subset(
        "v", bbox=box, depth_min=depth_value, depth_max=depth_value, time_indices=[idx]
    )

    velocity = VelocityField(
        u_subset.values[0, 0], v_subset.values[0, 0], u_subset.lats, u_subset.lons
    )
    result = simulate_drift(
        velocity,
        origin_lat=body.lat,
        origin_lon=body.lon,
        n_particles=body.n_particles,
        duration_hours=body.duration_hours,
        timestep_minutes=body.timestep_minutes,
        initial_spread_km=body.initial_spread_km,
        diffusion_m2_s=body.diffusion_m2_s,
        windage=body.windage,
        wind_u=body.wind_u,
        wind_v=body.wind_v,
        seed=body.seed,
    )

    payload = result.to_dict()
    payload.update(
        {
            "dataset": handle.id,
            "product": "lagrangian_drift",
            "origin": {"lat": body.lat, "lon": body.lon},
            "depth_m": depth_value,
            "model_time": (
                handle.time_strings()[idx] if handle.times.size else None
            ),
            "n_particles": body.n_particles,
            "duration_hours": body.duration_hours,
            "final_search_radius_km": result.radius_km[-1] if result.radius_km else 0.0,
            "final_centroid": result.centroid[-1] if result.centroid else None,
            "disclaimer": (
                "Demonstration model driven by a single static current field. "
                "Not a certified search-and-rescue planning product."
            ),
        }
    )
    return payload
