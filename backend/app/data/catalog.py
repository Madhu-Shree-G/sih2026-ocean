"""Dataset catalog: discovery, metadata and validated subsetting.

The catalog owns every open :class:`xarray.Dataset`.  Handles are opened once
at startup and reused, because re-opening a Zarr store per request is the
single easiest way to make an otherwise fast API feel sluggish.
"""

from __future__ import annotations

import threading
from dataclasses import dataclass, field
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

import numpy as np
import pandas as pd
import xarray as xr

from app.config import settings
from app.core.errors import DataUnavailableError, NotFoundError, ValidationError
from app.core.logging import get_logger
from app.data.adapters.base import VariableSpec, registry
from app.data.adapters.netcdf_model import NetCDFModelAdapter
from app.data.conventions import variable_spec
from app.security.validation import safe_identifier

logger = get_logger(__name__)


@dataclass(slots=True)
class Axis:
    """Description of one coordinate axis, as published to the client."""

    name: str
    size: int
    min: float | str
    max: float | str
    units: str = ""
    values: list[float] | list[str] = field(default_factory=list)


@dataclass(slots=True)
class SubsetResult:
    """A materialised subset plus the axes that describe it."""

    values: np.ndarray                    # shape (time, depth, lat, lon)
    lats: np.ndarray
    lons: np.ndarray
    depths: np.ndarray
    times: list[str]
    variable: str
    units: str
    actual_min: float
    actual_max: float

    @property
    def shape(self) -> tuple[int, int, int, int]:
        return tuple(self.values.shape)  # type: ignore[return-value]


