"""OGC Web Map Service 1.3.0 interface.

The problem statement requires open standards so the platform interoperates
with national and international ocean portals rather than becoming another
silo.  A conformant WMS means QGIS, ArcGIS, Leaflet and existing INCOIS
portal tooling can consume these layers with no bespoke client code.

Supported operations: ``GetCapabilities``, ``GetMap``, ``GetLegendGraphic``,
``GetFeatureInfo``.  Layer names are ``<dataset>/<variable>``.

WMS parameter names are case-insensitive per the specification, so the raw
query string is normalised before use instead of relying on FastAPI's
case-sensitive ``Query`` binding.
"""

from __future__ import annotations

from typing import Any
from xml.sax.saxutils import escape

import numpy as np
from fastapi import APIRouter, Depends, Request, Response

from app.config import settings
from app.core.errors import ValidationError
from app.data.catalog import Catalog, DatasetHandle
from app.data.colormap import ColorScale, blank_png, render_legend, render_png
from app.security.deps import get_catalog, require_api_key
from app.security.validation import parse_iso_time, safe_identifier

router = APIRouter(tags=["ogc"], dependencies=[Depends(require_api_key)])

WMS_VERSION = "1.3.0"
MAX_IMAGE_DIMENSION = 4096
SUPPORTED_CRS = ("CRS:84", "EPSG:4326")


def _params(request: Request) -> dict[str, str]:
    """Lower-case every WMS parameter name, per the specification."""
    return {key.lower(): value for key, value in request.query_params.items()}


def _require(params: dict[str, str], key: str) -> str:
    value = params.get(key)
    if value is None or value == "":
        raise ValidationError(f"Missing required WMS parameter '{key.upper()}'.", field=key)
    return value


def _parse_layer(layer: str, catalog: Catalog) -> tuple[DatasetHandle, str]:
    """Resolve ``<dataset>/<variable>`` (or a bare variable) to a handle."""
    if "," in layer:
        layer = layer.split(",")[0].strip()

    if "/" in layer:
        dataset_id, _, variable = layer.partition("/")
        safe_identifier(dataset_id, field="dataset")
        safe_identifier(variable, field="variable")
        handle = catalog.get(dataset_id)
    else:
        safe_identifier(layer, field="variable")
        handle = catalog.default()
        variable = layer

    handle.require_variable(variable)
    return handle, variable


def _parse_bbox(params: dict[str, str]) -> tuple[float, float, float, float]:
    """Parse BBOX, honouring the CRS axis-order rules of WMS 1.3.0."""
    raw = _require(params, "bbox")
    parts = raw.split(",")
    if len(parts) != 4:
        raise ValidationError("BBOX must contain four comma-separated numbers.", field="bbox")

    try:
        a, b, c, d = (float(p) for p in parts)
    except ValueError:
        raise ValidationError("BBOX values must be numeric.", field="bbox") from None

    crs = (params.get("crs") or params.get("srs") or "CRS:84").upper()
    if crs not in SUPPORTED_CRS:
        raise ValidationError(
            f"Unsupported CRS '{crs}'. Supported: {', '.join(SUPPORTED_CRS)}.", field="crs"
        )

    # In WMS 1.3.0 EPSG:4326 is lat,lon; CRS:84 is lon,lat.
    min_lon, min_lat, max_lon, max_lat = (b, a, d, c) if crs == "EPSG:4326" else (a, b, c, d)

    if min_lon >= max_lon or min_lat >= max_lat:
        raise ValidationError("BBOX minimum must be smaller than maximum.", field="bbox")
    return min_lon, min_lat, max_lon, max_lat


def _dimension(params: dict[str, str], key: str) -> int:
    raw = _require(params, key)
    try:
        value = int(raw)
    except ValueError:
        raise ValidationError(f"'{key.upper()}' must be an integer.", field=key) from None
    if not 1 <= value <= MAX_IMAGE_DIMENSION:
        raise ValidationError(
            f"'{key.upper()}' must be between 1 and {MAX_IMAGE_DIMENSION}.", field=key
        )
    return value


