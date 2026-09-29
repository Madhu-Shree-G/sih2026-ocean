/**
 * Derive operational alerts from the anomaly field and eddy census.
 *
 * These are computed from real backend responses rather than hard-coded, so
 * the alert list actually changes as you scrub through time - which is the
 * whole point of showing it. A static list would be decoration.
 */

import type { AnomalyResult, EddyCensus, OceanAlert, AlertSeverity } from "@/types/api";
import { formatUnits } from "./format";

interface Region {
  name: string;
  minLon: number;
  maxLon: number;
  minLat: number;
  maxLat: number;
}

/** Named basins used to describe where an event is happening. */
const REGIONS: Region[] = [
  { name: "Bay of Bengal", minLon: 80, maxLon: 95, minLat: 5, maxLat: 23 },
  { name: "Arabian Sea", minLon: 55, maxLon: 78, minLat: 5, maxLat: 26 },
  { name: "Somali Coast", minLon: 45, maxLon: 56, minLat: -2, maxLat: 13 },
  { name: "Andaman Sea", minLon: 92, maxLon: 100, minLat: 5, maxLat: 20 },
  { name: "Laccadive Sea", minLon: 70, maxLon: 80, minLat: 5, maxLat: 14 },
  { name: "Equatorial Indian Ocean", minLon: 55, maxLon: 100, minLat: -5, maxLat: 5 },
  { name: "Southern Indian Ocean", minLon: 55, maxLon: 100, minLat: -12, maxLat: -5 },
];

export function regionFor(lat: number, lon: number): string {
  for (const region of REGIONS) {
    if (
      lon >= region.minLon &&
      lon <= region.maxLon &&
      lat >= region.minLat &&
      lat <= region.maxLat
    ) {
      return region.name;
    }
  }
  return "Indian Ocean";
}

interface Extremum {
  lat: number;
  lon: number;
  value: number;
  cells: number;
}

/**
 * Find the strongest positive and negative excursions in an anomaly grid,
 * counting how many cells exceed the threshold near each.
 */
function findExtrema(anomaly: AnomalyResult, threshold: number): {
  warm: Extremum | null;
  cool: Extremum | null;
} {
  const { lats, lons, values } = anomaly.grid;
  let warm: Extremum | null = null;
  let cool: Extremum | null = null;
  let warmCells = 0;
  let coolCells = 0;

  for (let y = 0; y < values.length; y++) {
    const row = values[y];
    if (!row) continue;
    for (let x = 0; x < row.length; x++) {
      const value = row[x];
      if (value === null || !Number.isFinite(value)) continue;

      if (value >= threshold) {
        warmCells++;
        if (!warm || value > warm.value) {
          warm = { lat: lats[y], lon: lons[x], value, cells: 0 };
        }
      } else if (value <= -threshold) {
        coolCells++;
        if (!cool || value < cool.value) {
          cool = { lat: lats[y], lon: lons[x], value, cells: 0 };
        }
      }
    }
  }

  if (warm) warm.cells = warmCells;
  if (cool) cool.cells = coolCells;
  return { warm, cool };
}

/** Severity from how far the anomaly runs past the alert threshold. */
function severityFor(magnitude: number, threshold: number): AlertSeverity {
  if (magnitude >= threshold * 2.2) return "high";
  if (magnitude >= threshold * 1.3) return "moderate";
  return "low";
}

export function deriveAlerts(
  anomaly: AnomalyResult | undefined,
  eddies: EddyCensus | undefined,
  options: { threshold?: number } = {},
): OceanAlert[] {
  const threshold = options.threshold ?? 1.0;
  const alerts: OceanAlert[] = [];

  if (anomaly) {
    const { warm, cool } = findExtrema(anomaly, threshold);

    // A strong cold anomaly in the Bay of Bengal during cyclone season reads
    // as a storm cold wake; elsewhere the same signature is upwelling.
    if (cool) {
      const region = regionFor(cool.lat, cool.lon);
      const isBay = region === "Bay of Bengal" || region === "Andaman Sea";
      alerts.push({
        id: `cool-${cool.lat.toFixed(2)}-${cool.lon.toFixed(2)}`,
        title: isBay ? "Cyclone Cold Wake" : "Upwelling Event",
        location: region,
        severity: severityFor(Math.abs(cool.value), threshold),
        kind: isBay ? "cyclone" : "upwelling",
        detail: `${cool.value.toFixed(2)} ${formatUnits(anomaly.units)} below normal across ${cool.cells} cells`,
        focus: { lat: cool.lat, lon: cool.lon },
      });
    }

    if (warm && anomaly.heatwave.cells_flagged > 0) {
      alerts.push({
        id: `heatwave-${warm.lat.toFixed(2)}-${warm.lon.toFixed(2)}`,
        title: "Marine Heatwave",
        location: `${regionFor(warm.lat, warm.lon)} (${warm.lon.toFixed(1)}°E, ${warm.lat.toFixed(1)}°N)`,
        severity: severityFor(warm.value, threshold),
        kind: "heatwave",
        detail: `+${warm.value.toFixed(2)} ${formatUnits(anomaly.units)} peak, ${(anomaly.heatwave.area_fraction * 100).toFixed(1)}% of area`,
        focus: { lat: warm.lat, lon: warm.lon },
      });
    }
  }

  // Surface the single most energetic eddy: it is what a fishery advisory
  // would key on, and it gives the alert list a third, non-thermal entry.
  if (eddies && eddies.eddies.length > 0) {
    const strongest = eddies.eddies.reduce((best, current) =>
      current["max_speed_ms-1"] > best["max_speed_ms-1"] ? current : best,
    );
    if (strongest["max_speed_ms-1"] >= 0.5) {
      alerts.push({
        id: `eddy-${strongest.id}`,
        title: `${strongest.polarity === "cyclonic" ? "Cyclonic" : "Anticyclonic"} Eddy`,
        location: regionFor(strongest.centre.lat, strongest.centre.lon),
        severity: strongest["max_speed_ms-1"] >= 0.9 ? "moderate" : "low",
        kind: "eddy",
        detail: `${strongest.radius_km.toFixed(0)} km radius, ${strongest["max_speed_ms-1"].toFixed(2)} m/s peak`,
        focus: strongest.centre,
      });
    }
  }

  const rank: Record<AlertSeverity, number> = { high: 0, moderate: 1, low: 2 };
  return alerts.sort((a, b) => rank[a.severity] - rank[b.severity]);
}

export const SEVERITY_LABEL: Record<AlertSeverity, string> = {
  high: "High",
  moderate: "Moderate",
  low: "Low",
};
