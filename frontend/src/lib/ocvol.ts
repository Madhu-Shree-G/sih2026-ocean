/**
 * OCVOL1 container decoder.
 *
 * The backend ships gridded fields as uint8 quantised blocks rather than JSON
 * numbers: a 512x512x40 float32 cube is 42 MiB per variable per timestep,
 * where the same cube quantised to uint8 is 10 MiB. The precision lost is
 * below what a colour ramp can resolve.
 *
 * Wire format
 *   offset  size  content
 *   0       8     magic "OCVOL1\0\0"
 *   8       4     uint32 LE header length H
 *   12      H     UTF-8 JSON header
 *   12+H    N     uint8 payload, C-order [time][depth][lat][lon]
 *
 * Reconstruction, matching the shader:
 *   value = offset + (raw - minValidRaw) * scale      raw === nodataRaw -> NaN
 */

const MAGIC = "OCVOL1\0\0";

export interface OcvolHeader {
  format: string;
  dataset: string;
  variable: string;
  units: string;
  dtype: string;
  /** [time, depth, lat, lon] for volumes; [lat, lon] for slices. */
  shape: number[];
  axis_order: string[];
  scale: number;
  offset: number;
  nodata_raw: number;
  min_valid_raw: number;
  value_range: [number, number];
  colormap: string;
  bbox: [number, number, number, number];
  lat_range: [number, number];
  lon_range: [number, number];
  depths?: number[];
  times?: string[];
  depth_m?: number;
  time?: string;
  nodata_count?: number;
  actual_range?: [number, number];
  long_name?: string;
  stride?: number;
}

export interface OcvolBlock {
  header: OcvolHeader;
  data: Uint8Array;
  /** Convenience accessors, normalised across volume and slice payloads. */
  nTime: number;
  nDepth: number;
  nLat: number;
  nLon: number;
}

export class OcvolError extends Error {
  constructor(message: string) {
    super(message);
    this.name = "OcvolError";
  }
}

/** Decode an OCVOL1 buffer into its header and raw uint8 payload. */
export function decodeOcvol(buffer: ArrayBuffer): OcvolBlock {
  if (buffer.byteLength < 12) {
    throw new OcvolError("Buffer too short to be an OCVOL1 container.");
  }

  const bytes = new Uint8Array(buffer);
  const magic = String.fromCharCode(...bytes.subarray(0, 8));
  if (magic !== MAGIC) {
    throw new OcvolError("Bad magic: response is not an OCVOL1 container.");
  }

  const view = new DataView(buffer);
  const headerLength = view.getUint32(8, true);
  const headerStart = 12;
  const payloadStart = headerStart + headerLength;

  if (payloadStart > buffer.byteLength) {
    throw new OcvolError("Declared header length exceeds the buffer.");
  }

  const headerText = new TextDecoder("utf-8").decode(
    bytes.subarray(headerStart, payloadStart),
  );

  let header: OcvolHeader;
  try {
    header = JSON.parse(headerText) as OcvolHeader;
  } catch {
    throw new OcvolError("OCVOL1 header is not valid JSON.");
  }

  const data = bytes.subarray(payloadStart);
  const expected = header.shape.reduce((a, b) => a * b, 1);
  if (data.length < expected) {
    throw new OcvolError(
      `Payload is ${data.length} bytes but the header declares ${expected}.`,
    );
  }

  // Slices arrive as [lat, lon]; volumes as [time, depth, lat, lon]. Normalise
  // so callers never have to branch on which endpoint produced the block.
  const s = header.shape;
  const [nTime, nDepth, nLat, nLon] =
    s.length === 4 ? s : s.length === 3 ? [1, s[0], s[1], s[2]] : [1, 1, s[0], s[1]];

  return { header, data, nTime, nDepth, nLat, nLon };
}

/** Physical value at a cell, or NaN where there is no data. */
export function valueAt(block: OcvolBlock, index: number): number {
  const raw = block.data[index];
  if (raw === block.header.nodata_raw) return NaN;
  return (
    block.header.offset + (raw - block.header.min_valid_raw) * block.header.scale
  );
}

/** Flat index into the payload for a (time, depth, lat, lon) cell. */
export function cellIndex(
  block: OcvolBlock,
  t: number,
  z: number,
  y: number,
  x: number,
): number {
  return ((t * block.nDepth + z) * block.nLat + y) * block.nLon + x;
}

/**
 * Physical value at a geographic position, or NaN outside the block.
 * Nearest-neighbour: a scientific readout must never invent a value between
 * two grid cells.
 */
export function sampleAt(
  block: OcvolBlock,
  lat: number,
  lon: number,
  t = 0,
  z = 0,
): number {
  const [latMin, latMax] = block.header.lat_range;
  const [lonMin, lonMax] = block.header.lon_range;
  if (lat < latMin || lat > latMax || lon < lonMin || lon > lonMax) return NaN;

  const fy = (lat - latMin) / (latMax - latMin || 1);
  const fx = (lon - lonMin) / (lonMax - lonMin || 1);
  const y = Math.min(block.nLat - 1, Math.max(0, Math.round(fy * (block.nLat - 1))));
  const x = Math.min(block.nLon - 1, Math.max(0, Math.round(fx * (block.nLon - 1))));

  return valueAt(block, cellIndex(block, t, z, y, x));
}

