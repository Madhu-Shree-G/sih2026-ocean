"""Deep — voice agent endpoints."""

from __future__ import annotations

from typing import Any

from fastapi import APIRouter, Depends
from pydantic import BaseModel, ConfigDict, Field, field_validator

from app.agent.context import ScreenContext
from app.agent.deep import AGENT_NAME, deep_agent
from app.agent.resolver import RULES
from app.agent.vocabulary import REGIONS, WAKE_WORDS
from app.core.errors import ValidationError
from app.security.deps import require_api_key

router = APIRouter(tags=["agent"], dependencies=[Depends(require_api_key)])

#: A spoken utterance is short. Anything longer is not speech, and capping it
#: keeps the prompt bounded when the language-model tier is enabled.
MAX_TRANSCRIPT_CHARS = 600
MAX_HISTORY_TURNS = 8


class HistoryTurn(BaseModel):
    model_config = ConfigDict(extra="ignore")

    role: str = Field(pattern="^(user|assistant)$")
    content: str = Field(max_length=MAX_TRANSCRIPT_CHARS)


class CommandRequest(BaseModel):
    """One utterance plus the state of the screen when it was spoken."""

    model_config = ConfigDict(extra="ignore")

    transcript: str = Field(..., max_length=MAX_TRANSCRIPT_CHARS)
    context: ScreenContext = Field(default_factory=ScreenContext)
    history: list[HistoryTurn] = Field(default_factory=list)

    @field_validator("transcript")
    @classmethod
    def _non_empty(cls, value: str) -> str:
        if not value.strip():
            raise ValueError("transcript must not be empty")
        return value.strip()

    @field_validator("history")
    @classmethod
    def _cap_history(cls, value: list[HistoryTurn]) -> list[HistoryTurn]:
        return value[-MAX_HISTORY_TURNS:]


@router.post("/command", summary="Send a spoken utterance to Deep")
async def command(body: CommandRequest) -> dict[str, Any]:
    """Resolve one utterance into a spoken reply and a list of UI actions.

    Deep never mutates state itself. It returns declarative actions that the
    client applies, so every action is inspectable before it happens and the
    client keeps final authority over its own state.
    """
    try:
        reply = deep_agent.respond(
            body.transcript,
            body.context,
            [turn.model_dump() for turn in body.history],
        )
    except Exception as exc:  # pragma: no cover - defensive
        raise ValidationError(f"Deep could not handle that utterance: {exc}") from exc

    return reply.to_dict()


@router.get("/capabilities", summary="What Deep can do in this deployment")
async def capabilities() -> dict[str, Any]:
    """Advertise the wake words, intent set and whether the LLM tier is live.

    The client reads this on boot to configure speech recognition and to show
    an accurate command list.
    """
    return {
        **deep_agent.capabilities(),
        "intents": sorted({rule.name for rule in RULES}),
        "regions": sorted({label for *_, label in REGIONS.values()}),
        "wake_words": list(WAKE_WORDS),
        "examples": [
            "Deep, what am I looking at?",
            "Show salinity",
            "Go to five hundred metres",
            "Play the animation",
            "Show me the eddies",
            "Where is the heatwave?",
            "Fly to the Bay of Bengal",
            "How does the model compare?",
            "Turn off the currents",
            "Vertical exaggeration thirty",
        ],
    }


@router.get("/health", summary="Agent readiness")
async def health() -> dict[str, Any]:
    return {
        "agent": AGENT_NAME,
        "status": "ready",
        "grammar_rules": len(RULES),
        "llm_tier": deep_agent.llm_available,
    }
