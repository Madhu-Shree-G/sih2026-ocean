"""Adapter for gridded model output stored as NetCDF or Zarr.

Handles CMEMS/GLORYS, HYCOM, ROMS and INCOIS INDOFOS style files: anything
whose coordinates can be normalised onto ``(time, depth, lat, lon)``.
"""

from __future__ import annotations

from pathlib import Path
from typing import Any, ClassVar

import xarray as xr

from app.core.logging import get_logger
from app.data.adapters.base import ModelAdapter, VariableSpec, registry
from app.data.conventions import (
    attach_cf_attributes,
    canonical_variable_name,
    normalise_dataset,
    variable_spec,
)

logger = get_logger(__name__)


@registry.register
class NetCDFModelAdapter(ModelAdapter):
    """Read gridded ocean model fields from NetCDF or a Zarr store."""

    name: ClassVar[str] = "netcdf_model"
    description: ClassVar[str] = (
        "Gridded ocean model output (NetCDF-4 / Zarr) with CF coordinates. "
        "Covers CMEMS GLORYS, HYCOM GOFS, ROMS and INCOIS INDOFOS products."
    )
    suffixes: ClassVar[tuple[str, ...]] = (".nc", ".nc4", ".cdf", ".zarr")

    def __init__(self, path: Path | str) -> None:
        self.path = Path(path)
        self._ds: xr.Dataset | None = None

    @classmethod
    def can_handle(cls, path: Path) -> bool:
        if path.suffix.lower() == ".zarr" or (path.is_dir() and path.name.endswith(".zarr")):
            return True
        return path.suffix.lower() in cls.suffixes

    # -- lifecycle ---------------------------------------------------------
    def open_dataset(self) -> xr.Dataset:
        if self._ds is not None:
            return self._ds

        if not self.path.exists():
            raise FileNotFoundError(f"Model source not found: {self.path}")

        if self.path.name.endswith(".zarr"):
            ds = self._open_zarr()
        else:
            ds = xr.open_dataset(self.path, decode_timedelta=True)

        ds = attach_cf_attributes(normalise_dataset(ds))
        self._ds = ds
        return ds

    def _open_zarr(self) -> xr.Dataset:
        """Open a Zarr store, tolerating stores without consolidated metadata."""
        try:
            return xr.open_zarr(self.path, consolidated=True, decode_timedelta=True)
        except (KeyError, ValueError, FileNotFoundError, OSError):
            logger.debug("zarr_unconsolidated_fallback", extra={"path": str(self.path)})
            return xr.open_zarr(self.path, consolidated=False, decode_timedelta=True)

    def close(self) -> None:
        if self._ds is not None:
            self._ds.close()
            self._ds = None

    # -- introspection -----------------------------------------------------
    def variables(self) -> list[VariableSpec]:
        ds = self.open_dataset()
        specs: list[VariableSpec] = []
        for name in ds.data_vars:
            str_name = str(name)
            # Skip ancillary fields that are not renderable scalar/vector data.
            if str_name.endswith(("_qc", "_flag", "_mask", "_bnds", "_bounds")):
                continue
            units = ds[name].attrs.get("units")
            specs.append(variable_spec(canonical_variable_name(str_name) or str_name, units=units))
        return specs

    def describe(self) -> dict[str, Any]:
        ds = self.open_dataset()
        return {
            "adapter": self.name,
            "path": str(self.path),
            "dims": {str(k): int(v) for k, v in ds.sizes.items()},
            "variables": [spec.name for spec in self.variables()],
            "attrs": {k: str(v) for k, v in ds.attrs.items()},
        }

    def validate(self) -> list[str]:
        problems: list[str] = []
        try:
            ds = self.open_dataset()
        except Exception as exc:
            return [f"Cannot open dataset: {exc}"]

        for axis in ("lat", "lon"):
            if axis not in ds.coords:
                problems.append(f"Missing required coordinate '{axis}'.")
        if not ds.data_vars:
            problems.append("Dataset contains no data variables.")
        if "depth" in ds.coords and ds["depth"].size == 0:
            problems.append("Depth coordinate is empty.")
        return problems
