/**
 * Deep's client half: build the screen snapshot, call the agent, apply the
 * actions it returns.
 *
 * The agent never mutates state itself — it returns declarative actions and
 * this module applies them through the same store the UI uses. That keeps one
 * code path for every state change, whether it came from a click or a voice
 * command.
 */

import { useAppStore, type AnalysisLayer, type LayerId } from "@/state/store";
import type { CollocationResult, DatasetAxes, OceanAlert, VariableSpec } from "@/types/api";

const BASE = "/api/v1/agent";

/* ========================================================================== */
/* Wire types                                                                 */
/* ========================================================================== */

export interface AgentAction {
  type: string;
  payload: Record<string, unknown>;
  label: string;
}

export interface AgentResponse {
  agent: string;
  intent: string;
  reply: string;
  actions: AgentAction[];
  confidence: number;
  source: "grammar" | "llm" | "fallback";
  suggestions: string[];
  listening: boolean;
}

export interface AgentCapabilities {
  agent: string;
  grammar: boolean;
  llm: boolean;
  llm_model: string | null;
  wake_words: string[];
  intents: string[];
  examples: string[];
}

/* ========================================================================== */
/* Screen snapshot                                                            */
/* ========================================================================== */

export interface SnapshotInputs {
  axes?: DatasetAxes;
  spec?: VariableSpec;
  variables: VariableSpec[];
  alerts: OceanAlert[];
  collocation?: CollocationResult;
  visiblePlatforms: number;
  dataRange?: [number, number];
  eddyCount?: number;
  heatwaveCells?: number;
  meanBias?: number | null;
  camera?: { lat: number; lon: number; heightKm: number };
}

/**
 * Assemble what Deep can "see".
 *
 * Bulky coordinate arrays are included only where the agent genuinely needs
 * them — depths, to resolve "go to 500 metres" onto a real level, and times,
 * to name the current step.
 */
export function buildSnapshot(inputs: SnapshotInputs): Record<string, unknown> {
  const state = useAppStore.getState();
  const depths = inputs.axes?.depths ?? [];
  const times = inputs.axes?.times ?? [];
  const selected = inputs.collocation;
  const stats = selected?.statistics;

  return {
    dataset: state.datasetId,
    variable: state.variable,
    variable_units: inputs.spec?.units ?? null,
    available_variables: inputs.variables
      .filter((v) => v.vector_group === null && v.name !== "bathymetry")
      .map((v) => v.name),

    depth_index: state.depthIndex,
    depth_m: depths[Math.min(state.depthIndex, depths.length - 1)] ?? 0,
    available_depths: depths,

    time_index: state.timeIndex,
    time: times[Math.min(state.timeIndex, times.length - 1)] ?? null,
    available_times: times,

    colormap: state.colorScale.colormap,
    color_range: [state.colorScale.vmin, state.colorScale.vmax],
    data_range: inputs.dataRange ?? null,
    layers: state.layers.map((layer) => ({
      id: layer.id,
      label: layer.label,
      enabled: layer.enabled,
      opacity: layer.opacity,
    })),
    vertical_exaggeration: state.verticalExaggeration,
    analysis_layer: state.analysisLayer,
    analysis_open: state.analysisOpen,

    playing: state.playing,
    playback_rate: state.playbackRate,

    camera: inputs.camera
      ? { lat: inputs.camera.lat, lon: inputs.camera.lon, height_km: inputs.camera.heightKm }
      : {},
    visible_platforms: inputs.visiblePlatforms,
    alerts: inputs.alerts.map((alert) => ({
      id: alert.id,
      title: alert.title,
      location: alert.location,
      severity: alert.severity,
      kind: alert.kind,
      detail: alert.detail ?? null,
      lat: alert.focus?.lat ?? null,
      lon: alert.focus?.lon ?? null,
    })),

    selection: {
      profile_id: state.selectedProfileId,
      platform_id: state.selectedPlatformId,
      lat: selected?.location.lat ?? null,
      lon: selected?.location.lon ?? null,
      variable: selected?.variable ?? state.collocationVariable,
      units: selected?.units ?? null,
      bias: stats?.bias ?? null,
      rmsd: stats?.rmsd ?? null,
      mae: stats?.mae ?? null,
      correlation: stats?.correlation ?? null,
      max_abs_difference: stats?.max_abs_difference ?? null,
      depth_of_max_difference_m: stats?.depth_of_max_difference_m ?? null,
      n_levels: stats?.n_levels ?? null,
    },

    eddy_count: inputs.eddyCount ?? null,
    heatwave_cells: inputs.heatwaveCells ?? null,
    mean_bias: inputs.meanBias ?? null,
  };
}

/* ========================================================================== */
/* Transport                                                                  */
/* ========================================================================== */

