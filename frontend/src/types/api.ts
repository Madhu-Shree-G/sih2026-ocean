/** Response contracts for the OceanView3D backend (SIH26067). */

export interface ApiErrorBody {
  error: {
    code: string;
    message: string;
    request_id: string;
    details?: Record<string, unknown>;
  };
}

export interface VariableSpec {
  name: string;
  standard_name: string;
  long_name: string;
  units: string;
  default_colormap: string;
  default_range: [number, number] | null;
  vector_group: string | null;
}

export interface AxisInfo {
  size: number;
  min: number | string;
  max: number | string;
  units: string;
  values?: number[] | string[];
}

export interface DatasetInfo {
  id: string;
  title: string;
  summary: string;
  institution: string;
  source: string;
  conventions: string;
  adapter: string;
  bbox: { min_lon: number; min_lat: number; max_lon: number; max_lat: number };
  axes: Record<string, AxisInfo>;
  variables: VariableSpec[];
}

export interface DatasetAxes {
  dataset: string;
  depths: number[];
  times: string[];
  lat_range: [number, number];
  lon_range: [number, number];
  grid_shape: { lat: number; lon: number; depth: number; time: number };
}

export interface Platform {
  platform_id: string;
  platform_type: string;
  wmo_id: string | null;
  project: string | null;
  institution: string | null;
  status: string;
  profile_count: number;
  first_observation: string | null;
  last_observation: string | null;
  last_position: { lat: number; lon: number } | null;
  trajectory?: TrajectoryPoint[];
}

export interface TrajectoryPoint {
  cycle: number;
  time: string;
  lat: number;
  lon: number;
  profile_id: number;
}

export interface ProfileSummary {
  profile_id: number;
  platform_id: string | null;
  platform_type: string | null;
  cycle: number;
  time: string;
  location: { lat: number; lon: number };
  n_levels: number;
  max_depth_m: number;
  data_mode: string;
  surface_temperature: number | null;
  surface_salinity: number | null;
}

export interface ProfileDetail extends ProfileSummary {
  source_file: string | null;
  measurements: {
    depth_m: number[];
    temperature: (number | null)[];
    salinity: (number | null)[];
    chlorophyll: (number | null)[];
    oxygen: (number | null)[];
  };
}

export interface MatchStatistics {
  n_levels: number;
  bias: number | null;
  rmsd: number | null;
  mae: number | null;
  correlation: number | null;
  observation_mean: number | null;
  model_mean: number | null;
  max_abs_difference: number | null;
  depth_of_max_difference_m: number | null;
}

/** The response behind the platform's central interaction. */
export interface CollocationResult {
  variable: string;
  units: string;
  dataset: string;
  platform_id: string;
  location: { lat: number; lon: number };
  observation_time: string;
  model_time: string;
  time_offset_hours: number | null;
  grid_distance_km: number | null;
  profile: {
    depth_m: number[];
    observed: (number | null)[];
    modelled: (number | null)[];
    difference: (number | null)[];
  };
  statistics: MatchStatistics | null;
  warnings: string[];
  profile_id?: number;
  cycle?: number;
}

export interface BiasMarker {
  profile_id: number;
  platform_id: string;
  platform_type: string | null;
  lat: number;
  lon: number;
  time: string;
  bias: number | null;
  rmsd: number | null;
  n_levels: number;
}

export interface BiasMap {
  dataset: string;
  variable: string;
  units: string;
  depth_max_m: number;
  count: number;
  markers: BiasMarker[];
  summary: {
    profiles_matched: number;
    mean_bias: number | null;
    median_bias?: number | null;
    std_bias?: number | null;
    mean_rmsd: number | null;
    worst_platform: {
      platform_id: string;
      bias: number | null;
      lat: number;
      lon: number;
    } | null;
  };
  suggested_scale: { colormap: string; vmin: number; vmax: number };
}

export interface GridPayload {
  shape: [number, number];
  lats: number[];
  lons: number[];
  values: (number | null)[][];
}

export interface DerivedGrid {
  dataset: string;
  product: string;
  units?: string;
  method?: string;
  time: string;
  bbox: number[];
  value_range: [number | null, number | null];
  colormap: string;
  grid: GridPayload;
}

export interface AnomalyResult {
  dataset: string;
  product: string;
  variable: string;
  units: string;
  reference: string;
  reference_note: string | null;
  time: string;
  depth_m: number;
  bbox: number[];
  colormap: string;
  suggested_scale: { vmin: number; vmax: number };
  heatwave: {
    threshold: number;
    cells_flagged: number;
    cells_valid: number;
    area_fraction: number;
    max_anomaly: number;
    min_anomaly: number;
    mean_anomaly_in_event: number;
    mask: boolean[][];
  };
  grid: GridPayload;
}

export interface Eddy {
  id: number;
  centre: { lat: number; lon: number };
  polarity: "cyclonic" | "anticyclonic";
  radius_km: number;
  area_km2: number;
  "mean_vorticity_s-1": number;
  "max_speed_ms-1": number;
  "okubo_weiss_s-2": number;
}

export interface EddyCensus {
  dataset: string;
  product: string;
  method: string;
  time: string;
  depth_m: number;
  bbox: number[];
  count: number;
  cyclonic: number;
  anticyclonic: number;
  eddies: Eddy[];
}

export interface DriftResult {
  dataset: string;
  product: string;
  origin: { lat: number; lon: number };
  depth_m: number;
  model_time: string | null;
  times_hours: number[];
  /** [step][particle][lon, lat] */
  positions: number[][][];
  centroid: number[][];
  search_radius_km: number[];
  particles_stranded: number;
  n_particles: number;
  duration_hours: number;
  final_search_radius_km: number;
  final_centroid: number[] | null;
  disclaimer: string;
}

export interface TransectResult {
  dataset: string;
  variable: string;
  units: string;
  time: string | null;
  start: { lat: number; lon: number };
  end: { lat: number; lon: number };
  n_points: number;
  total_distance_km: number;
  distance_km: number[];
  track: { lat: number; lon: number }[];
  depth_m: number[];
  values: (number | null)[][];
  value_range: [number | null, number | null];
  colormap: string;
}

export interface PointProfile {
  dataset: string;
  variable: string;
  units: string;
  requested: { lat: number; lon: number };
  grid_point: { lat: number; lon: number };
  time: string | null;
  depth_m: number[];
  values: (number | null)[];
}

export interface ObservationStatistics {
  platforms: number;
  profiles: number;
  measurement_levels: number;
  platforms_by_type: Record<string, number>;
  time_coverage: { start: string | null; end: string | null };
}

export interface ServiceInfo {
  service: string;
  version: string;
  environment: string;
  datasets: string[];
  plugins: { name: string; kind: string; description: string; suffixes: string[] }[];
  capabilities: Record<string, boolean>;
  limits: Record<string, number>;
}

export interface ReadyState {
  status: "ready" | "degraded";
  checks: Record<string, string | number>;
  datasets: string[];
  hint: string | null;
}

export interface ColormapEntry {
  name: string;
  group: string;
  source: string;
  swatch: string[];
  reversible: boolean;
}

/** Alerts are derived client-side from the derived-product endpoints. */
export type AlertSeverity = "high" | "moderate" | "low";

export interface OceanAlert {
  id: string;
  title: string;
  location: string;
  severity: AlertSeverity;
  kind: "cyclone" | "heatwave" | "upwelling" | "eddy" | "bias";
  detail?: string;
  focus?: { lat: number; lon: number };
}
