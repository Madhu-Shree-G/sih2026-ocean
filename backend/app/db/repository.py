"""Query and ingestion helpers for observation data."""

from __future__ import annotations

from datetime import datetime, timezone
from typing import Any, Iterable, Sequence

from sqlalchemy import func, select
from sqlalchemy.orm import Session, selectinload

from app.core.errors import NotFoundError
from app.core.logging import get_logger
from app.data.adapters.base import ProfileRecord
from app.db.models import IngestionRun, Level, Platform, Profile

logger = get_logger(__name__)

MAX_PAGE_SIZE = 2000


def _naive_utc(value: datetime) -> datetime:
    """SQLite stores naive datetimes; normalise everything to naive UTC."""
    if value.tzinfo is not None:
        value = value.astimezone(timezone.utc).replace(tzinfo=None)
    return value


# ---------------------------------------------------------------------------
# Queries
# ---------------------------------------------------------------------------
def list_platforms(
    session: Session,
    *,
    bbox: tuple[float, float, float, float] | None = None,
    platform_types: Sequence[str] | None = None,
    active_since: datetime | None = None,
    limit: int = 500,
    offset: int = 0,
    include_trajectory: bool = False,
) -> list[dict[str, Any]]:
    """List platforms, optionally filtered to a map view."""
    stmt = select(Platform)

    if include_trajectory:
        stmt = stmt.options(selectinload(Platform.profiles))

    if bbox is not None:
        min_lon, min_lat, max_lon, max_lat = bbox
        stmt = stmt.where(
            Platform.last_longitude.between(min_lon, max_lon),
            Platform.last_latitude.between(min_lat, max_lat),
        )
    if platform_types:
        stmt = stmt.where(Platform.platform_type.in_(list(platform_types)))
    if active_since is not None:
        stmt = stmt.where(Platform.last_observation >= _naive_utc(active_since))

    stmt = (
        stmt.order_by(Platform.last_observation.desc().nullslast(), Platform.platform_id)
        .limit(min(limit, MAX_PAGE_SIZE))
        .offset(max(0, offset))
    )
    return [p.to_dict(include_trajectory=include_trajectory) for p in session.scalars(stmt)]


def count_platforms(session: Session) -> int:
    return int(session.scalar(select(func.count()).select_from(Platform)) or 0)


def get_platform(session: Session, platform_id: str) -> Platform:
    stmt = (
        select(Platform)
        .where(Platform.platform_id == platform_id)
        .options(selectinload(Platform.profiles))
    )
    platform = session.scalars(stmt).first()
    if platform is None:
        raise NotFoundError(f"Platform '{platform_id}' was not found.")
    return platform


def list_profiles(
    session: Session,
    *,
    platform_id: str | None = None,
    bbox: tuple[float, float, float, float] | None = None,
    start_time: datetime | None = None,
    end_time: datetime | None = None,
    platform_types: Sequence[str] | None = None,
    limit: int = 500,
    offset: int = 0,
) -> list[Profile]:
    """Query profiles with spatial, temporal and platform filters."""
    stmt = select(Profile).join(Platform).options(selectinload(Profile.platform))

    if platform_id:
        stmt = stmt.where(Platform.platform_id == platform_id)
    if platform_types:
        stmt = stmt.where(Platform.platform_type.in_(list(platform_types)))
    if bbox is not None:
        min_lon, min_lat, max_lon, max_lat = bbox
        stmt = stmt.where(
            Profile.longitude.between(min_lon, max_lon),
            Profile.latitude.between(min_lat, max_lat),
        )
    if start_time is not None:
        stmt = stmt.where(Profile.time >= _naive_utc(start_time))
    if end_time is not None:
        stmt = stmt.where(Profile.time <= _naive_utc(end_time))

    stmt = (
        stmt.order_by(Profile.time.desc())
        .limit(min(limit, MAX_PAGE_SIZE))
        .offset(max(0, offset))
    )
    return list(session.scalars(stmt))


def get_profile(session: Session, profile_id: int) -> Profile:
    stmt = (
        select(Profile)
        .where(Profile.id == profile_id)
        .options(selectinload(Profile.levels), selectinload(Profile.platform))
    )
    profile = session.scalars(stmt).first()
    if profile is None:
        raise NotFoundError(f"Profile {profile_id} was not found.")
    return profile


def latest_profile_per_platform(
    session: Session,
    *,
    bbox: tuple[float, float, float, float] | None = None,
    start_time: datetime | None = None,
    end_time: datetime | None = None,
    limit: int = 400,
) -> list[Profile]:
    """Most recent profile for each platform - the bias-map working set."""
    subquery = (
        select(Profile.platform_pk, func.max(Profile.time).label("latest"))
        .group_by(Profile.platform_pk)
        .subquery()
    )
    stmt = (
        select(Profile)
        .join(
            subquery,
            (Profile.platform_pk == subquery.c.platform_pk)
            & (Profile.time == subquery.c.latest),
        )
        .options(selectinload(Profile.levels), selectinload(Profile.platform))
    )

    if bbox is not None:
        min_lon, min_lat, max_lon, max_lat = bbox
        stmt = stmt.where(
            Profile.longitude.between(min_lon, max_lon),
            Profile.latitude.between(min_lat, max_lat),
        )
    if start_time is not None:
        stmt = stmt.where(Profile.time >= _naive_utc(start_time))
    if end_time is not None:
        stmt = stmt.where(Profile.time <= _naive_utc(end_time))

    return list(session.scalars(stmt.order_by(Profile.time.desc()).limit(limit)))


