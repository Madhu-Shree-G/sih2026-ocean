"""Application configuration.

All tunables live here and can be overridden through environment variables
or a local ``.env`` file.  Limits that protect the service from resource
exhaustion are deliberately grouped under the ``Security / firewall`` block
so they can be audited in one place.
"""

from __future__ import annotations

from functools import lru_cache
from pathlib import Path

from pydantic import Field, field_validator
from pydantic_settings import BaseSettings, SettingsConfigDict

BASE_DIR = Path(__file__).resolve().parent.parent


class Settings(BaseSettings):
    model_config = SettingsConfigDict(
        env_file=str(BASE_DIR / ".env"),
        env_file_encoding="utf-8",
        env_prefix="OCEANVIEW_",
        extra="ignore",
    )

    # ---- Service identity -------------------------------------------------
    app_name: str = "OceanView3D API"
    version: str = "1.0.0"
    environment: str = Field(default="development")
    debug: bool = False

    # ---- Paths ------------------------------------------------------------
    data_dir: Path = BASE_DIR / "data"
    zarr_dir: Path = BASE_DIR / "data" / "zarr"
    raw_dir: Path = BASE_DIR / "data" / "raw"
    cache_dir: Path = BASE_DIR / "data" / "cache"
    database_url: str = f"sqlite:///{(BASE_DIR / 'data' / 'oceanview.db').as_posix()}"

    # ---- Geographic domain (Indian EEZ + surrounding basins) --------------
    domain_lat_min: float = -10.0
    domain_lat_max: float = 26.0
    domain_lon_min: float = 55.0
    domain_lon_max: float = 100.0

    # =======================================================================
    # Security / firewall
    # =======================================================================
    # CORS: explicit allow-list, never "*" when credentials are enabled.
    cors_allow_origins: list[str] = [
        "http://localhost:5173",
        "http://localhost:3000",
        "http://127.0.0.1:5173",
        "http://127.0.0.1:3000",
    ]
    cors_allow_credentials: bool = False

    # Trusted Host protection (Host header / DNS-rebinding defence).
    allowed_hosts: list[str] = ["localhost", "127.0.0.1", "testserver", "*.incois.gov.in", "*.onrender.com"]

    # Token-bucket rate limiting, per client IP.
    rate_limit_enabled: bool = True
    rate_limit_default_per_minute: int = 240
    rate_limit_heavy_per_minute: int = 40      # volume / WMS / drift endpoints
    rate_limit_burst_multiplier: float = 1.5
    rate_limit_block_seconds: int = 30         # cool-down after sustained abuse
    rate_limit_max_violations: int = 12        # violations before cool-down

    # Request hardening.
    max_request_body_bytes: int = 1 * 1024 * 1024      # 1 MiB
    max_query_string_bytes: int = 4096
    max_concurrent_heavy_requests: int = 8
    request_timeout_seconds: float = 60.0

    # Payload ceilings - the real DoS surface for a gridded-data API.
    max_volume_cells: int = 40_000_000     # nlat*nlon*ndepth*ntime before subsampling
    max_volume_bytes: int = 96 * 1024 * 1024
    max_timesteps_per_request: int = 60
    max_transect_points: int = 512
    max_drift_particles: int = 5000
    max_drift_hours: int = 240

    # Optional shared-secret gate for administrative routes.
    admin_api_key: str | None = None
    require_api_key: bool = False
    api_key: str | None = None

    # Response cache.
    cache_enabled: bool = True
    cache_max_entries: int = 128
    cache_ttl_seconds: int = 900

    @field_validator("cors_allow_origins", "allowed_hosts", mode="before")
    @classmethod
    def _split_csv(cls, v: object) -> object:
        """Allow ``A,B,C`` in environment variables as well as JSON lists."""
        if isinstance(v, str):
            stripped = v.strip()
            if stripped.startswith("["):
                return v
            return [item.strip() for item in stripped.split(",") if item.strip()]
        return v

    @property
    def is_production(self) -> bool:
        return self.environment.lower() in {"production", "prod"}

    def ensure_directories(self) -> None:
        for path in (self.data_dir, self.zarr_dir, self.raw_dir, self.cache_dir):
            path.mkdir(parents=True, exist_ok=True)


@lru_cache(maxsize=1)
def get_settings() -> Settings:
    settings = Settings()
    settings.ensure_directories()
    return settings


settings = get_settings()
