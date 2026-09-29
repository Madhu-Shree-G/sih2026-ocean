/**
 * Every server read the app makes, in one place.
 *
 * Views call these hooks rather than `useQuery` directly, so a key is defined
 * once and cannot drift between two screens that show the same number. React
 * Query deduplicates, so several views mounting the same hook costs one
 * request.
 */

import { useQuery } from "@tanstack/react-query";
import * as api from "@/lib/api";
import { bboxParam } from "@/lib/format";
import { DOMAIN } from "@/lib/cesium-setup";
import { useAppStore } from "@/state/store";
import type { OcvolBlock } from "./ocvol";

export const DOMAIN_BBOX = bboxParam(DOMAIN.west, DOMAIN.south, DOMAIN.east, DOMAIN.north);

/** Volume payloads are immutable for a given query, so cache them hard. */
const VOLUME_CACHE = { staleTime: 10 * 60_000, gcTime: 30 * 60_000 } as const;
const DERIVED_CACHE = { staleTime: 5 * 60_000 } as const;

/**
 * The backend refuses more than 60 timesteps in one volume request, so a
 * longer run comes back subsampled. Mapping the UI's index onto the block's
 * own axis keeps the map, the clock and the readouts on the same step; the
 * previous code capped at 20 and then indexed the block directly, which
 * silently showed the wrong day for any dataset longer than 20 steps.
 */
export const MAX_VOLUME_TIMES = 60;

export function volumeTimeIndex(
  timeIndex: number,
  axisLength: number,
  block: OcvolBlock | undefined,
): number {
  if (!block) return 0;
  if (block.nTime >= axisLength || axisLength <= 1) {
    return Math.min(Math.max(timeIndex, 0), block.nTime - 1);
  }
  const fraction = timeIndex / (axisLength - 1);
  return Math.min(block.nTime - 1, Math.max(0, Math.round(fraction * (block.nTime - 1))));
}

/* ========================================================================== */
/* Service                                                                    */
/* ========================================================================== */

export function useReady() {
  return useQuery({
    queryKey: ["ready"],
    queryFn: ({ signal }) => api.getReady(signal),
    retry: 1,
    refetchInterval: 60_000,
  });
}

export function useServiceInfo(enabled = true) {
  return useQuery({
    queryKey: ["info"],
    queryFn: ({ signal }) => api.getInfo(signal),
    enabled,
    staleTime: 60_000,
  });
}

export function useDatasets(enabled = true) {
  return useQuery({
    queryKey: ["datasets"],
    queryFn: ({ signal }) => api.listDatasets(signal),
    enabled,
    staleTime: Infinity,
  });
}

export function useDataset() {
  const datasetId = useAppStore((state) => state.datasetId);
  return useQuery({
    queryKey: ["dataset", datasetId],
    queryFn: ({ signal }) => api.getDataset(datasetId!, signal),
    enabled: Boolean(datasetId),
    staleTime: Infinity,
  });
}

export function useAxes() {
  const datasetId = useAppStore((state) => state.datasetId);
  return useQuery({
    queryKey: ["axes", datasetId],
    queryFn: ({ signal }) => api.getAxes(datasetId!, signal),
    enabled: Boolean(datasetId),
    staleTime: Infinity,
  });
}

export function usePlugins(enabled = true) {
  return useQuery({
    queryKey: ["plugins"],
    queryFn: ({ signal }) => api.listPlugins(signal),
    enabled,
    staleTime: Infinity,
  });
}

/* ========================================================================== */
/* Colour                                                                     */
/* ========================================================================== */

export function useLut(colormap: string) {
  return useQuery({
    queryKey: ["lut", colormap],
    queryFn: ({ signal }) => api.getLut(colormap, false, signal),
    staleTime: Infinity,
  });
}

export function useColormaps() {
  return useQuery({
    queryKey: ["colormaps"],
    queryFn: ({ signal }) => api.listColormaps(signal),
    staleTime: Infinity,
  });
}