def _resample(
    values: np.ndarray,
    source_lats: np.ndarray,
    source_lons: np.ndarray,
    bbox: tuple[float, float, float, float],
    width: int,
    height: int,
) -> np.ndarray:
    """Nearest-neighbour resample onto the requested image grid.

    Nearest-neighbour is the right default for a scientific WMS: it never
    invents intermediate values, so a forecaster reading a pixel sees a
    value the model actually produced.
    """
    min_lon, min_lat, max_lon, max_lat = bbox

    # Pixel centres, latitude descending so row 0 is the north edge.
    target_lons = np.linspace(min_lon, max_lon, width, endpoint=False) + (max_lon - min_lon) / (2 * width)
    target_lats = np.linspace(max_lat, min_lat, height, endpoint=False) - (max_lat - min_lat) / (2 * height)

    lat_idx = np.clip(np.searchsorted(source_lats, target_lats), 0, source_lats.size - 1)
    lat_idx_prev = np.clip(lat_idx - 1, 0, source_lats.size - 1)
    choose_prev = np.abs(source_lats[lat_idx_prev] - target_lats) < np.abs(
        source_lats[lat_idx] - target_lats
    )
    lat_idx = np.where(choose_prev, lat_idx_prev, lat_idx)

    lon_idx = np.clip(np.searchsorted(source_lons, target_lons), 0, source_lons.size - 1)
    lon_idx_prev = np.clip(lon_idx - 1, 0, source_lons.size - 1)
    choose_prev_lon = np.abs(source_lons[lon_idx_prev] - target_lons) < np.abs(
        source_lons[lon_idx] - target_lons
    )
    lon_idx = np.where(choose_prev_lon, lon_idx_prev, lon_idx)

    resampled = values[np.ix_(lat_idx, lon_idx)]

    # Blank out pixels that fall outside the data's own footprint.
    outside_lat = (target_lats < source_lats.min()) | (target_lats > source_lats.max())
    outside_lon = (target_lons < source_lons.min()) | (target_lons > source_lons.max())
    resampled = resampled.astype("float64", copy=True)
    resampled[outside_lat, :] = np.nan
    resampled[:, outside_lon] = np.nan
    return resampled


@router.get("", summary="OGC WMS 1.3.0 endpoint", response_class=Response)
async def wms(request: Request, catalog: Catalog = Depends(get_catalog)) -> Response:
    """Dispatch to the requested WMS operation."""
    params = _params(request)

    service = (params.get("service") or "WMS").upper()
    if service != "WMS":
        raise ValidationError(f"Unsupported SERVICE '{service}'; only WMS is available.")

    operation = (params.get("request") or "").lower()
    if operation == "getcapabilities":
        return _get_capabilities(request, catalog)
    if operation == "getmap":
        return _get_map(params, catalog)
    if operation == "getlegendgraphic":
        return _get_legend(params, catalog)
    if operation == "getfeatureinfo":
        return _get_feature_info(params, catalog)

    raise ValidationError(
        "REQUEST must be one of GetCapabilities, GetMap, GetLegendGraphic, GetFeatureInfo.",
        field="request",
    )


