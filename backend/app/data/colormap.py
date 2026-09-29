"""Colour handling: palette resolution, lookup tables, tiles and legends.

The client does almost all recolouring on the GPU by swapping a 256-entry
lookup table, so ``lut()`` is the endpoint that matters for interactivity -
dragging a colorbar range never re-fetches field data.  Server-side raster
rendering is still needed for the OGC WMS interface, which by definition
returns images.
"""

from __future__ import annotations

import io
from dataclasses import dataclass
from typing import Any, Literal

import matplotlib

matplotlib.use("Agg")  # No GUI backend: this process has no display.

import matplotlib.colors as mcolors  # noqa: E402
import numpy as np  # noqa: E402
from matplotlib import colormaps as mpl_colormaps  # noqa: E402
from matplotlib.figure import Figure  # noqa: E402
from PIL import Image  # noqa: E402

from app.core.errors import ValidationError  # noqa: E402
from app.core.logging import get_logger  # noqa: E402

logger = get_logger(__name__)

ScaleType = Literal["linear", "log"]

#: Oceanographic palettes from cmocean, which is what operational ocean
#: centres actually use.  Falls back to matplotlib equivalents if absent.
CMOCEAN_FALLBACK: dict[str, str] = {
    "thermal": "inferno",
    "haline": "viridis",
    "solar": "plasma",
    "ice": "Blues_r",
    "deep": "YlGnBu",
    "dense": "magma",
    "algae": "YlGn",
    "matter": "YlOrRd",
    "turbid": "YlOrBr",
    "speed": "viridis",
    "amp": "Reds",
    "tempo": "GnBu",
    "balance": "RdBu_r",
    "delta": "RdYlBu_r",
    "curl": "PuOr_r",
    "diff": "coolwarm",
    "oxy": "cividis",
    "phase": "twilight",
    "topo": "terrain",
}

#: Palettes surfaced in the API catalog, grouped for the UI's palette picker.
PALETTE_GROUPS: dict[str, list[str]] = {
    "oceanographic": [
        "thermal", "haline", "deep", "dense", "algae", "ice",
        "solar", "turbid", "speed", "oxy", "matter", "amp",
    ],
    "diverging": ["balance", "delta", "curl", "diff", "RdBu_r", "coolwarm", "seismic"],
    "sequential": ["viridis", "plasma", "inferno", "magma", "cividis", "YlGnBu", "Blues"],
    "cyclic": ["phase", "twilight", "hsv"],
}

_HAS_CMOCEAN = False
try:  # pragma: no cover - depends on optional install
    import cmocean  # type: ignore

    _HAS_CMOCEAN = True
except Exception:  # pragma: no cover
    logger.info("cmocean_unavailable_using_matplotlib_fallbacks")

_LUT_CACHE: dict[tuple[str, bool], np.ndarray] = {}


@dataclass(slots=True)
class ColorScale:
    """A resolved palette plus the numeric range and transfer function."""

    name: str
    vmin: float
    vmax: float
    scale: ScaleType = "linear"
    reverse: bool = False

    def normalise(self, values: np.ndarray) -> np.ndarray:
        """Map physical values into ``[0, 1]``, preserving NaN."""
        array = np.asarray(values, dtype="float64")

        if self.scale == "log":
            # Log scaling is undefined at or below zero; mask those cells.
            lo = max(self.vmin, 1e-12)
            hi = max(self.vmax, lo * 10.0)
            with np.errstate(divide="ignore", invalid="ignore"):
                safe = np.where(array > 0, array, np.nan)
                out = (np.log10(safe) - np.log10(lo)) / (np.log10(hi) - np.log10(lo))
        else:
            span = self.vmax - self.vmin
            if span <= 0:
                span = 1.0
            out = (array - self.vmin) / span

        return np.clip(out, 0.0, 1.0)


def resolve_colormap(name: str) -> mcolors.Colormap:
    """Resolve a palette name across cmocean and matplotlib registries."""
    if not isinstance(name, str) or not name:
        raise ValidationError("'colormap' must be a non-empty string.", field="colormap")

    base = name[:-2] if name.endswith("_r") else name
    reversed_requested = name.endswith("_r")

    cmap: mcolors.Colormap | None = None

    if _HAS_CMOCEAN and base in CMOCEAN_FALLBACK:
        cmap = getattr(cmocean.cm, base, None)  # type: ignore[attr-defined]

    if cmap is None:
        try:
            cmap = mpl_colormaps[name]
            return cmap
        except KeyError:
            pass

    if cmap is None and base in CMOCEAN_FALLBACK:
        try:
            cmap = mpl_colormaps[CMOCEAN_FALLBACK[base]]
        except KeyError:
            cmap = None

    if cmap is None:
        try:
            cmap = mpl_colormaps[base]
        except KeyError:
            raise ValidationError(
                f"Unknown colormap '{name}'.", field="colormap",
                available=available_colormaps()[:40],
            ) from None

    return cmap.reversed() if reversed_requested else cmap


