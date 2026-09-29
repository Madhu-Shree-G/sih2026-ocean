/**
 * Animated current streamlines.
 *
 * Particles are advected in geographic space and projected to screen through
 * Cesium's camera each frame, then drawn onto a transparent 2-D canvas
 * overlaid on the globe. Drawing to an overlay rather than re-uploading a
 * Cesium imagery layer every frame is what keeps this affordable: the globe
 * itself is untouched, and the canvas is cheap to clear and repaint.
 *
 * The trail effect comes from fading the previous frame rather than storing
 * per-particle history, which keeps memory flat regardless of trail length.
 */

import { Cartesian3, SceneTransforms, type Viewer } from "cesium";

export interface VelocityField {
  u: Float32Array;
  v: Float32Array;
  nLat: number;
  nLon: number;
  latMin: number;
  latMax: number;
  lonMin: number;
  lonMax: number;
}

interface Particle {
  lat: number;
  lon: number;
  /** Frames remaining before forced respawn, so the field keeps refreshing. */
  life: number;
}

export interface ParticleOptions {
  count?: number;
  speedFactor?: number;
  trailFade?: number;
  lineWidth?: number;
  color?: string;
  maxLifetime?: number;
}

const DEFAULTS: Required<ParticleOptions> = {
  count: 2600,
  // Degrees travelled per frame per m/s. Tuned so a 1 m/s current reads as
  // fast but individual particles remain trackable by eye.
  speedFactor: 0.09,
  trailFade: 0.086,
  lineWidth: 1.15,
  color: "rgba(232, 245, 255, 0.85)",
  maxLifetime: 130,
};

export class ParticleLayer {
  private readonly viewer: Viewer;
  private readonly canvas: HTMLCanvasElement;
  private readonly context: CanvasRenderingContext2D;
  private readonly options: Required<ParticleOptions>;

  private field: VelocityField | null = null;
  private particles: Particle[] = [];
  private frame = 0;
  private running = false;
  private opacity = 1;

  constructor(viewer: Viewer, canvas: HTMLCanvasElement, options: ParticleOptions = {}) {
    this.viewer = viewer;
    this.canvas = canvas;
    this.options = { ...DEFAULTS, ...options };

    const context = canvas.getContext("2d", { alpha: true });
    if (!context) throw new Error("Could not acquire a 2D context for the particle layer.");
    this.context = context;
  }

  setField(field: VelocityField | null): void {
    this.field = field;
    if (field) this.seed();
    else this.particles = [];
  }

  setOpacity(opacity: number): void {
    this.opacity = Math.max(0, Math.min(1, opacity));
  }

  resize(width: number, height: number, dpr = window.devicePixelRatio || 1): void {
    this.canvas.width = Math.max(1, Math.floor(width * dpr));
    this.canvas.height = Math.max(1, Math.floor(height * dpr));
    this.canvas.style.width = `${width}px`;
    this.canvas.style.height = `${height}px`;
    this.context.setTransform(dpr, 0, 0, dpr, 0, 0);
  }

  start(): void {
    if (this.running) return;
    this.running = true;
    this.loop();
  }

  stop(): void {
    this.running = false;
  }

  clear(): void {
    this.context.save();
    this.context.setTransform(1, 0, 0, 1, 0, 0);
    this.context.clearRect(0, 0, this.canvas.width, this.canvas.height);
    this.context.restore();
  }

  // -- internals ----------------------------------------------------------
  private randomPosition(): Particle {
    const field = this.field;
    if (!field) return { lat: 0, lon: 0, life: 0 };
    return {
      lat: field.latMin + Math.random() * (field.latMax - field.latMin),
      lon: field.lonMin + Math.random() * (field.lonMax - field.lonMin),
      life: Math.random() * this.options.maxLifetime,
    };
  }

  private seed(): void {
    this.particles = Array.from({ length: this.options.count }, () => this.randomPosition());
  }

