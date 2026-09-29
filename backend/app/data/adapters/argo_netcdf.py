"""Adapter for Argo float and glider profiles in NetCDF form.

Reads the Argo GDAC profile layout (``PLATFORM_NUMBER``, ``JULD``, ``PRES``,
``TEMP``, ``PSAL``, ...) and tolerates the reduced variants produced by
glider mission processing, where a subset of those variables is present.

Reference: Argo User's Manual, data format for single-cycle profile files.
"""

from __future__ import annotations

from datetime import datetime, timezone
from pathlib import Path
from typing import Any, ClassVar, Iterator

import numpy as np
import xarray as xr

from app.core.logging import get_logger
from app.data.adapters.base import ObservationAdapter, ProfileRecord, registry

logger = get_logger(__name__)

#: Argo QC flags considered acceptable: 1 = good, 2 = probably good,
#: 5 = changed/adjusted, 8 = interpolated.
ACCEPTABLE_QC = frozenset({1, 2, 5, 8})


def _decode(value: Any) -> str:
    """Argo stores identifiers as fixed-width byte arrays."""
    if isinstance(value, bytes):
        return value.decode("utf-8", errors="ignore").strip()
    if isinstance(value, np.ndarray):
        if value.dtype.kind == "S":
            return b"".join(value.ravel().tolist()).decode("utf-8", errors="ignore").strip()
        return "".join(str(v) for v in value.ravel()).strip()
    return str(value).strip()


def _to_float_list(array: np.ndarray | None) -> list[float | None]:
    if array is None:
        return []
    values = np.asarray(array, dtype="float64").ravel()
    return [None if not np.isfinite(v) else float(v) for v in values]


def _first_present(ds: xr.Dataset, *names: str) -> xr.DataArray | None:
    for name in names:
        if name in ds.variables:
            return ds[name]
    return None


@registry.register
class ArgoNetCDFAdapter(ObservationAdapter):
    """Read in-situ vertical profiles from Argo-format NetCDF."""

    name: ClassVar[str] = "argo_netcdf"
    description: ClassVar[str] = (
        "Argo float / glider vertical profiles in Argo GDAC NetCDF format "
        "(PLATFORM_NUMBER, JULD, PRES, TEMP, PSAL, DOXY, CHLA)."
    )
    suffixes: ClassVar[tuple[str, ...]] = (".nc", ".nc4")

    #: Argo reference epoch for the JULD variable.
    EPOCH = datetime(1950, 1, 1, tzinfo=timezone.utc)

    def __init__(self, path: Path | str, *, platform_type: str = "argo_float") -> None:
        self.path = Path(path)
        self.platform_type = platform_type

    @classmethod
    def can_handle(cls, path: Path) -> bool:
        if path.suffix.lower() not in cls.suffixes:
            return False
        try:
            with xr.open_dataset(path, decode_times=False) as ds:
                return "JULD" in ds.variables or "PRES" in ds.variables
        except Exception:
            return False

    def _juld_to_datetime(self, value: float) -> datetime | None:
        if not np.isfinite(value):
            return None
        try:
            return self.EPOCH + np.timedelta64(int(value * 86400.0), "s").item()
        except (ValueError, OverflowError):
            return None

    def read_profiles(self) -> Iterator[ProfileRecord]:
        with xr.open_dataset(self.path, decode_times=False) as ds:
            n_profiles = int(ds.sizes.get("N_PROF", 1))

            platform = _first_present(ds, "PLATFORM_NUMBER", "platform_number")
            cycles = _first_present(ds, "CYCLE_NUMBER", "cycle_number")
            juld = _first_present(ds, "JULD", "juld", "TIME")
            lats = _first_present(ds, "LATITUDE", "latitude")
            lons = _first_present(ds, "LONGITUDE", "longitude")
            pres = _first_present(ds, "PRES_ADJUSTED", "PRES", "pressure", "DEPTH")
            temp = _first_present(ds, "TEMP_ADJUSTED", "TEMP", "temperature")
            psal = _first_present(ds, "PSAL_ADJUSTED", "PSAL", "salinity")
            doxy = _first_present(ds, "DOXY_ADJUSTED", "DOXY")
            chla = _first_present(ds, "CHLA_ADJUSTED", "CHLA")
            mode = _first_present(ds, "DATA_MODE", "data_mode")

            if pres is None or lats is None or lons is None:
                logger.warning("argo_missing_core_variables", extra={"path": str(self.path)})
                return

            for i in range(n_profiles):
                lat = float(np.asarray(lats.values).ravel()[i])
                lon = float(np.asarray(lons.values).ravel()[i])
                if not (np.isfinite(lat) and np.isfinite(lon)):
                    continue

                time_value = None
                if juld is not None:
                    time_value = self._juld_to_datetime(
                        float(np.asarray(juld.values).ravel()[i])
                    )
                if time_value is None:
                    continue

                depth_row = np.asarray(pres.values)
                depth_row = depth_row[i] if depth_row.ndim > 1 else depth_row
                depths = _to_float_list(depth_row)

                valid = [idx for idx, d in enumerate(depths) if d is not None]
                if not valid:
                    continue

                def column(var: xr.DataArray | None) -> list[float | None]:
                    if var is None:
                        return [None] * len(valid)
                    arr = np.asarray(var.values)
                    row = arr[i] if arr.ndim > 1 else arr
                    series = _to_float_list(row)
                    return [series[idx] if idx < len(series) else None for idx in valid]

                platform_id = (
                    _decode(np.asarray(platform.values)[i]) if platform is not None
                    else self.path.stem
                )
                cycle = 0
                if cycles is not None:
                    raw_cycle = np.asarray(cycles.values).ravel()[i]
                    if np.isfinite(raw_cycle):
                        cycle = int(raw_cycle)

                yield ProfileRecord(
                    platform_id=platform_id or self.path.stem,
                    platform_type=self.platform_type,
                    cycle_number=cycle,
                    time=time_value,
                    latitude=lat,
                    longitude=lon,
                    depth=[depths[idx] for idx in valid],  # type: ignore[misc]
                    temperature=column(temp),
                    salinity=column(psal),
                    chlorophyll=column(chla),
                    oxygen=column(doxy),
                    data_mode=_decode(np.asarray(mode.values)[i]) if mode is not None else "R",
                    source_file=self.path.name,
                )

    def describe(self) -> dict[str, Any]:
        return {"adapter": self.name, "path": str(self.path), "kind": self.kind}

    def validate(self) -> list[str]:
        if not self.path.exists():
            return [f"File not found: {self.path}"]
        try:
            count = sum(1 for _ in self.read_profiles())
        except Exception as exc:
            return [f"Cannot read profiles: {exc}"]
        return [] if count else ["No usable profiles found in file."]
