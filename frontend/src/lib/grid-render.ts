/**
 * Painting the JSON derived-product grids (anomaly, mixed-layer depth,
 * thermocline) onto a canvas so they can go on the globe as imagery.
 *
 * The main model fields arrive quantised in an OCVOL block and are painted by
 * `ocvol.ts`. The derived products arrive as plain JSON grids with nulls for
 * land, which is a different shape and gets its own small renderer rather than
 * a branch inside the hot path.
 */

import type { GridPayload } from "@/types/api";

export interface Ramp {
  /** Stops from 0 to 1, as [position, r, g, b]. */
  stops: [number, number, number, number][];
}

/**
 * Blue-white-red, centred on zero. The convention for anomalies: white is
 * "as expected", and the eye reads distance from white as distance from
 * normal in either direction.
 */
export const DIVERGING: Ramp = {
  stops: [
    [0.0, 33, 78, 138],
    [0.25, 84, 148, 199],
    [0.5, 247, 247, 247],
    [0.75, 222, 118, 84],
    [1.0, 155, 25, 30],
  ],
};

/** Shallow-to-deep, for mixed-layer depth and thermocline depth. */
export const DEPTH_RAMP: Ramp = {
  stops: [
    [0.0, 231, 245, 236],
    [0.35, 122, 197, 178],
    [0.7, 40, 116, 154],
    [1.0, 17, 40, 92],
  ],
};

function sample(ramp: Ramp, t: number): [number, number, number] {
  const clamped = t < 0 ? 0 : t > 1 ? 1 : t;
  const { stops } = ramp;

  for (let i = 1; i < stops.length; i++) {
    const [pos, r, g, b] = stops[i];
    if (clamped <= pos) {
      const [prevPos, pr, pg, pb] = stops[i - 1];
      const span = pos - prevPos || 1;
      const f = (clamped - prevPos) / span;
      return [pr + (r - pr) * f, pg + (g - pg) * f, pb + (b - pb) * f];
    }
  }
  const last = stops[stops.length - 1];
  return [last[1], last[2], last[3]];
}

export function rampCss(ramp: Ramp): string {
  const stops = ramp.stops.map(
    ([position, r, g, b]) => `rgb(${r}, ${g}, ${b}) ${(position * 100).toFixed(0)}%`,
  );
  return `linear-gradient(90deg, ${stops.join(", ")})`;
}

/**
 * Render a derived grid to a canvas, north-up.
 *
 * `null` cells become fully transparent rather than a colour, so land and
 * below-seafloor stay as the basemap instead of being painted over with a
 * value that does not exist.
 */
export function renderGridToCanvas(
  grid: GridPayload,
  range: [number, number],
  ramp: Ramp,
  alpha = 235,
): HTMLCanvasElement | null {
  const height = grid.values.length;
  const width = grid.values[0]?.length ?? 0;
  if (height === 0 || width === 0) return null;

  const [lo, hi] = range;
  const span = hi - lo || 1;

  const pixels = new Uint8ClampedArray(width * height * 4);
  // The grid's first row is the southernmost latitude; images run north-down.
  const northUp = grid.lats[0] < grid.lats[grid.lats.length - 1];

  for (let y = 0; y < height; y++) {
    const row = grid.values[northUp ? height - 1 - y : y];
    if (!row) continue;

    for (let x = 0; x < width; x++) {
      const value = row[x];
      const out = (y * width + x) * 4;
      if (value === null || !Number.isFinite(value)) {
        pixels[out + 3] = 0;
        continue;
      }
      const [r, g, b] = sample(ramp, (value - lo) / span);
      pixels[out] = r;
      pixels[out + 1] = g;
      pixels[out + 2] = b;
      pixels[out + 3] = alpha;
    }
  }

  const canvas = document.createElement("canvas");
  canvas.width = width;
  canvas.height = height;
  const context = canvas.getContext("2d");
  if (!context) return null;
  context.putImageData(new ImageData(pixels, width, height), 0, 0);
  return canvas;
}

/** Geographic extent of a grid, in the order Cesium's Rectangle wants. */
export function gridExtent(grid: GridPayload): [number, number, number, number] {
  const lats = grid.lats;
  const lons = grid.lons;
  return [
    Math.min(lons[0], lons[lons.length - 1]),
    Math.min(lats[0], lats[lats.length - 1]),
    Math.max(lons[0], lons[lons.length - 1]),
    Math.max(lats[0], lats[lats.length - 1]),
  ];
}

/** A symmetric range around zero, so the diverging ramp stays centred. */
export function symmetricRange(
  values: [number | null, number | null],
  fallback = 1,
): [number, number] {
  const magnitude = Math.max(
    Math.abs(values[0] ?? 0),
    Math.abs(values[1] ?? 0),
    0.001,
  );
  const limit = Number.isFinite(magnitude) ? magnitude : fallback;
  return [-limit, limit];
}
