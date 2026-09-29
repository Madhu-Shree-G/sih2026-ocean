"""Tests for Deep, the voice agent."""

from __future__ import annotations

import pytest

from app.agent.actions import ActionType
from app.agent.context import AlertState, LayerState, ScreenContext, SelectionState
from app.agent.deep import DeepAgent
from app.agent.resolver import resolve
from app.agent.vocabulary import (
    contains_wake_word,
    extract_number,
    lookup_region,
    normalise,
    strip_wake_word,
    words_to_number,
)


@pytest.fixture
def context() -> ScreenContext:
    """A representative console state, mirroring the demo dataset."""
    return ScreenContext(
        dataset="indofos_demo",
        variable="temperature",
        variable_units="degree_Celsius",
        available_variables=["temperature", "salinity", "chlorophyll", "u", "v", "ssh"],
        depth_index=0,
        depth_m=0.0,
        available_depths=[0, 1.84, 8.45, 20.62, 38.82, 63.43, 94.7, 133.0, 178.4,
                          231.2, 291.4, 359.4, 435.3, 519.1, 611.0, 711.2, 819.6,
                          936.6, 1062.1, 1196.2, 1339.2, 1490.9, 1651.6, 1821.2, 2000.0],
        time_index=0,
        time="2024-03-01T00:00:00Z",
        available_times=[f"2024-03-{d:02d}T00:00:00Z" for d in range(1, 16)],
        colormap="thermal",
        color_range=(23.0, 30.0),
        layers=[
            LayerState(id="surface", enabled=True, opacity=1.0),
            LayerState(id="currents", enabled=True, opacity=0.7),
            LayerState(id="bathymetry", enabled=True, opacity=0.8),
            LayerState(id="chlorophyll", enabled=False, opacity=0.5),
        ],
        vertical_exaggeration=20,
        visible_platforms=116,
    )


def first_action(resolution, action_type: ActionType):
    return next((a for a in resolution.actions if a.type == action_type), None)


# ---------------------------------------------------------------------------
# Vocabulary
# ---------------------------------------------------------------------------
class TestVocabulary:
    @pytest.mark.parametrize(
        "phrase,expected",
        [
            ("five hundred", 500),
            ("one thousand", 1000),
            ("fifty", 50),
            ("twenty five", 25),
            ("two hundred fifty", 250),
            ("thirty", 30),
        ],
    )
    def test_spoken_numbers(self, phrase: str, expected: float) -> None:
        assert words_to_number(phrase) == expected

    def test_digits_win_over_words(self) -> None:
        assert extract_number("go to 500 metres") == 500

    def test_words_used_when_no_digits(self) -> None:
        assert extract_number("go to five hundred metres") == 500

    def test_no_number_returns_none(self) -> None:
        assert extract_number("show salinity") is None

    def test_normalise_strips_filler_and_punctuation(self) -> None:
        # "please" is filler; "could you" is deliberately kept, because
        # stripping it would turn "what can you do" into "what do".
        assert normalise("Deep, please show salinity?") == "deep show salinity"

    def test_normalise_keeps_can_you(self) -> None:
        assert normalise("what can you do") == "what can you do"

    def test_politeness_does_not_block_matching(self) -> None:
        # Patterns use search(), so a retained "could you" is harmless.
        assert resolve("could you show salinity").intent == "set_variable"

    @pytest.mark.parametrize(
        "phrase", ["deep show salinity", "hey deep play", "ok deep what is this"]
    )
    def test_wake_word_detected(self, phrase: str) -> None:
        assert contains_wake_word(phrase)

    def test_wake_word_stripped(self) -> None:
        assert strip_wake_word("Hey Deep, show salinity") == "show salinity"
        assert strip_wake_word("show salinity") == "show salinity"

    def test_region_lookup_prefers_longest_match(self) -> None:
        region = lookup_region("fly to the bay of bengal")
        assert region is not None
        assert region[3] == "the Bay of Bengal"


