/**
 * Deep's avatar geometry — a leaping dolphin rendered as particles.
 *
 * The body is built as a tapered tube: a centreline sampled at intervals,
 * with a half-width at each sample, rasterised as a union of discs. Defining
 * the body by its spine rather than its outline is what keeps the crescent of
 * a leaping dolphin correct — an outline path tends to close across the arc
 * and fill the hollow, which reads as a blob rather than an animal.
 *
 * Fins and flukes are separate filled paths layered on top. The whole
 * silhouette is rasterised once, then sampled on a jittered grid to produce
 * the halftone particle cloud of the reference artwork.
 */

export const DOLPHIN_VIEWBOX = 1000;

/**
 * Body spine, rostrum to tail stock: ``[x, y, halfWidth]``.
 * The dolphin faces right and arcs down to the left, tail below.
 */
const SPINE: [number, number, number][] = [
  [948, 492, 13],
  [924, 484, 21],
  [900, 474, 31],
  [872, 461, 44],
  [842, 445, 57],
  [812, 428, 68],
  [778, 404, 82],
  [742, 376, 95],
  [702, 350, 107],
  [656, 330, 118],
  [604, 316, 127],
  [548, 308, 133],
  [492, 308, 136],
  [438, 318, 136],
  [388, 338, 132],
  [346, 366, 126],
  [314, 402, 119],
  [292, 444, 112],
  [280, 490, 105],
  [277, 538, 98],
  [284, 588, 91],
  [300, 638, 83],
  [322, 686, 75],
  [348, 732, 67],
  [376, 776, 58],
  [402, 816, 49],
  [424, 852, 40],
  [440, 882, 32],
];

/** Dorsal fin, swept back over the shoulder of the arc. */
export const DOLPHIN_DORSAL = `
M 392 212
C 368 174 350 134 344 104
C 341 90 357 82 366 94
C 404 140 452 184 496 212
Z
`;

/** Pectoral fin, hanging from the belly below the shoulder. */
export const DOLPHIN_PECTORAL = `
M 600 438
C 628 500 662 554 708 590
C 670 602 628 586 596 552
C 566 522 550 478 552 444
Z
`;

/** Tail flukes, spread either side of the stock. */
export const DOLPHIN_FLUKES = `
M 442 858
C 382 878 302 916 264 970
C 240 1004 254 1046 298 1050
C 352 1054 412 1018 444 970
C 482 1006 548 1024 598 1008
C 640 994 648 950 612 924
C 568 892 498 876 450 884
Z
`;

/** Eye highlight, placed as a single bright particle. */
export const DOLPHIN_EYE: [number, number] = [812, 410];

export interface Particle {
  /** Target position, in viewBox units. */
  x: number;
  y: number;
  /** Scattered origin, also in viewBox units. */
  ox: number;
  oy: number;
  radius: number;
  color: string;
  /** 0..1 stagger, so the silhouette resolves nose-first. */
  delay: number;
  /** Accent particles that pulse; used sparingly. */
  spark: boolean;
}

/** Palette sampled from the reference artwork: deep navy through bright cyan. */
const PALETTE = [
  "#0b3a86",
  "#134da3",
  "#1a60c0",
  "#2274d9",
  "#2d89ec",
  "#3aa1fa",
  "#53b8ff",
  "#82d4ff",
];

function hashNoise(x: number, y: number): number {
  const value = Math.sin(x * 12.9898 + y * 78.233) * 43758.5453;
  return value - Math.floor(value);
}

/** Rasterise the full silhouette into an alpha mask. */
function rasterise(size: number): Uint8ClampedArray | null {
  const canvas = document.createElement("canvas");
  canvas.width = size;
  canvas.height = size;

  const context = canvas.getContext("2d", { willReadFrequently: true });
  if (!context) return null;

  const scale = size / DOLPHIN_VIEWBOX;
  context.scale(scale, scale);
  context.fillStyle = "#fff";

  // Body: union of discs along the spine, interpolated so the tube is smooth.
  for (let i = 0; i < SPINE.length - 1; i++) {
    const [x0, y0, w0] = SPINE[i];
    const [x1, y1, w1] = SPINE[i + 1];
    const steps = 12;
    for (let s = 0; s <= steps; s++) {
      const t = s / steps;
      context.beginPath();
      context.arc(
        x0 + (x1 - x0) * t,
        y0 + (y1 - y0) * t,
        w0 + (w1 - w0) * t,
        0,
        Math.PI * 2,
      );
      context.fill();
    }
  }

  for (const path of [DOLPHIN_DORSAL, DOLPHIN_PECTORAL, DOLPHIN_FLUKES]) {
    context.fill(new Path2D(path));
  }

  return context.getImageData(0, 0, size, size).data;
}

