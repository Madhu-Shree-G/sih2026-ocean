"""Deep — the voice agent for the INDO-FOS console.

Two tiers, in order:

1. **Grammar.** A deterministic intent resolver owns every command. It is
   instant, offline, and cannot invent an action that does not exist. On a
   demo stage that reliability is worth more than flexibility.

2. **Language model (optional).** When the grammar cannot classify an
   utterance at all, and an Anthropic API key is configured, Claude answers
   the open-ended question using the on-screen state as grounding.

The second tier **never emits actions directly**. It may propose a command
*phrase*, which is then fed back through the grammar; if the grammar
recognises it, the resulting actions run. So every action Deep takes is one
the grammar validated, whether a human or a model phrased it.
"""

from __future__ import annotations

import json
import os
from dataclasses import dataclass, field
from typing import Any

from app.agent.actions import Action
from app.agent.context import ScreenContext
from app.agent.resolver import Resolution, resolve
from app.core.logging import get_logger

logger = get_logger(__name__)

AGENT_NAME = "Deep"
MODEL = "claude-opus-5"

SYSTEM_PROMPT = """\
You are Deep, the voice assistant built into INDO-FOS, an operational ocean \
forecasting console run by INCOIS under India's Ministry of Earth Sciences.

You are speaking aloud to an oceanographer. Keep replies under 40 words, in \
plain spoken sentences. No markdown, no lists, no emoji, no formatting.

You are given a JSON snapshot of exactly what is on the user's screen. Ground \
every answer in it. If the snapshot does not contain what is needed, say so \
plainly rather than guessing — never invent a number.

Domain notes you may rely on:
- The platform compares numerical ocean model output against in-situ \
observations from Argo floats, gliders and CTD casts. That comparison is \
called collocation. Bias is model minus observation.
- Depth increases downward; the thermocline is where temperature falls \
fastest, typically 50 to 200 metres in this basin.
- Eddies are detected with the Okubo-Weiss parameter. Anomaly is the field \
minus climatology.

If the user is asking you to *do* something rather than asking a question, \
you may propose a short command phrase the console understands, such as \
"show salinity", "go to 500 metres", "show me the eddies", "play", \
"fly to the Bay of Bengal", or "show the bias map".

Reply with JSON only, no other text:
{"reply": "<what you will say aloud>", "command": "<command phrase or empty>"}\
"""


@dataclass
class AgentReply:
    """What the client receives for one utterance."""

    agent: str
    intent: str
    reply: str
    actions: list[Action] = field(default_factory=list)
    confidence: float = 1.0
    source: str = "grammar"
    suggestions: list[str] = field(default_factory=list)
    #: True when the client should keep the microphone open for a follow-up.
    listening: bool = True

    def to_dict(self) -> dict[str, Any]:
        return {
            "agent": self.agent,
            "intent": self.intent,
            "reply": self.reply,
            "actions": [a.model_dump() for a in self.actions],
            "confidence": round(self.confidence, 3),
            "source": self.source,
            "suggestions": self.suggestions,
            "listening": self.listening,
        }


