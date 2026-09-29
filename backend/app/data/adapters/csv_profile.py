"""Adapter for delimited-text profile data (CSV / TSV / whitespace).

The problem statement lists "ASCII/text formats" alongside NetCDF.  Ship CTD
casts, mooring exports and quick-look glider dumps routinely arrive this way.

Expected layout - one measurement per row, profiles grouped by platform and
cycle.  Column names are matched case-insensitively against a set of aliases,
so most real-world exports work without editing:

    platform_id,cycle,time,latitude,longitude,depth,temperature,salinity
    CTD_001,1,2024-03-01T06:00:00Z,12.5,72.3,0,29.8,35.1
    CTD_001,1,2024-03-01T06:00:00Z,12.5,72.3,10,29.6,35.1
"""

from __future__ import annotations

import csv
import io
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, ClassVar, Iterator

from app.core.logging import get_logger
from app.data.adapters.base import ObservationAdapter, ProfileRecord, registry

logger = get_logger(__name__)

COLUMN_ALIASES: dict[str, tuple[str, ...]] = {
    "platform_id": ("platform_id", "platform", "platform_number", "wmo", "wmo_id", "id", "station"),
    "cycle": ("cycle", "cycle_number", "profile", "profile_id", "cast"),
    "time": ("time", "date", "datetime", "timestamp", "juld"),
    "latitude": ("latitude", "lat"),
    "longitude": ("longitude", "lon", "long"),
    "depth": ("depth", "pres", "pressure", "z", "depth_m"),
    "temperature": ("temperature", "temp", "t", "potential_temperature"),
    "salinity": ("salinity", "psal", "sal", "s"),
    "chlorophyll": ("chlorophyll", "chla", "chl", "chlorophyll_a"),
    "oxygen": ("oxygen", "doxy", "o2", "dissolved_oxygen"),
}

#: Values that commonly stand in for "missing" in ASCII ocean data.
NULL_TOKENS = frozenset({"", "nan", "na", "n/a", "null", "none", "-999", "-999.0", "-9999", "99999"})


def _to_float(raw: str | None) -> float | None:
    if raw is None:
        return None
    text = raw.strip()
    if text.lower() in NULL_TOKENS:
        return None
    try:
        value = float(text)
    except ValueError:
        return None
    # Sentinel fill values used by several ASCII conventions.
    if value in (-999.0, -9999.0, 99999.0):
        return None
    return value


def _parse_time(raw: str | None) -> datetime | None:
    if not raw:
        return None
    text = raw.strip()
    if text.endswith(("Z", "z")):
        text = text[:-1] + "+00:00"
    for parser in (
        lambda t: datetime.fromisoformat(t),
        lambda t: datetime.strptime(t, "%Y-%m-%d %H:%M:%S"),
        lambda t: datetime.strptime(t, "%Y-%m-%d"),
        lambda t: datetime.strptime(t, "%d/%m/%Y %H:%M"),
        lambda t: datetime.strptime(t, "%Y%m%d"),
    ):
        try:
            parsed = parser(text)
        except (ValueError, TypeError):
            continue
        return parsed.replace(tzinfo=parsed.tzinfo or timezone.utc).astimezone(timezone.utc)
    return None


