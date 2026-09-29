"""Intent resolution: spoken text plus screen state to actions and a reply.

Deliberately a deterministic grammar rather than a language model. For a
closed command vocabulary this is the right engineering call:

* it answers in microseconds, with no network round trip on stage,
* it cannot hallucinate an action that does not exist,
* it works with no API key and no connectivity, which is the same constraint
  that shaped the rest of this project,
* and every decision it makes is inspectable and testable.

An optional LLM tier handles genuinely open-ended questions; see
:mod:`app.agent.deep`. The grammar always runs first and wins when confident.
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field
from typing import Callable

from app.agent import actions as A
from app.agent.context import ScreenContext
from app.agent.vocabulary import (
    ANALYSIS_SYNONYMS,
    COLORMAP_SYNONYMS,
    LAYER_SYNONYMS,
    VARIABLE_SYNONYMS,
    extract_number,
    extract_numbers,
    lookup,
    lookup_region,
    speak_units,
    strip_wake_word,
)


@dataclass
class Resolution:
    """What Deep decided to do about one utterance."""

    intent: str
    reply: str
    actions: list[A.Action] = field(default_factory=list)
    confidence: float = 1.0
    #: Set when the grammar could not classify the utterance at all.
    needs_llm: bool = False
    suggestions: list[str] = field(default_factory=list)


Handler = Callable[[re.Match[str], str, ScreenContext], Resolution | None]


@dataclass
class Rule:
    name: str
    patterns: list[str]
    handler: Handler
    confidence: float = 0.95

    def compiled(self) -> list[re.Pattern[str]]:
        return [re.compile(p) for p in self.patterns]


RULES: list[Rule] = []


def rule(name: str, *patterns: str, confidence: float = 0.95):
    """Register an intent handler. Registration order is match priority."""

    def decorator(handler: Handler) -> Handler:
        RULES.append(Rule(name=name, patterns=list(patterns), handler=handler, confidence=confidence))
        return handler

    return decorator


def _pct(value: float) -> float:
    """Interpret a spoken percentage or fraction as 0..1."""
    return value / 100.0 if value > 1.0 else value


# ===========================================================================
# Meta
# ===========================================================================
@rule("dismiss", r"\b(that s all|thats all|thank you|thanks|goodbye|bye|dismiss|go away|sleep|stand by|nevermind|never mind|cancel)\b")
def _dismiss(_m: re.Match[str], _t: str, _c: ScreenContext) -> Resolution:
    return Resolution(
        intent="dismiss",
        reply="Standing by. Say Deep whenever you need me.",
        actions=[A.dismiss()],
    )


@rule("help", r"\b(help|what can you do|commands|options|how do i)\b")
def _help(_m: re.Match[str], _t: str, context: ScreenContext) -> Resolution:
    return Resolution(
        intent="help",
        reply=(
            "I can change the variable, depth and time, control layers and "
            "playback, run the analysis products, fly to a region, and read "
            "out the model-observation comparison for any float."
        ),
        suggestions=[
            "show salinity",
            "go to 500 metres",
            "play the animation",
            "show me the eddies",
            "fly to the Bay of Bengal",
            f"what am I looking at",
        ],
    )


# ===========================================================================
# Analysis products (before generic "show X", which would swallow these)
# ===========================================================================
@rule(
    "analysis_off",
    r"\b(turn off|hide|clear|remove|stop)\b.*\b(analysis|anomaly|anomalies|eddies|eddy|bias|overlay|layer)\b",
)
def _analysis_off(_m: re.Match[str], _t: str, _c: ScreenContext) -> Resolution:
    return Resolution(
        intent="analysis_off",
        reply="Analysis layers off.",
        actions=[A.set_analysis_layer("none"), A.close_analysis_panel()],
    )


@rule(
    "set_analysis",
    r"\b(show|display|run|open|give me|turn on|enable|switch to)\b.*\b(anomaly|anomalies|heatwave|heat wave|marine heatwave|eddy|eddies|eddy census|vortices|bias|bias map|verification|validation|mixed layer|mixed layer depth|mld|thermocline|climatology)\b",
    r"\b(anomaly|anomalies|heatwave|heat wave|eddy census|eddies|bias map|mixed layer depth|thermocline)\b",
)
def _set_analysis(_m: re.Match[str], text: str, context: ScreenContext) -> Resolution | None:
    # "where is the heatwave" names an analysis product but is a question about
    # location; let the find_event rule take it.
    if re.search(r"\b(where|locate|how many|count)\b", text):
        return None

    layer = lookup(ANALYSIS_SYNONYMS, text)
    if layer is None:
        return None

    replies = {
        "anomaly": "Anomaly layer on, against the climatology.",
        "eddies": "Running the Okubo-Weiss eddy census.",
        "bias": "Model bias map. Every platform is coloured by how far the model is from what it measured.",
        "mixed_layer_depth": "Mixed layer depth, de Boyer Montegut criterion.",
        "thermocline": "Thermocline depth.",
    }
    reply = replies.get(layer, f"{layer} layer on.")

    # Ground the reply in what is already on screen where we can.
    if layer == "eddies" and context.eddy_count is not None:
        reply += f" {context.eddy_count} detected at this step."
    if layer == "anomaly" and context.heatwave_cells:
        reply += f" {context.heatwave_cells} cells are above the heatwave threshold."
    if layer == "bias" and context.mean_bias is not None:
        reply += f" Mean bias is {context.mean_bias:+.2f}."

    return Resolution(
        intent="set_analysis",
        reply=reply,
        actions=[A.set_analysis_layer(layer), A.open_analysis_panel()],
    )


# ===========================================================================
# Regions and camera
# ===========================================================================
@rule("reset_view", r"\b(reset|zoom out|whole domain|full domain|everything|show all|wide view|overview)\b")
def _reset_view(_m: re.Match[str], _t: str, _c: ScreenContext) -> Resolution:
    return Resolution(
        intent="reset_view", reply="Back to the full domain.", actions=[A.reset_view()]
    )


@rule(
    "fly_to",
    r"\b(go to|fly to|take me to|show me|zoom to|zoom in on|focus on|navigate to|centre on|center on|look at)\b",
)
def _fly_to(_m: re.Match[str], text: str, _c: ScreenContext) -> Resolution | None:
    region = lookup_region(text)
    if region is None:
        return None
    lat, lon, height, label = region
    return Resolution(
        intent="fly_to",
        reply=f"Flying to {label}.",
        actions=[A.fly_to(lat, lon, f"Flying to {label}", height)],
    )


@rule("find_event", r"\b(where|find|locate|take me to)\b.*\b(heatwave|heat wave|cyclone|cold wake|upwelling|eddy|alert|event|anomaly)\b")
def _find_event(_m: re.Match[str], text: str, context: ScreenContext) -> Resolution:
    if not context.alerts:
        return Resolution(
            intent="find_event",
            reply="Nothing is flagged at this timestep. Try scrubbing later in the run.",
        )

    wanted = None
    for keyword, kind in (
        ("heatwave", "heatwave"), ("heat wave", "heatwave"),
        ("cyclone", "cyclone"), ("cold wake", "cyclone"),
        ("upwelling", "upwelling"), ("eddy", "eddy"),
    ):
        if keyword in text:
            wanted = kind
            break

    alert = next((a for a in context.alerts if a.kind == wanted), None) if wanted else None
    alert = alert or context.alerts[0]

    if alert.lat is None or alert.lon is None:
        return Resolution(
            intent="find_event",
            reply=f"{alert.title} in {alert.location}, severity {alert.severity}.",
        )

    return Resolution(
        intent="find_event",
        reply=f"{alert.title} in {alert.location}. Severity {alert.severity}. Taking you there.",
        actions=[A.fly_to(alert.lat, alert.lon, f"Flying to the {alert.title.lower()}", 1800)],
    )


# ===========================================================================
# Playback
# ===========================================================================
@rule("pause", r"\b(pause|stop|halt|freeze)\b(?!.*\b(analysis|layer|overlay)\b)")
def _pause(_m: re.Match[str], _t: str, _c: ScreenContext) -> Resolution:
    return Resolution(intent="pause", reply="Paused.", actions=[A.set_playing(False)])


@rule("play", r"\b(play|animate|resume|run the animation)\b", r"\bstart\b(?!\s*(of|at))")
def _play(_m: re.Match[str], _t: str, context: ScreenContext) -> Resolution:
    return Resolution(
        intent="play",
        reply=f"Playing {context.n_times or 'the'} timesteps.",
        actions=[A.set_playing(True)],
    )


@rule("speed", r"\b(faster|slower|speed|double speed|half speed)\b")
def _speed(_m: re.Match[str], text: str, context: ScreenContext) -> Resolution:
    current = context.playback_rate or 1.0
    if "faster" in text or "double" in text:
        rate = min(4.0, current * 2)
    elif "slower" in text or "half" in text:
        rate = max(0.5, current / 2)
    else:
        value = extract_number(text)
        rate = max(0.5, min(4.0, value)) if value else current
    return Resolution(
        intent="speed", reply=f"Speed {rate:g}x.", actions=[A.set_playback_rate(rate)]
    )


# ===========================================================================
# Time
# ===========================================================================
@rule(
    "set_time",
    r"\b(next|previous|prev|last|final|first|beginning|start|end|earliest|latest)\b.*\b(frame|step|timestep|time|day)\b",
    r"\b(frame|step|timestep)\b.*\b(next|previous|last|first)\b",
    r"\b(go to|jump to|show)\b.*\b(end|beginning|start|last day|first day|latest|earliest)\b",
    r"\b(next|previous|prev)\b$",
)
def _set_time(_m: re.Match[str], text: str, context: ScreenContext) -> Resolution:
    last = max(0, context.n_times - 1)
    current = context.time_index

    if re.search(r"\b(next|forward)\b", text):
        index = min(last, current + 1)
    elif re.search(r"\b(previous|prev|back)\b", text):
        index = max(0, current - 1)
    elif re.search(r"\b(last|final|end|latest)\b", text):
        index = last
    elif re.search(r"\b(first|beginning|start|earliest)\b", text):
        index = 0
    else:
        index = current

    label = (
        context.available_times[index].replace("T", " ").replace("Z", " UTC")
        if index < len(context.available_times)
        else f"step {index + 1}"
    )
    return Resolution(
        intent="set_time",
        reply=f"Step {index + 1} of {context.n_times or '?'}, {label}.",
        actions=[A.set_time_index(index, label)],
    )


# ===========================================================================
# Depth
# ===========================================================================
@rule("set_depth_surface", r"\b(surface|top|sea surface)\b")
def _depth_surface(_m: re.Match[str], _t: str, context: ScreenContext) -> Resolution:
    index, depth = context.nearest_depth_index(0.0)
    return Resolution(
        intent="set_depth",
        reply="At the surface.",
        actions=[A.set_depth_index(index, depth)],
    )


@rule("set_depth_relative", r"\b(deeper|shallower|further down|further up|down a bit|up a bit|bottom|deepest)\b")
def _depth_relative(_m: re.Match[str], text: str, context: ScreenContext) -> Resolution:
    n = max(0, context.n_depths - 1)
    if re.search(r"\b(bottom|deepest)\b", text):
        index = n
    elif re.search(r"\b(deeper|further down|down a bit)\b", text):
        index = min(n, context.depth_index + 2)
    else:
        index = max(0, context.depth_index - 2)

    depth = context.available_depths[index] if context.available_depths else 0.0
    return Resolution(
        intent="set_depth",
        reply=f"{depth:.0f} metres.",
        actions=[A.set_depth_index(index, depth)],
    )


@rule(
    "set_depth",
    r"\b(depth|deep|down to|dive to|go to|set depth|at)\b[^0-9a-z]*.*?(\d+|one|two|three|four|five|six|seven|eight|nine|ten|twenty|thirty|forty|fifty|hundred|thousand)",
    r"(\d+)\s*(m|meters|metres|meter|metre)\b",
)
def _set_depth(_m: re.Match[str], text: str, context: ScreenContext) -> Resolution | None:
    # Ignore phrasings that are really about time or colour.
    if re.search(r"\b(step|frame|timestep|percent|opacity|range|exaggeration|speed)\b", text):
        return None

    value = extract_number(text)
    if value is None or value < 0:
        return None

    index, depth = context.nearest_depth_index(value)
    note = "" if abs(depth - value) < 1 else f" Nearest level is {depth:.0f}."
    return Resolution(
        intent="set_depth",
        reply=f"{depth:.0f} metres.{note}",
        actions=[A.set_depth_index(index, depth)],
    )


# ===========================================================================
# Vertical exaggeration
# ===========================================================================
@rule("set_exaggeration", r"\b(vertical )?exaggeration|exaggerate\b")
def _set_exaggeration(_m: re.Match[str], text: str, context: ScreenContext) -> Resolution:
    current = context.vertical_exaggeration or 20
    if re.search(r"\b(more|increase|higher|up)\b", text):
        value = min(50, current + 10)
    elif re.search(r"\b(less|decrease|lower|down|reduce)\b", text):
        value = max(1, current - 10)
    else:
        number = extract_number(text)
        value = int(max(1, min(50, number))) if number else current
    return Resolution(
        intent="set_exaggeration",
        reply=f"Vertical exaggeration {value}x.",
        actions=[A.set_exaggeration(int(value))],
    )


# ===========================================================================
# Layers
# ===========================================================================
@rule("set_opacity", r"\b(opacity|transparent|transparency|percent|fade)\b")
def _set_opacity(_m: re.Match[str], text: str, context: ScreenContext) -> Resolution | None:
    layer = lookup(LAYER_SYNONYMS, text)
    if layer is None:
        return None

    if re.search(r"\bmore transparent|fade|dimmer\b", text):
        existing = context.layer(layer)
        opacity = max(0.1, (existing.opacity if existing else 1.0) - 0.25)
    elif re.search(r"\bless transparent|brighter|stronger|solid\b", text):
        existing = context.layer(layer)
        opacity = min(1.0, (existing.opacity if existing else 1.0) + 0.25)
    else:
        number = extract_number(text)
        if number is None:
            return None
        opacity = max(0.0, min(1.0, _pct(number)))

    return Resolution(
        intent="set_opacity",
        reply=f"{layer} at {opacity * 100:.0f} percent.",
        actions=[A.set_layer_opacity(layer, round(opacity, 3))],
    )


@rule(
    "toggle_layer",
    r"\b(turn on|turn off|hide|enable|disable|toggle)\b",
    r"\b(show|display|add|remove)\b.*\b(layer|streamlines|particles)\b",
)
def _toggle_layer(_m: re.Match[str], text: str, context: ScreenContext) -> Resolution | None:
    layer = lookup(LAYER_SYNONYMS, text)
    if layer is None:
        return None

    if re.search(r"\b(turn off|hide|disable|remove)\b", text):
        enabled = False
    elif re.search(r"\b(turn on|show|enable|add)\b", text):
        enabled = True
    else:
        existing = context.layer(layer)
        enabled = not (existing.enabled if existing else False)

    return Resolution(
        intent="toggle_layer",
        reply=f"{'Showing' if enabled else 'Hiding'} {layer}.",
        actions=[A.set_layer_enabled(layer, enabled)],
    )


# ===========================================================================
# Colour
# ===========================================================================
@rule("autofit_range", r"\b(auto|autoscale|auto scale|fit)\b.*\b(range|scale|colour|color|data)\b", r"\bfit to data\b")
def _autofit(_m: re.Match[str], _t: str, _c: ScreenContext) -> Resolution:
    return Resolution(
        intent="autofit_range",
        reply="Fitted the colour range to the data on screen.",
        actions=[A.autofit_color_range()],
    )


@rule("set_range", r"\b(range|scale|limits|between)\b.*?(-?\d+).*?(-?\d+)")
def _set_range(_m: re.Match[str], text: str, _c: ScreenContext) -> Resolution | None:
    values = extract_numbers(text, limit=2)
    if len(values) < 2:
        return None
    vmin, vmax = sorted(values[:2])
    if vmin == vmax:
        return None
    return Resolution(
        intent="set_range",
        reply=f"Colour range {vmin:g} to {vmax:g}.",
        actions=[A.set_color_range(vmin, vmax)],
    )


@rule("set_colormap", r"\b(palette|colormap|colour map|color map|colour scheme|color scheme)\b")
def _set_colormap(_m: re.Match[str], text: str, _c: ScreenContext) -> Resolution | None:
    name = lookup(COLORMAP_SYNONYMS, text)
    if name is None:
        return None
    return Resolution(
        intent="set_colormap", reply=f"{name} palette.", actions=[A.set_colormap(name)]
    )


# ===========================================================================
# Observations and collocation
# ===========================================================================
@rule("clear_selection", r"\b(clear|close|deselect|dismiss)\b.*\b(selection|profile|float|panel)\b")
def _clear_selection(_m: re.Match[str], _t: str, _c: ScreenContext) -> Resolution:
    return Resolution(
        intent="clear_selection", reply="Cleared.", actions=[A.clear_selection()]
    )


@rule("select_platform", r"\b(select|open|show|pick|choose)\b.*\b(float|platform|glider|ctd|buoy)\b", r"\bfloat\s*(\d{4,})\b")
def _select_platform(_m: re.Match[str], text: str, _c: ScreenContext) -> Resolution | None:
    match = re.search(r"\b(\d{4,})\b", text)
    if not match:
        return Resolution(
            intent="select_platform",
            reply="Which one? Say the float number, or click a marker on the globe.",
        )
    return Resolution(
        intent="select_platform",
        reply=f"Opening float {match.group(1)}.",
        actions=[
            A.Action.make(
                A.ActionType.SELECT_PROFILE,
                f"Select platform {match.group(1)}",
                platform_id=match.group(1),
                profile_id=None,
            )
        ],
    )


@rule(
    "explain_collocation",
    r"\b(bias|rmsd|compare|comparison|how good|how close|agreement|match|verify|verification|difference|discrepancy)\b",
)
def _explain_collocation(_m: re.Match[str], _t: str, context: ScreenContext) -> Resolution:
    sel = context.selection
    if sel.profile_id is None and sel.platform_id is None:
        return Resolution(
            intent="explain_collocation",
            reply=(
                "Nothing is selected yet. Click a float on the globe, or say "
                "show me the bias map to see the whole fleet at once."
            ),
            actions=[A.set_analysis_layer("bias"), A.open_analysis_panel()],
        )

    if sel.bias is None:
        return Resolution(
            intent="explain_collocation",
            reply=f"{sel.platform_id} is open but the comparison has not finished loading.",
        )

    units = speak_units(sel.units)
    parts = [
        f"For {sel.platform_id}, the model is {abs(sel.bias):.2f} {units} "
        f"{'warmer' if sel.bias > 0 else 'cooler'} than the float on average."
    ]
    if sel.rmsd is not None:
        parts.append(f"RMSD {sel.rmsd:.2f}.")
    if sel.correlation is not None:
        parts.append(f"Correlation {sel.correlation:.2f}.")
    if sel.max_abs_difference is not None and sel.depth_of_max_difference_m is not None:
        parts.append(
            f"The largest disagreement is {sel.max_abs_difference:.2f} {units} "
            f"at {sel.depth_of_max_difference_m:.0f} metres, which is the thermocline."
        )
    return Resolution(intent="explain_collocation", reply=" ".join(parts))


# ===========================================================================
# Questions about the screen
# ===========================================================================
@rule("list_alerts", r"\b(alert|alerts|warning|warnings|anything happening|what s wrong|whats wrong)\b")
def _list_alerts(_m: re.Match[str], _t: str, context: ScreenContext) -> Resolution:
    if not context.alerts:
        return Resolution(
            intent="list_alerts",
            reply="No alerts at this timestep. Scrub toward the end of the run and the heatwave appears.",
        )
    spoken = ", ".join(f"{a.title} in {a.location}, {a.severity}" for a in context.alerts[:3])
    return Resolution(
        intent="list_alerts",
        reply=f"{len(context.alerts)} active: {spoken}.",
    )


@rule("describe_screen", r"\b(what am i looking at|what s on screen|whats on screen|describe|explain this|what is this|status|where am i|what s showing|whats showing)\b")
def _describe(_m: re.Match[str], _t: str, context: ScreenContext) -> Resolution:
    units = context.variable_units or ""
    parts = [
        f"You are looking at {context.variable} at {context.depth_m:.0f} metres, "
        f"{context.describe_time()}."
    ]
    if context.color_range:
        lo, hi = context.color_range
        parts.append(f"Colour range {lo:g} to {hi:g} {units}.")
    active = [layer.id for layer in context.layers if layer.enabled]
    if active:
        parts.append(f"Layers on: {', '.join(active)}.")
    if context.analysis_layer and context.analysis_layer != "none":
        parts.append(f"Analysis layer: {context.analysis_layer}.")
    if context.visible_platforms:
        parts.append(f"{context.visible_platforms} platforms in view.")
    if context.alerts:
        parts.append(f"{len(context.alerts)} alerts active.")
    if context.selection.platform_id:
        parts.append(f"Float {context.selection.platform_id} is open.")
    return Resolution(intent="describe_screen", reply=" ".join(parts))


@rule("count_query", r"\b(how many|count|number of)\b")
def _count(_m: re.Match[str], text: str, context: ScreenContext) -> Resolution | None:
    if "eddy" in text or "eddies" in text:
        n = context.eddy_count
        return Resolution(
            intent="count_query",
            reply=f"{n} eddies at this step." if n is not None
            else "Turn on the eddy census and I can count them.",
        )
    if "float" in text or "platform" in text or "observation" in text:
        return Resolution(
            intent="count_query",
            reply=f"{context.visible_platforms} platforms in view.",
        )
    if "alert" in text:
        return Resolution(
            intent="count_query", reply=f"{len(context.alerts)} alerts active."
        )
    return None


# ===========================================================================
# Variable selection - last, because "show X" is the loosest pattern
# ===========================================================================
@rule(
    "set_variable",
    r"\b(show|display|switch to|change to|give me|view|plot|colour by|color by|look at)\b",
    r"^(temperature|salinity|chlorophyll|currents|ssh|bathymetry)$",
    confidence=0.85,
)
def _set_variable(_m: re.Match[str], text: str, context: ScreenContext) -> Resolution | None:
    name = lookup(VARIABLE_SYNONYMS, text)
    if name is None:
        return None

    # "show currents" means the streamline layer, not a scalar field.
    if name in ("u", "v"):
        return Resolution(
            intent="toggle_layer",
            reply="Currents on.",
            actions=[A.set_layer_enabled("currents", True)],
        )

    if not context.has_variable(name):
        return Resolution(
            intent="set_variable",
            reply=f"This dataset has no {name}. Available: {', '.join(context.available_variables)}.",
        )

    actions = [A.set_variable(name)]
    # Comparable variables should follow the field, so the profile panel keeps
    # showing the same quantity the globe is showing.
    if name in ("temperature", "salinity", "chlorophyll", "oxygen"):
        actions.append(A.set_collocation_variable(name))

    return Resolution(
        intent="set_variable", reply=f"Showing {name}.", actions=actions
    )


# ===========================================================================
# Entry point
# ===========================================================================
_COMPILED: list[tuple[Rule, list[re.Pattern[str]]]] | None = None


def _compiled_rules() -> list[tuple[Rule, list[re.Pattern[str]]]]:
    global _COMPILED
    if _COMPILED is None:
        _COMPILED = [(r, r.compiled()) for r in RULES]
    return _COMPILED


def resolve(transcript: str, context: ScreenContext | None = None) -> Resolution:
    """Classify one utterance and produce actions plus a spoken reply."""
    ctx = context or ScreenContext()
    text = strip_wake_word(transcript)

    if not text:
        return Resolution(
            intent="greeting",
            reply="Deep here. What would you like to see?",
            suggestions=["show salinity", "go to 500 metres", "show me the eddies"],
        )

    for rule_def, patterns in _compiled_rules():
        for pattern in patterns:
            match = pattern.search(text)
            if not match:
                continue
            result = rule_def.handler(match, text, ctx)
            if result is not None:
                result.confidence = rule_def.confidence
                return result

    return Resolution(
        intent="unknown",
        reply="",
        confidence=0.0,
        needs_llm=True,
        suggestions=["what am I looking at", "show me the eddies", "go to 500 metres"],
    )