class DeepAgent:
    """Resolves utterances into spoken replies and console actions."""

    def __init__(self, api_key: str | None = None, model: str = MODEL) -> None:
        self._api_key = api_key or os.environ.get("OCEANVIEW_ANTHROPIC_API_KEY") or os.environ.get(
            "ANTHROPIC_API_KEY"
        )
        self._model = model
        self._client: Any = None
        self._client_failed = False

    # -- capabilities -------------------------------------------------------
    @property
    def llm_available(self) -> bool:
        return bool(self._api_key) and not self._client_failed

    def capabilities(self) -> dict[str, Any]:
        return {
            "agent": AGENT_NAME,
            "grammar": True,
            "llm": self.llm_available,
            "llm_model": self._model if self.llm_available else None,
            "wake_words": ["deep", "hey deep", "ok deep"],
        }

    # -- main entry point ---------------------------------------------------
    def respond(
        self,
        transcript: str,
        context: ScreenContext | None = None,
        history: list[dict[str, str]] | None = None,
    ) -> AgentReply:
        ctx = context or ScreenContext()
        resolution = resolve(transcript, ctx)

        if not resolution.needs_llm:
            return AgentReply(
                agent=AGENT_NAME,
                intent=resolution.intent,
                reply=resolution.reply,
                actions=resolution.actions,
                confidence=resolution.confidence,
                source="grammar",
                suggestions=resolution.suggestions,
                listening=resolution.intent != "dismiss",
            )

        # The grammar did not recognise it. Try the model, if configured.
        if self.llm_available:
            answered = self._ask_model(transcript, ctx, history or [])
            if answered is not None:
                return answered

        return AgentReply(
            agent=AGENT_NAME,
            intent="unknown",
            reply=(
                "I did not catch a command in that. Try asking what you are "
                "looking at, or say show me the eddies."
            ),
            confidence=0.0,
            source="fallback",
            suggestions=resolution.suggestions,
        )

    # -- language-model tier ------------------------------------------------
    def _ensure_client(self) -> Any:
        if self._client is not None:
            return self._client
        try:
            import anthropic  # imported lazily: the package is optional
        except ImportError:
            logger.info("anthropic_sdk_not_installed")
            self._client_failed = True
            return None
        try:
            self._client = anthropic.Anthropic(api_key=self._api_key)
        except Exception:
            logger.exception("anthropic_client_init_failed")
            self._client_failed = True
            return None
        return self._client

    def _ask_model(
        self,
        transcript: str,
        context: ScreenContext,
        history: list[dict[str, str]],
    ) -> AgentReply | None:
        client = self._ensure_client()
        if client is None:
            return None

        snapshot = json.dumps(self._grounding(context), separators=(",", ":"))
        messages: list[dict[str, Any]] = []

        # A couple of turns of history is enough for pronoun resolution and
        # costs far less than replaying a whole session.
        for turn in history[-4:]:
            role = turn.get("role")
            content = (turn.get("content") or "").strip()
            if role in ("user", "assistant") and content:
                messages.append({"role": role, "content": content})

        messages.append(
            {
                "role": "user",
                "content": f"Screen state:\n{snapshot}\n\nUser said: {transcript}",
            }
        )

        try:
            response = client.messages.create(
                model=self._model,
                max_tokens=400,
                system=SYSTEM_PROMPT,
                # A spoken reply must arrive quickly; low effort is right for
                # a short, grounded answer.
                output_config={"effort": "low"},
                messages=messages,
            )
        except Exception:
            logger.exception("deep_llm_call_failed")
            return None

        text = "".join(
            block.text for block in response.content if getattr(block, "type", "") == "text"
        ).strip()
        if not text:
            return None

        reply, command = self._parse_model_output(text)
        if not reply:
            return None

        actions: list[Action] = []
        intent = "llm_answer"

        # A proposed command is only honoured if the grammar recognises it.
        if command:
            follow_up = resolve(command, context)
            if not follow_up.needs_llm and follow_up.actions:
                actions = follow_up.actions
                intent = follow_up.intent

        return AgentReply(
            agent=AGENT_NAME,
            intent=intent,
            reply=reply,
            actions=actions,
            confidence=0.7,
            source="llm",
        )

    @staticmethod
    def _parse_model_output(text: str) -> tuple[str, str]:
        """Extract reply and optional command from the model's JSON."""
        candidate = text.strip()
        if candidate.startswith("```"):
            candidate = candidate.strip("`")
            _, _, candidate = candidate.partition("\n")

        start = candidate.find("{")
        end = candidate.rfind("}")
        if start != -1 and end > start:
            try:
                payload = json.loads(candidate[start : end + 1])
                return (
                    str(payload.get("reply", "")).strip(),
                    str(payload.get("command", "")).strip(),
                )
            except (json.JSONDecodeError, TypeError, AttributeError):
                pass

        # The model ignored the format; the prose is still a usable answer.
        return candidate, ""

    @staticmethod
    def _grounding(context: ScreenContext) -> dict[str, Any]:
        """Compact screen snapshot for the model.

        Trimmed deliberately: long coordinate arrays would dominate the
        prompt without helping the model answer anything.
        """
        selection = context.selection
        payload: dict[str, Any] = {
            "variable": context.variable,
            "units": context.variable_units,
            "depth_m": context.depth_m,
            "time": context.time,
            "step": f"{context.time_index + 1} of {context.n_times}",
            "colormap": context.colormap,
            "color_range": context.color_range,
            "data_range": context.data_range,
            "layers_on": [layer.id for layer in context.layers if layer.enabled],
            "analysis_layer": context.analysis_layer,
            "playing": context.playing,
            "platforms_in_view": context.visible_platforms,
            "available_variables": context.available_variables,
        }
        if context.camera.lat is not None:
            payload["camera"] = {
                "lat": round(context.camera.lat, 2),
                "lon": round(context.camera.lon or 0, 2),
            }
        if context.alerts:
            payload["alerts"] = [
                {"title": a.title, "where": a.location, "severity": a.severity}
                for a in context.alerts[:4]
            ]
        if selection.platform_id:
            payload["selected_platform"] = {
                "id": selection.platform_id,
                "type": selection.platform_type,
                "lat": selection.lat,
                "lon": selection.lon,
                "variable": selection.variable,
                "bias": selection.bias,
                "rmsd": selection.rmsd,
                "correlation": selection.correlation,
                "max_abs_difference": selection.max_abs_difference,
                "depth_of_max_difference_m": selection.depth_of_max_difference_m,
            }
        if context.eddy_count is not None:
            payload["eddy_count"] = context.eddy_count
        if context.heatwave_cells is not None:
            payload["heatwave_cells"] = context.heatwave_cells
        if context.mean_bias is not None:
            payload["mean_bias"] = context.mean_bias
        return payload


#: Process-wide agent. Stateless, so sharing one instance is safe.
deep_agent = DeepAgent()
