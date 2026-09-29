"""Generate a physically plausible demo dataset for the Indian Ocean domain.

Why synthetic data
------------------
The platform is designed against real products (CMEMS GLORYS, HYCOM GOFS,
INCOIS INDOFOS, the Argo GDAC).  Those require credentials, large downloads
and a working network - none of which can be relied on at a demo venue.

This script builds a self-consistent stand-in with the same structure as the
real thing: CF-compliant NetCDF/Zarr on a regular grid, and Argo-format
profiles that genuinely deviate from the model, so the collocation view has
something real to show rather than two identical curves.

    python scripts/generate_sample_data.py
    python scripts/generate_sample_data.py --resolution 0.5 --times 10

Every field here is a plausible caricature, not a forecast.  Swap in real
data with ``scripts/ingest_netcdf.py`` when you have it.
"""

from __future__ import annotations

import argparse
import math
import sys
from datetime import datetime, timedelta, timezone
from pathlib import Path

import numpy as np
import xarray as xr

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from app.config import settings  # noqa: E402
from app.core.logging import configure_logging, get_logger  # noqa: E402
from app.data.adapters.base import ProfileRecord  # noqa: E402
from app.db import repository  # noqa: E402
from app.db.session import init_db, session_scope  # noqa: E402
from app.db.models import Level, Platform, Profile  # noqa: E402

logger = get_logger("generate_sample_data")

GRAVITY = 9.81
OMEGA = 7.2921e-5

# ---------------------------------------------------------------------------
# Coarse land polygons for the domain.  Deliberately simple: enough to make
# the coastline read correctly in a 3-D view and to mask land cells.
# ---------------------------------------------------------------------------
LAND_POLYGONS: dict[str, list[tuple[float, float]]] = {
    "indian_peninsula": [
        (68.2, 23.8), (72.6, 21.0), (72.9, 19.1), (73.5, 15.9), (74.9, 13.0),
        (76.3, 9.2), (77.5, 8.1), (79.3, 9.2), (80.3, 13.1), (80.2, 16.3),
        (82.3, 17.0), (84.8, 19.3), (87.0, 21.5), (89.1, 21.7), (89.0, 26.0),
        (77.0, 26.0), (68.6, 26.0),
    ],
    "sri_lanka": [
        (79.7, 8.0), (81.0, 8.9), (81.9, 7.2), (81.7, 6.3), (80.3, 5.9), (79.7, 6.9),
    ],
    "arabian_peninsula": [
        (55.0, 26.0), (59.8, 22.5), (58.0, 20.5), (55.0, 17.0), (52.5, 16.0),
        (45.0, 12.8), (43.3, 12.6), (43.0, 26.0),
    ],
    "horn_of_africa": [
        (43.0, 11.5), (51.4, 11.9), (51.0, 10.4), (47.0, 4.0), (41.5, -2.0),
        (40.1, -6.0), (39.2, -10.0), (36.0, -10.0), (36.0, 11.5),
    ],
    "myanmar_thailand": [
        (92.2, 21.5), (94.5, 18.0), (97.5, 16.5), (98.5, 12.0), (100.0, 7.0),
        (100.0, 26.0), (92.0, 26.0),
    ],
    "andaman": [(92.6, 13.5), (93.1, 13.4), (93.0, 10.5), (92.5, 10.6)],
    "sumatra": [
        (95.2, 5.6), (98.9, 3.7), (100.0, 2.0), (100.0, -6.0), (97.0, -6.0),
        (94.5, 0.0),
    ],
    "maldives": [(72.8, 7.1), (73.6, 7.1), (73.6, -0.7), (72.8, -0.7)],
}


def build_land_mask(lats: np.ndarray, lons: np.ndarray) -> np.ndarray:
    """Rasterise the land polygons onto the model grid."""
    from matplotlib.path import Path as MplPath

    lon_grid, lat_grid = np.meshgrid(lons, lats)
    points = np.column_stack([lon_grid.ravel(), lat_grid.ravel()])
    mask = np.zeros(points.shape[0], dtype=bool)

    for name, polygon in LAND_POLYGONS.items():
        # The Maldives are an atoll chain, not a landmass; keeping them would
        # punch an unrealistic hole through the middle of the Arabian Sea.
        if name == "maldives":
            continue
        mask |= MplPath(np.asarray(polygon)).contains_points(points)

    return mask.reshape(lat_grid.shape)


def distance_to_land_km(land_mask: np.ndarray, lats: np.ndarray, lons: np.ndarray) -> np.ndarray:
    """Approximate distance from every ocean cell to the nearest land cell."""
    from scipy import ndimage

    d_lat_km = float(np.mean(np.diff(lats))) * 111.32 if lats.size > 1 else 27.83
    distance_cells = ndimage.distance_transform_edt(~land_mask)
    return np.asarray(distance_cells) * abs(d_lat_km)


