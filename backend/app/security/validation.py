"""Input validation helpers.

These are the second half of the firewall: the middleware stops abusive
*traffic*, while these functions stop abusive *parameters*.  For a gridded
data API the request that asks for a 200 GB hypercube is far more dangerous
than the one that arrives too often.
"""

from __future__ import annotations

import re
from datetime import datetime, timezone

import numpy as np

from app.core.errors import PayloadTooLargeError, ValidationError

#: Dataset and variable identifiers are used to build filesystem paths and
#: Zarr group keys, so they are restricted to an explicit safe alphabet.
IDENTIFIER_RE = re.compile(r"^[a-zA-Z0-9][a-zA-Z0-9_\-]{0,63}$")

_TRAVERSAL_TOKENS = ("..", "/", "\\", "\x00", "~", ":")


def safe_identifier(value: str, *, field: str = "identifier") -> str:
    """Validate an identifier that will be interpolated into a path or key."""
    if not isinstance(value, str) or not value:
        raise ValidationError(f"'{field}' must be a non-empty string.", field=field)
    if any(token in value for token in _TRAVERSAL_TOKENS):
        raise ValidationError(
            f"'{field}' contains characters that are not permitted.", field=field
        )
    if not IDENTIFIER_RE.match(value):
        raise ValidationError(
            f"'{field}' must match {IDENTIFIER_RE.pattern}.", field=field, value=value[:64]
        )
    return value


def parse_bbox(
    bbox: str | None,
    *,
    default: tuple[float, float, float, float],
) -> tuple[float, float, float, float]:
    """Parse ``min_lon,min_lat,max_lon,max_lat`` (OGC axis order)."""
    if bbox is None or not bbox.strip():
        return default

    parts = [p.strip() for p in bbox.split(",")]
    if len(parts) != 4:
        raise ValidationError(
            "'bbox' must contain exactly four comma-separated numbers: "
            "min_lon,min_lat,max_lon,max_lat.",
            field="bbox",
        )
    try:
        min_lon, min_lat, max_lon, max_lat = (float(p) for p in parts)
    except ValueError:
        raise ValidationError("'bbox' values must be numeric.", field="bbox") from None

    for name, value in (("longitude", min_lon), ("longitude", max_lon)):
        if not -360.0 <= value <= 360.0:
            raise ValidationError(f"bbox {name} {value} is out of range.", field="bbox")
    for name, value in (("latitude", min_lat), ("latitude", max_lat)):
        if not -90.0 <= value <= 90.0:
            raise ValidationError(f"bbox {name} {value} is out of range.", field="bbox")

    if min_lon >= max_lon:
        raise ValidationError("bbox min_lon must be smaller than max_lon.", field="bbox")
    if min_lat >= max_lat:
        raise ValidationError("bbox min_lat must be smaller than max_lat.", field="bbox")

    return min_lon, min_lat, max_lon, max_lat


def parse_depth_range(
    depth_min: float | None,
    depth_max: float | None,
    *,
    available_min: float,
    available_max: float,
) -> tuple[float, float]:
    """Clamp a requested depth window to what the dataset actually holds."""
    lo = available_min if depth_min is None else float(depth_min)
    hi = available_max if depth_max is None else float(depth_max)

    if lo > hi:
        raise ValidationError(
            "'depth_min' must be less than or equal to 'depth_max'.", field="depth_min"
        )
    if hi < available_min or lo > available_max:
        raise ValidationError(
            "Requested depth window lies outside the dataset range "
            f"[{available_min}, {available_max}] m.",
            field="depth_min",
        )
    return max(lo, available_min), min(hi, available_max)


def parse_iso_time(value: str | None, *, field: str = "time") -> datetime | None:
    """Parse an ISO-8601 timestamp, tolerating a trailing ``Z``."""
    if value is None or not value.strip():
        return None
    text = value.strip()
    if text.endswith(("Z", "z")):
        text = text[:-1] + "+00:00"
    try:
        parsed = datetime.fromisoformat(text)
    except ValueError:
        raise ValidationError(
            f"'{field}' must be an ISO-8601 timestamp, e.g. 2024-03-01T00:00:00Z.",
            field=field,
        ) from None
    if parsed.tzinfo is None:
        parsed = parsed.replace(tzinfo=timezone.utc)
    return parsed.astimezone(timezone.utc)


def guard_cell_budget(
    *,
    n_lat: int,
    n_lon: int,
    n_depth: int = 1,
    n_time: int = 1,
    bytes_per_cell: int = 1,
    max_cells: int,
    max_bytes: int,
) -> int:
    """Reject a request whose materialised array would be too large.

    Returns the total cell count when the request is acceptable.
    """
    if min(n_lat, n_lon, n_depth, n_time) <= 0:
        raise ValidationError(
            "The requested subset is empty. Check the bbox, depth and time filters.",
        )

    total_cells = int(n_lat) * int(n_lon) * int(n_depth) * int(n_time)
    total_bytes = total_cells * bytes_per_cell

    if total_cells > max_cells:
        raise PayloadTooLargeError(
            "The requested subset contains "
            f"{total_cells:,} cells, above the {max_cells:,} cell limit. "
            "Narrow the bbox, depth window or time range, or increase 'stride'.",
            cells=total_cells,
            max_cells=max_cells,
        )
    if total_bytes > max_bytes:
        raise PayloadTooLargeError(
            f"The response would be {total_bytes / 1048576:.1f} MiB, above the "
            f"{max_bytes / 1048576:.0f} MiB limit.",
            bytes=total_bytes,
            max_bytes=max_bytes,
        )
    return total_cells


def clamp_int(value: int | None, *, default: int, minimum: int, maximum: int, field: str) -> int:
    """Coerce an integer parameter into an accepted range."""
    if value is None:
        return default
    try:
        ivalue = int(value)
    except (TypeError, ValueError):
        raise ValidationError(f"'{field}' must be an integer.", field=field) from None
    if ivalue < minimum or ivalue > maximum:
        raise ValidationError(
            f"'{field}' must be between {minimum} and {maximum}.", field=field, value=ivalue
        )
    return ivalue


def sanitise_float(value: float, *, field: str, allow_nan: bool = False) -> float:
    """Reject NaN/Inf inputs that would poison downstream array maths."""
    fvalue = float(value)
    if not allow_nan and not np.isfinite(fvalue):
        raise ValidationError(f"'{field}' must be a finite number.", field=field)
    return fvalue
