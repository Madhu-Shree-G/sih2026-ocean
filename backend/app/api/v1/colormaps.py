"""Colour palette endpoints.

The client recolours on the GPU by swapping a 256-entry lookup table, so
``/colormaps/{name}/lut`` is what makes dragging a colorbar range feel
instant: no field data is re-fetched, only a 1 KiB texture.
"""

from __future__ import annotations

from typing import Any

from fastapi import APIRouter, Depends, Path, Query, Response

from app.data.colormap import ColorScale, catalog, lut, render_legend
from app.security.deps import require_api_key

router = APIRouter(tags=["colormaps"], dependencies=[Depends(require_api_key)])


@router.get("", summary="List available colour palettes")
async def list_colormaps() -> dict[str, Any]:
    """Palettes with preview swatches, grouped for the UI picker."""
    entries = catalog()
    groups: dict[str, list[str]] = {}
    for entry in entries:
        groups.setdefault(entry["group"], []).append(entry["name"])
    return {"count": len(entries), "groups": groups, "colormaps": entries}


@router.get(
    "/{name}/lut",
    summary="256-entry RGBA lookup table",
    response_class=Response,
    responses={200: {"content": {"application/octet-stream": {}, "application/json": {}}}},
)
async def get_lut(
    name: str = Path(..., max_length=64),
    reverse: bool = Query(False),
    size: int = Query(256, ge=2, le=1024),
    format: str = Query("binary", pattern="^(binary|json)$"),
) -> Response:
    """Return the palette as RGBA bytes for direct texture upload."""
    table = lut(name, reverse=reverse, size=size)

    if format == "json":
        import json

        return Response(
            content=json.dumps(
                {
                    "name": name,
                    "reverse": reverse,
                    "size": int(table.shape[0]),
                    "rgba": table.tolist(),
                },
                separators=(",", ":"),
            ),
            media_type="application/json",
            headers={"Cache-Control": "public, max-age=86400"},
        )

    return Response(
        content=table.tobytes(),
        media_type="application/octet-stream",
        headers={
            "X-Ocean-LUT-Size": str(int(table.shape[0])),
            "X-Ocean-LUT-Channels": "4",
            "Cache-Control": "public, max-age=86400",
        },
    )


@router.get(
    "/{name}/legend",
    summary="Rendered colorbar legend",
    response_class=Response,
    responses={200: {"content": {"image/png": {}}}},
)
async def get_legend(
    name: str = Path(..., max_length=64),
    vmin: float = Query(0.0),
    vmax: float = Query(1.0),
    scale: str = Query("linear", pattern="^(linear|log)$"),
    label: str = Query("", max_length=64),
    reverse: bool = Query(False),
    horizontal: bool = Query(False),
    width: int = Query(110, ge=40, le=800),
    height: int = Query(330, ge=40, le=800),
) -> Response:
    """PNG colorbar for print-ready figures and the WMS legend endpoint."""
    if vmax <= vmin:
        vmax = vmin + 1.0

    image = render_legend(
        ColorScale(name=name, vmin=vmin, vmax=vmax, scale=scale, reverse=reverse),  # type: ignore[arg-type]
        label=label,
        width=width,
        height=height,
        horizontal=horizontal,
    )
    return Response(
        content=image,
        media_type="image/png",
        headers={"Cache-Control": "public, max-age=3600"},
    )
