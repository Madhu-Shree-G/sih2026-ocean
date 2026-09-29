"""Quantisation and binary packing of gridded fields for WebGL upload.

Why this module exists
----------------------
A browser cannot usefully consume float32 NetCDF.  A 512x512x40 float32 cube
is 42 MiB *per variable per timestep*; twenty timesteps of three variables
would be 2.5 GiB of GPU memory and the demo laptop dies.

Quantising to uint8 with a scale/offset pair - exactly the mechanism CF
already defines via ``scale_factor``/``add_offset`` - costs 8 bits of
precision that a colour ramp cannot resolve anyway, and drops the same cube
to 10 MiB.  The client uploads the payload directly as a WebGL2
``TEXTURE_3D`` with internal format ``R8`` and reconstructs physical values
in the shader:

    value = offset + (raw - 1) * scale      // raw == 0 means no-data

Raw value 0 is reserved as the no-data sentinel so land and below-seafloor
cells can be discarded in the fragment shader, leaving 255 usable levels.

Wire format ("OCVOL1")
----------------------
    offset  size  content
    0       8     magic  b"OCVOL1\\x00\\x00"
    8       4     uint32 little-endian header length H
    12      H     UTF-8 JSON header
    12+H    N     uint8 payload, C-order [time][depth][lat][lon]
"""

from __future__ import annotations

import json
import struct
from dataclasses import dataclass
from typing import Any

import numpy as np

MAGIC = b"OCVOL1\x00\x00"
HEADER_STRUCT = struct.Struct("<I")
NODATA_RAW = 0
MIN_VALID_RAW = 1
MAX_VALID_RAW = 255
VALID_LEVELS = MAX_VALID_RAW - MIN_VALID_RAW  # 254 intervals


@dataclass(slots=True)
class QuantisedField:
    """A uint8-quantised array plus the parameters needed to invert it."""

    data: np.ndarray          # uint8, C-contiguous
    scale: float
    offset: float
    vmin: float
    vmax: float
    nodata_count: int

    def dequantise(self) -> np.ndarray:
        """Reconstruct physical values (used by tests and server-side maths)."""
        out = np.full(self.data.shape, np.nan, dtype="float32")
        valid = self.data >= MIN_VALID_RAW
        out[valid] = self.offset + (self.data[valid].astype("float32") - MIN_VALID_RAW) * self.scale
        return out


def quantise(
    values: np.ndarray,
    *,
    vmin: float | None = None,
    vmax: float | None = None,
) -> QuantisedField:
    """Map a float array onto ``uint8`` with 0 reserved for no-data.

    When ``vmin``/``vmax`` are omitted the range is taken from the finite
    values present.  Values outside the requested range are clamped rather
    than discarded, so an explicit range acts as a contrast stretch.
    """
    array = np.asarray(values, dtype="float32")
    finite_mask = np.isfinite(array)

    if not finite_mask.any():
        return QuantisedField(
            data=np.zeros(array.shape, dtype="uint8"),
            scale=1.0, offset=0.0, vmin=0.0, vmax=0.0,
            nodata_count=int(array.size),
        )

    lo = float(np.min(array[finite_mask])) if vmin is None else float(vmin)
    hi = float(np.max(array[finite_mask])) if vmax is None else float(vmax)

    # A degenerate range would divide by zero; widen it symmetrically.
    if not np.isfinite(lo) or not np.isfinite(hi) or hi <= lo:
        centre = lo if np.isfinite(lo) else 0.0
        lo, hi = centre - 0.5, centre + 0.5

    scale = (hi - lo) / VALID_LEVELS

    normalised = (array - lo) / (hi - lo)
    # NaN cells are overwritten with the sentinel below, but they must be
    # finite before the integer cast or numpy reports undefined behaviour.
    normalised = np.nan_to_num(normalised, nan=0.0, posinf=1.0, neginf=0.0)
    np.clip(normalised, 0.0, 1.0, out=normalised)
    raw = np.rint(normalised * VALID_LEVELS).astype("uint16") + MIN_VALID_RAW
    np.clip(raw, MIN_VALID_RAW, MAX_VALID_RAW, out=raw)

    data = raw.astype("uint8")
    data[~finite_mask] = NODATA_RAW

    return QuantisedField(
        data=np.ascontiguousarray(data),
        scale=scale,
        offset=lo,
        vmin=lo,
        vmax=hi,
        nodata_count=int((~finite_mask).sum()),
    )