def build_bathymetry(
    land_mask: np.ndarray, coast_distance: np.ndarray, lats: np.ndarray, lons: np.ndarray
) -> np.ndarray:
    """Synthetic seafloor depth with a continental shelf and slope."""
    shelf = 60.0 + 140.0 * np.clip(coast_distance / 120.0, 0.0, 1.0)
    deep = 1000.0 + 3200.0 * np.clip((coast_distance - 120.0) / 700.0, 0.0, 1.0)
    depth = np.maximum(shelf, deep)

    # A broad ridge to break up the flat abyssal plain.
    lon_grid, lat_grid = np.meshgrid(lons, lats)
    ridge = 900.0 * np.exp(-(((lon_grid - 68.0) / 4.0) ** 2 + ((lat_grid - 5.0) / 12.0) ** 2))
    depth = np.maximum(200.0, depth - ridge)

    depth[land_mask] = 0.0
    return depth


def depth_levels(n_levels: int, max_depth: float = 2000.0) -> np.ndarray:
    """Stretched vertical grid: fine near the surface, coarse at depth."""
    fractions = np.linspace(0.0, 1.0, n_levels)
    return np.round(max_depth * fractions**2.2, 2)


# ---------------------------------------------------------------------------
# Ocean state
# ---------------------------------------------------------------------------
def eddy_field(
    lats: np.ndarray,
    lons: np.ndarray,
    day: float,
    rng: np.random.Generator,
    eddies: list[dict],
) -> np.ndarray:
    """Sea-surface-height perturbation from a population of drifting eddies."""
    lon_grid, lat_grid = np.meshgrid(lons, lats)
    ssh = np.zeros_like(lon_grid)

    for eddy in eddies:
        # Mesoscale eddies propagate westward at a few cm/s.
        drift_deg = eddy["speed_deg_per_day"] * day
        centre_lon = eddy["lon"] - drift_deg
        centre_lat = eddy["lat"] + 0.15 * math.sin(day / 9.0 + eddy["phase"])

        radius_deg = eddy["radius_km"] / 111.0
        distance_sq = ((lon_grid - centre_lon) / radius_deg) ** 2 + (
            (lat_grid - centre_lat) / radius_deg
        ) ** 2
        ssh += eddy["amplitude"] * np.exp(-distance_sq)

    return ssh


def surface_temperature(
    lat_grid: np.ndarray,
    lon_grid: np.ndarray,
    day_of_year: float,
    ssh: np.ndarray,
    coast_distance: np.ndarray,
) -> np.ndarray:
    """Sea surface temperature with a seasonal cycle and monsoon upwelling."""
    # Warm pool near the equator, cooling polewards.
    base = 29.6 - 0.085 * np.abs(lat_grid - 4.0) ** 1.35

    # Seasonal cycle, stronger in the north.
    seasonal = 1.9 * np.sin(2 * np.pi * (day_of_year - 105) / 365.0)
    base = base + seasonal * np.clip(lat_grid / 20.0, 0.0, 1.0)

    # Bay of Bengal runs warmer than the Arabian Sea at the same latitude.
    bay_of_bengal = (lon_grid > 80.0) & (lat_grid > 5.0)
    base = np.where(bay_of_bengal, base + 0.7, base)

    # South-west monsoon upwelling off Somalia and Oman: strong summer cooling.
    monsoon = np.clip(np.sin(2 * np.pi * (day_of_year - 150) / 365.0), 0.0, 1.0)
    somali = np.exp(-(((lon_grid - 52.0) / 5.0) ** 2 + ((lat_grid - 8.0) / 5.0) ** 2))
    oman = np.exp(-(((lon_grid - 58.5) / 3.5) ** 2 + ((lat_grid - 19.0) / 3.0) ** 2))
    base = base - monsoon * (3.4 * somali + 2.6 * oman)

    # Coastal upwelling elsewhere, plus the eddy signature in SST.
    base = base - 0.9 * np.exp(-coast_distance / 90.0) * monsoon
    base = base + 1.6 * ssh

    return base


def build_profile(
    surface: np.ndarray,
    depths: np.ndarray,
    mixed_layer: np.ndarray,
    thermocline_thickness: np.ndarray,
    deep_value: float,
) -> np.ndarray:
    """Expand a surface field into a water column.

    Uniform through the mixed layer, a hyperbolic-tangent thermocline below
    it, then a slow approach to the deep-water value.

    The transition is clamped to zero above the mixed layer depth.  Using a
    plain ``tanh`` centred on the MLD would leave the surface already partly
    mixed toward the deep value whenever the thermocline is thick relative to
    the mixed layer, which cools the SST by several degrees.
    """
    n_depth = depths.size
    column = np.empty((n_depth,) + surface.shape, dtype="float32")

    for k, z in enumerate(depths):
        below_mld = np.maximum(0.0, z - mixed_layer)

        # Two vertical scales. A single exponential cannot reproduce both the
        # sharp tropical thermocline and the slow kilometre-scale approach to
        # abyssal values; using one scale gives either a thermocline that is
        # far too abrupt or a deep ocean that stays implausibly warm.
        fast_scale = np.maximum(thermocline_thickness, 1.0)
        slow_scale = fast_scale * 10.0
        fast = 1.0 - np.exp(-below_mld / fast_scale)
        slow = 1.0 - np.exp(-below_mld / slow_scale)

        transition = np.clip(0.65 * fast + 0.35 * slow, 0.0, 1.0)
        value = surface * (1.0 - transition) + deep_value * transition
        # Weak continued decrease below the thermocline.
        value = value - 0.00035 * max(0.0, z - 800.0) * (surface - deep_value) / 25.0
        column[k] = value

    return column


