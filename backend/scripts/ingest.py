"""Ingest real ocean data into the platform.

This is the bridge from the synthetic demo to operational data.  Adapters are
selected automatically from the file, so the same command handles CMEMS
NetCDF, an Argo GDAC profile file and a CTD text export.

Model fields (converted to a chunked Zarr store)::

    python scripts/ingest.py model path/to/glorys.nc --id glorys_arabian_sea
    python scripts/ingest.py model path/to/*.nc --id indofos --concat-dim time

In-situ observations (loaded into the database)::

    python scripts/ingest.py observations data/raw/sample_argo_profiles.nc
    python scripts/ingest.py observations data/raw/sample_ctd_casts.csv --type ctd
    python scripts/ingest.py observations path/to/argo_dir/ --pattern "*.nc"

Inspect what an adapter makes of a file without writing anything::

    python scripts/ingest.py inspect path/to/file.nc

Where to get real data
----------------------
* CMEMS GLORYS / Global Analysis-Forecast - marine.copernicus.eu (registration)
* HYCOM GOFS 3.1 - open OPeNDAP, no registration
* Argo GDAC - data-argo.ifremer.fr
* INCOIS ERDDAP / Live Access Server - incois.gov.in
"""

from __future__ import annotations

import argparse
import shutil
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

import xarray as xr  # noqa: E402

from app.config import settings  # noqa: E402
from app.core.logging import configure_logging, get_logger  # noqa: E402
from app.data.adapters.base import registry  # noqa: E402
from app.data.conventions import attach_cf_attributes, normalise_dataset  # noqa: E402
from app.db import repository  # noqa: E402
from app.db.session import init_db, session_scope  # noqa: E402
from app.security.validation import safe_identifier  # noqa: E402

logger = get_logger("ingest")

PLATFORM_TYPES = ("argo_float", "glider", "ctd", "mooring", "adcp", "drifter")


def _resolve_sources(path: Path, pattern: str) -> list[Path]:
    if path.is_dir():
        return sorted(path.glob(pattern))
    return [path] if path.exists() else []


# ---------------------------------------------------------------------------
# Model ingestion
# ---------------------------------------------------------------------------
def ingest_model(args: argparse.Namespace) -> int:
    sources = _resolve_sources(Path(args.source), args.pattern)
    if not sources:
        logger.error("no_source_files", extra={"source": args.source})
        return 1

    dataset_id = safe_identifier(args.id, field="id")
    target = settings.zarr_dir / f"{dataset_id}.zarr"

    if target.exists() and not args.overwrite:
        logger.error(
            "target_exists", extra={"path": str(target), "hint": "pass --overwrite"}
        )
        return 1

    logger.info("opening", extra={"files": len(sources)})
    if len(sources) == 1:
        dataset = xr.open_dataset(sources[0], decode_timedelta=True)
    else:
        dataset = xr.open_mfdataset(
            [str(p) for p in sources],
            combine="by_coords" if args.concat_dim is None else "nested",
            concat_dim=args.concat_dim,
            decode_timedelta=True,
        )

    try:
        dataset = attach_cf_attributes(normalise_dataset(dataset))

        missing = [axis for axis in ("lat", "lon") if axis not in dataset.coords]
        if missing:
            logger.error(
                "missing_coordinates",
                extra={"missing": missing, "found": list(dataset.coords)},
            )
            return 1

        if args.variables:
            keep = [v for v in args.variables if v in dataset.data_vars]
            unknown = set(args.variables) - set(keep)
            if unknown:
                logger.warning("variables_not_found", extra={"variables": sorted(unknown)})
            if not keep:
                logger.error("no_requested_variables_present")
                return 1
            dataset = dataset[keep]

        if args.bbox:
            min_lon, min_lat, max_lon, max_lat = (float(v) for v in args.bbox.split(","))
            dataset = dataset.sel(
                lat=slice(min_lat, max_lat), lon=slice(min_lon, max_lon)
            )

        if args.depth_max is not None and "depth" in dataset.coords:
            dataset = dataset.sel(depth=slice(0, args.depth_max))

        for axis in ("lat", "lon", "depth", "time"):
            if axis in dataset.sizes and dataset.sizes[axis] == 0:
                logger.error("empty_after_subsetting", extra={"axis": axis})
                return 1

        chunks: dict[str, int] = {}
        if "time" in dataset.sizes:
            chunks["time"] = 1
        if "depth" in dataset.sizes:
            chunks["depth"] = int(dataset.sizes["depth"])
        chunks["lat"] = min(args.chunk, int(dataset.sizes.get("lat", args.chunk)))
        chunks["lon"] = min(args.chunk, int(dataset.sizes.get("lon", args.chunk)))

        if target.exists():
            shutil.rmtree(target)

        logger.info("writing_zarr", extra={"path": str(target), "sizes": dict(dataset.sizes)})
        dataset.chunk(chunks).to_zarr(target, mode="w", consolidated=True)
    finally:
        dataset.close()

    size_mb = sum(f.stat().st_size for f in target.rglob("*") if f.is_file()) / 1048576
    print(f"\nWrote {target}  ({size_mb:.1f} MiB)")
    print("Reload the running service with:")
    print('  curl -X POST -H "X-Admin-Key: $OCEANVIEW_ADMIN_API_KEY" '
          "http://localhost:8000/api/v1/admin/catalog/reload\n")
    return 0


