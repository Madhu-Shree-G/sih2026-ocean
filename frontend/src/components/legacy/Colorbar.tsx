import { useEffect, useMemo, useRef, useState } from "react";
import { RotateCcw, SlidersHorizontal } from "lucide-react";
import { useAppStore } from "@/state/store";
import { niceTicks, tickLabel, variableLabel } from "@/lib/format";
import type { VariableSpec } from "@/types/api";
import "./Colorbar.css";

interface ColorbarProps {
  spec: VariableSpec | undefined;
  lut: Uint8Array | undefined;
  /** Actual data range in the current view, used by the auto-fit control. */
  actualRange?: [number, number];
}

/** Render the LUT into a CSS gradient so the bar needs no canvas. */
function gradientFromLut(lut: Uint8Array | undefined): string {
  if (!lut || lut.length < 4) return "linear-gradient(90deg, #1b3a5c, #d94f2b)";
  const stops: string[] = [];
  for (let i = 0; i <= 16; i++) {
    const index = Math.min(255, Math.round((i / 16) * 255)) * 4;
    stops.push(
      `rgb(${lut[index]}, ${lut[index + 1]}, ${lut[index + 2]}) ${(i / 16) * 100}%`,
    );
  }
  return `linear-gradient(90deg, ${stops.join(", ")})`;
}

export function Colorbar({ spec, lut, actualRange }: ColorbarProps) {
  const { colorScale, setColorScale, resetColorScale } = useAppStore();
  const [editing, setEditing] = useState(false);
  const [draftMin, setDraftMin] = useState(String(colorScale.vmin));
  const [draftMax, setDraftMax] = useState(String(colorScale.vmax));
  const panelRef = useRef<HTMLDivElement>(null);

  useEffect(() => {
    setDraftMin(String(colorScale.vmin));
    setDraftMax(String(colorScale.vmax));
  }, [colorScale.vmin, colorScale.vmax]);

  // Dismiss the editor on an outside click, the way a popover should behave.
  useEffect(() => {
    if (!editing) return;
    const onPointerDown = (event: PointerEvent) => {
      if (panelRef.current && !panelRef.current.contains(event.target as Node)) {
        setEditing(false);
      }
    };
    document.addEventListener("pointerdown", onPointerDown);
    return () => document.removeEventListener("pointerdown", onPointerDown);
  }, [editing]);

  const gradient = useMemo(() => gradientFromLut(lut), [lut]);
  const ticks = useMemo(
    () => niceTicks(colorScale.vmin, colorScale.vmax, 6),
    [colorScale.vmin, colorScale.vmax],
  );

  const label = spec ? variableLabel(spec.name, spec.units, spec.long_name) : "Value";

  const commit = () => {
    const lo = Number(draftMin);
    const hi = Number(draftMax);
    if (Number.isFinite(lo) && Number.isFinite(hi) && hi > lo) {
      setColorScale({ vmin: lo, vmax: hi });
    } else {
      setDraftMin(String(colorScale.vmin));
      setDraftMax(String(colorScale.vmax));
    }
  };

  const autoFit = () => {
    if (!actualRange) return;
    const [lo, hi] = actualRange;
    if (Number.isFinite(lo) && Number.isFinite(hi) && hi > lo) {
      setColorScale({ vmin: Number(lo.toFixed(2)), vmax: Number(hi.toFixed(2)) });
    }
  };

  const restoreDefault = () => {
    if (!spec) return;
    const [lo, hi] = spec.default_range ?? [0, 1];
    resetColorScale(spec.default_colormap, lo, hi);
  };

  return (
    <div className="cbar" ref={panelRef}>
      <div className="cbar__head">
        <span className="cbar__label">{label}</span>
        <div className="cbar__actions">
          {colorScale.custom && (
            <button
              className="cbar__mini"
              type="button"
              onClick={restoreDefault}
              title="Restore the default range"
            >
              <RotateCcw size={12} />
            </button>
          )}
          <button
            className={`cbar__mini${editing ? " is-on" : ""}`}
            type="button"
            onClick={() => setEditing((open) => !open)}
            title="Edit colour range"
            aria-expanded={editing}
          >
            <SlidersHorizontal size={12} />
          </button>
        </div>
      </div>

      <div className="cbar__ramp" style={{ background: gradient }} />

      <div className="cbar__ticks mono">
        {ticks.map((tick, index) => (
          <span key={index}>{tickLabel(tick)}</span>
        ))}
      </div>

      {editing && (
        <div className="cbar__editor">
          <div className="cbar__field">
            <label className="label" htmlFor="cbar-min">
              Min
            </label>
            <input
              id="cbar-min"
              className="cbar__input mono"
              value={draftMin}
              inputMode="decimal"
              onChange={(event) => setDraftMin(event.target.value)}
              onBlur={commit}
              onKeyDown={(event) => event.key === "Enter" && commit()}
            />
          </div>
          <div className="cbar__field">
            <label className="label" htmlFor="cbar-max">
              Max
            </label>
            <input
              id="cbar-max"
              className="cbar__input mono"
              value={draftMax}
              inputMode="decimal"
              onChange={(event) => setDraftMax(event.target.value)}
              onBlur={commit}
              onKeyDown={(event) => event.key === "Enter" && commit()}
            />
          </div>
          <button className="cbar__fit" type="button" onClick={autoFit} disabled={!actualRange}>
            Fit to data
          </button>
        </div>
      )}
    </div>
  );
}
