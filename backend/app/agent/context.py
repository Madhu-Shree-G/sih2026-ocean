"""What Deep can see.

The client sends a snapshot of the interface with every utterance. This is
what "screen awareness" actually means here: Deep is not guessing at state or
holding a stale copy of it, and it can resolve relative commands ("go
deeper", "next frame", "compare this float") against what the user is
literally looking at right now.

Everything is optional. A partial context degrades Deep's answers, it never
breaks them.
"""

from __future__ import annotations

from typing import Any, Literal

from pydantic import BaseModel, ConfigDict, Field


class LayerState(BaseModel):
    model_config = ConfigDict(extra="ignore")

    id: str
    label: str = ""
    enabled: bool = False
    opacity: float = 1.0


class CameraState(BaseModel):
    model_config = ConfigDict(extra="ignore")

    lat: float | None = None
    lon: float | None = None
    height_km: float | None = None


class AlertState(BaseModel):
    model_config = ConfigDict(extra="ignore")

    id: str = ""
    title: str = ""
    location: str = ""
    severity: str = "low"
    kind: str = ""
    detail: str | None = None
    lat: float | None = None
    lon: float | None = None


class SelectionState(BaseModel):
    """The platform whose profile is open in the right-hand panel."""

    model_config = ConfigDict(extra="ignore")

    profile_id: int | None = None
    platform_id: str | None = None
    platform_type: str | None = None
    lat: float | None = None
    lon: float | None = None
    #: Collocation metrics, when a comparison is on screen.
    variable: str | None = None
    units: str | None = None
    bias: float | None = None
    rmsd: float | None = None
    mae: float | None = None
    correlation: float | None = None
    max_abs_difference: float | None = None
    depth_of_max_difference_m: float | None = None
    n_levels: int | None = None


class ScreenContext(BaseModel):
    """A snapshot of the interface at the moment the user spoke."""

    model_config = ConfigDict(extra="ignore")

    # ---- Dataset and field ----------------------------------------------
    dataset: str | None = None
    variable: str = "temperature"
    variable_units: str | None = None
    available_variables: list[str] = Field(default_factory=list)

    depth_index: int = 0
    depth_m: float = 0.0
    available_depths: list[float] = Field(default_factory=list)

    time_index: int = 0
    time: str | None = None
    available_times: list[str] = Field(default_factory=list)

    # ---- Presentation ----------------------------------------------------
    colormap: str = "thermal"
    color_range: tuple[float, float] | None = None
    data_range: tuple[float, float] | None = None
    layers: list[LayerState] = Field(default_factory=list)
    vertical_exaggeration: int = 20
    analysis_layer: str = "none"
    analysis_open: bool = False

    # ---- Playback --------------------------------------------------------
    playing: bool = False
    playback_rate: float = 1.0

    # ---- Scene -----------------------------------------------------------
    camera: CameraState = Field(default_factory=CameraState)
    visible_platforms: int = 0
    alerts: list[AlertState] = Field(default_factory=list)
    selection: SelectionState = Field(default_factory=SelectionState)

    # ---- Derived readouts currently on screen ---------------------------
    eddy_count: int | None = None
    heatwave_cells: int | None = None
    mean_bias: float | None = None

    # -- helpers -----------------------------------------------------------
    @property
    def n_times(self) -> int:
        return len(self.available_times)

    @property
    def n_depths(self) -> int:
        return len(self.available_depths)

    def layer(self, layer_id: str) -> LayerState | None:
        for layer in self.layers:
            if layer.id == layer_id:
                return layer
        return None

    def nearest_depth_index(self, target_m: float) -> tuple[int, float]:
        """Closest available depth level to a requested depth in metres."""
        if not self.available_depths:
            return 0, 0.0
        best = min(
            range(len(self.available_depths)),
            key=lambda i: abs(self.available_depths[i] - target_m),
        )
        return best, self.available_depths[best]

    def has_variable(self, name: str) -> bool:
        return not self.available_variables or name in self.available_variables

    def describe_time(self) -> str:
        if self.time:
            return self.time.replace("T", " ").replace("Z", " UTC")
        return f"step {self.time_index + 1}"

    def summary(self) -> dict[str, Any]:
        """Compact form used when grounding a spoken answer."""
        return {
            "variable": self.variable,
            "depth_m": self.depth_m,
            "time": self.time,
            "analysis_layer": self.analysis_layer,
            "playing": self.playing,
            "alerts": len(self.alerts),
            "selected": self.selection.platform_id,
        }


Mode = Literal["command", "question", "chat"]
