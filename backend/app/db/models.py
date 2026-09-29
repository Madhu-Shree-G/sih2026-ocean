"""SQLAlchemy models for in-situ observations.

Gridded model output lives in Zarr; point observations live here.  The split
matters: floats and gliders are irregular in space and time, so they need a
spatial/temporal index rather than an array store.

The schema is deliberately generic - an Argo float, a glider mission and a
shipboard CTD cast all land in the same three tables, distinguished only by
``Platform.platform_type``.  Adding a mooring or an ADCP therefore needs a
new adapter, not a new table.
"""

from __future__ import annotations

from datetime import datetime, timezone
from typing import Any

from sqlalchemy import (
    Float,
    ForeignKey,
    Index,
    Integer,
    String,
    UniqueConstraint,
    func,
)
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column, relationship
from sqlalchemy.types import DateTime


class Base(DeclarativeBase):
    pass


class Platform(Base):
    """An autonomous instrument or observing station."""

    __tablename__ = "platforms"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    platform_id: Mapped[str] = mapped_column(String(64), unique=True, index=True)
    platform_type: Mapped[str] = mapped_column(String(32), index=True, default="argo_float")
    wmo_id: Mapped[str | None] = mapped_column(String(32), nullable=True)
    project: Mapped[str | None] = mapped_column(String(128), nullable=True)
    institution: Mapped[str | None] = mapped_column(String(128), nullable=True)

    first_observation: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)
    last_observation: Mapped[datetime | None] = mapped_column(DateTime, index=True, nullable=True)
    last_latitude: Mapped[float | None] = mapped_column(Float, nullable=True)
    last_longitude: Mapped[float | None] = mapped_column(Float, nullable=True)
    profile_count: Mapped[int] = mapped_column(Integer, default=0)
    status: Mapped[str] = mapped_column(String(16), default="active")

    profiles: Mapped[list["Profile"]] = relationship(
        back_populates="platform",
        cascade="all, delete-orphan",
        order_by="Profile.time",
    )

    def to_dict(self, *, include_trajectory: bool = False) -> dict[str, Any]:
        payload: dict[str, Any] = {
            "platform_id": self.platform_id,
            "platform_type": self.platform_type,
            "wmo_id": self.wmo_id,
            "project": self.project,
            "institution": self.institution,
            "status": self.status,
            "profile_count": self.profile_count,
            "first_observation": _iso(self.first_observation),
            "last_observation": _iso(self.last_observation),
            "last_position": (
                {"lat": self.last_latitude, "lon": self.last_longitude}
                if self.last_latitude is not None
                else None
            ),
        }
        if include_trajectory:
            payload["trajectory"] = [
                {
                    "cycle": p.cycle_number,
                    "time": _iso(p.time),
                    "lat": p.latitude,
                    "lon": p.longitude,
                    "profile_id": p.id,
                }
                for p in self.profiles
            ]
        return payload