export async function askDeep(
  transcript: string,
  snapshot: Record<string, unknown>,
  history: { role: "user" | "assistant"; content: string }[] = [],
  signal?: AbortSignal,
): Promise<AgentResponse> {
  const response = await fetch(`${BASE}/command`, {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ transcript, context: snapshot, history: history.slice(-6) }),
    signal,
  });

  if (!response.ok) {
    let message = `Deep is unavailable (${response.status}).`;
    try {
      const body = await response.json();
      message = body?.error?.message ?? message;
    } catch {
      /* non-JSON error body */
    }
    throw new Error(message);
  }

  return (await response.json()) as AgentResponse;
}

export async function fetchCapabilities(signal?: AbortSignal): Promise<AgentCapabilities> {
  const response = await fetch(`${BASE}/capabilities`, { signal });
  if (!response.ok) throw new Error("Could not read Deep's capabilities.");
  return (await response.json()) as AgentCapabilities;
}

/* ========================================================================== */
/* Action application                                                         */
/* ========================================================================== */

export interface ActionHandlers {
  flyTo?: (lat: number, lon: number, heightKm: number) => void;
  resetView?: () => void;
  autofitColorRange?: () => void;
  selectPlatformById?: (platformId: string) => void;
  dismiss?: () => void;
}

function num(value: unknown, fallback = 0): number {
  return typeof value === "number" && Number.isFinite(value) ? value : fallback;
}

/**
 * Names the backend grammar still calls "layers" but which are really
 * variables: the field can only be coloured by one at a time.
 */
const VARIABLE_LAYERS = new Set(["chlorophyll", "salinity", "ssh", "temperature", "bathymetry"]);

/**
 * Apply one action. Unknown action types are ignored rather than thrown —
 * a newer backend must never be able to break an older client mid-demo.
 */
export function applyAction(action: AgentAction, handlers: ActionHandlers = {}): void {
  const store = useAppStore.getState();
  const p = action.payload ?? {};

  switch (action.type) {
    case "set_variable":
      if (typeof p.variable === "string") store.setVariable(p.variable);
      break;

    case "set_depth_index":
      store.setDepthIndex(Math.max(0, Math.round(num(p.index))));
      break;

    case "set_time_index":
      store.setPlaying(false);
      store.setTimeIndex(Math.max(0, Math.round(num(p.index))));
      break;

    case "set_playing":
      store.setPlaying(Boolean(p.playing));
      break;

    case "set_playback_rate":
      store.setPlaybackRate(num(p.rate, 1));
      break;

    case "set_layer_enabled": {
      const requested = typeof p.layer === "string" ? p.layer : "";
      const layer = store.layers.find((l) => l.id === requested);

      if (layer) {
        store.setLayerEnabled(layer.id, Boolean(p.enabled));
        break;
      }

      // The grammar still speaks the old vocabulary, where every variable was
      // also a "layer" — "show chlorophyll" arrives as set_layer_enabled. In
      // this interface a variable is what the field is coloured by, so route
      // it there instead of dropping the command on the floor.
      if (VARIABLE_LAYERS.has(requested) && p.enabled !== false) {
        store.setVariable(requested);
      }
      break;
    }

    case "set_layer_opacity":
      if (typeof p.layer === "string") {
        store.setLayerOpacity(p.layer as LayerId, num(p.opacity, 1));
      }
      break;

    case "set_exaggeration":
      store.setVerticalExaggeration(Math.round(num(p.value, 20)));
      break;

    case "set_colormap":
      if (typeof p.colormap === "string") store.setColorScale({ colormap: p.colormap });
      break;

    case "set_color_range":
      store.setColorScale({ vmin: num(p.vmin), vmax: num(p.vmax) });
      break;

    case "autofit_color_range":
      handlers.autofitColorRange?.();
      break;

    case "set_analysis_layer":
      if (typeof p.layer === "string") store.setAnalysisLayer(p.layer as AnalysisLayer);
      break;

    case "select_profile":
      if (typeof p.profile_id === "number") {
        store.selectProfile(p.profile_id, (p.platform_id as string) ?? null);
      } else if (typeof p.platform_id === "string") {
        handlers.selectPlatformById?.(p.platform_id);
      }
      break;

    case "clear_selection":
      store.selectProfile(null);
      break;

    case "set_collocation_variable":
      if (typeof p.variable === "string") store.setCollocationVariable(p.variable);
      break;

    case "fly_to":
      handlers.flyTo?.(num(p.lat), num(p.lon), num(p.height_km, 2600));
      break;

    case "reset_view":
      handlers.resetView?.();
      break;

    case "open_analysis_panel":
      if (!store.analysisOpen) store.toggleAnalysis();
      break;

    case "close_analysis_panel":
      if (store.analysisOpen) store.toggleAnalysis();
      break;

    case "dismiss":
      handlers.dismiss?.();
      break;

    default:
      // Forward-compatible: ignore what we do not understand.
      break;
  }
}

export function applyActions(actions: AgentAction[], handlers: ActionHandlers = {}): void {
  for (const action of actions) applyAction(action, handlers);
}