def _get_capabilities(request: Request, catalog: Catalog) -> Response:
    """Advertise every dataset/variable pair as a WMS layer."""
    base_url = str(request.url).split("?")[0]
    layers: list[str] = []

    for handle in (catalog.get(dataset_id) for dataset_id in catalog.ids()):
        min_lon, min_lat, max_lon, max_lat = handle.bounds()
        times = handle.time_strings()
        depths = handle.depths

        for spec in handle.variable_specs.values():
            dimensions = ""
            if times:
                dimensions += (
                    '        <Dimension name="time" units="ISO8601" default="{0}">{1}</Dimension>\n'
                ).format(escape(times[0]), escape(",".join(times)))
            if depths.size > 1:
                dimensions += (
                    '        <Dimension name="elevation" units="m" default="{0}">{1}</Dimension>\n'
                ).format(
                    float(depths[0]),
                    ",".join(str(round(float(d), 3)) for d in depths),
                )

            default_range = spec.default_range or (0.0, 1.0)
            layers.append(
                f"""      <Layer queryable="1">
        <Name>{escape(handle.id)}/{escape(spec.name)}</Name>
        <Title>{escape(spec.long_name)} ({escape(handle.id)})</Title>
        <Abstract>{escape(spec.standard_name)} in {escape(spec.units)}</Abstract>
        <CRS>CRS:84</CRS>
        <CRS>EPSG:4326</CRS>
        <EX_GeographicBoundingBox>
          <westBoundLongitude>{min_lon}</westBoundLongitude>
          <eastBoundLongitude>{max_lon}</eastBoundLongitude>
          <southBoundLatitude>{min_lat}</southBoundLatitude>
          <northBoundLatitude>{max_lat}</northBoundLatitude>
        </EX_GeographicBoundingBox>
        <BoundingBox CRS="CRS:84" minx="{min_lon}" miny="{min_lat}" maxx="{max_lon}" maxy="{max_lat}"/>
{dimensions}        <Style>
          <Name>default</Name>
          <Title>{escape(spec.default_colormap)} [{default_range[0]}, {default_range[1]}]</Title>
          <LegendURL width="110" height="330">
            <Format>image/png</Format>
            <OnlineResource xmlns:xlink="http://www.w3.org/1999/xlink" xlink:href="{escape(base_url)}?REQUEST=GetLegendGraphic&amp;LAYER={escape(handle.id)}/{escape(spec.name)}"/>
          </LegendURL>
        </Style>
      </Layer>"""
            )

    xml = f"""<?xml version="1.0" encoding="UTF-8"?>
<WMS_Capabilities version="{WMS_VERSION}" xmlns="http://www.opengis.net/wms"
  xmlns:xlink="http://www.w3.org/1999/xlink"
  xmlns:xsi="http://www.w3.org/2001/XMLSchema-instance"
  xsi:schemaLocation="http://www.opengis.net/wms http://schemas.opengis.net/wms/1.3.0/capabilities_1_3_0.xsd">
  <Service>
    <Name>WMS</Name>
    <Title>{escape(settings.app_name)}</Title>
    <Abstract>3-D ocean model and in-situ observation visualisation platform.</Abstract>
    <OnlineResource xlink:href="{escape(base_url)}"/>
    <MaxWidth>{MAX_IMAGE_DIMENSION}</MaxWidth>
    <MaxHeight>{MAX_IMAGE_DIMENSION}</MaxHeight>
  </Service>
  <Capability>
    <Request>
      <GetCapabilities>
        <Format>text/xml</Format>
        <DCPType><HTTP><Get><OnlineResource xlink:href="{escape(base_url)}"/></Get></HTTP></DCPType>
      </GetCapabilities>
      <GetMap>
        <Format>image/png</Format>
        <DCPType><HTTP><Get><OnlineResource xlink:href="{escape(base_url)}"/></Get></HTTP></DCPType>
      </GetMap>
      <GetFeatureInfo>
        <Format>application/json</Format>
        <DCPType><HTTP><Get><OnlineResource xlink:href="{escape(base_url)}"/></Get></HTTP></DCPType>
      </GetFeatureInfo>
    </Request>
    <Exception><Format>XML</Format></Exception>
    <Layer>
      <Title>{escape(settings.app_name)} layers</Title>
      <CRS>CRS:84</CRS>
      <CRS>EPSG:4326</CRS>
{chr(10).join(layers)}
    </Layer>
  </Capability>
</WMS_Capabilities>
"""
    return Response(content=xml, media_type="text/xml")


def _extract_plane(
    params: dict[str, str], catalog: Catalog
) -> tuple[DatasetHandle, str, np.ndarray, np.ndarray, np.ndarray, float, str]:
    """Shared field extraction for GetMap and GetFeatureInfo."""
    handle, variable = _parse_layer(_require(params, "layers") if "layers" in params else _require(params, "query_layers"), catalog)

    elevation = params.get("elevation")
    depth_value = float(handle.depths[handle.depth_index(float(elevation) if elevation else 0.0)])

    time_param = params.get("time")
    time_index = handle.time_index(parse_iso_time(time_param, field="time")) if time_param else 0

    subset = handle.subset(
        variable,
        bbox=handle.bounds(),
        depth_min=depth_value,
        depth_max=depth_value,
        time_indices=[time_index],
    )
    return (
        handle, variable, subset.values[0, 0],
        subset.lats, subset.lons, depth_value, subset.times[0],
    )