def geostrophic_velocity(
    ssh: np.ndarray, lats: np.ndarray, lons: np.ndarray
) -> tuple[np.ndarray, np.ndarray]:
    """Surface geostrophic velocity from sea surface height.

    The Coriolis parameter is floored away from zero: geostrophy is singular
    at the equator, and this dataset is a visual stand-in, not a dynamical
    model.
    """
    d_lat_m = float(np.mean(np.diff(lats))) * 111_320.0
    d_lon_m = float(np.mean(np.diff(lons))) * 111_320.0 * np.cos(np.deg2rad(lats))
    d_lon_m = np.where(np.abs(d_lon_m) < 1.0, 1.0, d_lon_m)

    f = 2.0 * OMEGA * np.sin(np.deg2rad(lats))
    f = np.where(np.abs(f) < 2.0e-5, np.sign(f + 1e-12) * 2.0e-5, f)
    f_grid = f[:, np.newaxis]

    d_ssh_dy, d_ssh_dx = np.gradient(ssh)
    d_ssh_dy = d_ssh_dy / d_lat_m
    d_ssh_dx = d_ssh_dx / d_lon_m[:, np.newaxis]

    u = -(GRAVITY / f_grid) * d_ssh_dy
    v = (GRAVITY / f_grid) * d_ssh_dx

    # Keep speeds in a physically sensible band.
    return np.clip(u, -2.0, 2.0), np.clip(v, -2.0, 2.0)