def available_colormaps() -> list[str]:
    names: list[str] = []
    for group in PALETTE_GROUPS.values():
        names.extend(group)
    return sorted(set(names))


def catalog() -> list[dict[str, Any]]:
    """Palette catalog with inline preview swatches for the UI picker."""
    entries: list[dict[str, Any]] = []
    for group, names in PALETTE_GROUPS.items():
        for name in names:
            try:
                table = lut(name)
            except ValidationError:
                continue
            swatch = [
                "#{0:02x}{1:02x}{2:02x}".format(*table[i, :3]) for i in range(0, 256, 32)
            ]
            entries.append(
                {
                    "name": name,
                    "group": group,
                    "source": "cmocean" if (_HAS_CMOCEAN and name in CMOCEAN_FALLBACK) else "matplotlib",
                    "swatch": swatch,
                    "reversible": True,
                }
            )
    return entries


def lut(name: str, *, reverse: bool = False, size: int = 256) -> np.ndarray:
    """Return an ``(size, 4)`` uint8 RGBA lookup table.

    The client uploads this as a 1-D texture; recolouring then costs one
    texture swap instead of a data round-trip.
    """
    cache_key = (f"{name}:{size}", reverse)
    cached = _LUT_CACHE.get(cache_key)
    if cached is not None:
        return cached

    cmap = resolve_colormap(name)
    if reverse:
        cmap = cmap.reversed()

    samples = np.linspace(0.0, 1.0, size)
    table = (np.asarray(cmap(samples)) * 255.0).round().astype("uint8")
    _LUT_CACHE[cache_key] = table
    return table


def render_rgba(values: np.ndarray, scale: ColorScale) -> np.ndarray:
    """Colour a 2-D field, returning ``(rows, cols, 4)`` uint8 RGBA.

    No-data cells become fully transparent so tiles composite correctly over
    a basemap.
    """
    array = np.asarray(values, dtype="float64")
    if array.ndim != 2:
        raise ValidationError(f"Expected a 2-D field, received {array.ndim} dimensions.")

    normalised = scale.normalise(array)
    table = lut(scale.name, reverse=scale.reverse)

    indices = np.zeros(array.shape, dtype="uint8")
    valid = np.isfinite(normalised)
    indices[valid] = np.rint(normalised[valid] * 255).astype("uint8")

    rgba = table[indices]
    rgba[~valid, 3] = 0
    return rgba


def render_png(values: np.ndarray, scale: ColorScale, *, flip_vertical: bool = True) -> bytes:
    """Render a 2-D field to PNG bytes.

    ``flip_vertical`` converts from ascending-latitude array order to the
    top-down row order that image formats and WMS clients expect.
    """
    rgba = render_rgba(values, scale)
    if flip_vertical:
        rgba = np.flipud(rgba)

    image = Image.fromarray(rgba, mode="RGBA")
    buffer = io.BytesIO()
    image.save(buffer, format="PNG", optimize=False, compress_level=1)
    return buffer.getvalue()


def render_legend(
    scale: ColorScale,
    *,
    label: str = "",
    width: int = 110,
    height: int = 330,
    horizontal: bool = False,
) -> bytes:
    """Render a colorbar legend as PNG (WMS ``GetLegendGraphic``)."""
    dpi = 100.0
    figure = Figure(figsize=(width / dpi, height / dpi), dpi=dpi)
    figure.patch.set_alpha(0.0)

    if horizontal:
        axes = figure.add_axes([0.05, 0.45, 0.90, 0.25])
        orientation = "horizontal"
    else:
        axes = figure.add_axes([0.08, 0.06, 0.32, 0.88])
        orientation = "vertical"

    cmap = resolve_colormap(scale.name)
    if scale.reverse:
        cmap = cmap.reversed()

    if scale.scale == "log":
        norm = mcolors.LogNorm(vmin=max(scale.vmin, 1e-12), vmax=max(scale.vmax, 1e-11))
    else:
        norm = mcolors.Normalize(vmin=scale.vmin, vmax=scale.vmax)

    colorbar = figure.colorbar(
        matplotlib.cm.ScalarMappable(norm=norm, cmap=cmap),
        cax=axes,
        orientation=orientation,
    )
    if label:
        colorbar.set_label(label, fontsize=8, color="#e8eef5")
    colorbar.ax.tick_params(labelsize=7, colors="#e8eef5")
    colorbar.outline.set_edgecolor("#8fa3b8")

    buffer = io.BytesIO()
    figure.savefig(buffer, format="png", transparent=True, bbox_inches="tight")
    return buffer.getvalue()


def blank_png(width: int, height: int) -> bytes:
    """Fully transparent tile - returned when a WMS request selects no data."""
    image = Image.new("RGBA", (max(1, width), max(1, height)), (0, 0, 0, 0))
    buffer = io.BytesIO()
    image.save(buffer, format="PNG")
    return buffer.getvalue()
