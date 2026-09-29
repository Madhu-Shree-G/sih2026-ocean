/**
 * Typed client for the OceanView3D backend.
 *
 * Everything goes through `request()` so error handling, the JSON error
 * envelope and abort signals are consistent across every call site.
 */

import { decodeOcvol, type OcvolBlock } from "./ocvol";
import type {
  AnomalyResult,
  BiasMap,
  CollocationResult,
  ColormapEntry,
  DatasetAxes,
  DatasetInfo,
  DerivedGrid,
  DriftResult,
  EddyCensus,
  ObservationStatistics,
  Platform,
  PointProfile,
  ProfileDetail,
  ProfileSummary,
  ReadyState,
  ServiceInfo,
  TransectResult,
} from "@/types/api";

const BASE = `${import.meta.env.VITE_API_URL}/api/v1`;

export class ApiError extends Error {
  readonly status: number;
  readonly code: string;
  readonly requestId: string;
  readonly details?: Record<string, unknown>;

  constructor(
    status: number,
    code: string,
    message: string,
    requestId = "",
    details?: Record<string, unknown>,
  ) {
    super(message);
    this.name = "ApiError";
    this.status = status;
    this.code = code;
    this.requestId = requestId;
    this.details = details;
  }

  /** True when the backend has no dataset loaded yet. */
  get isDataUnavailable(): boolean {
    return this.code === "data_unavailable";
  }
}

type QueryValue = string | number | boolean | undefined | null;

function buildUrl(path: string, params?: Record<string, QueryValue>): string {
  const url = `${BASE}${path}`;
  if (!params) return url;

  const search = new URLSearchParams();
  for (const [key, value] of Object.entries(params)) {
    if (value === undefined || value === null || value === "") continue;
    search.append(key, String(value));
  }
  const qs = search.toString();
  return qs ? `${url}?${qs}` : url;
}

async function toApiError(response: Response): Promise<ApiError> {
  let code = "http_error";
  let message = `${response.status} ${response.statusText}`;
  let requestId = response.headers.get("X-Request-ID") ?? "";
  let details: Record<string, unknown> | undefined;

  try {
    const body = await response.json();
    if (body?.error) {
      code = body.error.code ?? code;
      message = body.error.message ?? message;
      requestId = body.error.request_id ?? requestId;
      details = body.error.details;
    }
  } catch {
    // Non-JSON error body: keep the status-line message.
  }

  return new ApiError(response.status, code, message, requestId, details);
}

async function request<T>(
  path: string,
  params?: Record<string, QueryValue>,
  init?: RequestInit,
): Promise<T> {
  const response = await fetch(buildUrl(path, params), {
    headers: { Accept: "application/json", ...(init?.headers ?? {}) },
    ...init,
  });
  if (!response.ok) throw await toApiError(response);
  return (await response.json()) as T;
}

async function requestBinary(
  path: string,
  params?: Record<string, QueryValue>,
  signal?: AbortSignal,
): Promise<ArrayBuffer> {
  const response = await fetch(buildUrl(path, params), {
    headers: { Accept: "application/octet-stream" },
    signal,
  });
  if (!response.ok) throw await toApiError(response);
  return response.arrayBuffer();
}

/* ========================================================================== */
/* Health and catalog                                                         */
/* ========================================================================== */

export const getReady = (signal?: AbortSignal) =>
  request<ReadyState>("/health/ready", undefined, { signal });

export const getInfo = (signal?: AbortSignal) =>
  request<ServiceInfo>("/health/info", undefined, { signal });

export const listDatasets = (signal?: AbortSignal) =>
  request<{ count: number; default: string | null; datasets: DatasetInfo[] }>(
    "/datasets",
    undefined,
    { signal },
  );

export const getDataset = (id: string, signal?: AbortSignal) =>
  request<DatasetInfo>(`/datasets/${encodeURIComponent(id)}`, undefined, { signal });

export const getAxes = (id: string, signal?: AbortSignal) =>
  request<DatasetAxes>(`/datasets/${encodeURIComponent(id)}/axes`, undefined, {
    signal,
  });