def generate_model_dataset(
    *, resolution: float, n_times: int, n_depths: int, start: datetime, seed: int
) -> xr.Dataset:
    """Build the full 4-D model dataset."""
    rng = np.random.default_rng(seed)

    lats = np.round(
        np.arange(settings.domain_lat_min, settings.domain_lat_max + resolution / 2, resolution), 4
    )
    lons = np.round(
        np.arange(settings.domain_lon_min, settings.domain_lon_max + resolution / 2, resolution), 4
    )
    depths = depth_levels(n_depths)
    times = [start + timedelta(days=i) for i in range(n_times)]

    logger.info(
        "grid",
        extra={
            "lat": lats.size, "lon": lons.size, "depth": depths.size, "time": len(times),
            "cells_per_variable": int(lats.size * lons.size * depths.size * len(times)),
        },
    )

    land_mask = build_land_mask(lats, lons)
    coast_distance = distance_to_land_km(land_mask, lats, lons)
    bathymetry = build_bathymetry(land_mask, coast_distance, lats, lons)
    lon_grid, lat_grid = np.meshgrid(lons, lats)

    # A population of mesoscale eddies that drift westward through the run.
    eddies = [
        {
            "lon": rng.uniform(settings.domain_lon_min + 3, settings.domain_lon_max - 3),
            "lat": rng.uniform(settings.domain_lat_min + 3, settings.domain_lat_max - 3),
            "radius_km": rng.uniform(110.0, 320.0),
            "amplitude": rng.choice([-1.0, 1.0]) * rng.uniform(0.10, 0.34),
            "speed_deg_per_day": rng.uniform(0.02, 0.06),
            "phase": rng.uniform(0.0, 2 * math.pi),
        }
        for _ in range(26)
    ]

    shape4d = (len(times), depths.size, lats.size, lons.size)
    temperature = np.empty(shape4d, dtype="float32")
    salinity = np.empty(shape4d, dtype="float32")
    chlorophyll = np.empty(shape4d, dtype="float32")
    u_current = np.empty(shape4d, dtype="float32")
    v_current = np.empty(shape4d, dtype="float32")
    ssh_out = np.empty((len(times), lats.size, lons.size), dtype="float32")

    # Cells below the seafloor are masked per level.
    below_seafloor = depths[:, np.newaxis, np.newaxis] > bathymetry[np.newaxis, :, :]
    invalid = below_seafloor | land_mask[np.newaxis, :, :]

    for t, timestamp in enumerate(times):
        day = float(t)
        day_of_year = float(timestamp.timetuple().tm_yday)

        ssh = eddy_field(lats, lons, day, rng, eddies)
        # Large-scale dynamic topography: high in the warm pool, low in the south.
        ssh = ssh + 0.22 * np.exp(-((lat_grid - 6.0) / 14.0) ** 2) - 0.05 * (lat_grid / 25.0)

        # A tropical cyclone crossing the Bay of Bengal in the second half of
        # the run, leaving the cold wake that makes the animation worth watching.
        cyclone_cooling = np.zeros_like(lat_grid)
        if t >= n_times // 2:
            age = t - n_times // 2
            centre_lon = 88.0 - 0.35 * age
            centre_lat = 12.0 + 0.55 * age
            wake = np.exp(
                -(((lon_grid - centre_lon) / 2.2) ** 2 + ((lat_grid - centre_lat) / 2.0) ** 2)
            )
            cyclone_cooling = 2.8 * wake * min(1.0, 0.35 * age)

        # A marine heatwave building through the run in the eastern Arabian
        # Sea, so the anomaly layer has a real event to detect rather than
        # noise. Arabian Sea heatwaves are a documented, intensifying feature.
        heatwave_growth = t / max(1, n_times - 1)
        heatwave_patch = np.exp(
            -(((lon_grid - 68.5) / 4.5) ** 2 + ((lat_grid - 14.5) / 3.5) ** 2)
        )
        heatwave_warming = 3.5 * heatwave_growth * heatwave_patch

        sst = surface_temperature(lat_grid, lon_grid, day_of_year, ssh, coast_distance)
        sst = sst - cyclone_cooling + heatwave_warming

        # Mixed layer deepens with latitude, in winter, and under the cyclone.
        mixed_layer = (
            22.0
            + 34.0 * np.clip(np.abs(lat_grid) / 25.0, 0.0, 1.0)
            - 14.0 * np.sin(2 * np.pi * (day_of_year - 105) / 365.0)
            + 45.0 * cyclone_cooling / 2.8
        )
        mixed_layer = np.clip(mixed_layer, 12.0, 140.0)
        thermocline_thickness = 55.0 + 40.0 * np.clip(np.abs(lat_grid) / 25.0, 0.0, 1.0)

        temperature[t] = build_profile(
            sst.astype("float32"), depths, mixed_layer, thermocline_thickness, deep_value=3.2
        )

        # Surface salinity: Bay of Bengal is freshened by river discharge, the
        # Arabian Sea is saltier through evaporation.
        sss = np.full_like(lat_grid, 35.1)
        bay = np.exp(-(((lon_grid - 88.0) / 8.0) ** 2 + ((lat_grid - 17.0) / 7.0) ** 2))
        sss = sss - 3.1 * bay
        arabian = np.exp(-(((lon_grid - 63.0) / 8.0) ** 2 + ((lat_grid - 18.0) / 6.0) ** 2))
        sss = sss + 1.5 * arabian
        sss = sss - 0.35 * np.exp(-coast_distance / 70.0)

        salinity[t] = build_profile(
            sss.astype("float32"), depths, mixed_layer, thermocline_thickness, deep_value=34.85
        )

        # Chlorophyll: coastal and upwelling maxima, with a subsurface peak.
        monsoon = float(np.clip(np.sin(2 * np.pi * (day_of_year - 150) / 365.0), 0.0, 1.0))
        surface_chl = (
            0.09
            + 1.5 * np.exp(-coast_distance / 110.0)
            + 1.1 * monsoon * np.exp(-(((lon_grid - 54.0) / 6.0) ** 2 + ((lat_grid - 9.0) / 6.0) ** 2))
            + 0.5 * np.clip(-ssh, 0.0, None)
        )
        for k, z in enumerate(depths):
            subsurface_max = np.exp(-((z - (mixed_layer + 25.0)) / 34.0) ** 2)
            decay = np.exp(-z / 90.0)
            chlorophyll[t, k] = (surface_chl * (0.45 * decay + 0.85 * subsurface_max)).astype(
                "float32"
            )

        u_surface, v_surface = geostrophic_velocity(ssh, lats, lons)
        for k, z in enumerate(depths):
            # Currents weaken and rotate with depth (an Ekman-like spiral).
            attenuation = float(np.exp(-z / 260.0))
            angle = -z / 900.0
            cos_a, sin_a = math.cos(angle), math.sin(angle)
            u_current[t, k] = ((u_surface * cos_a - v_surface * sin_a) * attenuation).astype("float32")
            v_current[t, k] = ((u_surface * sin_a + v_surface * cos_a) * attenuation).astype("float32")

        ssh_out[t] = ssh.astype("float32")

        for array in (temperature, salinity, chlorophyll, u_current, v_current):
            array[t][invalid] = np.nan
        ssh_out[t][land_mask] = np.nan

    time_index = np.array([np.datetime64(t.replace(tzinfo=None), "ns") for t in times])

    dataset = xr.Dataset(
        data_vars={
            "temperature": (("time", "depth", "lat", "lon"), temperature),
            "salinity": (("time", "depth", "lat", "lon"), salinity),
            "chlorophyll": (("time", "depth", "lat", "lon"), chlorophyll),
            "u": (("time", "depth", "lat", "lon"), u_current),
            "v": (("time", "depth", "lat", "lon"), v_current),
            "ssh": (("time", "lat", "lon"), ssh_out),
            "bathymetry": (("lat", "lon"), bathymetry.astype("float32")),
        },
        coords={"time": time_index, "depth": depths, "lat": lats, "lon": lons},
        attrs={
            "title": "OceanView3D synthetic Indian Ocean demo",
            "summary": (
                "Physically plausible synthetic ocean state for the Indian EEZ "
                "and surrounding basins. Structure matches CMEMS GLORYS / INCOIS "
                "INDOFOS output so real products can be substituted directly."
            ),
            "institution": "OceanView3D (SIH 2026 PS26067 reference implementation)",
            "source": "scripts/generate_sample_data.py",
            "Conventions": "CF-1.8",
            "synthetic": "true",
            "disclaimer": (
                "SYNTHETIC DATA - generated for demonstration. Not a forecast, "
                "analysis or observation of the real ocean."
            ),
            "embedded_features": (
                "26 drifting mesoscale eddies; a tropical cyclone cold wake "
                "crossing the Bay of Bengal from the midpoint of the run; a "
                "marine heatwave intensifying in the eastern Arabian Sea "
                "(~68.5E, 14.5N); Somali and Oman monsoon upwelling; Bay of "
                "Bengal freshwater cap."
            ),
        },
    )

    dataset["temperature"].attrs = {
        "standard_name": "sea_water_potential_temperature",
        "long_name": "Sea water potential temperature", "units": "degree_Celsius",
    }
    dataset["salinity"].attrs = {
        "standard_name": "sea_water_salinity",
        "long_name": "Sea water practical salinity", "units": "psu",
    }
    dataset["chlorophyll"].attrs = {
        "standard_name": "mass_concentration_of_chlorophyll_a_in_sea_water",
        "long_name": "Chlorophyll-a concentration", "units": "mg m-3",
    }
    dataset["u"].attrs = {
        "standard_name": "eastward_sea_water_velocity",
        "long_name": "Eastward sea water velocity", "units": "m s-1",
    }
    dataset["v"].attrs = {
        "standard_name": "northward_sea_water_velocity",
        "long_name": "Northward sea water velocity", "units": "m s-1",
    }
    dataset["ssh"].attrs = {
        "standard_name": "sea_surface_height_above_geoid",
        "long_name": "Sea surface height", "units": "m",
    }
    dataset["bathymetry"].attrs = {
        "standard_name": "sea_floor_depth_below_geoid",
        "long_name": "Sea floor depth", "units": "m", "positive": "down",
    }
    dataset["lat"].attrs = {"standard_name": "latitude", "units": "degrees_north", "axis": "Y"}
    dataset["lon"].attrs = {"standard_name": "longitude", "units": "degrees_east", "axis": "X"}
    dataset["depth"].attrs = {
        "standard_name": "depth", "units": "m", "axis": "Z", "positive": "down",
    }

    return dataset


