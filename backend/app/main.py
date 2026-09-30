"""Application factory and ASGI entrypoint.

Run with::

    uvicorn app.main:app --reload
"""

from __future__ import annotations

from contextlib import asynccontextmanager
from pathlib import Path
from typing import AsyncIterator

from fastapi import FastAPI
from fastapi.staticfiles import StaticFiles
from fastapi.middleware.cors import CORSMiddleware
from fastapi.middleware.gzip import GZipMiddleware
from fastapi.middleware.trustedhost import TrustedHostMiddleware
from fastapi.responses import FileResponse, JSONResponse

from app.api.v1.router import api_router
from app.config import settings
from app.core.cache import TTLCache
from app.core.errors import register_exception_handlers
from app.core.logging import configure_logging, get_logger
from app.data.adapters.base import registry
from app.data.catalog import Catalog
from app.db.session import init_db
from app.security.middleware import (
    BodyLimitMiddleware,
    ConcurrencyLimitMiddleware,
    RateLimitMiddleware,
    RequestContextMiddleware,
    SecurityHeadersMiddleware,
)
from app.security.ratelimit import RateLimiter

logger = get_logger(__name__)

DESCRIPTION = """
Web-based interactive 3-D visualisation platform integrating numerical ocean
model output with in-situ observations.

**SIH 2026 - Problem Statement 26067** (Ministry of Earth Sciences / INCOIS)

### What this API provides

* **`/fields/volume`** - quantised 3-D blocks (OCVOL1 binary) for direct
  WebGL `TEXTURE_3D` upload. Depth slicing, isosurface thresholds and
  colorbar edits then run entirely on the GPU with no further requests.
* **`/collocation/profile/{id}`** - the core capability: an observed profile
  and the model's prediction at the same point in space and time, on one
  depth axis, with bias / RMSD / correlation.
* **`/derived/*`** - mixed layer depth, thermocline, anomaly and marine
  heatwave flags, Okubo-Weiss eddy census, and Lagrangian drift for
  search-and-rescue support.
* **`/wms`** - conformant OGC WMS 1.3.0, so QGIS and existing portal tooling
  can consume the same layers.
* **`/datasets/plugins`** - the ingestion adapter registry; new instruments
  are added by writing one class, not by re-engineering the API.
"""


@asynccontextmanager
async def lifespan(app: FastAPI) -> AsyncIterator[None]:
    """Start-up and shut-down: initialise shared state exactly once."""
    configure_logging(json_logs=settings.is_production, level="DEBUG" if settings.debug else "INFO")
    logger.info(
        "starting",
        extra={"version": settings.version, "environment": settings.environment},
    )

    settings.ensure_directories()

    app.state.cache = TTLCache(
        max_entries=settings.cache_max_entries,
        ttl_seconds=settings.cache_ttl_seconds,
        enabled=settings.cache_enabled,
    )
    app.state.rate_limiter = RateLimiter(
        default_per_minute=settings.rate_limit_default_per_minute,
        heavy_per_minute=settings.rate_limit_heavy_per_minute,
        burst_multiplier=settings.rate_limit_burst_multiplier,
        block_seconds=settings.rate_limit_block_seconds,
        max_violations=settings.rate_limit_max_violations,
        enabled=settings.rate_limit_enabled,
    )
    # Only honour X-Forwarded-For when explicitly deployed behind a proxy.
    app.state.trust_proxy_headers = settings.is_production

    try:
        init_db()
    except Exception:
        # A missing database must not prevent the model-field endpoints from
        # serving; readiness will report the degraded state.
        logger.exception("database_init_failed")

    registry.discover()
    catalog = Catalog()
    try:
        catalog.load()
    except Exception:
        logger.exception("catalog_load_failed")
    app.state.catalog = catalog

    if catalog.is_empty():
        logger.warning(
            "no_datasets_found: run 'python scripts/generate_sample_data.py' "
            "to build the demo dataset"
        )

    logger.info(
        "ready",
        extra={
            "datasets": catalog.ids(),
            "plugins": [p["name"] for p in catalog.plugin_manifest()],
        },
    )

    try:
        yield
    finally:
        logger.info("shutting_down")
        catalog.close()
        app.state.cache.clear()