class Profile(Base):
    """One vertical cast: a single dive-and-surface cycle."""

    __tablename__ = "profiles"
    __table_args__ = (
        UniqueConstraint("platform_pk", "cycle_number", name="uq_platform_cycle"),
        Index("ix_profiles_space", "latitude", "longitude"),
        Index("ix_profiles_time_space", "time", "latitude", "longitude"),
    )

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    platform_pk: Mapped[int] = mapped_column(
        ForeignKey("platforms.id", ondelete="CASCADE"), index=True
    )
    cycle_number: Mapped[int] = mapped_column(Integer, default=0)
    time: Mapped[datetime] = mapped_column(DateTime, index=True)
    latitude: Mapped[float] = mapped_column(Float)
    longitude: Mapped[float] = mapped_column(Float)

    n_levels: Mapped[int] = mapped_column(Integer, default=0)
    max_depth: Mapped[float] = mapped_column(Float, default=0.0)
    data_mode: Mapped[str] = mapped_column(String(4), default="R")
    quality_flag: Mapped[int] = mapped_column(Integer, default=1)
    source_file: Mapped[str | None] = mapped_column(String(255), nullable=True)

    #: Denormalised surface values - lets the map colour thousands of markers
    #: without touching the levels table.
    surface_temperature: Mapped[float | None] = mapped_column(Float, nullable=True)
    surface_salinity: Mapped[float | None] = mapped_column(Float, nullable=True)

    platform: Mapped[Platform] = relationship(back_populates="profiles")
    levels: Mapped[list["Level"]] = relationship(
        back_populates="profile",
        cascade="all, delete-orphan",
        order_by="Level.depth",
        lazy="selectin",
    )

    def to_summary(self) -> dict[str, Any]:
        return {
            "profile_id": self.id,
            "platform_id": self.platform.platform_id if self.platform else None,
            "platform_type": self.platform.platform_type if self.platform else None,
            "cycle": self.cycle_number,
            "time": _iso(self.time),
            "location": {"lat": self.latitude, "lon": self.longitude},
            "n_levels": self.n_levels,
            "max_depth_m": self.max_depth,
            "data_mode": self.data_mode,
            "surface_temperature": self.surface_temperature,
            "surface_salinity": self.surface_salinity,
        }

    def to_dict(self) -> dict[str, Any]:
        payload = self.to_summary()
        payload["measurements"] = {
            "depth_m": [level.depth for level in self.levels],
            "temperature": [level.temperature for level in self.levels],
            "salinity": [level.salinity for level in self.levels],
            "chlorophyll": [level.chlorophyll for level in self.levels],
            "oxygen": [level.oxygen for level in self.levels],
        }
        payload["source_file"] = self.source_file
        return payload

    def series(self, variable: str) -> tuple[list[float], list[float | None]]:
        """Return ``(depths, values)`` for one measured variable."""
        column = {
            "temperature": "temperature",
            "salinity": "salinity",
            "chlorophyll": "chlorophyll",
            "oxygen": "oxygen",
        }.get(variable)
        if column is None:
            return [], []
        return (
            [level.depth for level in self.levels],
            [getattr(level, column) for level in self.levels],
        )


class Level(Base):
    """One measurement level within a profile."""

    __tablename__ = "levels"
    __table_args__ = (Index("ix_levels_profile_depth", "profile_pk", "depth"),)

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    profile_pk: Mapped[int] = mapped_column(
        ForeignKey("profiles.id", ondelete="CASCADE"), index=True
    )
    depth: Mapped[float] = mapped_column(Float)
    temperature: Mapped[float | None] = mapped_column(Float, nullable=True)
    salinity: Mapped[float | None] = mapped_column(Float, nullable=True)
    chlorophyll: Mapped[float | None] = mapped_column(Float, nullable=True)
    oxygen: Mapped[float | None] = mapped_column(Float, nullable=True)

    profile: Mapped[Profile] = relationship(back_populates="levels")


class IngestionRun(Base):
    """Audit trail for every ingestion, so a bad load can be traced."""

    __tablename__ = "ingestion_runs"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    started_at: Mapped[datetime] = mapped_column(DateTime, default=func.now())
    finished_at: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)
    adapter: Mapped[str] = mapped_column(String(64))
    source: Mapped[str] = mapped_column(String(512))
    profiles_ingested: Mapped[int] = mapped_column(Integer, default=0)
    platforms_touched: Mapped[int] = mapped_column(Integer, default=0)
    status: Mapped[str] = mapped_column(String(16), default="running")
    message: Mapped[str | None] = mapped_column(String(1024), nullable=True)

    def to_dict(self) -> dict[str, Any]:
        return {
            "id": self.id,
            "adapter": self.adapter,
            "source": self.source,
            "started_at": _iso(self.started_at),
            "finished_at": _iso(self.finished_at),
            "profiles_ingested": self.profiles_ingested,
            "platforms_touched": self.platforms_touched,
            "status": self.status,
            "message": self.message,
        }


def _iso(value: datetime | None) -> str | None:
    if value is None:
        return None
    if value.tzinfo is None:
        value = value.replace(tzinfo=timezone.utc)
    return value.astimezone(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")
