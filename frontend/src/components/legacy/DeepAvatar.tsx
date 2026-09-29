import { useEffect, useRef } from "react";
import {
  DOLPHIN_VIEWBOX,
  buildDolphinParticles,
  easeOutBack,
  type Particle,
} from "@/lib/dolphin-shape";
import "./DeepAvatar.css";

export type AvatarState = "hidden" | "assembling" | "idle" | "listening" | "thinking" | "speaking";

interface DeepAvatarProps {
  state: AvatarState;
  /** Rendered size in CSS pixels. */
  size?: number;
  /** 0..1 microphone level, used to make the avatar breathe with the voice. */
  level?: number;
}

/** How long the particles take to gather, in milliseconds. */
const ASSEMBLE_MS = 1500;
const DISPERSE_MS = 620;

/**
 * Deep's avatar: a leaping dolphin that assembles from scattered particles.
 *
 * Drawn on a canvas rather than as DOM nodes — there are roughly three
 * thousand particles, and three thousand elements would stall the main
 * thread on every frame. The whole animation is one `requestAnimationFrame`
 * loop over a flat array.
 */
export function DeepAvatar({ state, size = 280, level = 0 }: DeepAvatarProps) {
  const canvasRef = useRef<HTMLCanvasElement>(null);
  const particlesRef = useRef<Particle[]>([]);
  const frameRef = useRef<number>(0);

  // Animation clock, kept in refs so the render loop never re-subscribes.
  const phaseRef = useRef<{ state: AvatarState; startedAt: number }>({
    state: "hidden",
    startedAt: 0,
  });
  const levelRef = useRef(0);
  const progressRef = useRef(0);

  useEffect(() => {
    levelRef.current = level;
  }, [level]);

  useEffect(() => {
    if (phaseRef.current.state !== state) {
      phaseRef.current = { state, startedAt: performance.now() };
    }
  }, [state]);

  useEffect(() => {
    const canvas = canvasRef.current;
    if (!canvas) return;

    const context = canvas.getContext("2d", { alpha: true });
    if (!context) return;

    // Particle positions live in viewBox units; the canvas is scaled once.
    if (particlesRef.current.length === 0) {
      particlesRef.current = buildDolphinParticles(13);
    }

    const dpr = Math.min(2, window.devicePixelRatio || 1);
    canvas.width = size * dpr;
    canvas.height = size * dpr;

    const scale = (size / DOLPHIN_VIEWBOX) * dpr;

    const render = (now: number) => {
      frameRef.current = requestAnimationFrame(render);

      const { state: phase, startedAt } = phaseRef.current;
      const elapsed = now - startedAt;

      // `progress` is 0 fully scattered, 1 fully assembled.
      let target = 1;
      if (phase === "hidden") target = 0;
      else if (phase === "assembling") {
        target = Math.min(1, elapsed / ASSEMBLE_MS);
      }

      if (phase === "hidden") {
        progressRef.current = Math.max(
          0,
          progressRef.current - (16.7 / DISPERSE_MS),
        );
      } else {
        progressRef.current = target;
      }

      const progress = progressRef.current;

      context.setTransform(1, 0, 0, 1, 0, 0);
      context.clearRect(0, 0, canvas.width, canvas.height);

      if (progress <= 0.001) return;

      context.setTransform(scale, 0, 0, scale, 0, 0);

      // Idle motion: a slow vertical bob plus a breathing scale, so the
      // dolphin never looks frozen.
      const t = now / 1000;
      const bob = Math.sin(t * 1.1) * 9;
      const breathe = 1 + Math.sin(t * 1.7) * 0.008;
      const voice = phase === "speaking" ? levelRef.current : 0;

      context.save();
      context.translate(DOLPHIN_VIEWBOX / 2, DOLPHIN_VIEWBOX / 2 + bob);
      context.scale(breathe, breathe);
      context.translate(-DOLPHIN_VIEWBOX / 2, -DOLPHIN_VIEWBOX / 2);

      for (const particle of particlesRef.current) {
        // Each particle runs its own eased sub-interval of the assembly.
        const span = 1 - particle.delay;
        const local = Math.min(
          1,
          Math.max(0, (progress - particle.delay) / (span || 1)),
        );
        if (local <= 0) continue;

        const eased = progress >= 1 ? 1 : easeOutBack(local);
        let x = particle.ox + (particle.x - particle.ox) * eased;
        let y = particle.oy + (particle.y - particle.oy) * eased;

        // Settled particles shimmer very slightly, which keeps the halftone
        // alive without reading as noise.
        if (progress >= 1) {
          const wobble = Math.sin(t * 2.2 + particle.x * 0.05) * 0.9;
          x += wobble;
          y += Math.cos(t * 1.9 + particle.y * 0.045) * 0.9;
        }

        let radius = particle.radius;
        let alpha = Math.min(1, local * 1.3);

        if (particle.spark) {
          const pulse = 0.6 + 0.4 * Math.sin(t * 3.4 + particle.x * 0.02);
          radius *= 1 + pulse * 0.5;
          alpha *= 0.7 + pulse * 0.3;
        }

        if (phase === "listening") {
          // A travelling brightness band, so listening is legible at a glance.
          const band = Math.sin(t * 2.6 - particle.x * 0.012);
          if (band > 0.72) {
            radius *= 1.45;
            alpha = Math.min(1, alpha * 1.5);
          }
        } else if (phase === "thinking") {
          const sweep = Math.sin(t * 4.2 - particle.y * 0.016);
          if (sweep > 0.8) radius *= 1.35;
        } else if (phase === "speaking" && voice > 0.02) {
          radius *= 1 + voice * 0.55;
        }

        context.globalAlpha = alpha;
        context.fillStyle = particle.color;
        context.beginPath();
        context.arc(x, y, radius, 0, Math.PI * 2);
        context.fill();
      }

      context.globalAlpha = 1;
      context.restore();
    };

    frameRef.current = requestAnimationFrame(render);
    return () => cancelAnimationFrame(frameRef.current);
  }, [size]);

  return (
    <canvas
      ref={canvasRef}
      className={`deepAvatar deepAvatar--${state}`}
      style={{ width: size, height: size }}
      aria-hidden
    />
  );
}