/* ========================================================================== */
/* Fields                                                                     */
/* ========================================================================== */

export function useField(nTimes: number) {
  const datasetId = useAppStore((state) => state.datasetId);
  const variable = useAppStore((state) => state.variable);
  const requested = Math.min(nTimes, MAX_VOLUME_TIMES);

  return useQuery({
    queryKey: ["volume", datasetId, variable, requested],
    queryFn: ({ signal }) =>
      api.getVolume(
        {
          dataset: datasetId!,
          variable,
          bbox: DOMAIN_BBOX,
          n_times: requested,
          auto_stride: true,
        },
        signal,
      ),
    enabled: Boolean(datasetId) && Boolean(variable) && nTimes > 0,
    ...VOLUME_CACHE,
  });
}

export function useVelocity(nTimes: number) {
  const datasetId = useAppStore((state) => state.datasetId);
  const requested = Math.min(nTimes, MAX_VOLUME_TIMES);

  return useQuery({
    queryKey: ["velocity", datasetId, requested],
    queryFn: async ({ signal }) => {
      const [u, v] = await Promise.all([
        api.getVolume(
          { dataset: datasetId!, variable: "u", bbox: DOMAIN_BBOX, n_times: requested, stride: 2 },
          signal,
        ),
        api.getVolume(
          { dataset: datasetId!, variable: "v", bbox: DOMAIN_BBOX, n_times: requested, stride: 2 },
          signal,
        ),
      ]);
      return { u, v };
    },
    enabled: Boolean(datasetId) && nTimes > 0,
    ...VOLUME_CACHE,
  });
}

export function useTimeseries(
  point: { lat: number; lon: number } | null,
  depth = 0,
) {
  const datasetId = useAppStore((state) => state.datasetId);
  const variable = useAppStore((state) => state.variable);

  return useQuery({
    queryKey: ["timeseries", datasetId, variable, point?.lat, point?.lon, depth],
    queryFn: ({ signal }) =>
      api.getTimeseries(
        { dataset: datasetId!, variable, lat: point!.lat, lon: point!.lon, depth },
        signal,
      ),
    enabled: Boolean(datasetId) && point !== null,
    staleTime: 5 * 60_000,
  });
}

export function useTransect(
  line: { start: { lat: number; lon: number }; end: { lat: number; lon: number } } | null,
  timeIndex: number,
) {
  const datasetId = useAppStore((state) => state.datasetId);
  const variable = useAppStore((state) => state.variable);

  return useQuery({
    queryKey: [
      "transect",
      datasetId,
      variable,
      timeIndex,
      line?.start.lat,
      line?.start.lon,
      line?.end.lat,
      line?.end.lon,
    ],
    queryFn: ({ signal }) =>
      api.getTransect(
        {
          dataset: datasetId!,
          variable,
          start_lat: line!.start.lat,
          start_lon: line!.start.lon,
          end_lat: line!.end.lat,
          end_lon: line!.end.lon,
          n_points: 120,
          time_index: timeIndex,
        },
        signal,
      ),
    enabled: Boolean(datasetId) && line !== null,
    staleTime: 5 * 60_000,
  });
}

/* ========================================================================== */
/* Observations                                                               */
/* ========================================================================== */

export function usePlatforms(enabled: boolean) {
  return useQuery({
    queryKey: ["platforms"],
    queryFn: ({ signal }) => api.listPlatforms({ include_trajectory: true, limit: 400 }, signal),
    enabled,
    staleTime: 5 * 60_000,
  });
}

export function useObservationStatistics(enabled: boolean) {
  return useQuery({
    queryKey: ["obs-stats"],
    queryFn: ({ signal }) => api.getObservationStatistics(signal),
    enabled,
    staleTime: 5 * 60_000,
  });
}

export function useProfile(profileId: number | null) {
  return useQuery({
    queryKey: ["profile", profileId],
    queryFn: ({ signal }) => api.getProfile(profileId!, signal),
    enabled: profileId !== null,
    staleTime: 10 * 60_000,
  });
}

