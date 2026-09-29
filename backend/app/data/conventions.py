"""CF convention helpers: coordinate normalisation and the variable canon.

Model output arrives with wildly inconsistent naming (``lat``/``latitude``/
``nav_lat``, ``depth``/``lev``/``z``).  Everything is normalised once here so
that the rest of the codebase can assume the canonical axes
``(time, depth, lat, lon)``.
"""

from __future__ import annotations

from typing import Any

import xarray as xr

from app.data.adapters.base import VariableSpec

# ---------------------------------------------------------------------------
# Coordinate aliases
# ---------------------------------------------------------------------------
LAT_ALIASES = ("lat", "latitude", "nav_lat", "y", "yc", "LATITUDE", "Latitude")
LON_ALIASES = ("lon", "longitude", "nav_lon", "x", "xc", "LONGITUDE", "Longitude")
DEPTH_ALIASES = ("depth", "lev", "level", "z", "deptht", "zlev", "DEPTH", "Depth", "pressure")
TIME_ALIASES = ("time", "t", "TIME", "Time", "time_counter", "ocean_time")

CANONICAL_AXES = ("time", "depth", "lat", "lon")

# ---------------------------------------------------------------------------
# Variable canon
# ---------------------------------------------------------------------------
#: Known ocean state variables with sensible display defaults.  ``aliases``
#: lets an adapter recognise the same physical quantity across products.
VARIABLE_CANON: dict[str, dict[str, Any]] = {
    "temperature": {
        "standard_name": "sea_water_potential_temperature",
        "long_name": "Sea water potential temperature",
        "units": "degree_Celsius",
        "default_colormap": "thermal",
        "default_range": (2.0, 32.0),
        "aliases": ("thetao", "temp", "TEMP", "votemper", "water_temp", "t", "sst"),
    },
    "salinity": {
        "standard_name": "sea_water_salinity",
        "long_name": "Sea water practical salinity",
        "units": "psu",
        "default_colormap": "haline",
        "default_range": (32.0, 37.0),
        "aliases": ("so", "psal", "PSAL", "vosaline", "salt", "s"),
    },
    "u": {
        "standard_name": "eastward_sea_water_velocity",
        "long_name": "Eastward sea water velocity",
        "units": "m s-1",
        "default_colormap": "balance",
        "default_range": (-1.5, 1.5),
        "aliases": ("uo", "u_velocity", "vozocrtx", "water_u", "eastward_velocity"),
        "vector_group": "current",
    },
    "v": {
        "standard_name": "northward_sea_water_velocity",
        "long_name": "Northward sea water velocity",
        "units": "m s-1",
        "default_colormap": "balance",
        "default_range": (-1.5, 1.5),
        "aliases": ("vo", "v_velocity", "vomecrty", "water_v", "northward_velocity"),
        "vector_group": "current",
    },
    "chlorophyll": {
        "standard_name": "mass_concentration_of_chlorophyll_a_in_sea_water",
        "long_name": "Chlorophyll-a concentration",
        "units": "mg m-3",
        "default_colormap": "algae",
        "default_range": (0.0, 3.0),
        "aliases": ("chl", "CHLA", "chlor_a", "chla"),
    },
    "oxygen": {
        "standard_name": "moles_of_oxygen_per_unit_mass_in_sea_water",
        "long_name": "Dissolved oxygen concentration",
        "units": "micromole kg-1",
        "default_colormap": "oxy",
        "default_range": (0.0, 260.0),
        "aliases": ("o2", "DOXY", "doxy", "oxygen_concentration"),
    },
    "ssh": {
        "standard_name": "sea_surface_height_above_geoid",
        "long_name": "Sea surface height",
        "units": "m",
        "default_colormap": "balance",
        "default_range": (-1.0, 1.0),
        "aliases": ("zos", "sea_surface_height", "adt", "surf_el"),
    },
}

#: Reverse lookup from any known alias to the canonical name.
_ALIAS_LOOKUP: dict[str, str] = {}
for _canonical, _meta in VARIABLE_CANON.items():
    _ALIAS_LOOKUP[_canonical.lower()] = _canonical
    for _alias in _meta.get("aliases", ()):
        _ALIAS_LOOKUP[_alias.lower()] = _canonical