  /** Bilinear sample of the velocity field; NaN where there is no water. */
  private sample(lat: number, lon: number): [number, number] {
    const field = this.field;
    if (!field) return [NaN, NaN];

    const fy = ((lat - field.latMin) / (field.latMax - field.latMin)) * (field.nLat - 1);
    const fx = ((lon - field.lonMin) / (field.lonMax - field.lonMin)) * (field.nLon - 1);

    if (fy < 0 || fy > field.nLat - 1 || fx < 0 || fx > field.nLon - 1) return [NaN, NaN];

    const y0 = Math.floor(fy);
    const x0 = Math.floor(fx);
    const y1 = Math.min(y0 + 1, field.nLat - 1);
    const x1 = Math.min(x0 + 1, field.nLon - 1);
    const ty = fy - y0;
    const tx = fx - x0;

    const idx = (y: number, x: number) => y * field.nLon + x;

    const u00 = field.u[idx(y0, x0)];
    const u10 = field.u[idx(y1, x0)];
    const u01 = field.u[idx(y0, x1)];
    const u11 = field.u[idx(y1, x1)];
    if (!Number.isFinite(u00) && !Number.isFinite(u10) && !Number.isFinite(u01) && !Number.isFinite(u11)) {
      return [NaN, NaN];
    }

    const blend = (a: number, b: number, c: number, d: number): number => {
      // Treat land cells as zero rather than discarding the whole sample, so
      // particles decelerate near a coast instead of vanishing abruptly.
      const av = Number.isFinite(a) ? a : 0;
      const bv = Number.isFinite(b) ? b : 0;
      const cv = Number.isFinite(c) ? c : 0;
      const dv = Number.isFinite(d) ? d : 0;
      return (
        av * (1 - ty) * (1 - tx) + bv * ty * (1 - tx) + cv * (1 - ty) * tx + dv * ty * tx
      );
    };

    return [
      blend(u00, u10, u01, u11),
      blend(
        field.v[idx(y0, x0)],
        field.v[idx(y1, x0)],
        field.v[idx(y0, x1)],
        field.v[idx(y1, x1)],
      ),
    ];
  }

  private loop = (): void => {
    if (!this.running) return;
    this.render();
    requestAnimationFrame(this.loop);
  };

  private render(): void {
    const context = this.context;
    const width = this.canvas.width / (window.devicePixelRatio || 1);
    const height = this.canvas.height / (window.devicePixelRatio || 1);

    // Fade the previous frame to leave trails.
    context.globalCompositeOperation = "destination-out";
    context.fillStyle = `rgba(0, 0, 0, ${this.options.trailFade})`;
    context.fillRect(0, 0, width, height);
    context.globalCompositeOperation = "source-over";

    if (!this.field || this.opacity <= 0.01 || this.particles.length === 0) return;

    this.frame++;
    const scene = this.viewer.scene;

    context.strokeStyle = this.options.color;
    context.globalAlpha = this.opacity;
    context.lineWidth = this.options.lineWidth;
    context.lineCap = "round";
    context.beginPath();

    for (const particle of this.particles) {
      const [u, v] = this.sample(particle.lat, particle.lon);

      if (!Number.isFinite(u) || !Number.isFinite(v) || particle.life <= 0) {
        Object.assign(particle, this.randomPosition());
        continue;
      }

      const startLat = particle.lat;
      const startLon = particle.lon;

      // Convert m/s to degrees, widening longitude steps toward the poles.
      const cosLat = Math.max(0.15, Math.cos((particle.lat * Math.PI) / 180));
      particle.lon += (u * this.options.speedFactor) / cosLat;
      particle.lat += v * this.options.speedFactor;
      particle.life -= 1;

      const from = this.project(startLon, startLat, scene);
      const to = this.project(particle.lon, particle.lat, scene);
      if (!from || !to) continue;

      // A long screen-space jump means the point crossed the horizon.
      const dx = to.x - from.x;
      const dy = to.y - from.y;
      if (dx * dx + dy * dy > 4000) continue;

      context.moveTo(from.x, from.y);
      context.lineTo(to.x, to.y);
    }

    context.stroke();
    context.globalAlpha = 1;
  }

  private project(
    lon: number,
    lat: number,
    scene: Viewer["scene"],
  ): { x: number; y: number } | null {
    const cartesian = Cartesian3.fromDegrees(lon, lat, 0);

    // Cull points on the far side of the globe, which would otherwise project
    // onto the visible hemisphere and draw spurious lines.
    const camera = scene.camera;
    const toPoint = Cartesian3.subtract(cartesian, camera.positionWC, new Cartesian3());
    if (Cartesian3.dot(cartesian, toPoint) > 0) return null;

    const window2d = SceneTransforms.worldToWindowCoordinates(scene, cartesian);
    if (!window2d) return null;
    return { x: window2d.x, y: window2d.y };
  }
}
