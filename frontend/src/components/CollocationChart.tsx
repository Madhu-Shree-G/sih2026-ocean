import { useMemo, useState } from "react";
import type { CollocationResult } from "@/types/api";
import { formatUnits, shortName } from "@/lib/format";
import "./CollocationChart.css";

interface CollocationChartProps {
  data: CollocationResult;
  width?: number;
  height?: number;
}

const MARGIN = { top: 12, right: 16, bottom: 40, left: 50 };

interface Point {
  value: number;
  depth: number;
}

function series(depths: number[], values: (number | null)[]): Point[] {
  const points: Point[] = [];
  for (let i = 0; i < depths.length; i++) {
    const value = values[i];
    if (value === null || !Number.isFinite(value)) continue;
    points.push({ value, depth: depths[i] });
  }
  return points;
}

/**
 * Observed against modelled profile on a shared depth axis.
 *
 * Depth runs downward, which is the convention every oceanographer reads
 * without thinking. The shaded band between the two lines is the point of the
 * chart: it is the disagreement the platform exists to surface.
 */
export function CollocationChart({
  data,
  width = 420,
  height = 320,
}: CollocationChartProps) {
  const [hover, setHover] = useState<number | null>(null);

  const { depth_m, observed, modelled } = data.profile;

  const observedPoints = useMemo(() => series(depth_m, observed), [depth_m, observed]);
  const modelledPoints = useMemo(() => series(depth_m, modelled), [depth_m, modelled]);

  const plotWidth = width - MARGIN.left - MARGIN.right;
  const plotHeight = height - MARGIN.top - MARGIN.bottom;

  const scales = useMemo(() => {
    const all = [...observedPoints, ...modelledPoints];
    if (all.length === 0) return null;

    const values = all.map((p) => p.value);
    let vMin = Math.min(...values);
    let vMax = Math.max(...values);
    const pad = (vMax - vMin) * 0.08 || 1;
    vMin -= pad;
    vMax += pad;

    const depths = all.map((p) => p.depth);
    const dMin = 0;
    const dMax = Math.max(...depths);

    return {
      vMin,
      vMax,
      dMin,
      dMax,
      x: (value: number) => ((value - vMin) / (vMax - vMin || 1)) * plotWidth,
      y: (depth: number) => ((depth - dMin) / (dMax - dMin || 1)) * plotHeight,
    };
  }, [observedPoints, modelledPoints, plotWidth, plotHeight]);

  if (!scales) {
    return <p className="cchart__empty">No paired levels to compare.</p>;
  }

  const path = (points: Point[]) =>
    points
      .map((p, i) => `${i === 0 ? "M" : "L"}${scales.x(p.value).toFixed(2)},${scales.y(p.depth).toFixed(2)}`)
      .join(" ");

  // Difference band: down the observed curve, back up the modelled one.
  const band = (() => {
    const paired: { depth: number; a: number; b: number }[] = [];
    for (let i = 0; i < depth_m.length; i++) {
      const o = observed[i];
      const m = modelled[i];
      if (o === null || m === null || !Number.isFinite(o) || !Number.isFinite(m)) continue;
      paired.push({ depth: depth_m[i], a: o, b: m });
    }
    if (paired.length < 2) return "";

    const down = paired
      .map((p, i) => `${i === 0 ? "M" : "L"}${scales.x(p.a).toFixed(2)},${scales.y(p.depth).toFixed(2)}`)
      .join(" ");
    const up = [...paired]
      .reverse()
      .map((p) => `L${scales.x(p.b).toFixed(2)},${scales.y(p.depth).toFixed(2)}`)
      .join(" ");
    return `${down} ${up} Z`;
  })();

  const xTicks = 5;
  const depthTicks = [0, 500, 1000, 1500, 2000].filter((d) => d <= scales.dMax * 1.02);

  const hovered = hover === null ? null : {
    depth: depth_m[hover],
    observed: observed[hover],
    modelled: modelled[hover],
  };

  return (
    <div className="cchart">
      <div className="cchart__legend">
        <span className="cchart__key">
          <svg width="18" height="8" aria-hidden>
            <line x1="0" y1="4" x2="18" y2="4" stroke="var(--obs-color)" strokeWidth="2.4" />
          </svg>
          Observed
        </span>
        <span className="cchart__key">
          <svg width="18" height="8" aria-hidden>
            <line
              x1="0"
              y1="4"
              x2="18"
              y2="4"
              stroke="var(--model-color)"
              strokeWidth="2.4"
              strokeDasharray="5 3"
            />
          </svg>
          Model
        </span>
        <span className="cchart__key">
          <svg width="14" height="9" aria-hidden>
            <rect width="14" height="9" fill="var(--danger)" fillOpacity="0.28" />
          </svg>
          Difference
        </span>
      </div>

      <svg
        className="cchart__svg"
        viewBox={`0 0 ${width} ${height}`}
        role="img"
        aria-label={`Observed and modelled ${data.variable} profile for ${data.platform_id}`}
        onMouseLeave={() => setHover(null)}
      >
        <g transform={`translate(${MARGIN.left}, ${MARGIN.top})`}>
          {/* Grid */}
          {Array.from({ length: xTicks }, (_, i) => {
            const x = (i / (xTicks - 1)) * plotWidth;
            return (
              <line
                key={`gx-${i}`}
                x1={x}
                y1={0}
                x2={x}
                y2={plotHeight}
                stroke="var(--line-subtle)"
                strokeWidth="1"
              />
            );
          })}
          {depthTicks.map((depth) => (
            <line
              key={`gy-${depth}`}
              x1={0}
              y1={scales.y(depth)}
              x2={plotWidth}
              y2={scales.y(depth)}
              stroke="var(--line-subtle)"
              strokeWidth="1"
            />
          ))}

          {/* The disagreement, shaded */}
          {band && <path d={band} fill="var(--danger)" fillOpacity="0.24" stroke="none" />}

          <path d={path(modelledPoints)} fill="none" stroke="var(--model-color)" strokeWidth="2.2" strokeDasharray="5 3" />
          <path d={path(observedPoints)} fill="none" stroke="var(--obs-color)" strokeWidth="2.4" />

          {/* Hover readout */}
          {hovered && Number.isFinite(hovered.depth) && (
            <g>
              <line
                x1={0}
                y1={scales.y(hovered.depth)}
                x2={plotWidth}
                y2={scales.y(hovered.depth)}
                stroke="var(--saffron-500)"
                strokeWidth="1"
                strokeDasharray="3 2"
              />
              {hovered.observed !== null && Number.isFinite(hovered.observed) && (
                <circle cx={scales.x(hovered.observed)} cy={scales.y(hovered.depth)} r="4" fill="var(--obs-color)" />
              )}
              {hovered.modelled !== null && Number.isFinite(hovered.modelled) && (
                <circle cx={scales.x(hovered.modelled)} cy={scales.y(hovered.depth)} r="4" fill="var(--model-color)" />
              )}
            </g>
          )}

          {/* Invisible hit targets, one per level */}
          {depth_m.map((depth, index) => (
            <rect
              key={`hit-${index}`}
              x={0}
              y={scales.y(depth) - 3}
              width={plotWidth}
              height={6}
              fill="transparent"
              onMouseEnter={() => setHover(index)}
            />
          ))}

          {/* Depth axis */}
          {depthTicks.map((depth) => (
            <text
              key={`ty-${depth}`}
              x={-7}
              y={scales.y(depth)}
              textAnchor="end"
              dominantBaseline="middle"
              className="cchart__tick"
            >
              {depth}
            </text>
          ))}

          {/* Value axis */}
          {Array.from({ length: xTicks }, (_, i) => {
            const value = scales.vMin + (i / (xTicks - 1)) * (scales.vMax - scales.vMin);
            return (
              <text
                key={`tx-${i}`}
                x={(i / (xTicks - 1)) * plotWidth}
                y={plotHeight + 14}
                textAnchor="middle"
                className="cchart__tick"
              >
                {value.toFixed(value >= 100 ? 0 : 1)}
              </text>
            );
          })}
        </g>

        <text
          x={11}
          y={height / 2}
          className="cchart__axis"
          textAnchor="middle"
          transform={`rotate(-90, 11, ${height / 2})`}
        >
          Depth (m)
        </text>
        <text x={width / 2} y={height - 3} className="cchart__axis" textAnchor="middle">
          {shortName(data.variable)} ({formatUnits(data.units)})
        </text>
      </svg>

      {hovered && Number.isFinite(hovered.depth) && (
        <div className="cchart__readout mono">
          <span>{hovered.depth.toFixed(0)} m</span>
          <span>
            obs {hovered.observed === null ? "—" : hovered.observed.toFixed(2)}
          </span>
          <span>
            mdl {hovered.modelled === null ? "—" : hovered.modelled.toFixed(2)}
          </span>
        </div>
      )}
    </div>
  );
}