def create_app() -> FastAPI:
    """Build the FastAPI application with the full middleware stack."""
    app = FastAPI(
        title=settings.app_name,
        version=settings.version,
        description=DESCRIPTION,
        lifespan=lifespan,
        docs_url="/docs",
        redoc_url="/redoc",
        openapi_url="/openapi.json",
        contact={"name": "OceanView3D", "url": "https://incois.gov.in"},
        license_info={"name": "MIT"},
    )

    # ---- Middleware --------------------------------------------------------
    # Starlette treats the LAST registered middleware as the OUTERMOST layer,
    # so these are added innermost-first. Effective request order:
    #   RequestContext -> TrustedHost -> CORS -> SecurityHeaders
    #     -> BodyLimit -> RateLimit -> GZip -> Concurrency -> route
    app.add_middleware(
        ConcurrencyLimitMiddleware, max_concurrent=settings.max_concurrent_heavy_requests
    )
    app.add_middleware(GZipMiddleware, minimum_size=1024, compresslevel=5)
    app.add_middleware(RateLimitMiddleware)
    app.add_middleware(
        BodyLimitMiddleware,
        max_body_bytes=settings.max_request_body_bytes,
        max_query_bytes=settings.max_query_string_bytes,
    )
    app.add_middleware(SecurityHeadersMiddleware, enable_hsts=settings.is_production)
    app.add_middleware(
        CORSMiddleware,
        allow_origins=settings.cors_allow_origins,
        allow_credentials=settings.cors_allow_credentials,
        allow_methods=["GET", "POST", "OPTIONS"],
        allow_headers=["Content-Type", "X-API-Key", "X-Admin-Key", "X-Request-ID"],
        expose_headers=[
            "X-Request-ID",
            "X-Response-Time-ms",
            "X-Ocean-Format",
            "X-Ocean-Variable",
            "X-Ocean-Dataset",
            "X-Ocean-Payload-Bytes",
            "X-Ocean-LUT-Size",
            "X-Ocean-LUT-Channels",
            "X-RateLimit-Limit",
            "X-RateLimit-Remaining",
            "Retry-After",
        ],
        max_age=600,
    )
    app.add_middleware(TrustedHostMiddleware, allowed_hosts=settings.allowed_hosts)
    app.add_middleware(RequestContextMiddleware)

    register_exception_handlers(app, debug=settings.debug)
    app.include_router(api_router)

    # Serve the React frontend from the same FastAPI service.
    frontend_dist = Path(__file__).resolve().parents[2] / "frontend" / "dist"
    if frontend_dist.exists():
        app.mount("/assets", StaticFiles(directory=frontend_dist / "assets"), name="assets")
        if (frontend_dist / "cesium").exists():
            app.mount("/cesium", StaticFiles(directory=frontend_dist / "cesium"), name="cesium")
        if (frontend_dist / "cesium").exists():
            app.mount("/cesium", StaticFiles(directory=frontend_dist / "cesium"), name="cesium")

    @app.get("/", include_in_schema=False)
    async def root():
        if frontend_dist.exists():
            return FileResponse(frontend_dist / "index.html")
        return JSONResponse(
            {
                "service": settings.app_name,
                "version": settings.version,
                "docs": "/docs",
                "health": "/api/v1/health",
            }
        )

    @app.get("/{path:path}", include_in_schema=False)
    async def frontend_fallback(path: str):
        if frontend_dist.exists():
            requested = frontend_dist / path
            if requested.is_file():
                return FileResponse(requested)
            return FileResponse(frontend_dist / "index.html")
        return JSONResponse({"detail": "Frontend not built"}, status_code=404)

    return app


app = create_app()