# ---------------------------------------------------------------------------
# Field and depth commands
# ---------------------------------------------------------------------------
class TestFieldCommands:
    @pytest.mark.parametrize(
        "phrase,expected",
        [
            ("show salinity", "salinity"),
            ("switch to chlorophyll", "chlorophyll"),
            ("display temperature", "temperature"),
            ("show me the salt", "salinity"),
            ("show sanity", "salinity"),          # common mis-hearing
            ("colour by chlorophyll", "chlorophyll"),
        ],
    )
    def test_set_variable(self, phrase: str, expected: str, context: ScreenContext) -> None:
        result = resolve(phrase, context)
        action = first_action(result, ActionType.SET_VARIABLE)
        assert action is not None
        assert action.payload["variable"] == expected

    def test_variable_change_follows_into_collocation(self, context: ScreenContext) -> None:
        result = resolve("show salinity", context)
        assert first_action(result, ActionType.SET_COLLOCATION_VARIABLE) is not None

    def test_unknown_variable_is_reported_not_actioned(self, context: ScreenContext) -> None:
        context.available_variables = ["temperature"]
        result = resolve("show salinity", context)
        assert result.actions == []
        assert "no salinity" in result.reply.lower()

    def test_currents_is_a_layer_not_a_field(self, context: ScreenContext) -> None:
        result = resolve("show currents", context)
        action = first_action(result, ActionType.SET_LAYER_ENABLED)
        assert action is not None
        assert action.payload == {"layer": "currents", "enabled": True}

    @pytest.mark.parametrize(
        "phrase,expected_m",
        [
            ("go to 500 metres", 519.1),
            ("dive to five hundred meters", 519.1),
            ("depth 1000", 1062.1),
            ("go to 100 m", 94.7),
        ],
    )
    def test_set_depth(self, phrase: str, expected_m: float, context: ScreenContext) -> None:
        result = resolve(phrase, context)
        action = first_action(result, ActionType.SET_DEPTH_INDEX)
        assert action is not None
        assert action.payload["depth_m"] == pytest.approx(expected_m, abs=0.1)

    def test_surface(self, context: ScreenContext) -> None:
        context.depth_index = 10
        result = resolve("back to the surface", context)
        action = first_action(result, ActionType.SET_DEPTH_INDEX)
        assert action is not None
        assert action.payload["depth_m"] == 0

    def test_deeper_is_relative(self, context: ScreenContext) -> None:
        context.depth_index = 5
        result = resolve("go deeper", context)
        action = first_action(result, ActionType.SET_DEPTH_INDEX)
        assert action is not None
        assert action.payload["index"] > 5

    def test_bottom(self, context: ScreenContext) -> None:
        result = resolve("take me to the bottom", context)
        action = first_action(result, ActionType.SET_DEPTH_INDEX)
        assert action is not None
        assert action.payload["depth_m"] == 2000.0


# ---------------------------------------------------------------------------
# Time and playback
# ---------------------------------------------------------------------------
class TestPlayback:
    def test_play(self, context: ScreenContext) -> None:
        action = first_action(resolve("play", context), ActionType.SET_PLAYING)
        assert action is not None and action.payload["playing"] is True

    def test_pause(self, context: ScreenContext) -> None:
        action = first_action(resolve("pause", context), ActionType.SET_PLAYING)
        assert action is not None and action.payload["playing"] is False

    def test_faster_doubles_rate(self, context: ScreenContext) -> None:
        context.playback_rate = 1.0
        action = first_action(resolve("faster", context), ActionType.SET_PLAYBACK_RATE)
        assert action is not None and action.payload["rate"] == 2.0

    def test_rate_is_capped(self, context: ScreenContext) -> None:
        context.playback_rate = 4.0
        action = first_action(resolve("faster", context), ActionType.SET_PLAYBACK_RATE)
        assert action is not None and action.payload["rate"] == 4.0

    def test_last_timestep(self, context: ScreenContext) -> None:
        action = first_action(resolve("go to the end", context), ActionType.SET_TIME_INDEX)
        assert action is not None and action.payload["index"] == 14

    def test_next_frame(self, context: ScreenContext) -> None:
        context.time_index = 3
        action = first_action(resolve("next frame", context), ActionType.SET_TIME_INDEX)
        assert action is not None and action.payload["index"] == 4

    def test_next_frame_clamps_at_end(self, context: ScreenContext) -> None:
        context.time_index = 14
        action = first_action(resolve("next frame", context), ActionType.SET_TIME_INDEX)
        assert action is not None and action.payload["index"] == 14


