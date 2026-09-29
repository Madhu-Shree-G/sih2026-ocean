"""Plugin contract for data ingestion.

The problem statement calls out that existing tools cannot absorb a new
instrument or model variable "without significant re-engineering".  The
answer here is a narrow interface plus a registry: to teach the platform
about a new sensor you write one subclass and register it, and nothing in
the API layer changes.

Adapters are discovered from two places:

1. Modules inside ``app.data.adapters`` (built-in adapters).
2. Any installed distribution exposing the ``oceanview.adapters`` entry
   point group (third-party plugins, no fork required).
"""

from __future__ import annotations

import abc
import importlib
import pkgutil
from dataclasses import dataclass, field
from datetime import datetime
from pathlib import Path
from typing import Any, ClassVar, Iterator, Literal

from app.core.logging import get_logger

logger = get_logger(__name__)

AdapterKind = Literal["model", "observation"]


@dataclass(slots=True)
class ProfileRecord:
    """One vertical profile from an autonomous or ship-borne instrument.

    Field names follow CF/Argo conventions so that records coming from an
    Argo NetCDF file, a glider mission and a CTD cast are interchangeable
    downstream.
    """

    platform_id: str
    platform_type: str
    cycle_number: int
    time: datetime
    latitude: float
    longitude: float
    depth: list[float]
    temperature: list[float | None] = field(default_factory=list)
    salinity: list[float | None] = field(default_factory=list)
    chlorophyll: list[float | None] = field(default_factory=list)
    oxygen: list[float | None] = field(default_factory=list)
    quality_flag: int = 1
    data_mode: str = "R"
    source_file: str = ""
    extra: dict[str, Any] = field(default_factory=dict)

    def __post_init__(self) -> None:
        n = len(self.depth)
        # Normalise every measured series to the length of the depth axis so
        # consumers never have to defend against ragged arrays.
        for name in ("temperature", "salinity", "chlorophyll", "oxygen"):
            series = list(getattr(self, name) or [])
            if len(series) < n:
                series.extend([None] * (n - len(series)))
            elif len(series) > n:
                series = series[:n]
            setattr(self, name, series)


@dataclass(slots=True)
class VariableSpec:
    """CF-style description of a model variable exposed by an adapter."""

    name: str
    standard_name: str
    long_name: str
    units: str
    default_colormap: str = "viridis"
    default_range: tuple[float, float] | None = None
    is_vector_component: bool = False
    vector_group: str | None = None


class DataSourceAdapter(abc.ABC):
    """Base class for every ingestion plugin."""

    #: Unique registry key.
    name: ClassVar[str] = "base"
    #: Human-readable description shown in the API catalog.
    description: ClassVar[str] = ""
    #: Whether this adapter yields gridded model fields or point observations.
    kind: ClassVar[AdapterKind] = "model"
    #: File suffixes this adapter is willing to try.
    suffixes: ClassVar[tuple[str, ...]] = ()

    @classmethod
    def can_handle(cls, path: Path) -> bool:
        """Return ``True`` when this adapter recognises ``path``."""
        return path.suffix.lower() in cls.suffixes

    @abc.abstractmethod
    def describe(self) -> dict[str, Any]:
        """Return catalog metadata for this source."""

    def validate(self) -> list[str]:
        """Return a list of human-readable problems, empty when healthy."""
        return []


class ModelAdapter(DataSourceAdapter):
    """Adapter that exposes a gridded, depth-resolved model field."""

    kind: ClassVar[AdapterKind] = "model"

    @abc.abstractmethod
    def open_dataset(self):
        """Return an :class:`xarray.Dataset` with CF-compliant coordinates."""

    @abc.abstractmethod
    def variables(self) -> list[VariableSpec]:
        """Return the variables this source publishes."""


class ObservationAdapter(DataSourceAdapter):
    """Adapter that yields in-situ vertical profiles."""

    kind: ClassVar[AdapterKind] = "observation"

    @abc.abstractmethod
    def read_profiles(self) -> Iterator[ProfileRecord]:
        """Yield every profile contained in the source."""


class AdapterRegistry:
    """Registry of available adapters, keyed by :attr:`DataSourceAdapter.name`."""

    def __init__(self) -> None:
        self._adapters: dict[str, type[DataSourceAdapter]] = {}
        self._loaded = False

    def register(self, adapter_cls: type[DataSourceAdapter]) -> type[DataSourceAdapter]:
        key = adapter_cls.name
        if key in self._adapters and self._adapters[key] is not adapter_cls:
            logger.warning("adapter_override", extra={"adapter": key})
        self._adapters[key] = adapter_cls
        return adapter_cls

    def discover(self, *, force: bool = False) -> None:
        """Import built-in adapter modules and any installed entry points."""
        if self._loaded and not force:
            return
        self._loaded = True

        package = importlib.import_module("app.data.adapters")
        for module_info in pkgutil.iter_modules(package.__path__):
            if module_info.name in {"base", "__init__"}:
                continue
            try:
                importlib.import_module(f"app.data.adapters.{module_info.name}")
            except Exception:  # pragma: no cover - a bad plugin must not kill boot
                logger.exception("adapter_import_failed", extra={"module": module_info.name})

        try:
            from importlib.metadata import entry_points

            for ep in entry_points(group="oceanview.adapters"):
                try:
                    self.register(ep.load())
                except Exception:  # pragma: no cover
                    logger.exception("adapter_entrypoint_failed", extra={"entrypoint": ep.name})
        except Exception:  # pragma: no cover
            logger.debug("entry_point_discovery_unavailable")

    def get(self, name: str) -> type[DataSourceAdapter] | None:
        self.discover()
        return self._adapters.get(name)

    def for_path(self, path: Path, *, kind: AdapterKind | None = None) -> type[DataSourceAdapter] | None:
        self.discover()
        for adapter_cls in self._adapters.values():
            if kind is not None and adapter_cls.kind != kind:
                continue
            try:
                if adapter_cls.can_handle(path):
                    return adapter_cls
            except Exception:  # pragma: no cover
                logger.exception("adapter_can_handle_failed", extra={"adapter": adapter_cls.name})
        return None

    def all(self) -> dict[str, type[DataSourceAdapter]]:
        self.discover()
        return dict(self._adapters)

    def manifest(self) -> list[dict[str, Any]]:
        """Machine-readable listing of registered plugins for the API."""
        self.discover()
        return sorted(
            (
                {
                    "name": cls.name,
                    "kind": cls.kind,
                    "description": cls.description,
                    "suffixes": list(cls.suffixes),
                }
                for cls in self._adapters.values()
            ),
            key=lambda item: (item["kind"], item["name"]),
        )


registry = AdapterRegistry()
