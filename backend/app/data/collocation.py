"""Model / observation collocation.

This is the module the problem statement is really about.  INCOIS's stated
pain is that forecasters "toggle between disparate software packages" and so
cannot rapidly "correlate model predictions with observational evidence".

Collocation means: given an in-situ profile at (lat, lon, time), extract the
model's prediction at that same point in space and time, interpolate both
onto a common depth axis, and quantify the difference.  Everything the UI
needs to draw the observed profile and the modelled profile on one pair of
axes comes out of :func:`collocate_profile`.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime
from typing import Any, Sequence

import numpy as np

from app.core.errors import ValidationError
from app.core.logging import get_logger
from app.data.catalog import DatasetHandle

logger = get_logger(__name__)

#: Observation depths deeper than the model's deepest level cannot be
#: compared and are dropped rather than extrapolated.
MAX_EXTRAPOLATION_M = 0.0


@dataclass(slots=True)
class MatchStatistics:
    """Agreement metrics between an observed and a modelled profile."""

    count: int
    bias: float               # mean(model - observation)
    rmsd: float
    mae: float
    correlation: float
    obs_mean: float
    model_mean: float
    max_abs_difference: float
    depth_of_max_difference: float

    def to_dict(self) -> dict[str, Any]:
        return {
            "n_levels": self.count,
            "bias": _round(self.bias),
            "rmsd": _round(self.rmsd),
            "mae": _round(self.mae),
            "correlation": _round(self.correlation),
            "observation_mean": _round(self.obs_mean),
            "model_mean": _round(self.model_mean),
            "max_abs_difference": _round(self.max_abs_difference),
            "depth_of_max_difference_m": _round(self.depth_of_max_difference, 1),
        }


@dataclass(slots=True)
class CollocationResult:
    """A paired observed/modelled profile ready for plotting."""

    variable: str
    units: str
    dataset_id: str
    platform_id: str
    latitude: float
    longitude: float
    observation_time: str
    model_time: str
    time_offset_hours: float
    grid_distance_km: float
    depths: list[float] = field(default_factory=list)
    observed: list[float | None] = field(default_factory=list)
    modelled: list[float | None] = field(default_factory=list)
    difference: list[float | None] = field(default_factory=list)
    statistics: MatchStatistics | None = None
    warnings: list[str] = field(default_factory=list)

    def to_dict(self) -> dict[str, Any]:
        return {
            "variable": self.variable,
            "units": self.units,
            "dataset": self.dataset_id,
            "platform_id": self.platform_id,
            "location": {"lat": self.latitude, "lon": self.longitude},
            "observation_time": self.observation_time,
            "model_time": self.model_time,
            "time_offset_hours": _round(self.time_offset_hours, 2),
            "grid_distance_km": _round(self.grid_distance_km, 2),
            "profile": {
                "depth_m": self.depths,
                "observed": self.observed,
                "modelled": self.modelled,
                "difference": self.difference,
            },
            "statistics": self.statistics.to_dict() if self.statistics else None,
            "warnings": self.warnings,
        }


def _round(value: float, digits: int = 4) -> float | None:
    if value is None or not np.isfinite(value):
        return None
    return round(float(value), digits)


def haversine_km(lat1: float, lon1: float, lat2: float, lon2: float) -> float:
    """Great-circle distance in kilometres."""
    r = 6371.0088
    phi1, phi2 = np.deg2rad(lat1), np.deg2rad(lat2)
    d_phi = phi2 - phi1
    d_lambda = np.deg2rad(lon2 - lon1)
    a = np.sin(d_phi / 2) ** 2 + np.cos(phi1) * np.cos(phi2) * np.sin(d_lambda / 2) ** 2
    return float(2 * r * np.arcsin(np.sqrt(np.clip(a, 0.0, 1.0))))


def compute_statistics(
    observed: np.ndarray, modelled: np.ndarray, depths: np.ndarray
) -> MatchStatistics | None:
    """Standard verification metrics over the levels where both are present."""
    obs = np.asarray(observed, dtype="float64")
    mod = np.asarray(modelled, dtype="float64")
    both = np.isfinite(obs) & np.isfinite(mod)

    if both.sum() < 2:
        return None

    o = obs[both]
    m = mod[both]
    z = np.asarray(depths, dtype="float64")[both]
    difference = m - o

    # Correlation is undefined when either series is constant.
    if np.std(o) < 1e-12 or np.std(m) < 1e-12:
        correlation = float("nan")
    else:
        correlation = float(np.corrcoef(o, m)[0, 1])

    max_index = int(np.argmax(np.abs(difference)))
    return MatchStatistics(
        count=int(both.sum()),
        bias=float(np.mean(difference)),
        rmsd=float(np.sqrt(np.mean(difference**2))),
        mae=float(np.mean(np.abs(difference))),
        correlation=correlation,
        obs_mean=float(np.mean(o)),
        model_mean=float(np.mean(m)),
        max_abs_difference=float(np.abs(difference[max_index])),
        depth_of_max_difference=float(z[max_index]),
    )


def interpolate_to_depths(
    model_depths: np.ndarray,
    model_values: np.ndarray,
    target_depths: np.ndarray,
) -> np.ndarray:
    """Linearly interpolate a model profile onto observation depths.

    Levels outside the model's vertical range return NaN: an operational tool
    must never invent data below the deepest model level.
    """
    z = np.asarray(model_depths, dtype="float64")
    v = np.asarray(model_values, dtype="float64")
    target = np.asarray(target_depths, dtype="float64")

    valid = np.isfinite(z) & np.isfinite(v)
    if valid.sum() < 2:
        return np.full(target.shape, np.nan)

    z_valid = z[valid]
    v_valid = v[valid]
    order = np.argsort(z_valid)
    z_valid = z_valid[order]
    v_valid = v_valid[order]

    result = np.interp(target, z_valid, v_valid, left=np.nan, right=np.nan)
    out_of_range = (target < z_valid[0] - MAX_EXTRAPOLATION_M) | (
        target > z_valid[-1] + MAX_EXTRAPOLATION_M
    )
    result[out_of_range] = np.nan
    return result


def collocate_profile(
    handle: DatasetHandle,
    *,
    variable: str,
    platform_id: str,
    latitude: float,
    longitude: float,
    observation_time: datetime,
    depths: Sequence[float],
    values: Sequence[float | None],
) -> CollocationResult:
    """Pair one observed profile with the model field at the same point.

    The heart of the platform: everything needed to draw the observed and
    modelled profiles on a single chart, plus the metrics that say how far
    apart they are.
    """
    spec = handle.require_variable(variable)

    obs_depths = np.asarray(list(depths), dtype="float64")
    obs_values = np.asarray(
        [np.nan if v is None else float(v) for v in values], dtype="float64"
    )
    if obs_depths.size != obs_values.size:
        raise ValidationError("Observation depth and value arrays must be the same length.")
    if obs_depths.size == 0:
        raise ValidationError("The observed profile is empty.")

    warnings: list[str] = []

    # Nearest model timestep to the observation.
    time_index = handle.time_index(observation_time)
    model_times = handle.time_strings()
    model_time = model_times[time_index] if model_times else "unknown"

    offset_hours = 0.0
    if model_times:
        try:
            model_dt = datetime.strptime(model_time, "%Y-%m-%dT%H:%M:%SZ")
            naive_obs = observation_time.replace(tzinfo=None)
            offset_hours = (model_dt - naive_obs).total_seconds() / 3600.0
        except ValueError:  # pragma: no cover
            offset_hours = float("nan")

    if abs(offset_hours) > 36.0:
        warnings.append(
            f"Nearest model timestep is {offset_hours:+.1f} h from the observation."
        )

    # Model profile at the nearest grid cell.
    model_depths, model_values = handle.point_profile(
        variable, lat=latitude, lon=longitude, time_index=time_index
    )

    nearest_lat = float(handle.lats[int(np.argmin(np.abs(handle.lats - latitude)))])
    nearest_lon = float(handle.lons[int(np.argmin(np.abs(handle.lons - longitude)))])
    distance_km = haversine_km(latitude, longitude, nearest_lat, nearest_lon)

    if not np.isfinite(model_values).any():
        warnings.append(
            "The nearest model grid cell contains no valid data (land or below seafloor)."
        )

    interpolated = interpolate_to_depths(model_depths, model_values, obs_depths)

    deepest_model = float(np.max(model_depths)) if model_depths.size else 0.0
    if obs_depths.max() > deepest_model:
        warnings.append(
            f"Observation reaches {obs_depths.max():.0f} m but the model stops at "
            f"{deepest_model:.0f} m; deeper levels are not compared."
        )

    difference = interpolated - obs_values
    statistics = compute_statistics(obs_values, interpolated, obs_depths)

    return CollocationResult(
        variable=variable,
        units=spec.units,
        dataset_id=handle.id,
        platform_id=platform_id,
        latitude=round(latitude, 5),
        longitude=round(longitude, 5),
        observation_time=observation_time.strftime("%Y-%m-%dT%H:%M:%SZ"),
        model_time=model_time,
        time_offset_hours=offset_hours,
        grid_distance_km=distance_km,
        depths=[round(float(d), 2) for d in obs_depths],
        observed=[_round(v) for v in obs_values],
        modelled=[_round(v) for v in interpolated],
        difference=[_round(v) for v in difference],
        statistics=statistics,
        warnings=warnings,
    )


@dataclass(slots=True)
class ObservationInput:
    """One observed profile awaiting collocation."""

    platform_id: str
    latitude: float
    longitude: float
    observation_time: datetime
    depths: Sequence[float]
    values: Sequence[float | None]
    reference: Any = None


def collocate_many(
    handle: DatasetHandle,
    *,
    variable: str,
    observations: Sequence[ObservationInput],
) -> list[tuple[ObservationInput, CollocationResult]]:
    """Collocate a batch of profiles with far fewer store reads.

    Observations are grouped by the model timestep they fall closest to, so a
    fleet-wide bias map costs one track read per timestep rather than one per
    profile.
    """
    spec = handle.require_variable(variable)
    if not observations:
        return []

    by_time_index: dict[int, list[ObservationInput]] = {}
    for observation in observations:
        index = handle.time_index(observation.observation_time)
        by_time_index.setdefault(index, []).append(observation)

    model_times = handle.time_strings()
    paired: list[tuple[ObservationInput, CollocationResult]] = []

    for time_index, group in by_time_index.items():
        lats = np.asarray([o.latitude for o in group], dtype="float64")
        lons = np.asarray([o.longitude for o in group], dtype="float64")

        try:
            model_depths, track = handle.sample_track(
                variable, lats=lats, lons=lons, time_index=time_index
            )
        except Exception:
            logger.exception("collocation_track_failed", extra={"variable": variable})
            continue

        model_time = model_times[time_index] if model_times else "unknown"

        for column, observation in enumerate(group):
            obs_depths = np.asarray(list(observation.depths), dtype="float64")
            obs_values = np.asarray(
                [np.nan if v is None else float(v) for v in observation.values],
                dtype="float64",
            )
            if obs_depths.size == 0 or obs_depths.size != obs_values.size:
                continue

            interpolated = interpolate_to_depths(
                model_depths, track[:, column], obs_depths
            )
            statistics = compute_statistics(obs_values, interpolated, obs_depths)
            difference = interpolated - obs_values

            offset_hours = 0.0
            try:
                model_dt = datetime.strptime(model_time, "%Y-%m-%dT%H:%M:%SZ")
                offset_hours = (
                    model_dt - observation.observation_time.replace(tzinfo=None)
                ).total_seconds() / 3600.0
            except ValueError:
                offset_hours = float("nan")

            nearest_lat = float(
                handle.lats[int(np.argmin(np.abs(handle.lats - observation.latitude)))]
            )
            nearest_lon = float(
                handle.lons[int(np.argmin(np.abs(handle.lons - observation.longitude)))]
            )

            paired.append(
                (
                    observation,
                    CollocationResult(
                        variable=variable,
                        units=spec.units,
                        dataset_id=handle.id,
                        platform_id=observation.platform_id,
                        latitude=round(observation.latitude, 5),
                        longitude=round(observation.longitude, 5),
                        observation_time=observation.observation_time.strftime(
                            "%Y-%m-%dT%H:%M:%SZ"
                        ),
                        model_time=model_time,
                        time_offset_hours=offset_hours,
                        grid_distance_km=haversine_km(
                            observation.latitude, observation.longitude,
                            nearest_lat, nearest_lon,
                        ),
                        depths=[round(float(d), 2) for d in obs_depths],
                        observed=[_round(v) for v in obs_values],
                        modelled=[_round(v) for v in interpolated],
                        difference=[_round(v) for v in difference],
                        statistics=statistics,
                    ),
                )
            )

    return paired


def summarise_bias(
    results: list[CollocationResult],
) -> dict[str, Any]:
    """Aggregate many collocations into a fleet-wide verification summary."""
    biases = [
        r.statistics.bias for r in results
        if r.statistics is not None and np.isfinite(r.statistics.bias)
    ]
    rmsds = [
        r.statistics.rmsd for r in results
        if r.statistics is not None and np.isfinite(r.statistics.rmsd)
    ]

    if not biases:
        return {
            "profiles_matched": 0,
            "mean_bias": None,
            "mean_rmsd": None,
            "worst_platform": None,
        }

    worst = max(
        (r for r in results if r.statistics is not None),
        key=lambda r: abs(r.statistics.bias),  # type: ignore[union-attr]
    )
    return {
        "profiles_matched": len(biases),
        "mean_bias": _round(float(np.mean(biases))),
        "median_bias": _round(float(np.median(biases))),
        "std_bias": _round(float(np.std(biases))),
        "mean_rmsd": _round(float(np.mean(rmsds))) if rmsds else None,
        "worst_platform": {
            "platform_id": worst.platform_id,
            "bias": _round(worst.statistics.bias),  # type: ignore[union-attr]
            "lat": worst.latitude,
            "lon": worst.longitude,
        },
    }