# ---------------------------------------------------------------------------
# Layers and presentation
# ---------------------------------------------------------------------------
class TestLayers:
    def test_turn_off_layer(self, context: ScreenContext) -> None:
        action = first_action(resolve("turn off the currents", context), ActionType.SET_LAYER_ENABLED)
        assert action is not None
        assert action.payload == {"layer": "currents", "enabled": False}

    def test_hide_bathymetry(self, context: ScreenContext) -> None:
        action = first_action(resolve("hide bathymetry", context), ActionType.SET_LAYER_ENABLED)
        assert action is not None and action.payload["enabled"] is False

    def test_opacity_percentage(self, context: ScreenContext) -> None:
        action = first_action(
            resolve("set currents to 50 percent", context), ActionType.SET_LAYER_OPACITY
        )
        assert action is not None
        assert action.payload["opacity"] == pytest.approx(0.5)

    def test_exaggeration_absolute(self, context: ScreenContext) -> None:
        action = first_action(
            resolve("vertical exaggeration thirty", context), ActionType.SET_EXAGGERATION
        )
        assert action is not None and action.payload["value"] == 30

    def test_exaggeration_relative(self, context: ScreenContext) -> None:
        context.vertical_exaggeration = 20
        action = first_action(resolve("exaggerate more", context), ActionType.SET_EXAGGERATION)
        assert action is not None and action.payload["value"] == 30

    def test_colormap(self, context: ScreenContext) -> None:
        action = first_action(
            resolve("use the balance palette", context), ActionType.SET_COLORMAP
        )
        assert action is not None and action.payload["colormap"] == "balance"

    def test_color_range(self, context: ScreenContext) -> None:
        action = first_action(
            resolve("set the range 22 to 30", context), ActionType.SET_COLOR_RANGE
        )
        assert action is not None
        assert (action.payload["vmin"], action.payload["vmax"]) == (22.0, 30.0)

    def test_autofit(self, context: ScreenContext) -> None:
        assert first_action(resolve("fit to data", context), ActionType.AUTOFIT_COLOR_RANGE)


# ---------------------------------------------------------------------------
# Analysis
# ---------------------------------------------------------------------------
class TestAnalysis:
    @pytest.mark.parametrize(
        "phrase,expected",
        [
            ("show me the eddies", "eddies"),
            ("run the eddy census", "eddies"),
            ("show anomalies", "anomaly"),
            ("show the marine heatwave", "anomaly"),
            ("show the bias map", "bias"),
            ("display mixed layer depth", "mixed_layer_depth"),
            ("show the thermocline", "thermocline"),
        ],
    )
    def test_analysis_layers(self, phrase: str, expected: str, context: ScreenContext) -> None:
        action = first_action(resolve(phrase, context), ActionType.SET_ANALYSIS_LAYER)
        assert action is not None and action.payload["layer"] == expected

    def test_analysis_reply_is_grounded_in_screen_state(self, context: ScreenContext) -> None:
        context.eddy_count = 23
        result = resolve("show me the eddies", context)
        assert "23" in result.reply

    def test_analysis_off(self, context: ScreenContext) -> None:
        context.analysis_layer = "eddies"
        action = first_action(resolve("turn off the analysis", context), ActionType.SET_ANALYSIS_LAYER)
        assert action is not None and action.payload["layer"] == "none"


# ---------------------------------------------------------------------------
# Camera
# ---------------------------------------------------------------------------
class TestCamera:
    def test_fly_to_region(self, context: ScreenContext) -> None:
        action = first_action(resolve("fly to the bay of bengal", context), ActionType.FLY_TO)
        assert action is not None
        assert action.payload["lat"] == pytest.approx(15.0)
        assert action.payload["lon"] == pytest.approx(88.0)

    def test_reset_view(self, context: ScreenContext) -> None:
        assert first_action(resolve("reset the view", context), ActionType.RESET_VIEW)

    def test_find_event_flies_to_alert(self, context: ScreenContext) -> None:
        context.alerts = [
            AlertState(
                title="Marine Heatwave", location="Arabian Sea",
                severity="moderate", kind="heatwave", lat=14.5, lon=68.5,
            )
        ]
        action = first_action(resolve("where is the heatwave", context), ActionType.FLY_TO)
        assert action is not None
        assert action.payload["lat"] == pytest.approx(14.5)

    def test_find_event_without_alerts_says_so(self, context: ScreenContext) -> None:
        result = resolve("where is the heatwave", context)
        assert result.actions == []
        assert "nothing is flagged" in result.reply.lower()