def pack(header: dict[str, Any], payload: np.ndarray) -> bytes:
    """Serialise a header/payload pair into the OCVOL1 container."""
    if payload.dtype != np.uint8:
        raise TypeError(f"payload must be uint8, received {payload.dtype}")

    blob = json.dumps(header, separators=(",", ":"), allow_nan=False).encode("utf-8")
    body = np.ascontiguousarray(payload).tobytes()
    return MAGIC + HEADER_STRUCT.pack(len(blob)) + blob + body


def unpack(buffer: bytes) -> tuple[dict[str, Any], np.ndarray]:
    """Inverse of :func:`pack`. Used by the test-suite and CLI tooling."""
    if len(buffer) < len(MAGIC) + HEADER_STRUCT.size:
        raise ValueError("Buffer is too short to be an OCVOL1 container.")
    if buffer[: len(MAGIC)] != MAGIC:
        raise ValueError("Bad magic: not an OCVOL1 container.")

    start = len(MAGIC)
    (header_len,) = HEADER_STRUCT.unpack_from(buffer, start)
    start += HEADER_STRUCT.size

    header = json.loads(buffer[start : start + header_len].decode("utf-8"))
    payload = np.frombuffer(buffer, dtype="uint8", offset=start + header_len)
    return header, payload.reshape(header["shape"])


def build_volume_payload(
    *,
    values: np.ndarray,
    variable: str,
    units: str,
    dataset_id: str,
    lats: np.ndarray,
    lons: np.ndarray,
    depths: np.ndarray,
    times: list[str],
    colormap: str,
    vmin: float | None = None,
    vmax: float | None = None,
    extra: dict[str, Any] | None = None,
) -> bytes:
    """Quantise a ``(time, depth, lat, lon)`` block and pack it for transport."""
    field = quantise(values, vmin=vmin, vmax=vmax)
    n_time, n_depth, n_lat, n_lon = field.data.shape

    header: dict[str, Any] = {
        "format": "OCVOL1",
        "dataset": dataset_id,
        "variable": variable,
        "units": units,
        "dtype": "uint8",
        "shape": [n_time, n_depth, n_lat, n_lon],
        "axis_order": ["time", "depth", "lat", "lon"],
        # value = offset + (raw - 1) * scale, raw in [1, 255]; raw 0 = no data
        "scale": field.scale,
        "offset": field.offset,
        "nodata_raw": NODATA_RAW,
        "min_valid_raw": MIN_VALID_RAW,
        "value_range": [field.vmin, field.vmax],
        "nodata_count": field.nodata_count,
        "colormap": colormap,
        "bbox": [
            float(np.min(lons)), float(np.min(lats)),
            float(np.max(lons)), float(np.max(lats)),
        ],
        "lat_range": [float(np.min(lats)), float(np.max(lats))],
        "lon_range": [float(np.min(lons)), float(np.max(lons))],
        "depths": [round(float(d), 4) for d in depths],
        "times": times,
        "byte_length": int(field.data.size),
    }
    if extra:
        header.update(extra)

    return pack(header, field.data)


def subsample_to_budget(
    n_lat: int, n_lon: int, n_depth: int, n_time: int, *, max_cells: int
) -> int:
    """Choose the smallest horizontal stride that fits the cell budget.

    Returning a stride rather than raising keeps a whole-domain request
    usable: the client gets a coarser field instead of a 413.
    """
    stride = 1
    while stride <= 64:
        cells = ((n_lat + stride - 1) // stride) * ((n_lon + stride - 1) // stride)
        if cells * max(1, n_depth) * max(1, n_time) <= max_cells:
            return stride
        stride += 1
    return 64