def statistics(session: Session) -> dict[str, Any]:
    """Headline counts for the dashboard and the health endpoint."""
    platform_count = count_platforms(session)
    profile_count = int(session.scalar(select(func.count()).select_from(Profile)) or 0)
    level_count = int(session.scalar(select(func.count()).select_from(Level)) or 0)

    earliest = session.scalar(select(func.min(Profile.time)))
    latest = session.scalar(select(func.max(Profile.time)))

    by_type = session.execute(
        select(Platform.platform_type, func.count()).group_by(Platform.platform_type)
    ).all()

    return {
        "platforms": platform_count,
        "profiles": profile_count,
        "measurement_levels": level_count,
        "platforms_by_type": {row[0]: int(row[1]) for row in by_type},
        "time_coverage": {
            "start": earliest.strftime("%Y-%m-%dT%H:%M:%SZ") if earliest else None,
            "end": latest.strftime("%Y-%m-%dT%H:%M:%SZ") if latest else None,
        },
    }


# ---------------------------------------------------------------------------
# Ingestion
# ---------------------------------------------------------------------------
def ingest_records(
    session: Session,
    records: Iterable[ProfileRecord],
    *,
    adapter_name: str,
    source: str,
    batch_size: int = 500,
) -> IngestionRun:
    """Persist profile records, upserting platforms and skipping duplicates."""
    run = IngestionRun(adapter=adapter_name, source=source, status="running")
    session.add(run)
    session.flush()

    platform_cache: dict[str, Platform] = {}
    seen_cycles: set[tuple[int, int]] = set()
    ingested = 0

    try:
        for index, record in enumerate(records, start=1):
            platform = platform_cache.get(record.platform_id)
            if platform is None:
                platform = session.scalars(
                    select(Platform).where(Platform.platform_id == record.platform_id)
                ).first()
                if platform is None:
                    platform = Platform(
                        platform_id=record.platform_id,
                        platform_type=record.platform_type,
                        wmo_id=record.extra.get("wmo_id"),
                        project=record.extra.get("project"),
                        institution=record.extra.get("institution"),
                        profile_count=0,
                    )
                    session.add(platform)
                    session.flush()
                platform_cache[record.platform_id] = platform

            cycle_key = (platform.id, record.cycle_number)
            if cycle_key in seen_cycles:
                continue
            seen_cycles.add(cycle_key)

            existing = session.scalars(
                select(Profile.id).where(
                    Profile.platform_pk == platform.id,
                    Profile.cycle_number == record.cycle_number,
                )
            ).first()
            if existing is not None:
                continue

            observation_time = _naive_utc(record.time)
            depths = [d for d in record.depth if d is not None]
            if not depths:
                continue

            surface_index = int(min(range(len(depths)), key=lambda i: depths[i]))

            profile = Profile(
                platform_pk=platform.id,
                cycle_number=record.cycle_number,
                time=observation_time,
                latitude=float(record.latitude),
                longitude=float(record.longitude),
                n_levels=len(depths),
                max_depth=float(max(depths)),
                data_mode=(record.data_mode or "R")[:4],
                quality_flag=record.quality_flag,
                source_file=record.source_file[:255] if record.source_file else None,
                surface_temperature=_safe_index(record.temperature, surface_index),
                surface_salinity=_safe_index(record.salinity, surface_index),
            )
            session.add(profile)
            session.flush()

            session.add_all(
                [
                    Level(
                        profile_pk=profile.id,
                        depth=float(depth),
                        temperature=_safe_index(record.temperature, level_index),
                        salinity=_safe_index(record.salinity, level_index),
                        chlorophyll=_safe_index(record.chlorophyll, level_index),
                        oxygen=_safe_index(record.oxygen, level_index),
                    )
                    for level_index, depth in enumerate(record.depth)
                    if depth is not None
                ]
            )

            platform.profile_count += 1
            if platform.first_observation is None or observation_time < platform.first_observation:
                platform.first_observation = observation_time
            if platform.last_observation is None or observation_time >= platform.last_observation:
                platform.last_observation = observation_time
                platform.last_latitude = float(record.latitude)
                platform.last_longitude = float(record.longitude)

            ingested += 1
            if index % batch_size == 0:
                session.flush()

        run.profiles_ingested = ingested
        run.platforms_touched = len(platform_cache)
        run.status = "succeeded"
        run.finished_at = datetime.now(timezone.utc).replace(tzinfo=None)
        session.flush()
        logger.info(
            "ingestion_complete",
            extra={"adapter": adapter_name, "profiles": ingested, "source": source},
        )
    except Exception as exc:
        run.status = "failed"
        run.message = str(exc)[:1024]
        run.finished_at = datetime.now(timezone.utc).replace(tzinfo=None)
        logger.exception("ingestion_failed", extra={"adapter": adapter_name})
        raise

    return run


def _safe_index(series: Sequence[float | None], index: int) -> float | None:
    if 0 <= index < len(series):
        value = series[index]
        return float(value) if value is not None else None
    return None