# ---------------------------------------------------------------------------
# Screen awareness
# ---------------------------------------------------------------------------
class TestScreenAwareness:
    def test_describe_screen_reports_actual_state(self, context: ScreenContext) -> None:
        result = resolve("what am I looking at", context)
        assert "temperature" in result.reply
        assert "0 metres" in result.reply
        assert "116 platforms" in result.reply

    def test_describe_includes_active_layers(self, context: ScreenContext) -> None:
        result = resolve("what's on screen", context)
        assert "currents" in result.reply

    def test_alerts_listed_from_context(self, context: ScreenContext) -> None:
        context.alerts = [
            AlertState(title="Cyclone Cold Wake", location="Bay of Bengal", severity="high"),
            AlertState(title="Marine Heatwave", location="Arabian Sea", severity="moderate"),
        ]
        result = resolve("any alerts", context)
        assert "Cyclone Cold Wake" in result.reply
        assert "Marine Heatwave" in result.reply

    def test_no_alerts_message(self, context: ScreenContext) -> None:
        assert "no alerts" in resolve("any alerts", context).reply.lower()

    def test_count_eddies(self, context: ScreenContext) -> None:
        context.eddy_count = 23
        assert "23" in resolve("how many eddies", context).reply

    def test_count_platforms(self, context: ScreenContext) -> None:
        assert "116" in resolve("how many floats are there", context).reply

    def test_collocation_explained_from_selection(self, context: ScreenContext) -> None:
        context.selection = SelectionState(
            profile_id=360, platform_id="2900044", variable="temperature",
            units="degree_Celsius", bias=0.108, rmsd=0.284, correlation=0.9996,
            max_abs_difference=0.844, depth_of_max_difference_m=94.1, n_levels=35,
        )
        result = resolve("what's the bias", context)
        assert "2900044" in result.reply
        assert "warmer" in result.reply
        assert "94" in result.reply

    def test_collocation_without_selection_offers_bias_map(self, context: ScreenContext) -> None:
        result = resolve("how does the model compare", context)
        action = first_action(result, ActionType.SET_ANALYSIS_LAYER)
        assert action is not None and action.payload["layer"] == "bias"

    def test_cooler_bias_is_described_as_cooler(self, context: ScreenContext) -> None:
        context.selection = SelectionState(
            platform_id="2900001", profile_id=1, bias=-0.5, units="degree_Celsius"
        )
        assert "cooler" in resolve("what's the bias", context).reply


# ---------------------------------------------------------------------------
# Meta
# ---------------------------------------------------------------------------
class TestMeta:
    def test_bare_wake_word_greets(self, context: ScreenContext) -> None:
        result = resolve("deep", context)
        assert result.intent == "greeting"
        assert result.suggestions

    def test_dismiss(self, context: ScreenContext) -> None:
        result = resolve("thanks deep", context)
        assert result.intent == "dismiss"
        assert first_action(result, ActionType.DISMISS)

    def test_help_lists_examples(self, context: ScreenContext) -> None:
        result = resolve("what can you do", context)
        assert result.intent == "help"
        assert len(result.suggestions) >= 4

    def test_unrecognised_defers_to_llm_tier(self, context: ScreenContext) -> None:
        result = resolve("what is the airspeed velocity of a swallow", context)
        assert result.needs_llm
        assert result.confidence == 0.0

    def test_wake_word_prefix_is_ignored(self, context: ScreenContext) -> None:
        with_wake = resolve("hey deep show salinity", context)
        without = resolve("show salinity", context)
        assert with_wake.intent == without.intent == "set_variable"


