"""Derived ocean diagnostics computed from fields already in memory.

Everything here is deliberately cheap: once a velocity or temperature block
has been read for rendering, mixed-layer depth, eddy census, anomalies and
Lagrangian drift are all small amounts of extra arithmetic on the same
arrays.  That is what turns a viewer into an analysis tool.

References
----------
* Mixed layer depth - de Boyer Montegut et al. (2004), 0.2 degC threshold
  relative to a 10 m reference level.
* Eddy identification - Okubo (1970) / Weiss (1991) parameter,
  W = Sn^2 + Ss^2 - zeta^2, with cores at W < -0.2 * std(W).
* Marine heatwave - Hobday et al. (2016), anomaly above a percentile
  threshold sustained over a minimum duration.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Literal

import numpy as np
from scipy import ndimage

from app.core.errors import ValidationError

EARTH_RADIUS_M = 6_371_000.0
OMEGA = 7.2921e-5  # Earth's angular velocity, rad/s

# ---------------------------------------------------------------------------
# Mixed layer / thermocline
# ---------------------------------------------------------------------------
MLD_TEMPERATURE_THRESHOLD = 0.2   # degC, de Boyer Montegut criterion
MLD_REFERENCE_DEPTH = 10.0        # m


def mixed_layer_depth(
    temperature: np.ndarray,
    depths: np.ndarray,
    *,
    threshold: float = MLD_TEMPERATURE_THRESHOLD,
    reference_depth: float = MLD_REFERENCE_DEPTH,
) -> np.ndarray:
    """Mixed layer depth from a ``(depth, lat, lon)`` temperature block.

    Returns a ``(lat, lon)`` array in metres, NaN where undefined.
    """
    temp = np.asarray(temperature, dtype="float64")
    if temp.ndim != 3:
        raise ValidationError("mixed_layer_depth expects a (depth, lat, lon) array.")

    z = np.asarray(depths, dtype="float64")
    n_depth = temp.shape[0]
    if z.size != n_depth:
        raise ValidationError("Depth axis length does not match the temperature block.")

    ref_index = int(np.argmin(np.abs(z - reference_depth)))
    reference = temp[ref_index]

    # First depth below the reference level where |dT| exceeds the threshold.
    deviation = np.abs(temp - reference[np.newaxis, :, :])
    exceeds = deviation > threshold
    exceeds[: ref_index + 1] = False

    any_exceeds = exceeds.any(axis=0)
    first_index = np.argmax(exceeds, axis=0)

    mld = np.full(temp.shape[1:], np.nan, dtype="float64")
    rows, cols = np.where(any_exceeds)
    if rows.size:
        idx = first_index[rows, cols]
        upper = np.maximum(idx - 1, 0)

        # Linear interpolation between the bracketing levels for a smooth field.
        t_upper = temp[upper, rows, cols]
        t_lower = temp[idx, rows, cols]
        z_upper = z[upper]
        z_lower = z[idx]
        target = reference[rows, cols] + np.sign(t_lower - reference[rows, cols]) * threshold

        span = t_lower - t_upper
        with np.errstate(divide="ignore", invalid="ignore"):
            fraction = np.where(np.abs(span) > 1e-9, (target - t_upper) / span, 0.0)
        fraction = np.clip(fraction, 0.0, 1.0)
        mld[rows, cols] = z_upper + fraction * (z_lower - z_upper)

    # Columns that never exceed the threshold are mixed to the sampled floor.
    unresolved = (~any_exceeds) & np.isfinite(temp[ref_index])
    mld[unresolved] = float(z[-1])
    mld[~np.isfinite(temp[ref_index])] = np.nan
    return mld


def thermocline_depth(temperature: np.ndarray, depths: np.ndarray) -> np.ndarray:
    """Depth of the strongest vertical temperature gradient, in metres."""
    temp = np.asarray(temperature, dtype="float64")
    z = np.asarray(depths, dtype="float64")
    if temp.shape[0] < 3:
        return np.full(temp.shape[1:], np.nan)

    dz = np.gradient(z)
    gradient = np.gradient(temp, axis=0) / dz[:, np.newaxis, np.newaxis]

    with np.errstate(invalid="ignore"):
        magnitude = np.abs(np.nan_to_num(gradient, nan=0.0))
    index = np.argmax(magnitude, axis=0)

    result = z[index].astype("float64")
    result[~np.isfinite(temp[0])] = np.nan
    result[magnitude.max(axis=0) < 1e-6] = np.nan
    return result


# ---------------------------------------------------------------------------
# Eddy detection
# ---------------------------------------------------------------------------
@dataclass(slots=True)
class Eddy:
    """One detected mesoscale eddy."""

    id: int
    centre_lat: float
    centre_lon: float
    polarity: Literal["cyclonic", "anticyclonic"]
    radius_km: float
    area_km2: float
    mean_vorticity: float
    max_speed: float
    okubo_weiss: float

    def to_dict(self) -> dict[str, Any]:
        return {
            "id": self.id,
            "centre": {"lat": round(self.centre_lat, 4), "lon": round(self.centre_lon, 4)},
            "polarity": self.polarity,
            "radius_km": round(self.radius_km, 2),
            "area_km2": round(self.area_km2, 2),
            "mean_vorticity_s-1": float(f"{self.mean_vorticity:.3e}"),
            "max_speed_ms-1": round(self.max_speed, 3),
            "okubo_weiss_s-2": float(f"{self.okubo_weiss:.3e}"),
        }


def _metric_spacing(lats: np.ndarray, lons: np.ndarray) -> tuple[np.ndarray, float]:
    """Grid spacing in metres: ``(dx per latitude row, dy)``."""
    d_lat = float(np.mean(np.diff(lats))) if lats.size > 1 else 0.25
    d_lon = float(np.mean(np.diff(lons))) if lons.size > 1 else 0.25

    dy = np.deg2rad(d_lat) * EARTH_RADIUS_M
    dx = np.deg2rad(d_lon) * EARTH_RADIUS_M * np.cos(np.deg2rad(lats))
    dx = np.where(np.abs(dx) < 1.0, 1.0, dx)  # guard the poles
    return dx, dy


def okubo_weiss(
    u: np.ndarray, v: np.ndarray, lats: np.ndarray, lons: np.ndarray
) -> dict[str, np.ndarray]:
    """Compute the Okubo-Weiss parameter and its strain/vorticity components."""
    u_arr = np.asarray(u, dtype="float64")
    v_arr = np.asarray(v, dtype="float64")
    if u_arr.ndim != 2 or u_arr.shape != v_arr.shape:
        raise ValidationError("okubo_weiss expects two matching 2-D velocity fields.")

    dx, dy = _metric_spacing(lats, lons)
    dx_grid = dx[:, np.newaxis]

    du_dy, du_dx = np.gradient(u_arr)
    dv_dy, dv_dx = np.gradient(v_arr)

    du_dx = du_dx / dx_grid
    dv_dx = dv_dx / dx_grid
    du_dy = du_dy / dy
    dv_dy = dv_dy / dy

    normal_strain = du_dx - dv_dy
    shear_strain = dv_dx + du_dy
    vorticity = dv_dx - du_dy

    w = normal_strain**2 + shear_strain**2 - vorticity**2
    return {
        "w": w,
        "vorticity": vorticity,
        "normal_strain": normal_strain,
        "shear_strain": shear_strain,
        "speed": np.hypot(u_arr, v_arr),
    }


def detect_eddies(
    u: np.ndarray,
    v: np.ndarray,
    lats: np.ndarray,
    lons: np.ndarray,
    *,
    threshold_factor: float = 0.2,
    min_cells: int = 6,
    max_eddies: int = 300,
) -> tuple[list[Eddy], np.ndarray]:
    """Identify eddy cores as connected regions of strongly negative W.

    Returns the eddy list and the Okubo-Weiss field itself, so a caller that
    wants to render W as a layer does not have to recompute it.
    """
    fields = okubo_weiss(u, v, lats, lons)
    w = fields["w"]
    vorticity = fields["vorticity"]
    speed = fields["speed"]

    finite = np.isfinite(w)
    if not finite.any():
        return [], w

    w_std = float(np.nanstd(w[finite]))
    if not np.isfinite(w_std) or w_std <= 0:
        return [], w

    core_mask = np.where(finite, w < -threshold_factor * w_std, False)
    labels, count = ndimage.label(core_mask)
    if count == 0:
        return [], w

    dx, dy = _metric_spacing(lats, lons)
    # dy is a scalar, so broadcast the per-row cell area across every column
    # before indexing it with (row, col) pairs.
    cell_area_km2 = np.broadcast_to((dx[:, np.newaxis] * dy) / 1e6, w.shape)

    eddies: list[Eddy] = []
    for label_id in range(1, count + 1):
        rows, cols = np.where(labels == label_id)
        if rows.size < min_cells:
            continue

        area = float(np.sum(cell_area_km2[rows, cols]))
        mean_vort = float(np.nanmean(vorticity[rows, cols]))
        if not np.isfinite(mean_vort):
            continue

        centre_lat = float(np.mean(lats[rows]))
        centre_lon = float(np.mean(lons[cols]))

        eddies.append(
            Eddy(
                id=label_id,
                centre_lat=centre_lat,
                centre_lon=centre_lon,
                # Northern hemisphere convention: positive vorticity is cyclonic.
                polarity="cyclonic" if mean_vort > 0 else "anticyclonic",
                radius_km=float(np.sqrt(area / np.pi)),
                area_km2=area,
                mean_vorticity=mean_vort,
                max_speed=float(np.nanmax(speed[rows, cols])),
                okubo_weiss=float(np.nanmean(w[rows, cols])),
            )
        )

    eddies.sort(key=lambda e: e.area_km2, reverse=True)
    return eddies[:max_eddies], w


# ---------------------------------------------------------------------------
# Anomaly / marine heatwave
# ---------------------------------------------------------------------------
def anomaly(field_values: np.ndarray, climatology: np.ndarray) -> np.ndarray:
    """Field minus climatology, broadcasting a 2-D climatology if needed."""
    values = np.asarray(field_values, dtype="float64")
    clim = np.asarray(climatology, dtype="float64")
    if clim.shape != values.shape:
        try:
            clim = np.broadcast_to(clim, values.shape)
        except ValueError:
            raise ValidationError(
                f"Climatology shape {clim.shape} is incompatible with field shape {values.shape}."
            ) from None
    return values - clim


def heatwave_mask(
    anomaly_field: np.ndarray, *, threshold: float = 1.0
) -> dict[str, Any]:
    """Flag marine-heatwave cells and summarise their extent."""
    array = np.asarray(anomaly_field, dtype="float64")
    finite = np.isfinite(array)
    mask = np.where(finite, array >= threshold, False)

    total = int(finite.sum())
    flagged = int(mask.sum())
    return {
        "mask": mask,
        "threshold": threshold,
        "cells_flagged": flagged,
        "cells_valid": total,
        "fraction": round(flagged / total, 5) if total else 0.0,
        # Reported whether or not any cell crosses the threshold, so a caller
        # can see how close the field is to an event.
        "max_anomaly": float(np.nanmax(array[finite])) if total else 0.0,
        "min_anomaly": float(np.nanmin(array[finite])) if total else 0.0,
        "mean_anomaly_in_event": float(np.nanmean(array[mask])) if flagged else 0.0,
    }


# ---------------------------------------------------------------------------
# Lagrangian drift (search-and-rescue support)
# ---------------------------------------------------------------------------
@dataclass(slots=True)
class DriftResult:
    """Output of a particle drift simulation."""

    times_hours: list[float]
    positions: list[list[list[float]]] = field(default_factory=list)  # [step][particle][lon, lat]
    centroid: list[list[float]] = field(default_factory=list)
    radius_km: list[float] = field(default_factory=list)
    stranded: int = 0

    def to_dict(self) -> dict[str, Any]:
        return {
            "times_hours": self.times_hours,
            "positions": self.positions,
            "centroid": self.centroid,
            "search_radius_km": self.radius_km,
            "particles_stranded": self.stranded,
        }


class VelocityField:
    """Bilinear sampler over a static ``(lat, lon)`` velocity field.

    NaN cells (land, below seafloor) are treated as zero velocity, and the
    sampler reports whether a position fell on land so the caller can mark a
    particle as stranded.
    """

    def __init__(self, u: np.ndarray, v: np.ndarray, lats: np.ndarray, lons: np.ndarray) -> None:
        self.u = np.asarray(u, dtype="float64")
        self.v = np.asarray(v, dtype="float64")
        self.lats = np.asarray(lats, dtype="float64")
        self.lons = np.asarray(lons, dtype="float64")

        if self.u.shape != (self.lats.size, self.lons.size):
            raise ValidationError(
                f"Velocity shape {self.u.shape} does not match axes "
                f"({self.lats.size}, {self.lons.size})."
            )

        self.valid = np.isfinite(self.u) & np.isfinite(self.v)
        self._u_filled = np.nan_to_num(self.u, nan=0.0)
        self._v_filled = np.nan_to_num(self.v, nan=0.0)

    def sample(self, lat: np.ndarray, lon: np.ndarray) -> tuple[np.ndarray, np.ndarray, np.ndarray]:
        """Bilinearly interpolate ``(u, v)`` and return an on-water mask."""
        lat_c = np.clip(lat, self.lats[0], self.lats[-1])
        lon_c = np.clip(lon, self.lons[0], self.lons[-1])

        i = np.clip(np.searchsorted(self.lats, lat_c) - 1, 0, self.lats.size - 2)
        j = np.clip(np.searchsorted(self.lons, lon_c) - 1, 0, self.lons.size - 2)

        lat0, lat1 = self.lats[i], self.lats[i + 1]
        lon0, lon1 = self.lons[j], self.lons[j + 1]

        with np.errstate(divide="ignore", invalid="ignore"):
            ty = np.where(lat1 > lat0, (lat_c - lat0) / (lat1 - lat0), 0.0)
            tx = np.where(lon1 > lon0, (lon_c - lon0) / (lon1 - lon0), 0.0)
        ty = np.clip(np.nan_to_num(ty), 0.0, 1.0)
        tx = np.clip(np.nan_to_num(tx), 0.0, 1.0)

        def bilinear(grid: np.ndarray) -> np.ndarray:
            c00 = grid[i, j]
            c10 = grid[i + 1, j]
            c01 = grid[i, j + 1]
            c11 = grid[i + 1, j + 1]
            return (
                c00 * (1 - ty) * (1 - tx)
                + c10 * ty * (1 - tx)
                + c01 * (1 - ty) * tx
                + c11 * ty * tx
            )

        on_water = (
            self.valid[i, j] | self.valid[i + 1, j]
            | self.valid[i, j + 1] | self.valid[i + 1, j + 1]
        )
        return bilinear(self._u_filled), bilinear(self._v_filled), on_water


def simulate_drift(
    velocity: VelocityField,
    *,
    origin_lat: float,
    origin_lon: float,
    n_particles: int = 500,
    duration_hours: float = 48.0,
    timestep_minutes: float = 30.0,
    initial_spread_km: float = 2.0,
    diffusion_m2_s: float = 10.0,
    windage: float = 0.0,
    wind_u: float = 0.0,
    wind_v: float = 0.0,
    seed: int = 12345,
) -> DriftResult:
    """Advect particles with RK4 plus a random-walk diffusion term.

    This is the classic search-and-rescue formulation: a cloud of particles
    seeded on the last known position, advected by the modelled current, and
    spread by unresolved sub-grid turbulence.  The percentile radius of the
    resulting cloud is the search area a coordinator actually needs.
    """
    rng = np.random.default_rng(seed)
    n = max(1, int(n_particles))

    # Seed a Gaussian cloud around the last known position.
    spread_deg = initial_spread_km / 111.0
    lat = origin_lat + rng.normal(0.0, spread_deg, n)
    lon = origin_lon + rng.normal(0.0, spread_deg / max(0.2, np.cos(np.deg2rad(origin_lat))), n)

    dt = timestep_minutes * 60.0
    n_steps = max(1, int(round(duration_hours * 3600.0 / dt)))
    diffusion_step = np.sqrt(2.0 * max(0.0, diffusion_m2_s) * dt)

    active = np.ones(n, dtype=bool)
    result = DriftResult(times_hours=[0.0])
    result.positions.append(_stack(lon, lat))
    result.centroid.append([float(np.mean(lon)), float(np.mean(lat))])
    result.radius_km.append(_percentile_radius_km(lon, lat))

    for step in range(1, n_steps + 1):
        # RK4 in degrees, converting m/s to deg/s at each stage.
        k1u, k1v, water1 = velocity.sample(lat, lon)
        k1_lat, k1_lon = _to_degrees(k1u, k1v, lat)

        k2u, k2v, _ = velocity.sample(lat + 0.5 * dt * k1_lat, lon + 0.5 * dt * k1_lon)
        k2_lat, k2_lon = _to_degrees(k2u, k2v, lat)

        k3u, k3v, _ = velocity.sample(lat + 0.5 * dt * k2_lat, lon + 0.5 * dt * k2_lon)
        k3_lat, k3_lon = _to_degrees(k3u, k3v, lat)

        k4u, k4v, _ = velocity.sample(lat + dt * k3_lat, lon + dt * k3_lon)
        k4_lat, k4_lon = _to_degrees(k4u, k4v, lat)

        d_lat = (dt / 6.0) * (k1_lat + 2 * k2_lat + 2 * k3_lat + k4_lat)
        d_lon = (dt / 6.0) * (k1_lon + 2 * k2_lon + 2 * k3_lon + k4_lon)

        if windage > 0.0:
            wind_lat, wind_lon = _to_degrees(
                np.full(n, wind_u * windage), np.full(n, wind_v * windage), lat
            )
            d_lat += dt * wind_lat
            d_lon += dt * wind_lon

        if diffusion_step > 0.0:
            noise_lat, noise_lon = _to_degrees(
                rng.normal(0.0, diffusion_step / dt, n),
                rng.normal(0.0, diffusion_step / dt, n),
                lat,
            )
            d_lat += dt * noise_lat
            d_lon += dt * noise_lon

        lat = np.where(active, lat + d_lat, lat)
        lon = np.where(active, lon + d_lon, lon)
        active &= water1

        # Emit roughly 40 frames regardless of the internal timestep.
        emit_every = max(1, n_steps // 40)
        if step % emit_every == 0 or step == n_steps:
            result.times_hours.append(round(step * dt / 3600.0, 3))
            result.positions.append(_stack(lon, lat))
            result.centroid.append([float(np.mean(lon)), float(np.mean(lat))])
            result.radius_km.append(_percentile_radius_km(lon, lat))

    result.stranded = int((~active).sum())
    return result


def _to_degrees(
    u_ms: np.ndarray, v_ms: np.ndarray, lat: np.ndarray
) -> tuple[np.ndarray, np.ndarray]:
    """Convert velocity in m/s to degrees per second at the given latitude."""
    d_lat = np.rad2deg(v_ms / EARTH_RADIUS_M)
    cos_lat = np.maximum(np.cos(np.deg2rad(lat)), 0.05)
    d_lon = np.rad2deg(u_ms / (EARTH_RADIUS_M * cos_lat))
    return d_lat, d_lon


def _stack(lon: np.ndarray, lat: np.ndarray) -> list[list[float]]:
    return [[round(float(x), 5), round(float(y), 5)] for x, y in zip(lon, lat)]


def _percentile_radius_km(lon: np.ndarray, lat: np.ndarray, percentile: float = 95.0) -> float:
    """Radius containing ``percentile`` of the particle cloud, in kilometres."""
    centre_lon = float(np.mean(lon))
    centre_lat = float(np.mean(lat))
    dy = (lat - centre_lat) * 111.32
    dx = (lon - centre_lon) * 111.32 * float(np.cos(np.deg2rad(centre_lat)))
    return round(float(np.percentile(np.hypot(dx, dy), percentile)), 3)


def coriolis_parameter(lat: np.ndarray | float) -> np.ndarray:
    """Coriolis parameter f = 2*OMEGA*sin(phi), in s^-1."""
    return 2.0 * OMEGA * np.sin(np.deg2rad(np.asarray(lat, dtype="float64")))