@registry.register
class CSVProfileAdapter(ObservationAdapter):
    """Read in-situ profiles from delimited text."""

    name: ClassVar[str] = "csv_profile"
    description: ClassVar[str] = (
        "Delimited-text vertical profiles (CSV/TSV). Column names are matched "
        "against a configurable alias table, so most CTD and mooring exports "
        "load without pre-processing."
    )
    suffixes: ClassVar[tuple[str, ...]] = (".csv", ".tsv", ".txt", ".dat")

    def __init__(self, path: Path | str, *, platform_type: str = "ctd") -> None:
        self.path = Path(path)
        self.platform_type = platform_type

    def _resolve_columns(self, header: list[str]) -> dict[str, str]:
        lowered = {name.strip().lower(): name for name in header}
        resolved: dict[str, str] = {}
        for canonical, aliases in COLUMN_ALIASES.items():
            for alias in aliases:
                if alias in lowered:
                    resolved[canonical] = lowered[alias]
                    break
        return resolved

    def _open_reader(self) -> tuple[io.TextIOWrapper, csv.DictReader]:
        handle = open(self.path, "r", encoding="utf-8-sig", newline="")
        sample = handle.read(8192)
        handle.seek(0)
        try:
            dialect = csv.Sniffer().sniff(sample, delimiters=",;\t| ")
        except csv.Error:
            dialect = csv.excel  # type: ignore[assignment]
        reader = csv.DictReader(handle, dialect=dialect, skipinitialspace=True)
        return handle, reader

    def read_profiles(self) -> Iterator[ProfileRecord]:
        handle, reader = self._open_reader()
        try:
            if not reader.fieldnames:
                logger.warning("csv_no_header", extra={"path": str(self.path)})
                return

            columns = self._resolve_columns(list(reader.fieldnames))
            required = {"latitude", "longitude", "depth"}
            missing = required - columns.keys()
            if missing:
                logger.warning(
                    "csv_missing_columns",
                    extra={"path": str(self.path), "missing": sorted(missing)},
                )
                return

            # Group consecutive rows sharing (platform, cycle, time) into one profile.
            current_key: tuple[str, int, str] | None = None
            buffer: list[dict[str, Any]] = []

            def flush() -> ProfileRecord | None:
                if not buffer:
                    return None
                head = buffer[0]
                depths = [row["depth"] for row in buffer if row["depth"] is not None]
                if not depths:
                    return None
                order = sorted(range(len(buffer)), key=lambda i: buffer[i]["depth"] or 0.0)
                ordered = [buffer[i] for i in order]
                return ProfileRecord(
                    platform_id=head["platform_id"],
                    platform_type=self.platform_type,
                    cycle_number=head["cycle"],
                    time=head["time"],
                    latitude=head["latitude"],
                    longitude=head["longitude"],
                    depth=[row["depth"] for row in ordered],
                    temperature=[row["temperature"] for row in ordered],
                    salinity=[row["salinity"] for row in ordered],
                    chlorophyll=[row["chlorophyll"] for row in ordered],
                    oxygen=[row["oxygen"] for row in ordered],
                    source_file=self.path.name,
                )

            for raw_row in reader:
                def cell(key: str) -> str | None:
                    column = columns.get(key)
                    return raw_row.get(column) if column else None

                lat = _to_float(cell("latitude"))
                lon = _to_float(cell("longitude"))
                depth = _to_float(cell("depth"))
                if lat is None or lon is None or depth is None:
                    continue

                platform_id = (cell("platform_id") or self.path.stem).strip()
                cycle_raw = _to_float(cell("cycle"))
                cycle = int(cycle_raw) if cycle_raw is not None else 0
                time_value = _parse_time(cell("time")) or datetime.now(timezone.utc)

                key = (platform_id, cycle, time_value.isoformat())
                if key != current_key:
                    record = flush()
                    if record is not None:
                        yield record
                    buffer = []
                    current_key = key

                buffer.append(
                    {
                        "platform_id": platform_id,
                        "cycle": cycle,
                        "time": time_value,
                        "latitude": lat,
                        "longitude": lon,
                        "depth": depth,
                        "temperature": _to_float(cell("temperature")),
                        "salinity": _to_float(cell("salinity")),
                        "chlorophyll": _to_float(cell("chlorophyll")),
                        "oxygen": _to_float(cell("oxygen")),
                    }
                )

            record = flush()
            if record is not None:
                yield record
        finally:
            handle.close()

    def describe(self) -> dict[str, Any]:
        return {"adapter": self.name, "path": str(self.path), "kind": self.kind}

    def validate(self) -> list[str]:
        if not self.path.exists():
            return [f"File not found: {self.path}"]
        try:
            count = sum(1 for _ in self.read_profiles())
        except Exception as exc:
            return [f"Cannot read profiles: {exc}"]
        return [] if count else ["No usable profiles parsed from file."]
