"""Request bodies for endpoints that take structured input."""

from __future__ import annotations

from pydantic import BaseModel, ConfigDict, Field, field_validator

from app.config import settings


class DriftRequest(BaseModel):
    """Parameters for a Lagrangian drift / search-area simulation."""

    model_config = ConfigDict(extra="forbid")

    lat: float = Field(..., ge=-90, le=90, description="Last known latitude")
    lon: float = Field(..., ge=-360, le=360, description="Last known longitude")
    dataset: str | None = Field(None, max_length=64)
    depth: float = Field(0.0, ge=0, le=11000, description="Drift depth in metres")
    time_index: int | None = Field(None, ge=0, description="Model timestep to advect with")

    duration_hours: float = Field(48.0, gt=0, description="Forecast horizon")
    n_particles: int = Field(500, ge=1, description="Particles in the cloud")
    timestep_minutes: float = Field(30.0, ge=1, le=180)
    initial_spread_km: float = Field(2.0, ge=0, le=200, description="Position uncertainty")
    diffusion_m2_s: float = Field(10.0, ge=0, le=1000, description="Sub-grid turbulent diffusion")

    windage: float = Field(
        0.0, ge=0, le=0.1,
        description="Fraction of wind speed transferred to the object (0.00-0.05 typical)",
    )
    wind_u: float = Field(0.0, ge=-100, le=100, description="Eastward wind, m/s")
    wind_v: float = Field(0.0, ge=-100, le=100, description="Northward wind, m/s")
    seed: int = Field(12345, ge=0, le=2**31 - 1, description="RNG seed for reproducibility")

    @field_validator("duration_hours")
    @classmethod
    def _cap_duration(cls, value: float) -> float:
        if value > settings.max_drift_hours:
            raise ValueError(
                f"duration_hours must not exceed {settings.max_drift_hours}."
            )
        return value

    @field_validator("n_particles")
    @classmethod
    def _cap_particles(cls, value: int) -> int:
        if value > settings.max_drift_particles:
            raise ValueError(
                f"n_particles must not exceed {settings.max_drift_particles}."
            )
        return value