# ---------------------------------------------------------------------------
# Agent orchestration
# ---------------------------------------------------------------------------
class TestDeepAgent:
    def test_grammar_answers_without_llm(self, context: ScreenContext) -> None:
        agent = DeepAgent(api_key=None)
        reply = agent.respond("show salinity", context)
        assert reply.source == "grammar"
        assert reply.actions

    def test_graceful_fallback_when_no_llm_configured(self, context: ScreenContext) -> None:
        agent = DeepAgent(api_key=None)
        reply = agent.respond("ponder the nature of the sea", context)
        assert reply.source == "fallback"
        assert reply.reply
        assert reply.actions == []

    def test_dismiss_stops_listening(self, context: ScreenContext) -> None:
        agent = DeepAgent(api_key=None)
        assert agent.respond("thanks", context).listening is False

    def test_commands_keep_listening(self, context: ScreenContext) -> None:
        agent = DeepAgent(api_key=None)
        assert agent.respond("show salinity", context).listening is True

    def test_capabilities_report_llm_state(self) -> None:
        assert DeepAgent(api_key=None).capabilities()["llm"] is False
        assert DeepAgent(api_key="sk-test").capabilities()["llm"] is True

    def test_model_output_parsing(self) -> None:
        parse = DeepAgent._parse_model_output
        assert parse('{"reply": "Hello.", "command": "show salinity"}') == (
            "Hello.",
            "show salinity",
        )
        assert parse('```json\n{"reply": "Hi.", "command": ""}\n```')[0] == "Hi."
        # Prose that ignores the contract is still a usable spoken answer.
        assert parse("Just a sentence.") == ("Just a sentence.", "")

    def test_grounding_omits_bulky_axes(self, context: ScreenContext) -> None:
        payload = DeepAgent._grounding(context)
        assert "available_depths" not in payload
        assert "available_times" not in payload
        assert payload["variable"] == "temperature"


# ---------------------------------------------------------------------------
# HTTP surface
# ---------------------------------------------------------------------------
class TestAgentApi:
    def test_capabilities_endpoint(self, client) -> None:
        payload = client.get("/api/v1/agent/capabilities").json()
        assert payload["agent"] == "Deep"
        assert payload["grammar"] is True
        assert "deep" in payload["wake_words"]
        assert len(payload["examples"]) >= 6

    def test_health_endpoint(self, client) -> None:
        payload = client.get("/api/v1/agent/health").json()
        assert payload["status"] == "ready"
        assert payload["grammar_rules"] > 10

    def test_command_returns_actions(self, client) -> None:
        response = client.post(
            "/api/v1/agent/command",
            json={
                "transcript": "Deep, show salinity",
                "context": {"variable": "temperature", "available_variables": ["temperature", "salinity"]},
            },
        )
        assert response.status_code == 200
        payload = response.json()
        assert payload["agent"] == "Deep"
        assert any(a["type"] == "set_variable" for a in payload["actions"])

    def test_command_grounded_in_supplied_context(self, client) -> None:
        response = client.post(
            "/api/v1/agent/command",
            json={
                "transcript": "what am I looking at",
                "context": {
                    "variable": "chlorophyll",
                    "depth_m": 50,
                    "visible_platforms": 42,
                },
            },
        )
        reply = response.json()["reply"]
        assert "chlorophyll" in reply
        assert "42" in reply

    def test_empty_transcript_rejected(self, client) -> None:
        assert client.post(
            "/api/v1/agent/command", json={"transcript": "   "}
        ).status_code == 422

    def test_overlong_transcript_rejected(self, client) -> None:
        assert client.post(
            "/api/v1/agent/command", json={"transcript": "x" * 2000}
        ).status_code == 422

    def test_missing_context_is_tolerated(self, client) -> None:
        response = client.post("/api/v1/agent/command", json={"transcript": "play"})
        assert response.status_code == 200
        assert any(a["type"] == "set_playing" for a in response.json()["actions"])

    def test_history_is_capped(self, client) -> None:
        response = client.post(
            "/api/v1/agent/command",
            json={
                "transcript": "play",
                "history": [{"role": "user", "content": f"turn {i}"} for i in range(40)],
            },
        )
        assert response.status_code == 200