export function useComparableVariables(enabled: boolean) {
  return useQuery({
    queryKey: ["comparable"],
    queryFn: ({ signal }) => api.getComparableVariables(signal),
    enabled,
    staleTime: Infinity,
  });
}

/* ========================================================================== */
/* Collocation                                                                */
/* ========================================================================== */

export function useCollocation() {
  const datasetId = useAppStore((state) => state.datasetId);
  const profileId = useAppStore((state) => state.selectedProfileId);
  const variable = useAppStore((state) => state.collocationVariable);

  return useQuery({
    queryKey: ["collocation", profileId, variable, datasetId],
    queryFn: ({ signal }) =>
      api.collocateProfile(profileId!, variable, datasetId ?? undefined, signal),
    enabled: profileId !== null && Boolean(datasetId),
    retry: false,
  });
}

export function useBiasMap(enabled: boolean) {
  const datasetId = useAppStore((state) => state.datasetId);
  const variable = useAppStore((state) => state.collocationVariable);

  return useQuery({
    queryKey: ["bias", datasetId, variable],
    queryFn: ({ signal }) =>
      api.getBiasMap({ dataset: datasetId!, variable, limit: 200 }, signal),
    enabled: enabled && Boolean(datasetId),
    ...DERIVED_CACHE,
  });
}

/* ========================================================================== */
/* Derived products                                                           */
/* ========================================================================== */

export function useAnomaly(enabled: boolean) {
  const datasetId = useAppStore((state) => state.datasetId);
  const timeIndex = useAppStore((state) => state.timeIndex);

  return useQuery({
    queryKey: ["anomaly", datasetId, timeIndex],
    queryFn: ({ signal }) =>
      api.getAnomaly(
        {
          dataset: datasetId!,
          variable: "temperature",
          bbox: DOMAIN_BBOX,
          stride: 3,
          time_index: timeIndex,
        },
        signal,
      ),
    enabled: enabled && Boolean(datasetId),
    ...DERIVED_CACHE,
  });
}

export function useEddies(enabled: boolean) {
  const datasetId = useAppStore((state) => state.datasetId);
  const timeIndex = useAppStore((state) => state.timeIndex);

  // Note the key: time only. The census is computed at the surface, so keying
  // it on depth as well (as this once did) refetched an identical response
  // every time the depth slider moved.
  return useQuery({
    queryKey: ["eddies", datasetId, timeIndex],
    queryFn: ({ signal }) =>
      api.getEddies({ dataset: datasetId!, bbox: DOMAIN_BBOX, time_index: timeIndex }, signal),
    enabled: enabled && Boolean(datasetId),
    ...DERIVED_CACHE,
  });
}

export function useMixedLayerDepth(enabled: boolean) {
  const datasetId = useAppStore((state) => state.datasetId);
  const timeIndex = useAppStore((state) => state.timeIndex);

  return useQuery({
    queryKey: ["mld", datasetId, timeIndex],
    queryFn: ({ signal }) =>
      api.getMixedLayerDepth(
        { dataset: datasetId!, bbox: DOMAIN_BBOX, time_index: timeIndex, stride: 2 },
        signal,
      ),
    enabled: enabled && Boolean(datasetId),
    ...DERIVED_CACHE,
  });
}

export function useThermocline(enabled: boolean) {
  const datasetId = useAppStore((state) => state.datasetId);
  const timeIndex = useAppStore((state) => state.timeIndex);

  return useQuery({
    queryKey: ["thermocline", datasetId, timeIndex],
    queryFn: ({ signal }) =>
      api.getThermocline(
        { dataset: datasetId!, bbox: DOMAIN_BBOX, time_index: timeIndex, stride: 2 },
        signal,
      ),
    enabled: enabled && Boolean(datasetId),
    ...DERIVED_CACHE,
  });
}