def canonical_variable_name(name: str) -> str | None:
    """Map a product-specific variable name onto the canon, if known."""
    return _ALIAS_LOOKUP.get(name.lower())


def variable_spec(name: str, *, units: str | None = None) -> VariableSpec:
    """Build a :class:`VariableSpec`, falling back to generic defaults."""
    meta = VARIABLE_CANON.get(name)
    if meta is None:
        return VariableSpec(
            name=name,
            standard_name=name,
            long_name=name.replace("_", " ").capitalize(),
            units=units or "1",
        )
    return VariableSpec(
        name=name,
        standard_name=meta["standard_name"],
        long_name=meta["long_name"],
        units=units or meta["units"],
        default_colormap=meta["default_colormap"],
        default_range=meta["default_range"],
        is_vector_component=meta.get("vector_group") is not None,
        vector_group=meta.get("vector_group"),
    )


def _find_alias(names: set[str], aliases: tuple[str, ...]) -> str | None:
    lowered = {n.lower(): n for n in names}
    for alias in aliases:
        if alias.lower() in lowered:
            return lowered[alias.lower()]
    return None


def normalise_dataset(ds: xr.Dataset) -> xr.Dataset:
    """Rename axes and variables onto the canonical vocabulary.

    Also guarantees that ``lat``, ``depth`` and ``time`` are monotonically
    increasing, which lets every downstream slice use ``slice(lo, hi)``
    without worrying about the source's storage order.
    """
    names = set(ds.dims) | set(ds.coords) | set(ds.variables)
    rename: dict[str, str] = {}

    for canonical, aliases in (
        ("lat", LAT_ALIASES),
        ("lon", LON_ALIASES),
        ("depth", DEPTH_ALIASES),
        ("time", TIME_ALIASES),
    ):
        if canonical in ds.dims or canonical in ds.coords:
            continue
        found = _find_alias(names, aliases)
        if found is not None:
            rename[found] = canonical

    for var_name in list(ds.data_vars):
        canonical = canonical_variable_name(str(var_name))
        if canonical and canonical != var_name and canonical not in ds.data_vars:
            rename[str(var_name)] = canonical

    if rename:
        ds = ds.rename(rename)

    # Depth is stored positive-down; some products store it negative-up.
    if "depth" in ds.coords and ds["depth"].size > 1:
        depth_values = ds["depth"].values
        if float(depth_values[0]) > float(depth_values[-1]):
            ds = ds.isel(depth=slice(None, None, -1))
        if float(ds["depth"].values.min()) < 0:
            ds = ds.assign_coords(depth=abs(ds["depth"]))

    if "lat" in ds.coords and ds["lat"].size > 1:
        if float(ds["lat"].values[0]) > float(ds["lat"].values[-1]):
            ds = ds.isel(lat=slice(None, None, -1))

    return ds


def attach_cf_attributes(ds: xr.Dataset) -> xr.Dataset:
    """Stamp CF-1.8 metadata onto coordinates and known variables."""
    coord_attrs = {
        "lat": {"standard_name": "latitude", "units": "degrees_north", "axis": "Y"},
        "lon": {"standard_name": "longitude", "units": "degrees_east", "axis": "X"},
        "depth": {
            "standard_name": "depth", "units": "m", "axis": "Z", "positive": "down",
        },
        "time": {"standard_name": "time", "axis": "T"},
    }
    for coord, attrs in coord_attrs.items():
        if coord in ds.coords:
            ds[coord].attrs.update(attrs)

    for var_name in ds.data_vars:
        meta = VARIABLE_CANON.get(str(var_name))
        if meta:
            ds[var_name].attrs.setdefault("standard_name", meta["standard_name"])
            ds[var_name].attrs.setdefault("long_name", meta["long_name"])
            ds[var_name].attrs.setdefault("units", meta["units"])

    ds.attrs.setdefault("Conventions", "CF-1.8")
    return ds