class DatasetHandle:
    """A single opened model dataset with cached axis metadata."""

    def __init__(self, dataset_id: str, path: Path, adapter: NetCDFModelAdapter) -> None:
        self.id = dataset_id
        self.path = path
        self.adapter = adapter
        self._lock = threading.RLock()
        self._ds: xr.Dataset | None = None
        self._specs: dict[str, VariableSpec] | None = None

    # -- access ------------------------------------------------------------
    @property
    def ds(self) -> xr.Dataset:
        if self._ds is None:
            with self._lock:
                if self._ds is None:
                    self._ds = self.adapter.open_dataset()
        return self._ds

    def close(self) -> None:
        with self._lock:
            if self._ds is not None:
                try:
                    self._ds.close()
                except Exception:  # pragma: no cover
                    logger.debug("dataset_close_failed", extra={"dataset": self.id})
                self._ds = None

    # -- metadata ----------------------------------------------------------
    @property
    def variable_specs(self) -> dict[str, VariableSpec]:
        if self._specs is None:
            with self._lock:
                if self._specs is None:
                    self._specs = {spec.name: spec for spec in self.adapter.variables()}
        return self._specs

    def has_variable(self, name: str) -> bool:
        return name in self.variable_specs

    def require_variable(self, name: str) -> VariableSpec:
        safe_identifier(name, field="variable")
        spec = self.variable_specs.get(name)
        if spec is None:
            raise NotFoundError(
                f"Variable '{name}' is not present in dataset '{self.id}'.",
                available=sorted(self.variable_specs),
            )
        return spec

    def _axis_values(self, name: str) -> np.ndarray:
        if name not in self.ds.coords:
            return np.asarray([])
        return np.asarray(self.ds[name].values)

    @property
    def lats(self) -> np.ndarray:
        return self._axis_values("lat")

    @property
    def lons(self) -> np.ndarray:
        return self._axis_values("lon")

    @property
    def depths(self) -> np.ndarray:
        values = self._axis_values("depth")
        return values if values.size else np.asarray([0.0])

    @property
    def times(self) -> np.ndarray:
        return self._axis_values("time")

    def time_strings(self) -> list[str]:
        return [_isoformat(t) for t in self.times]

    def axes(self) -> dict[str, Axis]:
        result: dict[str, Axis] = {}
        for name, units in (("lat", "degrees_north"), ("lon", "degrees_east"), ("depth", "m")):
            values = self._axis_values(name)
            if values.size:
                result[name] = Axis(
                    name=name,
                    size=int(values.size),
                    min=float(np.min(values)),
                    max=float(np.max(values)),
                    units=units,
                    values=[float(v) for v in values] if name == "depth" else [],
                )
        times = self.time_strings()
        if times:
            result["time"] = Axis(
                name="time", size=len(times), min=times[0], max=times[-1],
                units="ISO-8601", values=times,
            )
        return result

    def bounds(self) -> tuple[float, float, float, float]:
        """Return ``(min_lon, min_lat, max_lon, max_lat)``."""
        lats, lons = self.lats, self.lons
        if not lats.size or not lons.size:
            return (
                settings.domain_lon_min, settings.domain_lat_min,
                settings.domain_lon_max, settings.domain_lat_max,
            )
        return (
            float(np.min(lons)), float(np.min(lats)),
            float(np.max(lons)), float(np.max(lats)),
        )

    def describe(self) -> dict[str, Any]:
        ds = self.ds
        bounds = self.bounds()
        return {
            "id": self.id,
            "title": str(ds.attrs.get("title", self.id)),
            "summary": str(ds.attrs.get("summary", "")),
            "institution": str(ds.attrs.get("institution", "")),
            "source": str(ds.attrs.get("source", "")),
            "conventions": str(ds.attrs.get("Conventions", "CF-1.8")),
            "adapter": self.adapter.name,
            "bbox": {
                "min_lon": bounds[0], "min_lat": bounds[1],
                "max_lon": bounds[2], "max_lat": bounds[3],
            },
            "axes": {name: _axis_payload(axis) for name, axis in self.axes().items()},
            "variables": [
                {
                    "name": spec.name,
                    "standard_name": spec.standard_name,
                    "long_name": spec.long_name,
                    "units": spec.units,
                    "default_colormap": spec.default_colormap,
                    "default_range": list(spec.default_range) if spec.default_range else None,
                    "vector_group": spec.vector_group,
                }
                for spec in self.variable_specs.values()
            ],
        }

    # -- index helpers -----------------------------------------------------
    def time_index(self, when: datetime | None, *, default: int = 0) -> int:
        """Nearest time index for a timestamp, clamped to the available range."""
        times = self.times
        if times.size == 0:
            return 0
        if when is None:
            return min(default, times.size - 1) if default >= 0 else times.size + default

        target = np.datetime64(when.replace(tzinfo=None), "ns")
        as_ns = times.astype("datetime64[ns]")
        return int(np.argmin(np.abs(as_ns - target)))

    def depth_index(self, depth: float | None) -> int:
        depths = self.depths
        if depth is None:
            return 0
        return int(np.argmin(np.abs(depths - float(depth))))

    def _slice_indices(
        self, axis_values: np.ndarray, lo: float, hi: float
    ) -> tuple[int, int]:
        """Inclusive index window covering ``[lo, hi]`` on an ascending axis."""
        if axis_values.size == 0:
            return 0, 0
        start = int(np.searchsorted(axis_values, lo, side="left"))
        stop = int(np.searchsorted(axis_values, hi, side="right"))
        start = max(0, min(start, axis_values.size - 1))
        stop = max(start + 1, min(stop, axis_values.size))
        return start, stop

    # -- the workhorse -----------------------------------------------------
    def subset(
        self,
        variable: str,
        *,
        bbox: tuple[float, float, float, float],
        depth_min: float | None = None,
        depth_max: float | None = None,
        time_indices: list[int] | None = None,
        stride: int = 1,
        depth_stride: int = 1,
    ) -> SubsetResult:
        """Extract a 4-D block, always returning shape ``(time, depth, lat, lon)``."""
        spec = self.require_variable(variable)
        ds = self.ds
        array = ds[variable]

        min_lon, min_lat, max_lon, max_lat = bbox
        lat_start, lat_stop = self._slice_indices(self.lats, min_lat, max_lat)
        lon_start, lon_stop = self._slice_indices(self.lons, min_lon, max_lon)

        selector: dict[str, Any] = {
            "lat": slice(lat_start, lat_stop, max(1, stride)),
            "lon": slice(lon_start, lon_stop, max(1, stride)),
        }

        has_depth = "depth" in array.dims
        if has_depth:
            depths = self.depths
            lo = depths.min() if depth_min is None else depth_min
            hi = depths.max() if depth_max is None else depth_max
            d_start, d_stop = self._slice_indices(depths, lo, hi)
            selector["depth"] = slice(d_start, d_stop, max(1, depth_stride))

        has_time = "time" in array.dims
        if has_time:
            indices = time_indices if time_indices else [0]
            n_times = int(self.times.size)
            indices = sorted({max(0, min(int(i), n_times - 1)) for i in indices})
            selector["time"] = indices

        block = array.isel(**selector)
        values = np.asarray(block.values, dtype="float32")

        # Normalise to a full 4-D block so downstream code has one shape to handle.
        if not has_time:
            values = values[np.newaxis, ...]
        if not has_depth:
            values = values[:, np.newaxis, ...]
        if values.ndim != 4:
            raise ValidationError(
                f"Variable '{variable}' has unsupported dimensionality {values.ndim}."
            )

        finite = values[np.isfinite(values)]
        actual_min = float(finite.min()) if finite.size else 0.0
        actual_max = float(finite.max()) if finite.size else 0.0

        sel_depths = (
            np.asarray(block["depth"].values, dtype="float64")
            if has_depth and "depth" in block.coords
            else np.asarray([0.0])
        )
        sel_times = (
            [_isoformat(t) for t in np.atleast_1d(block["time"].values)]
            if has_time and "time" in block.coords
            else ["1970-01-01T00:00:00Z"]
        )

        return SubsetResult(
            values=values,
            lats=np.asarray(block["lat"].values, dtype="float64"),
            lons=np.asarray(block["lon"].values, dtype="float64"),
            depths=sel_depths,
            times=sel_times,
            variable=variable,
            units=spec.units,
            actual_min=actual_min,
            actual_max=actual_max,
        )

    def sample_track(
        self,
        variable: str,
        *,
        lats: np.ndarray,
        lons: np.ndarray,
        time_index: int = 0,
        depth_max: float | None = None,
    ) -> tuple[np.ndarray, np.ndarray]:
        """Sample a whole track at once, returning ``(depths, values)``.

        ``values`` has shape ``(depth, points)``.  Vectorised deliberately:
        selecting the points one at a time turns an interactive transect drag
        into hundreds of separate store reads.
        """
        self.require_variable(variable)
        array = self.ds[variable]

        lat_index = xr.DataArray(np.asarray(lats, dtype="float64"), dims="points")
        lon_index = xr.DataArray(np.asarray(lons, dtype="float64"), dims="points")

        picked = array.sel(lat=lat_index, lon=lon_index, method="nearest")
        if "time" in picked.dims:
            picked = picked.isel(time=min(time_index, picked.sizes["time"] - 1))

        depths = self.depths
        if "depth" in picked.dims:
            if depth_max is not None:
                keep = np.where(depths <= depth_max)[0]
                if keep.size:
                    picked = picked.isel(depth=keep)
                    depths = depths[keep]
            values = np.asarray(picked.transpose("depth", "points").values, dtype="float64")
        else:
            depths = np.asarray([0.0])
            values = np.asarray(picked.values, dtype="float64")[np.newaxis, :]

        return depths, values

    def point_profile(
        self, variable: str, *, lat: float, lon: float, time_index: int = 0
    ) -> tuple[np.ndarray, np.ndarray]:
        """Return ``(depths, values)`` for the grid cell nearest ``(lat, lon)``."""
        self.require_variable(variable)
        array = self.ds[variable]

        selector: dict[str, Any] = {"lat": lat, "lon": lon}
        picked = array.sel(**selector, method="nearest")
        if "time" in picked.dims:
            picked = picked.isel(time=min(time_index, picked.sizes["time"] - 1))

        values = np.asarray(picked.values, dtype="float64").ravel()
        depths = self.depths if "depth" in array.dims else np.asarray([0.0])
        length = min(len(depths), len(values))
        return depths[:length], values[:length]