export const listPlugins = (signal?: AbortSignal) =>
  request<{
    count: number;
    plugins: { name: string; kind: string; description: string; suffixes: string[] }[];
    entry_point_group: string;
  }>("/datasets/plugins", undefined, { signal });

/* ========================================================================== */
/* Fields                                                                     */
/* ========================================================================== */

export interface VolumeQuery {
  dataset?: string;
  variable: string;
  bbox?: string;
  depth_min?: number;
  depth_max?: number;
  time_index?: number;
  n_times?: number;
  stride?: number;
  depth_stride?: number;
  vmin?: number;
  vmax?: number;
  auto_stride?: boolean;
}

/** Fetch a quantised 4-D block, ready for plane rendering or texture upload. */
export async function getVolume(
  query: VolumeQuery,
  signal?: AbortSignal,
): Promise<OcvolBlock> {
  const buffer = await requestBinary("/fields/volume", { ...query }, signal);
  return decodeOcvol(buffer);
}

export async function getSliceBinary(
  query: {
    dataset?: string;
    variable: string;
    depth?: number;
    bbox?: string;
    time_index?: number;
    stride?: number;
    vmin?: number;
    vmax?: number;
  },
  signal?: AbortSignal,
): Promise<OcvolBlock> {
  const buffer = await requestBinary(
    "/fields/slice",
    { ...query, format: "binary" },
    signal,
  );
  return decodeOcvol(buffer);
}

export const getTransect = (
  query: {
    dataset?: string;
    variable: string;
    start_lat: number;
    start_lon: number;
    end_lat: number;
    end_lon: number;
    n_points?: number;
    depth_max?: number;
    time_index?: number;
  },
  signal?: AbortSignal,
) => request<TransectResult>("/fields/transect", query, { signal });

export const getPointProfile = (
  query: {
    dataset?: string;
    variable: string;
    lat: number;
    lon: number;
    time_index?: number;
  },
  signal?: AbortSignal,
) => request<PointProfile>("/fields/profile", query, { signal });

export const getTimeseries = (
  query: {
    dataset?: string;
    variable: string;
    lat: number;
    lon: number;
    depth?: number;
  },
  signal?: AbortSignal,
) =>
  request<{
    dataset: string;
    variable: string;
    units: string;
    location: { lat: number; lon: number };
    depth_m: number;
    times: string[];
    values: (number | null)[];
  }>("/fields/timeseries", query, { signal });

export const getHovmoller = (
  query: {
    dataset?: string;
    variable: string;
    lat: number;
    lon: number;
    depth_max?: number;
  },
  signal?: AbortSignal,
) =>
  request<{
    dataset: string;
    variable: string;
    units: string;
    location: { lat: number; lon: number };
    times: string[];
    depth_m: number[];
    values: (number | null)[][];
    colormap: string;
  }>("/fields/hovmoller", query, { signal });

/* ========================================================================== */
/* Observations                                                               */
/* ========================================================================== */

export const listPlatforms = (
  query: {
    bbox?: string;
    platform_type?: string;
    include_trajectory?: boolean;
    limit?: number;
    offset?: number;
  } = {},
  signal?: AbortSignal,
) =>
  request<{
    count: number;
    limit: number;
    offset: number;
    platform_types: string[];
    platforms: Platform[];
  }>("/observations/platforms", query, { signal });

export const getPlatform = (id: string, signal?: AbortSignal) =>
  request<Platform>(
    `/observations/platforms/${encodeURIComponent(id)}`,
    undefined,
    { signal },
  );

export const listProfiles = (
  query: {
    bbox?: string;
    start_time?: string;
    end_time?: string;
    limit?: number;
    offset?: number;
  } = {},
  signal?: AbortSignal,
) =>
  request<{ count: number; limit: number; offset: number; profiles: ProfileSummary[] }>(
    "/observations/profiles",
    query,
    { signal },
  );

