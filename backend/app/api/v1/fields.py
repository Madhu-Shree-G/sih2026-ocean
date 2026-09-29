"""Gridded field endpoints: volumes, slices, transects, profiles, time series.

``/volume`` is the endpoint the 3-D renderer lives on.  It returns a binary
OCVOL1 container (see :mod:`app.data.volume`) rather than JSON, because a
40-level cube encoded as JSON numbers is roughly 15x larger and takes longer
to parse than the data took to read.
"""

from __future__ import annotations

from typing import Any

import numpy as np
from fastapi import APIRouter, Depends, Query, Request, Response

from app.config import settings
from app.core.cache import cache_key
from app.core.errors import ValidationError
from app.data.catalog import Catalog, DatasetHandle
from app.data.colormap import ColorScale, render_png
from app.data.volume import build_volume_payload, pack, quantise, subsample_to_budget
from app.security.deps import get_catalog, require_api_key
from app.security.validation import (
    clamp_int,
    guard_cell_budget,
    parse_bbox,
    parse_depth_range,
    parse_iso_time,
    safe_identifier,
)

router = APIRouter(tags=["fields"], dependencies=[Depends(require_api_key)])


# ---------------------------------------------------------------------------
# Shared parameter handling
# ---------------------------------------------------------------------------
def _resolve_time_indices(
    handle: DatasetHandle,
    *,
    time: str | None,
    time_index: int | None,
    n_times: int,
) -> list[int]:
    """Build the list of timesteps to extract, clamped to the request cap."""
    total = int(handle.times.size) or 1

    if time_index is not None:
        start = max(0, min(int(time_index), total - 1))
    elif time:
        start = handle.time_index(parse_iso_time(time, field="time"))
    else:
        start = 0

    count = clamp_int(
        n_times, default=1, minimum=1,
        maximum=min(settings.max_timesteps_per_request, total), field="n_times",
    )
    return list(range(start, min(start + count, total)))


def _default_bbox(handle: DatasetHandle) -> tuple[float, float, float, float]:
    return handle.bounds()


def _resolve_range(
    handle: DatasetHandle, variable: str, vmin: float | None, vmax: float | None
) -> tuple[float | None, float | None]:
    """Fall back to the variable's canonical display range when unspecified."""
    if vmin is not None and vmax is not None:
        if vmin >= vmax:
            raise ValidationError("'vmin' must be smaller than 'vmax'.", field="vmin")
        return vmin, vmax

    spec = handle.variable_specs.get(variable)
    default = spec.default_range if spec else None
    return (
        vmin if vmin is not None else (default[0] if default else None),
        vmax if vmax is not None else (default[1] if default else None),
    )


