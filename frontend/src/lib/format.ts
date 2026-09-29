/** Formatting helpers shared across panels. */

/** "15 Mar 2024, 12:00 UTC" — the header's timestamp format. */
export function formatUtc(iso: string | null | undefined): string {
  if (!iso) return "—";
  const date = new Date(iso);
  if (Number.isNaN(date.getTime())) return "—";

  const day = String(date.getUTCDate()).padStart(2, "0");
  const month = date.toLocaleString("en-GB", { month: "short", timeZone: "UTC" });
  const hours = String(date.getUTCHours()).padStart(2, "0");
  const minutes = String(date.getUTCMinutes()).padStart(2, "0");
  return `${day} ${month} ${date.getUTCFullYear()}, ${hours}:${minutes} UTC`;
}

/** "01 Mar 2024" — the time scrubber's endpoint labels. */
export function formatDate(iso: string | null | undefined): string {
  if (!iso) return "—";
  const date = new Date(iso);
  if (Number.isNaN(date.getTime())) return "—";
  const day = String(date.getUTCDate()).padStart(2, "0");
  const month = date.toLocaleString("en-GB", { month: "short", timeZone: "UTC" });
  return `${day} ${month} ${date.getUTCFullYear()}`;
}

/** "12.85° N, 80.33° E" — signed decimal degrees to hemisphere notation. */
export function formatLatLon(lat: number, lon: number, digits = 2): string {
  const ns = lat >= 0 ? "N" : "S";
  const ew = lon >= 0 ? "E" : "W";
  return `${Math.abs(lat).toFixed(digits)}° ${ns}, ${Math.abs(lon).toFixed(digits)}° ${ew}`;
}

/** Axis tick label: "25°N", "5°N", "15°S". */
export function formatLatTick(lat: number): string {
  if (Math.abs(lat) < 0.001) return "0°";
  return `${Math.abs(Math.round(lat))}°${lat >= 0 ? "N" : "S"}`;
}

export function formatLonTick(lon: number): string {
  const wrapped = ((lon + 180) % 360 + 360) % 360 - 180;
  if (Math.abs(wrapped) < 0.001) return "0°";
  return `${Math.abs(Math.round(wrapped))}°${wrapped >= 0 ? "E" : "W"}`;
}

/** Numeric value with fixed precision, or an em dash when absent. */
export function formatValue(
  value: number | null | undefined,
  digits = 2,
  suffix = "",
): string {
  if (value === null || value === undefined || !Number.isFinite(value)) return "—";
  return `${value.toFixed(digits)}${suffix}`;
}

/** Signed value, so a bias always shows its direction: "-0.18 °C". */
export function formatSigned(
  value: number | null | undefined,
  digits = 2,
  suffix = "",
): string {
  if (value === null || value === undefined || !Number.isFinite(value)) return "—";
  const sign = value > 0 ? "+" : "";
  return `${sign}${value.toFixed(digits)}${suffix}`;
}

/** Depth for display: metres below 1 km, kilometres above. */
export function formatDepth(metres: number): string {
  if (!Number.isFinite(metres)) return "—";
  if (metres < 1000) return `${Math.round(metres)} m`;
  return `${(metres / 1000).toFixed(2)} km`;
}

export function clamp(value: number, min: number, max: number): number {
  return value < min ? min : value > max ? max : value;
}

/** Evenly spaced ticks across a range, for colorbars and axes. */
export function niceTicks(min: number, max: number, count = 6): number[] {
  if (!Number.isFinite(min) || !Number.isFinite(max) || max <= min) return [min, max];
  const step = (max - min) / (count - 1);
  return Array.from({ length: count }, (_, i) => min + i * step);
}

/** Compact tick label that avoids trailing zeros on round numbers. */
export function tickLabel(value: number): string {
  if (!Number.isFinite(value)) return "";
  const abs = Math.abs(value);
  if (abs >= 100) return value.toFixed(0);
  if (abs >= 10) return value.toFixed(Number.isInteger(value) ? 0 : 1);
  if (abs >= 1) return value.toFixed(Number.isInteger(value) ? 0 : 1);
  return value.toFixed(2);
}

/** "argo_float" -> "Argo Float" for display in lists and tooltips. */
export function titleCase(value: string): string {
  return value
    .replace(/[_-]+/g, " ")
    .replace(/\b\w/g, (c) => c.toUpperCase());
}

export function platformLabel(type: string | null | undefined): string {
  switch (type) {
    case "argo_float":
      return "Argo Float";
    case "ctd":
      return "CTD Cast";
    case "glider":
      return "Glider";
    case "mooring":
      return "Mooring";
    case "adcp":
      return "ADCP";
    case "drifter":
      return "Drifter";
    default:
      return titleCase(type ?? "Platform");
  }
}

/** bbox string in OGC order, as the API expects it. */
export function bboxParam(
  minLon: number,
  minLat: number,
  maxLon: number,
  maxLat: number,
): string {
  return `${minLon.toFixed(4)},${minLat.toFixed(4)},${maxLon.toFixed(4)},${maxLat.toFixed(4)}`;
}

/**
 * CF unit strings are precise but unreadable on screen: "degree_Celsius",
 * "m s-1", "mg m-3". Map them to the symbols an oceanographer expects, and
 * pass anything unrecognised through unchanged rather than mangling it.
 */
const UNIT_SYMBOLS: Record<string, string> = {
  degree_celsius: "°C",
  degrees_celsius: "°C",
  celsius: "°C",
  degc: "°C",
  psu: "psu",
  "1e-3": "psu",
  "m s-1": "m/s",
  "m/s": "m/s",
  "mg m-3": "mg/m³",
  "kg m-3": "kg/m³",
  "micromole kg-1": "µmol/kg",
  "mmol m-3": "mmol/m³",
  m: "m",
  metres: "m",
  meters: "m",
  db: "dbar",
  decibar: "dbar",
  degrees_north: "°N",
  degrees_east: "°E",
  "1": "",
};

export function formatUnits(units: string | null | undefined): string {
  if (!units) return "";
  return UNIT_SYMBOLS[units.trim().toLowerCase()] ?? units;
}

/**
 * Short display name for a variable. The CF long_name ("Sea water potential
 * temperature") is correct but too long for a colorbar or a dropdown.
 */
const SHORT_NAMES: Record<string, string> = {
  temperature: "Temperature",
  salinity: "Salinity",
  chlorophyll: "Chlorophyll",
  oxygen: "Dissolved Oxygen",
  ssh: "Sea Surface Height",
  u: "Eastward Current",
  v: "Northward Current",
  bathymetry: "Bathymetry",
};

export function shortName(name: string, fallback?: string): string {
  return SHORT_NAMES[name] ?? fallback ?? titleCase(name);
}

/** "Temperature (°C)" — the label used on the colorbar and variable picker. */
export function variableLabel(
  name: string,
  units: string | null | undefined,
  fallback?: string,
): string {
  const symbol = formatUnits(units);
  const label = shortName(name, fallback);
  return symbol ? `${label} (${symbol})` : label;
}
