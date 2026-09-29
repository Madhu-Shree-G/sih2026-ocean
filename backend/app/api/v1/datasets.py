"""Dataset catalog endpoints."""

from __future__ import annotations

from typing import Any

from fastapi import APIRouter, Depends, Path

from app.data.catalog import Catalog
from app.security.deps import get_catalog, require_api_key
from app.security.validation import safe_identifier

router = APIRouter(tags=["datasets"], dependencies=[Depends(require_api_key)])


@router.get("", summary="List available datasets")
async def list_datasets(catalog: Catalog = Depends(get_catalog)) -> dict[str, Any]:
    """Full catalog: axes, variables, bounds and display defaults."""
    return {
        "count": len(catalog.ids()),
        "default": catalog.ids()[0] if catalog.ids() else None,
        "datasets": catalog.describe_all(),
    }


@router.get("/plugins", summary="List registered ingestion plugins")
async def list_plugins(catalog: Catalog = Depends(get_catalog)) -> dict[str, Any]:
    """Adapters currently registered.

    Demonstrates the extensibility requirement: dropping a new adapter into
    ``app/data/adapters/`` (or installing a package that advertises the
    ``oceanview.adapters`` entry point) makes it appear here without any
    change to the API layer.
    """
    manifest = catalog.plugin_manifest()
    return {
        "count": len(manifest),
        "plugins": manifest,
        "entry_point_group": "oceanview.adapters",
    }


@router.get("/{dataset_id}", summary="Describe one dataset")
async def describe_dataset(
    dataset_id: str = Path(..., description="Dataset identifier"),
    catalog: Catalog = Depends(get_catalog),
) -> dict[str, Any]:
    safe_identifier(dataset_id, field="dataset_id")
    return catalog.get(dataset_id).describe()


@router.get("/{dataset_id}/variables", summary="List variables in a dataset")
async def list_variables(
    dataset_id: str = Path(..., description="Dataset identifier"),
    catalog: Catalog = Depends(get_catalog),
) -> dict[str, Any]:
    safe_identifier(dataset_id, field="dataset_id")
    handle = catalog.get(dataset_id)
    return {
        "dataset": dataset_id,
        "variables": [
            {
                "name": spec.name,
                "standard_name": spec.standard_name,
                "long_name": spec.long_name,
                "units": spec.units,
                "default_colormap": spec.default_colormap,
                "default_range": list(spec.default_range) if spec.default_range else None,
                "vector_group": spec.vector_group,
            }
            for spec in handle.variable_specs.values()
        ],
    }


@router.get("/{dataset_id}/axes", summary="Axis definitions for a dataset")
async def dataset_axes(
    dataset_id: str = Path(..., description="Dataset identifier"),
    catalog: Catalog = Depends(get_catalog),
) -> dict[str, Any]:
    """Depth levels and timestamps, for populating sliders in the UI."""
    safe_identifier(dataset_id, field="dataset_id")
    handle = catalog.get(dataset_id)
    return {
        "dataset": dataset_id,
        "depths": [float(d) for d in handle.depths],
        "times": handle.time_strings(),
        "lat_range": [float(handle.lats.min()), float(handle.lats.max())],
        "lon_range": [float(handle.lons.min()), float(handle.lons.max())],
        "grid_shape": {
            "lat": int(handle.lats.size),
            "lon": int(handle.lons.size),
            "depth": int(handle.depths.size),
            "time": int(handle.times.size),
        },
    }