# ---------------------------------------------------------------------------
# Observation ingestion
# ---------------------------------------------------------------------------
def ingest_observations(args: argparse.Namespace) -> int:
    sources = _resolve_sources(Path(args.source), args.pattern)
    if not sources:
        logger.error("no_source_files", extra={"source": args.source})
        return 1

    registry.discover()
    init_db()

    total = 0
    failures = 0

    for source in sources:
        adapter_cls = registry.for_path(source, kind="observation")
        if adapter_cls is None:
            logger.warning("no_adapter", extra={"file": source.name})
            failures += 1
            continue

        try:
            adapter = adapter_cls(source, platform_type=args.type)  # type: ignore[call-arg]
        except TypeError:
            adapter = adapter_cls(source)  # type: ignore[call-arg]

        problems = adapter.validate()
        if problems:
            logger.warning(
                "adapter_validation_failed",
                extra={"file": source.name, "problems": problems},
            )
            failures += 1
            continue

        try:
            with session_scope() as session:
                run = repository.ingest_records(
                    session,
                    adapter.read_profiles(),  # type: ignore[attr-defined]
                    adapter_name=adapter_cls.name,
                    source=str(source),
                )
                total += run.profiles_ingested
                logger.info(
                    "file_ingested",
                    extra={"file": source.name, "profiles": run.profiles_ingested},
                )
        except Exception:
            logger.exception("file_failed", extra={"file": source.name})
            failures += 1

    print(f"\nIngested {total} profiles from {len(sources) - failures}/{len(sources)} files.")
    if failures:
        print(f"{failures} file(s) could not be read - see the log above.")
    return 1 if failures == len(sources) else 0


# ---------------------------------------------------------------------------
# Inspection
# ---------------------------------------------------------------------------
def inspect(args: argparse.Namespace) -> int:
    source = Path(args.source)
    if not source.exists():
        logger.error("file_not_found", extra={"path": str(source)})
        return 1

    registry.discover()
    print(f"\nFile: {source}")
    print(f"Size: {source.stat().st_size / 1048576:.2f} MiB" if source.is_file() else "Directory")

    for kind in ("model", "observation"):
        adapter_cls = registry.for_path(source, kind=kind)  # type: ignore[arg-type]
        print(f"\n  {kind:<12} adapter: {adapter_cls.name if adapter_cls else '(none matched)'}")

        if adapter_cls is None:
            continue

        try:
            adapter = adapter_cls(source)  # type: ignore[call-arg]
            problems = adapter.validate()
            if problems:
                print(f"  {'':<12} issues : {problems}")
                continue

            description = adapter.describe()
            for key, value in description.items():
                if key == "attrs":
                    continue
                text = str(value)
                print(f"  {'':<12} {key:<8}: {text[:110]}")
        except Exception as exc:  # noqa: BLE001
            print(f"  {'':<12} error  : {type(exc).__name__}: {exc}")

    print("\nRegistered adapters:")
    for entry in registry.manifest():
        print(f"  {entry['kind']:<12} {entry['name']:<16} {entry['suffixes']}")
    print()
    return 0


def main() -> int:
    parser = argparse.ArgumentParser(
        description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter
    )
    subparsers = parser.add_subparsers(dest="command", required=True)

    model = subparsers.add_parser("model", help="Ingest gridded model output")
    model.add_argument("source", help="NetCDF file, Zarr store, or directory")
    model.add_argument("--id", required=True, help="Dataset identifier")
    model.add_argument("--pattern", default="*.nc", help="Glob when source is a directory")
    model.add_argument("--variables", nargs="*", help="Restrict to these variables")
    model.add_argument("--bbox", help="min_lon,min_lat,max_lon,max_lat")
    model.add_argument("--depth-max", type=float, help="Discard levels below this depth")
    model.add_argument("--concat-dim", help="Dimension to concatenate multiple files along")
    model.add_argument("--chunk", type=int, default=64, help="Horizontal chunk size")
    model.add_argument("--overwrite", action="store_true")
    model.set_defaults(func=ingest_model)

    observations = subparsers.add_parser("observations", help="Ingest in-situ profiles")
    observations.add_argument("source", help="File or directory")
    observations.add_argument("--pattern", default="*", help="Glob when source is a directory")
    observations.add_argument(
        "--type", default="argo_float", choices=PLATFORM_TYPES, help="Platform type label"
    )
    observations.set_defaults(func=ingest_observations)

    inspector = subparsers.add_parser("inspect", help="Report what adapters make of a file")
    inspector.add_argument("source")
    inspector.set_defaults(func=inspect)

    args = parser.parse_args()
    configure_logging(level="INFO")
    settings.ensure_directories()
    return int(args.func(args))


if __name__ == "__main__":
    raise SystemExit(main())