# ---------------------------------------------------------------------------
# In-situ observations
# ---------------------------------------------------------------------------
def sample_model_column(
    dataset: xr.Dataset, variable: str, lat: float, lon: float, time_index: int
) -> np.ndarray:
    values = (
        dataset[variable]
        .isel(time=time_index)
        .sel(lat=lat, lon=lon, method="nearest")
        .values
    )
    return np.asarray(values, dtype="float64")


def generate_observations(
    dataset: xr.Dataset,
    *,
    n_floats: int,
    n_gliders: int,
    n_ctds: int,
    seed: int,
) -> list[ProfileRecord]:
    """Create Argo, glider and CTD profiles that sample the model imperfectly.

    The deliberate part: observations are *not* the model plus white noise.
    Each platform carries a small persistent offset, and the real ocean is
    given a sharper thermocline than the model resolves.  That is what makes
    the collocation view show a genuine, explainable divergence instead of
    two curves lying on top of each other.
    """
    rng = np.random.default_rng(seed)

    lats = dataset["lat"].values
    lons = dataset["lon"].values
    depths = dataset["depth"].values
    times = dataset["time"].values
    n_times = times.size

    bathymetry = dataset["bathymetry"].values
    valid_mask = np.isfinite(dataset["temperature"].isel(time=0, depth=0).values)

    ocean_rows, ocean_cols = np.where(valid_mask & (bathymetry > 500.0))
    if ocean_rows.size == 0:
        raise RuntimeError("No deep-ocean cells available for platform seeding.")

    records: list[ProfileRecord] = []

    def emit(
        platform_id: str,
        platform_type: str,
        lat: float,
        lon: float,
        time_index: int,
        cycle: int,
        max_depth: float,
        n_levels: int,
        offsets: dict[str, float],
        include_bgc: bool,
    ) -> ProfileRecord | None:
        model_temp = sample_model_column(dataset, "temperature", lat, lon, time_index)
        model_salt = sample_model_column(dataset, "salinity", lat, lon, time_index)
        model_chl = sample_model_column(dataset, "chlorophyll", lat, lon, time_index)

        if not np.isfinite(model_temp).any():
            return None

        # Argo samples on its own pressure axis, not the model's levels.
        obs_depths = np.unique(
            np.round(
                np.concatenate(
                    [
                        np.linspace(0, 200, max(6, n_levels // 2)),
                        np.linspace(220, max_depth, n_levels - max(6, n_levels // 2)),
                    ]
                ),
                1,
            )
        )
        obs_depths = obs_depths[obs_depths <= max_depth]

        finite = np.isfinite(model_temp)
        if finite.sum() < 3:
            return None

        temp = np.interp(obs_depths, depths[finite], model_temp[finite], left=np.nan, right=np.nan)
        salt_finite = np.isfinite(model_salt)
        salt = np.interp(
            obs_depths, depths[salt_finite], model_salt[salt_finite], left=np.nan, right=np.nan
        )
        chl_finite = np.isfinite(model_chl)
        chl = (
            np.interp(obs_depths, depths[chl_finite], model_chl[chl_finite], left=np.nan, right=np.nan)
            if include_bgc and chl_finite.sum() > 2
            else np.full(obs_depths.shape, np.nan)
        )

        # Structural difference: the ocean has a sharper thermocline than the
        # model resolves, so observations are cooler just below the mixed layer.
        thermocline_sharpening = -0.85 * np.exp(-((obs_depths - 95.0) / 45.0) ** 2)

        temp = (
            temp
            + offsets["temperature"]
            + thermocline_sharpening
            + rng.normal(0.0, 0.045, obs_depths.size)
        )
        salt = salt + offsets["salinity"] + rng.normal(0.0, 0.012, obs_depths.size)
        chl = np.clip(chl * rng.normal(1.0, 0.09, obs_depths.size), 0.0, None)

        # Sensors occasionally drop a level.
        dropout = rng.random(obs_depths.size) < 0.015
        temp[dropout] = np.nan
        salt[dropout] = np.nan

        timestamp = (
            times[time_index].astype("datetime64[s]").astype(datetime).replace(tzinfo=timezone.utc)
            + timedelta(hours=float(rng.uniform(-9, 9)))
        )

        return ProfileRecord(
            platform_id=platform_id,
            platform_type=platform_type,
            cycle_number=cycle,
            time=timestamp,
            latitude=float(lat),
            longitude=float(lon),
            depth=[float(d) for d in obs_depths],
            temperature=[None if not np.isfinite(v) else float(v) for v in temp],
            salinity=[None if not np.isfinite(v) else float(v) for v in salt],
            chlorophyll=[None if not np.isfinite(v) else float(v) for v in chl],
            oxygen=[],
            data_mode="D" if cycle % 3 == 0 else "R",
            source_file="synthetic",
        )

    # -- Argo floats: drift with the current, profile every ~5 days ----------
    for index in range(n_floats):
        pick = int(rng.integers(0, ocean_rows.size))
        lat = float(lats[ocean_rows[pick]])
        lon = float(lons[ocean_cols[pick]])

        wmo = 2900000 + index
        platform_id = str(wmo)
        offsets = {
            "temperature": float(rng.normal(0.0, 0.16)),
            "salinity": float(rng.normal(0.0, 0.028)),
        }
        include_bgc = index % 4 == 0  # roughly a quarter are BGC floats

        cycle = 1
        for time_index in range(0, n_times, max(1, n_times // 6)):
            record = emit(
                platform_id, "argo_float", lat, lon, time_index, cycle,
                max_depth=float(rng.choice([1000.0, 1500.0, 2000.0])),
                n_levels=int(rng.integers(28, 46)),
                offsets=offsets, include_bgc=include_bgc,
            )
            if record is not None:
                records.append(record)
                cycle += 1

            # Advect the float at its 1000 m parking depth between cycles.
            try:
                u = float(
                    dataset["u"].isel(time=time_index)
                    .sel(lat=lat, lon=lon, depth=1000.0, method="nearest").values
                )
                v = float(
                    dataset["v"].isel(time=time_index)
                    .sel(lat=lat, lon=lon, depth=1000.0, method="nearest").values
                )
            except Exception:
                u = v = 0.0

            if np.isfinite(u) and np.isfinite(v):
                days = max(1, n_times // 6)
                lat += v * 86400 * days / 111_320.0
                lon += u * 86400 * days / (111_320.0 * max(0.2, math.cos(math.radians(lat))))

            lat = float(np.clip(lat, lats.min() + 0.5, lats.max() - 0.5))
            lon = float(np.clip(lon, lons.min() + 0.5, lons.max() - 0.5))

    # -- Gliders: dense shallow profiles along a coastal transect ------------
    for index in range(n_gliders):
        pick = int(rng.integers(0, ocean_rows.size))
        lat = float(lats[ocean_rows[pick]])
        lon = float(lons[ocean_cols[pick]])
        heading = rng.uniform(0, 2 * math.pi)
        offsets = {
            "temperature": float(rng.normal(0.0, 0.11)),
            "salinity": float(rng.normal(0.0, 0.02)),
        }

        cycle = 1
        for time_index in range(min(n_times, 12)):
            record = emit(
                f"GL{index + 1:03d}", "glider", lat, lon, time_index, cycle,
                max_depth=float(rng.choice([200.0, 400.0, 1000.0])),
                n_levels=int(rng.integers(40, 70)),
                offsets=offsets, include_bgc=True,
            )
            if record is not None:
                records.append(record)
                cycle += 1
            lat += 0.18 * math.sin(heading)
            lon += 0.18 * math.cos(heading)
            lat = float(np.clip(lat, lats.min() + 0.5, lats.max() - 0.5))
            lon = float(np.clip(lon, lons.min() + 0.5, lons.max() - 0.5))

    # -- CTD casts: one-off ship stations ------------------------------------
    for index in range(n_ctds):
        pick = int(rng.integers(0, ocean_rows.size))
        record = emit(
            f"CTD_{index + 1:03d}", "ctd",
            float(lats[ocean_rows[pick]]), float(lons[ocean_cols[pick]]),
            int(rng.integers(0, n_times)), 1,
            max_depth=float(rng.choice([500.0, 1000.0, 1500.0])),
            n_levels=int(rng.integers(50, 90)),
            offsets={"temperature": float(rng.normal(0.0, 0.06)), "salinity": float(rng.normal(0.0, 0.01))},
            include_bgc=False,
        )
        if record is not None:
            records.append(record)

    return records


def write_argo_netcdf(records: list[ProfileRecord], path: Path, limit: int = 40) -> None:
    """Write a subset of profiles as an Argo-format NetCDF file.

    Exists so the Argo adapter is exercised against a real file on disk, not
    only against in-memory records.
    """
    subset = [r for r in records if r.platform_type == "argo_float"][:limit]
    if not subset:
        return

    n_prof = len(subset)
    n_levels = max(len(r.depth) for r in subset)
    epoch = datetime(1950, 1, 1, tzinfo=timezone.utc)

    def pad(series: list[float | None], length: int) -> list[float]:
        out = [np.nan if v is None else float(v) for v in series]
        return out + [np.nan] * (length - len(out))

    pres = np.array([pad(list(r.depth), n_levels) for r in subset], dtype="float32")
    temp = np.array([pad(r.temperature, n_levels) for r in subset], dtype="float32")
    psal = np.array([pad(r.salinity, n_levels) for r in subset], dtype="float32")

    dataset = xr.Dataset(
        data_vars={
            "PLATFORM_NUMBER": (
                ("N_PROF",),
                np.array([r.platform_id.ljust(8)[:8] for r in subset], dtype="S8"),
            ),
            "CYCLE_NUMBER": (("N_PROF",), np.array([r.cycle_number for r in subset], dtype="int32")),
            "JULD": (
                ("N_PROF",),
                np.array(
                    [(r.time - epoch).total_seconds() / 86400.0 for r in subset], dtype="float64"
                ),
            ),
            "LATITUDE": (("N_PROF",), np.array([r.latitude for r in subset], dtype="float64")),
            "LONGITUDE": (("N_PROF",), np.array([r.longitude for r in subset], dtype="float64")),
            "DATA_MODE": (("N_PROF",), np.array([r.data_mode for r in subset], dtype="S1")),
            "PRES": (("N_PROF", "N_LEVELS"), pres),
            "TEMP": (("N_PROF", "N_LEVELS"), temp),
            "PSAL": (("N_PROF", "N_LEVELS"), psal),
        },
        attrs={
            "title": "Synthetic Argo profiles (OceanView3D demo)",
            "Conventions": "Argo-3.1 CF-1.6",
            "synthetic": "true",
        },
    )
    dataset["JULD"].attrs = {
        "units": "days since 1950-01-01 00:00:00 UTC", "standard_name": "time",
    }
    dataset["PRES"].attrs = {"units": "decibar", "long_name": "Sea water pressure"}
    dataset["TEMP"].attrs = {"units": "degree_Celsius", "long_name": "Sea temperature in-situ"}
    dataset["PSAL"].attrs = {"units": "psu", "long_name": "Practical salinity"}

    path.parent.mkdir(parents=True, exist_ok=True)
    dataset.to_netcdf(path, engine="netcdf4")
    logger.info("argo_netcdf_written", extra={"path": str(path), "profiles": n_prof})


def write_ctd_csv(records: list[ProfileRecord], path: Path, limit: int = 12) -> None:
    """Write CTD casts as delimited text, exercising the CSV adapter."""
    subset = [r for r in records if r.platform_type == "ctd"][:limit]
    if not subset:
        return

    path.parent.mkdir(parents=True, exist_ok=True)
    with open(path, "w", encoding="utf-8", newline="") as handle:
        handle.write("platform_id,cycle,time,latitude,longitude,depth,temperature,salinity\n")
        for record in subset:
            stamp = record.time.strftime("%Y-%m-%dT%H:%M:%SZ")
            for index, depth in enumerate(record.depth):
                temperature = record.temperature[index]
                salinity = record.salinity[index]
                handle.write(
                    "{0},{1},{2},{3:.4f},{4:.4f},{5:.1f},{6},{7}\n".format(
                        record.platform_id, record.cycle_number, stamp,
                        record.latitude, record.longitude, depth,
                        "" if temperature is None else f"{temperature:.4f}",
                        "" if salinity is None else f"{salinity:.4f}",
                    )
                )
    logger.info("ctd_csv_written", extra={"path": str(path), "casts": len(subset)})


# ---------------------------------------------------------------------------
# Entrypoint
# ---------------------------------------------------------------------------
def write_zarr(dataset: xr.Dataset, path: Path) -> None:
    """Write a Zarr store, chunked for the access pattern the API uses."""
    import shutil

    if path.exists():
        shutil.rmtree(path)

    chunks: dict[str, int] = {}
    if "time" in dataset.dims:
        chunks["time"] = 1
    if "depth" in dataset.dims:
        chunks["depth"] = int(dataset.sizes["depth"])  # whole column in one chunk
    chunks["lat"] = min(64, int(dataset.sizes["lat"]))
    chunks["lon"] = min(64, int(dataset.sizes["lon"]))

    dataset.chunk(chunks).to_zarr(path, mode="w", consolidated=True)
    logger.info("zarr_written", extra={"path": str(path)})


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--resolution", type=float, default=0.25, help="Grid spacing in degrees")
    parser.add_argument("--times", type=int, default=15, help="Number of daily timesteps")
    parser.add_argument("--depths", type=int, default=25, help="Number of vertical levels")
    parser.add_argument("--floats", type=int, default=70, help="Argo floats to simulate")
    parser.add_argument("--gliders", type=int, default=6, help="Gliders to simulate")
    parser.add_argument("--ctds", type=int, default=40, help="CTD casts to simulate")
    parser.add_argument("--seed", type=int, default=20260824)
    parser.add_argument(
        "--dataset-id", type=str, default="indofos_demo", help="Identifier for the Zarr store"
    )
    parser.add_argument(
        "--skip-observations", action="store_true", help="Only build the gridded dataset"
    )
    args = parser.parse_args()

    configure_logging(level="INFO")

    if not 0.05 <= args.resolution <= 5.0:
        logger.error("resolution must be between 0.05 and 5.0 degrees")
        return 2
    if args.times < 1 or args.depths < 5:
        logger.error("need at least 1 timestep and 5 depth levels")
        return 2

    settings.ensure_directories()
    start = datetime(2024, 3, 1, tzinfo=timezone.utc)

    logger.info("generating_model_dataset")
    dataset = generate_model_dataset(
        resolution=args.resolution,
        n_times=args.times,
        n_depths=args.depths,
        start=start,
        seed=args.seed,
    )

    zarr_path = settings.zarr_dir / f"{args.dataset_id}.zarr"
    write_zarr(dataset, zarr_path)

    # A climatology store so /derived/anomaly has a genuine reference field.
    logger.info("generating_climatology")
    climatology = dataset[["temperature", "salinity", "chlorophyll"]].mean(
        dim="time", keep_attrs=True
    )
    climatology = climatology.expand_dims(time=[dataset["time"].values[0]])
    climatology.attrs = dict(dataset.attrs)
    climatology.attrs["title"] = "OceanView3D synthetic climatology"
    climatology.attrs["summary"] = (
        "Temporal mean of the demo dataset, standing in for a long-term "
        "climatology such as World Ocean Atlas 2023."
    )
    write_zarr(climatology, settings.zarr_dir / f"{args.dataset_id}_climatology.zarr")

    if args.skip_observations:
        logger.info("done", extra={"datasets": [str(zarr_path)]})
        return 0

    logger.info("generating_observations")
    records = generate_observations(
        dataset,
        n_floats=args.floats,
        n_gliders=args.gliders,
        n_ctds=args.ctds,
        seed=args.seed + 1,
    )
    logger.info("observations_generated", extra={"profiles": len(records)})

    write_argo_netcdf(records, settings.raw_dir / "sample_argo_profiles.nc")
    write_ctd_csv(records, settings.raw_dir / "sample_ctd_casts.csv")

    logger.info("loading_observations_into_database")
    init_db()
    with session_scope() as session:
        # Rebuild from scratch so repeated runs stay idempotent.
        session.query(Level).delete()
        session.query(Profile).delete()
        session.query(Platform).delete()
        session.flush()

        run = repository.ingest_records(
            session, records,
            adapter_name="synthetic_generator",
            source="scripts/generate_sample_data.py",
        )
        logger.info("ingested", extra={"profiles": run.profiles_ingested})

    print("\n" + "=" * 68)
    print("  Demo data ready")
    print("=" * 68)
    print(f"  Model store      : {zarr_path}")
    print(f"  Climatology      : {settings.zarr_dir / (args.dataset_id + '_climatology.zarr')}")
    print(f"  Argo NetCDF      : {settings.raw_dir / 'sample_argo_profiles.nc'}")
    print(f"  CTD CSV          : {settings.raw_dir / 'sample_ctd_casts.csv'}")
    print(f"  Profiles ingested: {len(records)}")
    print(f"  Grid             : {dataset.sizes}")
    print("\n  Start the API with:")
    print("    uvicorn app.main:app --reload")
    print("=" * 68 + "\n")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