class Catalog:
    """Discovers and holds every dataset the service can serve."""

    def __init__(self, zarr_dir: Path | None = None) -> None:
        self.zarr_dir = Path(zarr_dir or settings.zarr_dir)
        self._datasets: dict[str, DatasetHandle] = {}
        self._lock = threading.RLock()

    def load(self) -> None:
        """(Re)scan the data directory for Zarr stores and NetCDF files."""
        with self._lock:
            for handle in self._datasets.values():
                handle.close()
            self._datasets.clear()

            if not self.zarr_dir.exists():
                logger.warning("zarr_dir_missing", extra={"path": str(self.zarr_dir)})
                return

            candidates = sorted(
                [p for p in self.zarr_dir.iterdir() if p.name.endswith(".zarr")]
                + [p for p in self.zarr_dir.glob("*.nc")]
            )

            for path in candidates:
                dataset_id = path.name.removesuffix(".zarr").removesuffix(".nc")
                try:
                    dataset_id = safe_identifier(dataset_id, field="dataset_id")
                except ValidationError:
                    logger.warning("dataset_id_rejected", extra={"path": path.name})
                    continue

                adapter = NetCDFModelAdapter(path)
                problems = adapter.validate()
                if problems:
                    logger.warning(
                        "dataset_rejected",
                        extra={"dataset": dataset_id, "problems": problems},
                    )
                    continue

                self._datasets[dataset_id] = DatasetHandle(dataset_id, path, adapter)
                logger.info("dataset_loaded", extra={"dataset": dataset_id})

            logger.info("catalog_ready", extra={"count": len(self._datasets)})

    def close(self) -> None:
        with self._lock:
            for handle in self._datasets.values():
                handle.close()
            self._datasets.clear()

    # -- lookups -----------------------------------------------------------
    def ids(self) -> list[str]:
        return sorted(self._datasets)

    def is_empty(self) -> bool:
        return not self._datasets

    def get(self, dataset_id: str) -> DatasetHandle:
        safe_identifier(dataset_id, field="dataset_id")
        handle = self._datasets.get(dataset_id)
        if handle is None:
            if not self._datasets:
                raise DataUnavailableError()
            raise NotFoundError(
                f"Dataset '{dataset_id}' was not found.", available=self.ids()
            )
        return handle

    def default(self) -> DatasetHandle:
        if not self._datasets:
            raise DataUnavailableError()
        return self._datasets[self.ids()[0]]

    def resolve(self, dataset_id: str | None) -> DatasetHandle:
        return self.default() if not dataset_id else self.get(dataset_id)

    def describe_all(self) -> list[dict[str, Any]]:
        return [handle.describe() for handle in self._datasets.values()]

    def plugin_manifest(self) -> list[dict[str, Any]]:
        return registry.manifest()


def _isoformat(value: Any) -> str:
    """Render a numpy/pandas timestamp as a UTC ISO-8601 string."""
    try:
        stamp = pd.Timestamp(value)
    except (ValueError, TypeError):
        return str(value)
    if stamp.tzinfo is None:
        stamp = stamp.tz_localize(timezone.utc)
    return stamp.tz_convert(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


def _axis_payload(axis: Axis) -> dict[str, Any]:
    payload: dict[str, Any] = {
        "size": axis.size, "min": axis.min, "max": axis.max, "units": axis.units,
    }
    if axis.values:
        payload["values"] = axis.values
    return payload


__all__ = ["Catalog", "DatasetHandle", "SubsetResult", "Axis", "variable_spec"]