export const getProfile = (id: number, signal?: AbortSignal) =>
  request<ProfileDetail>(`/observations/profiles/${id}`, undefined, { signal });

export const getObservationStatistics = (signal?: AbortSignal) =>
  request<ObservationStatistics>("/observations/statistics", undefined, { signal });

/* ========================================================================== */
/* Collocation - the core capability                                          */
/* ========================================================================== */

export const collocateProfile = (
  profileId: number,
  variable = "temperature",
  dataset?: string,
  signal?: AbortSignal,
) =>
  request<CollocationResult>(
    `/collocation/profile/${profileId}`,
    { variable, dataset },
    { signal },
  );

export const getBiasMap = (
  query: {
    variable?: string;
    dataset?: string;
    bbox?: string;
    depth_max?: number;
    limit?: number;
  } = {},
  signal?: AbortSignal,
) => request<BiasMap>("/collocation/bias-map", query, { signal });

export const getComparableVariables = (signal?: AbortSignal) =>
  request<{
    dataset: string;
    comparable: string[];
    observation_variables: string[];
    model_variables: string[];
  }>("/collocation/variables", undefined, { signal });

/* ========================================================================== */
/* Derived products                                                           */
/* ========================================================================== */

export const getMixedLayerDepth = (
  query: { dataset?: string; bbox?: string; time_index?: number; stride?: number } = {},
  signal?: AbortSignal,
) => request<DerivedGrid>("/derived/mixed-layer-depth", query, { signal });

export const getThermocline = (
  query: { dataset?: string; bbox?: string; time_index?: number; stride?: number } = {},
  signal?: AbortSignal,
) => request<DerivedGrid>("/derived/thermocline", query, { signal });

export const getAnomaly = (
  query: {
    dataset?: string;
    variable?: string;
    bbox?: string;
    depth?: number;
    time_index?: number;
    stride?: number;
    heatwave_threshold?: number;
  } = {},
  signal?: AbortSignal,
) => request<AnomalyResult>("/derived/anomaly", query, { signal });

export const getEddies = (
  query: {
    dataset?: string;
    bbox?: string;
    depth?: number;
    time_index?: number;
    stride?: number;
  } = {},
  signal?: AbortSignal,
) => request<EddyCensus>("/derived/eddies", query, { signal });

export interface DriftRequest {
  lat: number;
  lon: number;
  dataset?: string;
  depth?: number;
  time_index?: number;
  duration_hours?: number;
  n_particles?: number;
  timestep_minutes?: number;
  initial_spread_km?: number;
  diffusion_m2_s?: number;
  windage?: number;
  wind_u?: number;
  wind_v?: number;
  seed?: number;
}

export const simulateDrift = (body: DriftRequest, signal?: AbortSignal) =>
  request<DriftResult>("/derived/drift", undefined, {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify(body),
    signal,
  });

/* ========================================================================== */
/* Colour                                                                     */
/* ========================================================================== */

export const listColormaps = (signal?: AbortSignal) =>
  request<{
    count: number;
    groups: Record<string, string[]>;
    colormaps: ColormapEntry[];
  }>("/colormaps", undefined, { signal });

const lutCache = new Map<string, Uint8Array>();

/**
 * Fetch a 256-entry RGBA lookup table.
 *
 * Cached indefinitely: palettes never change at runtime, and this is on the
 * hot path for every recolour.
 */
export async function getLut(
  name: string,
  reverse = false,
  signal?: AbortSignal,
): Promise<Uint8Array> {
  const key = `${name}:${reverse}`;
  const cached = lutCache.get(key);
  if (cached) return cached;

  const buffer = await requestBinary("/colormaps/" + encodeURIComponent(name) + "/lut", { reverse }, signal);
  const table = new Uint8Array(buffer);
  lutCache.set(key, table);
  return table;
}

export const legendUrl = (
  name: string,
  vmin: number,
  vmax: number,
  label = "",
  horizontal = false,
) => buildUrl(`/colormaps/${encodeURIComponent(name)}/legend`, { vmin, vmax, label, horizontal });