# ---------------------------------------------------------------------------
# Volume
# ---------------------------------------------------------------------------
@router.get(
    "/volume",
    summary="Extract a 3-D volume for WebGL upload",
    response_class=Response,
    responses={200: {"content": {"application/octet-stream": {}}}},
)
async def get_volume(
    request: Request,
    dataset: str | None = Query(None, description="Dataset id; defaults to the first available"),
    variable: str = Query("temperature", description="Variable name"),
    bbox: str | None = Query(None, description="min_lon,min_lat,max_lon,max_lat"),
    depth_min: float | None = Query(None, ge=0, le=11000),
    depth_max: float | None = Query(None, ge=0, le=11000),
    time: str | None = Query(None, description="ISO-8601 timestamp; nearest step is used"),
    time_index: int | None = Query(None, ge=0),
    n_times: int = Query(1, ge=1, description="Consecutive timesteps to include"),
    stride: int = Query(1, ge=1, le=32, description="Horizontal subsampling stride"),
    depth_stride: int = Query(1, ge=1, le=16),
    vmin: float | None = Query(None),
    vmax: float | None = Query(None),
    auto_stride: bool = Query(True, description="Coarsen automatically instead of failing"),
    catalog: Catalog = Depends(get_catalog),
) -> Response:
    """Return a quantised ``(time, depth, lat, lon)`` block as OCVOL1 binary.

    The payload uploads directly as a WebGL2 ``TEXTURE_3D``; depth slicing,
    isosurface thresholds and colorbar edits then happen entirely on the GPU
    with no further requests.
    """
    safe_identifier(variable, field="variable")
    handle = catalog.resolve(dataset)
    spec = handle.require_variable(variable)

    box = parse_bbox(bbox, default=_default_bbox(handle))
    depths = handle.depths
    d_lo, d_hi = parse_depth_range(
        depth_min, depth_max,
        available_min=float(depths.min()), available_max=float(depths.max()),
    )
    indices = _resolve_time_indices(handle, time=time, time_index=time_index, n_times=n_times)

    # Estimate the extraction size before touching the store.
    lat_count = int(np.sum((handle.lats >= box[1]) & (handle.lats <= box[3])))
    lon_count = int(np.sum((handle.lons >= box[0]) & (handle.lons <= box[2])))
    depth_count = int(np.sum((depths >= d_lo) & (depths <= d_hi)))
    depth_count = max(1, (depth_count + depth_stride - 1) // depth_stride)

    if auto_stride:
        needed = subsample_to_budget(
            lat_count, lon_count, depth_count, len(indices),
            max_cells=settings.max_volume_cells,
        )
        stride = max(stride, needed)

    guard_cell_budget(
        n_lat=(lat_count + stride - 1) // stride,
        n_lon=(lon_count + stride - 1) // stride,
        n_depth=depth_count,
        n_time=len(indices),
        bytes_per_cell=1,
        max_cells=settings.max_volume_cells,
        max_bytes=settings.max_volume_bytes,
    )

    key = cache_key(
        "volume", dataset=handle.id, variable=variable, bbox=box, depth=(d_lo, d_hi),
        indices=indices, stride=stride, depth_stride=depth_stride, vmin=vmin, vmax=vmax,
    )
    cache = request.app.state.cache

    def build() -> bytes:
        subset = handle.subset(
            variable, bbox=box, depth_min=d_lo, depth_max=d_hi,
            time_indices=indices, stride=stride, depth_stride=depth_stride,
        )
        lo, hi = _resolve_range(handle, variable, vmin, vmax)
        return build_volume_payload(
            values=subset.values,
            variable=variable,
            units=subset.units,
            dataset_id=handle.id,
            lats=subset.lats,
            lons=subset.lons,
            depths=subset.depths,
            times=subset.times,
            colormap=spec.default_colormap,
            vmin=lo,
            vmax=hi,
            extra={
                "long_name": spec.long_name,
                "standard_name": spec.standard_name,
                "stride": stride,
                "depth_stride": depth_stride,
                "actual_range": [subset.actual_min, subset.actual_max],
            },
        )

    payload = cache.get_or_set(key, build)
    return Response(
        content=payload,
        media_type="application/octet-stream",
        headers={
            "X-Ocean-Format": "OCVOL1",
            "X-Ocean-Variable": variable,
            "X-Ocean-Dataset": handle.id,
            "X-Ocean-Payload-Bytes": str(len(payload)),
            "Cache-Control": "public, max-age=300",
        },
    )


# ---------------------------------------------------------------------------
# Horizontal slice
# ---------------------------------------------------------------------------
@router.get(
    "/slice",
    summary="Extract one depth slice",
    response_class=Response,
    responses={200: {"content": {"application/octet-stream": {}, "image/png": {}, "application/json": {}}}},
)
async def get_slice(
    request: Request,
    dataset: str | None = Query(None),
    variable: str = Query("temperature"),
    depth: float = Query(0.0, ge=0, le=11000, description="Target depth in metres"),
    bbox: str | None = Query(None),
    time: str | None = Query(None),
    time_index: int | None = Query(None, ge=0),
    stride: int = Query(1, ge=1, le=32),
    vmin: float | None = Query(None),
    vmax: float | None = Query(None),
    colormap: str | None = Query(None),
    scale: str = Query("linear", pattern="^(linear|log)$"),
    format: str = Query("binary", pattern="^(binary|png|json)$"),
    catalog: Catalog = Depends(get_catalog),
) -> Response:
    """One horizontal level as binary, PNG or JSON.

    ``binary`` is what the 3-D client uses; ``png`` exists for map overlays
    and for the WMS-style workflows operational users already have.
    """
    safe_identifier(variable, field="variable")
    handle = catalog.resolve(dataset)
    spec = handle.require_variable(variable)

    box = parse_bbox(bbox, default=_default_bbox(handle))
    indices = _resolve_time_indices(handle, time=time, time_index=time_index, n_times=1)
    depth_index = handle.depth_index(depth)
    actual_depth = float(handle.depths[depth_index])

    subset = handle.subset(
        variable, bbox=box,
        depth_min=actual_depth, depth_max=actual_depth,
        time_indices=indices, stride=stride,
    )
    guard_cell_budget(
        n_lat=subset.values.shape[2], n_lon=subset.values.shape[3],
        max_cells=settings.max_volume_cells, max_bytes=settings.max_volume_bytes,
    )

    plane = subset.values[0, 0]
    lo, hi = _resolve_range(handle, variable, vmin, vmax)
    lo = subset.actual_min if lo is None else lo
    hi = subset.actual_max if hi is None else hi
    palette = colormap or spec.default_colormap

    if format == "png":
        image = render_png(
            plane,
            ColorScale(name=palette, vmin=lo, vmax=hi, scale=scale),  # type: ignore[arg-type]
        )
        return Response(
            content=image,
            media_type="image/png",
            headers={"Cache-Control": "public, max-age=300"},
        )

    if format == "json":
        return _json_response(
            {
                "dataset": handle.id,
                "variable": variable,
                "units": subset.units,
                "depth_m": actual_depth,
                "time": subset.times[0],
                "bbox": list(box),
                "shape": [int(plane.shape[0]), int(plane.shape[1])],
                "lats": [round(float(v), 5) for v in subset.lats],
                "lons": [round(float(v), 5) for v in subset.lons],
                "value_range": [lo, hi],
                "actual_range": [subset.actual_min, subset.actual_max],
                "values": [
                    [None if not np.isfinite(v) else round(float(v), 4) for v in row]
                    for row in plane
                ],
            }
        )

    field = quantise(plane, vmin=lo, vmax=hi)
    header = {
        "format": "OCVOL1",
        "dataset": handle.id,
        "variable": variable,
        "units": subset.units,
        "dtype": "uint8",
        "shape": [int(plane.shape[0]), int(plane.shape[1])],
        "axis_order": ["lat", "lon"],
        "scale": field.scale,
        "offset": field.offset,
        "nodata_raw": 0,
        "min_valid_raw": 1,
        "value_range": [field.vmin, field.vmax],
        "depth_m": actual_depth,
        "time": subset.times[0],
        "bbox": list(box),
        "lat_range": [float(subset.lats.min()), float(subset.lats.max())],
        "lon_range": [float(subset.lons.min()), float(subset.lons.max())],
        "colormap": palette,
    }
    payload = pack(header, field.data)
    return Response(
        content=payload,
        media_type="application/octet-stream",
        headers={"X-Ocean-Format": "OCVOL1", "Cache-Control": "public, max-age=300"},
    )


# ---------------------------------------------------------------------------
# Vertical transect
# ---------------------------------------------------------------------------
@router.get("/transect", summary="Vertical section along a line")
async def get_transect(
    dataset: str | None = Query(None),
    variable: str = Query("temperature"),
    start_lat: float = Query(..., ge=-90, le=90),
    start_lon: float = Query(..., ge=-360, le=360),
    end_lat: float = Query(..., ge=-90, le=90),
    end_lon: float = Query(..., ge=-360, le=360),
    n_points: int = Query(120, ge=2),
    depth_max: float | None = Query(None, ge=0, le=11000),
    time: str | None = Query(None),
    time_index: int | None = Query(None, ge=0),
    catalog: Catalog = Depends(get_catalog),
) -> Response:
    """Sample a depth section between two points.

    This is the everyday working tool of an operational oceanographer:
    draw a line across the map, see the water column underneath it.
    """
    safe_identifier(variable, field="variable")
    handle = catalog.resolve(dataset)
    spec = handle.require_variable(variable)

    points = clamp_int(
        n_points, default=120, minimum=2,
        maximum=settings.max_transect_points, field="n_points",
    )
    if abs(start_lat - end_lat) < 1e-9 and abs(start_lon - end_lon) < 1e-9:
        raise ValidationError("Transect start and end points must differ.", field="end_lat")

    indices = _resolve_time_indices(handle, time=time, time_index=time_index, n_times=1)
    time_idx = indices[0]

    lats = np.linspace(start_lat, end_lat, points)
    lons = np.linspace(start_lon, end_lon, points)

    depths, section = handle.sample_track(
        variable, lats=lats, lons=lons, time_index=time_idx, depth_max=depth_max
    )

    # Cumulative along-track distance in kilometres.
    distances = [0.0]
    for i in range(1, points):
        d_lat = (lats[i] - lats[i - 1]) * 111.32
        d_lon = (lons[i] - lons[i - 1]) * 111.32 * float(np.cos(np.deg2rad(lats[i])))
        distances.append(distances[-1] + float(np.hypot(d_lat, d_lon)))

    finite = section[np.isfinite(section)]
    return _json_response(
        {
            "dataset": handle.id,
            "variable": variable,
            "units": spec.units,
            "time": handle.time_strings()[time_idx] if handle.times.size else None,
            "start": {"lat": start_lat, "lon": start_lon},
            "end": {"lat": end_lat, "lon": end_lon},
            "n_points": points,
            "total_distance_km": round(distances[-1], 3),
            "distance_km": [round(d, 3) for d in distances],
            "track": [
                {"lat": round(float(a), 5), "lon": round(float(b), 5)}
                for a, b in zip(lats, lons)
            ],
            "depth_m": [round(float(d), 3) for d in depths],
            "values": [
                [None if not np.isfinite(v) else round(float(v), 4) for v in row]
                for row in section
            ],
            "value_range": (
                [round(float(finite.min()), 4), round(float(finite.max()), 4)]
                if finite.size else [None, None]
            ),
            "colormap": spec.default_colormap,
        }
    )


# ---------------------------------------------------------------------------
# Point profile and time series
# ---------------------------------------------------------------------------
@router.get("/profile", summary="Modelled vertical profile at a point")
async def get_point_profile(
    dataset: str | None = Query(None),
    variable: str = Query("temperature"),
    lat: float = Query(..., ge=-90, le=90),
    lon: float = Query(..., ge=-360, le=360),
    time: str | None = Query(None),
    time_index: int | None = Query(None, ge=0),
    catalog: Catalog = Depends(get_catalog),
) -> Response:
    """The model's water column at one location - the dashed line in the UI."""
    safe_identifier(variable, field="variable")
    handle = catalog.resolve(dataset)
    spec = handle.require_variable(variable)

    indices = _resolve_time_indices(handle, time=time, time_index=time_index, n_times=1)
    depths, values = handle.point_profile(variable, lat=lat, lon=lon, time_index=indices[0])

    nearest_lat = float(handle.lats[int(np.argmin(np.abs(handle.lats - lat)))])
    nearest_lon = float(handle.lons[int(np.argmin(np.abs(handle.lons - lon)))])

    return _json_response(
        {
            "dataset": handle.id,
            "variable": variable,
            "units": spec.units,
            "requested": {"lat": lat, "lon": lon},
            "grid_point": {"lat": nearest_lat, "lon": nearest_lon},
            "time": handle.time_strings()[indices[0]] if handle.times.size else None,
            "depth_m": [round(float(d), 3) for d in depths],
            "values": [None if not np.isfinite(v) else round(float(v), 4) for v in values],
        }
    )


@router.get("/timeseries", summary="Time series at a point and depth")
async def get_timeseries(
    dataset: str | None = Query(None),
    variable: str = Query("temperature"),
    lat: float = Query(..., ge=-90, le=90),
    lon: float = Query(..., ge=-360, le=360),
    depth: float = Query(0.0, ge=0, le=11000),
    catalog: Catalog = Depends(get_catalog),
) -> Response:
    """How one variable evolved at a fixed location and depth."""
    safe_identifier(variable, field="variable")
    handle = catalog.resolve(dataset)
    spec = handle.require_variable(variable)

    array = handle.ds[variable]
    selected = array.sel(lat=lat, lon=lon, method="nearest")
    if "depth" in selected.dims:
        selected = selected.sel(depth=depth, method="nearest")

    values = np.asarray(selected.values, dtype="float64").ravel()
    times = handle.time_strings() or ["1970-01-01T00:00:00Z"]

    return _json_response(
        {
            "dataset": handle.id,
            "variable": variable,
            "units": spec.units,
            "location": {"lat": lat, "lon": lon},
            "depth_m": float(handle.depths[handle.depth_index(depth)]),
            "times": times[: values.size],
            "values": [
                None if not np.isfinite(v) else round(float(v), 4)
                for v in values[: len(times)]
            ],
        }
    )


@router.get("/hovmoller", summary="Time-depth section at a point")
async def get_hovmoller(
    dataset: str | None = Query(None),
    variable: str = Query("temperature"),
    lat: float = Query(..., ge=-90, le=90),
    lon: float = Query(..., ge=-360, le=360),
    depth_max: float | None = Query(None, ge=0, le=11000),
    catalog: Catalog = Depends(get_catalog),
) -> Response:
    """Depth against time at one location.

    Reveals seasonal thermocline behaviour that no single snapshot shows.
    """
    safe_identifier(variable, field="variable")
    handle = catalog.resolve(dataset)
    spec = handle.require_variable(variable)

    array = handle.ds[variable]
    if "depth" not in array.dims or "time" not in array.dims:
        raise ValidationError(
            f"Variable '{variable}' lacks the depth or time axis needed for a Hovmoller plot."
        )

    selected = array.sel(lat=lat, lon=lon, method="nearest")
    depths = handle.depths
    if depth_max is not None:
        mask = depths <= depth_max
        if mask.any():
            selected = selected.isel(depth=np.where(mask)[0])
            depths = depths[mask]

    values = np.asarray(selected.values, dtype="float64")
    if values.ndim != 2:
        raise ValidationError("Unexpected array shape for a Hovmoller section.")
    # xarray returns (time, depth); the client wants depth-major rows.
    if values.shape[0] == len(handle.time_strings()):
        values = values.T

    return _json_response(
        {
            "dataset": handle.id,
            "variable": variable,
            "units": spec.units,
            "location": {"lat": lat, "lon": lon},
            "times": handle.time_strings(),
            "depth_m": [round(float(d), 3) for d in depths],
            "values": [
                [None if not np.isfinite(v) else round(float(v), 4) for v in row]
                for row in values
            ],
            "colormap": spec.default_colormap,
        }
    )


def _json_response(payload: dict[str, Any]) -> Response:
    """Serialise with orjson-like compactness while keeping NaN out of JSON."""
    import json

    return Response(
        content=json.dumps(payload, separators=(",", ":"), allow_nan=False),
        media_type="application/json",
        headers={"Cache-Control": "public, max-age=120"},
    )