/**
 * Sample the silhouette into a particle cloud.
 *
 * @param spacing Grid pitch in viewBox units; smaller means more particles.
 */
export function buildDolphinParticles(spacing = 13): Particle[] {
  const size = DOLPHIN_VIEWBOX;
  const data = rasterise(size);
  if (!data) return [];

  const alphaAt = (x: number, y: number): number => {
    if (x < 0 || y < 0 || x >= size || y >= size) return 0;
    return data[((y | 0) * size + (x | 0)) * 4 + 3];
  };

  const particles: Particle[] = [];

  for (let gy = 0; gy < size; gy += spacing) {
    for (let gx = 0; gx < size; gx += spacing) {
      // Jitter breaks the grid so the cloud reads as organic, not as a mesh.
      const noise = hashNoise(gx, gy);
      const jx = gx + (noise - 0.5) * spacing * 0.8;
      const jy = gy + (hashNoise(gy, gx) - 0.5) * spacing * 0.8;

      if (alphaAt(jx, jy) < 128) continue;

      // Cheap distance-to-edge probe along four axes.
      const probe = spacing * 1.7;
      const interior =
        ((alphaAt(jx - probe, jy) > 128 ? 1 : 0) +
          (alphaAt(jx + probe, jy) > 128 ? 1 : 0) +
          (alphaAt(jx, jy - probe) > 128 ? 1 : 0) +
          (alphaAt(jx, jy + probe) > 128 ? 1 : 0)) /
        4;

      // Navy across the back, cyan toward the underside and tail — the
      // gradient direction in the reference.
      const gradient = Math.min(
        1,
        Math.max(0, (jy / size) * 0.7 + (1 - jx / size) * 0.55),
      );
      const paletteIndex = Math.min(
        PALETTE.length - 1,
        Math.max(0, Math.floor(gradient * PALETTE.length + (noise - 0.5) * 1.3)),
      );

      // Fat dots inside, tapering at the edge: this is what makes a halftone
      // silhouette legible instead of a uniform speckle.
      const radius = spacing * (0.16 + interior * 0.3) * (0.75 + noise * 0.5);

      particles.push({
        x: jx,
        y: jy,
        ox: 0,
        oy: 0,
        radius,
        color: PALETTE[paletteIndex],
        delay: 0,
        spark: noise > 0.985,
      });
    }
  }

  // Loose particles trailing behind the tail, as in the artwork.
  for (let i = 0; i < 80; i++) {
    const n1 = hashNoise(i * 3.1, 7.7);
    const n2 = hashNoise(11.3, i * 5.9);
    particles.push({
      x: 60 + n1 * 230,
      y: 380 + n2 * 660,
      ox: 0,
      oy: 0,
      radius: spacing * (0.1 + n1 * 0.2),
      color: PALETTE[Math.floor(n2 * (PALETTE.length - 1)) + 1],
      delay: 0,
      spark: n1 > 0.92,
    });
  }

  // The eye: one bright particle, placed last so it draws on top.
  particles.push({
    x: DOLPHIN_EYE[0],
    y: DOLPHIN_EYE[1],
    ox: 0,
    oy: 0,
    radius: spacing * 0.42,
    color: "#eaf7ff",
    delay: 0,
    spark: true,
  });

  assignAssembly(particles, size);
  return particles;
}

/**
 * Give every particle a scattered origin and a staggered delay.
 *
 * Particles fly in from outside the frame along the vector from the centre,
 * so the assembly reads as a gather rather than a fade. Delay is ordered by
 * x so the dolphin resolves nose to tail.
 */
function assignAssembly(particles: Particle[], size: number): void {
  const centre = size / 2;

  for (const particle of particles) {
    const dx = particle.x - centre;
    const dy = particle.y - centre;
    const scatter = 2.0 + hashNoise(particle.x, particle.y) * 2.6;

    particle.ox = centre + dx * scatter;
    particle.oy = centre + dy * scatter;

    const headFirst = 1 - particle.x / size;
    particle.delay = Math.min(
      0.7,
      Math.max(0, headFirst * 0.52 + hashNoise(particle.y, particle.x) * 0.2),
    );
  }
}

/** Slight overshoot, so particles snap into place rather than drifting. */
export function easeOutBack(t: number): number {
  const c1 = 1.70158;
  const c3 = c1 + 1;
  const p = t - 1;
  return 1 + c3 * p * p * p + c1 * p * p;
}

export function easeOutCubic(t: number): number {
  const p = 1 - t;
  return 1 - p * p * p;
}

/** Exposed for the shape-preview check in development. */
export const _internals = { SPINE, rasterise };
