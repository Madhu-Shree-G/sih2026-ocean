"""Actions Deep can ask the interface to perform.

The agent never mutates UI state directly. It returns a list of declarative
actions, and the client applies them. That separation matters for three
reasons: the agent stays testable without a browser, the client keeps final
authority over its own state, and every action Deep takes is inspectable
before it happens.
"""

from __future__ import annotations

from enum import Enum
from typing import Any, Literal

from pydantic import BaseModel, Field


class ActionType(str, Enum):
    """The complete vocabulary of things Deep may do."""

    # ---- Field selection -------------------------------------------------
    SET_VARIABLE = "set_variable"
    SET_DEPTH_INDEX = "set_depth_index"
    SET_TIME_INDEX = "set_time_index"

    # ---- Playback --------------------------------------------------------
    SET_PLAYING = "set_playing"
    SET_PLAYBACK_RATE = "set_playback_rate"

    # ---- Layers ----------------------------------------------------------
    SET_LAYER_ENABLED = "set_layer_enabled"
    SET_LAYER_OPACITY = "set_layer_opacity"
    SET_EXAGGERATION = "set_exaggeration"

    # ---- Colour ----------------------------------------------------------
    SET_COLORMAP = "set_colormap"
    SET_COLOR_RANGE = "set_color_range"
    AUTOFIT_COLOR_RANGE = "autofit_color_range"

    # ---- Analysis --------------------------------------------------------
    SET_ANALYSIS_LAYER = "set_analysis_layer"

    # ---- Observations ----------------------------------------------------
    SELECT_PROFILE = "select_profile"
    CLEAR_SELECTION = "clear_selection"
    SET_COLLOCATION_VARIABLE = "set_collocation_variable"

    # ---- Camera ----------------------------------------------------------
    FLY_TO = "fly_to"
    RESET_VIEW = "reset_view"

    # ---- Chrome ----------------------------------------------------------
    OPEN_ANALYSIS_PANEL = "open_analysis_panel"
    CLOSE_ANALYSIS_PANEL = "close_analysis_panel"
    DISMISS = "dismiss"


class Action(BaseModel):
    """One instruction for the client, with a human-readable label."""

    type: ActionType
    payload: dict[str, Any] = Field(default_factory=dict)
    #: Shown in the transcript so the user can see what Deep did.
    label: str = ""

    @classmethod
    def make(cls, action_type: ActionType, label: str = "", **payload: Any) -> "Action":
        return cls(type=action_type, payload=payload, label=label)


# ---------------------------------------------------------------------------
# Convenience constructors
#
# These exist so intent handlers read as intent, not as dictionary assembly.
# ---------------------------------------------------------------------------
def set_variable(name: str) -> Action:
    return Action.make(ActionType.SET_VARIABLE, f"Switched to {name}", variable=name)


def set_depth_index(index: int, depth_m: float) -> Action:
    return Action.make(
        ActionType.SET_DEPTH_INDEX,
        f"Depth {depth_m:.0f} m",
        index=index,
        depth_m=depth_m,
    )


def set_time_index(index: int, label: str = "") -> Action:
    return Action.make(
        ActionType.SET_TIME_INDEX, label or f"Timestep {index + 1}", index=index
    )


def set_playing(playing: bool) -> Action:
    return Action.make(
        ActionType.SET_PLAYING, "Playing" if playing else "Paused", playing=playing
    )


def set_playback_rate(rate: float) -> Action:
    return Action.make(ActionType.SET_PLAYBACK_RATE, f"Speed {rate}x", rate=rate)


def set_layer_enabled(layer: str, enabled: bool) -> Action:
    return Action.make(
        ActionType.SET_LAYER_ENABLED,
        f"{'Showing' if enabled else 'Hiding'} {layer}",
        layer=layer,
        enabled=enabled,
    )


def set_layer_opacity(layer: str, opacity: float) -> Action:
    return Action.make(
        ActionType.SET_LAYER_OPACITY,
        f"{layer} at {opacity * 100:.0f}%",
        layer=layer,
        opacity=opacity,
    )


def set_exaggeration(value: int) -> Action:
    return Action.make(
        ActionType.SET_EXAGGERATION, f"Vertical exaggeration {value}x", value=value
    )


def set_colormap(name: str) -> Action:
    return Action.make(ActionType.SET_COLORMAP, f"Palette {name}", colormap=name)


def set_color_range(vmin: float, vmax: float) -> Action:
    return Action.make(
        ActionType.SET_COLOR_RANGE, f"Range {vmin:g} to {vmax:g}", vmin=vmin, vmax=vmax
    )


def autofit_color_range() -> Action:
    return Action.make(ActionType.AUTOFIT_COLOR_RANGE, "Fitted colour range to data")


def set_analysis_layer(layer: str) -> Action:
    labels = {
        "none": "Analysis layers off",
        "anomaly": "Anomaly and heatwave layer",
        "eddies": "Eddy census",
        "bias": "Model bias map",
        "mixed_layer_depth": "Mixed layer depth",
        "thermocline": "Thermocline depth",
    }
    return Action.make(
        ActionType.SET_ANALYSIS_LAYER, labels.get(layer, layer), layer=layer
    )


def select_profile(profile_id: int, platform_id: str | None = None) -> Action:
    return Action.make(
        ActionType.SELECT_PROFILE,
        f"Selected {platform_id or profile_id}",
        profile_id=profile_id,
        platform_id=platform_id,
    )


def clear_selection() -> Action:
    return Action.make(ActionType.CLEAR_SELECTION, "Cleared selection")


def set_collocation_variable(name: str) -> Action:
    return Action.make(
        ActionType.SET_COLLOCATION_VARIABLE, f"Comparing {name}", variable=name
    )


def fly_to(lat: float, lon: float, label: str = "", height_km: float = 2600) -> Action:
    return Action.make(
        ActionType.FLY_TO,
        label or f"Flying to {lat:.1f}, {lon:.1f}",
        lat=lat,
        lon=lon,
        height_km=height_km,
    )


def reset_view() -> Action:
    return Action.make(ActionType.RESET_VIEW, "Reset to the full domain")


def open_analysis_panel() -> Action:
    return Action.make(ActionType.OPEN_ANALYSIS_PANEL, "Opened analysis")


def close_analysis_panel() -> Action:
    return Action.make(ActionType.CLOSE_ANALYSIS_PANEL, "Closed analysis")


def dismiss() -> Action:
    return Action.make(ActionType.DISMISS, "Standing by")


Speakable = Literal["normal", "brief", "detailed"]