def _get_map(params: dict[str, str], catalog: Catalog) -> Response:
    """Render a georeferenced PNG tile."""
    bbox = _parse_bbox(params)
    width = _dimension(params, "width")
    height = _dimension(params, "height")

    image_format = (params.get("format") or "image/png").lower()
    if image_format not in ("image/png", "image/png; mode=32bit", "png"):
        raise ValidationError(
            f"Unsupported FORMAT '{image_format}'; only image/png is available.", field="format"
        )

    handle, variable, plane, lats, lons, _, _ = _extract_plane(params, catalog)
    spec = handle.variable_specs[variable]

    # Requested area entirely outside the data footprint -> transparent tile.
    if bbox[2] < lons.min() or bbox[0] > lons.max() or bbox[3] < lats.min() or bbox[1] > lats.max():
        return Response(content=blank_png(width, height), media_type="image/png")

    resampled = _resample(plane, lats, lons, bbox, width, height)

    default_range = spec.default_range or (float(np.nanmin(plane)), float(np.nanmax(plane)))
    vmin = float(params.get("colorscalemin", default_range[0]))
    vmax = float(params.get("colorscalemax", default_range[1]))
    if vmax <= vmin:
        vmax = vmin + 1.0

    palette = params.get("styles") or params.get("palette") or spec.default_colormap
    if palette in ("", "default"):
        palette = spec.default_colormap

    image = render_png(
        resampled,
        ColorScale(
            name=palette, vmin=vmin, vmax=vmax,
            scale="log" if params.get("logscale", "").lower() == "true" else "linear",
        ),
        flip_vertical=False,  # _resample already emits north-up rows.
    )
    return Response(
        content=image,
        media_type="image/png",
        headers={"Cache-Control": "public, max-age=300"},
    )


def _get_legend(params: dict[str, str], catalog: Catalog) -> Response:
    layer = params.get("layer") or params.get("layers")
    if not layer:
        raise ValidationError("GetLegendGraphic requires a LAYER parameter.", field="layer")

    handle, variable = _parse_layer(layer, catalog)
    spec = handle.variable_specs[variable]
    default_range = spec.default_range or (0.0, 1.0)

    vmin = float(params.get("colorscalemin", default_range[0]))
    vmax = float(params.get("colorscalemax", default_range[1]))
    if vmax <= vmin:
        vmax = vmin + 1.0

    palette = params.get("styles") or params.get("palette") or spec.default_colormap
    if palette in ("", "default"):
        palette = spec.default_colormap

    image = render_legend(
        ColorScale(name=palette, vmin=vmin, vmax=vmax),
        label=f"{spec.long_name} [{spec.units}]",
        horizontal=(params.get("horizontal", "").lower() == "true"),
    )
    return Response(
        content=image, media_type="image/png", headers={"Cache-Control": "public, max-age=3600"}
    )


def _get_feature_info(params: dict[str, str], catalog: Catalog) -> Response:
    """Return the data value under a pixel - the WMS 'click to query' operation."""
    import json

    bbox = _parse_bbox(params)
    width = _dimension(params, "width")
    height = _dimension(params, "height")

    try:
        i = int(_require(params, "i"))
        j = int(_require(params, "j"))
    except ValueError:
        raise ValidationError("'I' and 'J' must be integer pixel coordinates.", field="i") from None

    if not (0 <= i < width and 0 <= j < height):
        raise ValidationError("Pixel coordinates lie outside the requested image.", field="i")

    min_lon, min_lat, max_lon, max_lat = bbox
    lon = min_lon + (i + 0.5) * (max_lon - min_lon) / width
    lat = max_lat - (j + 0.5) * (max_lat - min_lat) / height

    handle, variable, _, _, _, depth_value, time_string = _extract_plane(params, catalog)
    array = handle.ds[variable]
    picked = array.sel(lat=lat, lon=lon, method="nearest")
    if "depth" in picked.dims:
        picked = picked.sel(depth=depth_value, method="nearest")
    if "time" in picked.dims:
        picked = picked.isel(time=0)

    raw = float(np.asarray(picked.values).ravel()[0])
    spec = handle.variable_specs[variable]

    payload: dict[str, Any] = {
        "type": "FeatureCollection",
        "features": [
            {
                "type": "Feature",
                "geometry": {"type": "Point", "coordinates": [round(lon, 5), round(lat, 5)]},
                "properties": {
                    "dataset": handle.id,
                    "variable": variable,
                    "long_name": spec.long_name,
                    "value": None if not np.isfinite(raw) else round(raw, 4),
                    "units": spec.units,
                    "depth_m": depth_value,
                    "time": time_string,
                },
            }
        ],
    }
    return Response(
        content=json.dumps(payload, separators=(",", ":"), allow_nan=False),
        media_type="application/json",
    )