/**
 * Render one (time, depth) plane to RGBA pixels using a 256-entry LUT.
 *
 * This is the function that makes the UI feel instant. Changing depth, time or
 * the colour range re-runs only this - no network request - because the whole
 * quantised volume already sits in memory.
 *
 * Rows are emitted north-up (image order), inverting the ascending-latitude
 * storage order.
 */
export function renderPlaneToImageData(
  block: OcvolBlock,
  lut: Uint8Array,
  options: { time?: number; depth?: number; vmin?: number; vmax?: number } = {},
): ImageData {
  const { time = 0, depth = 0 } = options;
  const { nLat, nLon, header } = block;

  const lo = options.vmin ?? header.value_range[0];
  const hi = options.vmax ?? header.value_range[1];
  const span = hi - lo || 1;

  const t = Math.min(Math.max(time, 0), block.nTime - 1);
  const z = Math.min(Math.max(depth, 0), block.nDepth - 1);

  const pixels = new Uint8ClampedArray(nLat * nLon * 4);
  const planeStart = (t * block.nDepth + z) * nLat * nLon;

  for (let y = 0; y < nLat; y++) {
    // Flip vertically: array row 0 is the southernmost latitude.
    const srcRow = planeStart + (nLat - 1 - y) * nLon;
    const dstRow = y * nLon * 4;

    for (let x = 0; x < nLon; x++) {
      const raw = block.data[srcRow + x];
      const out = dstRow + x * 4;

      if (raw === header.nodata_raw) {
        pixels[out + 3] = 0; // land / below seafloor -> transparent
        continue;
      }

      const value = header.offset + (raw - header.min_valid_raw) * header.scale;
      let normalised = (value - lo) / span;
      normalised = normalised < 0 ? 0 : normalised > 1 ? 1 : normalised;

      const entry = (normalised * 255) << 2;
      pixels[out] = lut[entry];
      pixels[out + 1] = lut[entry + 1];
      pixels[out + 2] = lut[entry + 2];
      pixels[out + 3] = 255;
    }
  }

  return new ImageData(pixels, nLon, nLat);
}

/** Render a plane onto a canvas, resizing it to the block's grid. */
export function renderPlaneToCanvas(
  block: OcvolBlock,
  lut: Uint8Array,
  options: { time?: number; depth?: number; vmin?: number; vmax?: number } = {},
  target?: HTMLCanvasElement,
): HTMLCanvasElement {
  const canvas = target ?? document.createElement("canvas");
  canvas.width = block.nLon;
  canvas.height = block.nLat;

  const context = canvas.getContext("2d", { willReadFrequently: false });
  if (!context) throw new OcvolError("Could not acquire a 2D canvas context.");

  context.putImageData(renderPlaneToImageData(block, lut, options), 0, 0);
  return canvas;
}

/** Decode a whole plane to Float32, NaN where there is no data. */
export function planeToFloat32(
  block: OcvolBlock,
  time = 0,
  depth = 0,
): Float32Array {
  const { nLat, nLon, header } = block;
  const out = new Float32Array(nLat * nLon);
  const planeStart = (time * block.nDepth + depth) * nLat * nLon;

  for (let i = 0; i < out.length; i++) {
    const raw = block.data[planeStart + i];
    out[i] =
      raw === header.nodata_raw
        ? NaN
        : header.offset + (raw - header.min_valid_raw) * header.scale;
  }
  return out;
}

/**
 * Robust value range for one plane, from percentiles rather than min/max.
 *
 * A colour ramp stretched to absolute extremes is at the mercy of a single
 * anomalous cell, which flattens every real gradient. Trimming the tails is
 * what scientific viewers do, and it is what makes a basin-scale field show
 * structure instead of one flat wash of colour.
 */
export function planePercentileRange(
  block: OcvolBlock,
  options: { time?: number; depth?: number; low?: number; high?: number } = {},
): [number, number] | null {
  const { time = 0, depth = 0, low = 0.02, high = 0.98 } = options;

  const { nLat, nLon, header } = block;
  const planeStart = (time * block.nDepth + depth) * nLat * nLon;
  const planeSize = nLat * nLon;

  // Work on the raw uint8 values: they are already monotonic in the physical
  // value, so a histogram over 256 bins is exact and needs no sorting.
  const histogram = new Uint32Array(256);
  let count = 0;

  for (let i = 0; i < planeSize; i++) {
    const raw = block.data[planeStart + i];
    if (raw === header.nodata_raw) continue;
    histogram[raw]++;
    count++;
  }

  if (count === 0) return null;

  const target = (fraction: number): number => {
    const wanted = fraction * count;
    let seen = 0;
    for (let raw = 0; raw < 256; raw++) {
      seen += histogram[raw];
      if (seen >= wanted) return raw;
    }
    return 255;
  };

  const toValue = (raw: number) =>
    header.offset + (raw - header.min_valid_raw) * header.scale;

  let lo = toValue(target(low));
  let hi = toValue(target(high));

  if (!(hi > lo)) {
    const centre = (lo + hi) / 2;
    lo = centre - 0.5;
    hi = centre + 0.5;
  }
  return [lo, hi];
}

/** Round a range to readable colorbar endpoints. */
export function roundRange([lo, hi]: [number, number]): [number, number] {
  const span = hi - lo;
  const step =
    span > 50 ? 5 : span > 20 ? 2 : span > 5 ? 1 : span > 1 ? 0.5 : span > 0.2 ? 0.1 : 0.01;
  return [Math.floor(lo / step) * step, Math.ceil(hi / step) * step];
}
