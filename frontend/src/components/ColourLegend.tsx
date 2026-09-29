/**
 * The colour legend, and the range editor behind it.
 *
 * A legend that cannot be adjusted is a caption; this one is a control. The
 * "fit to what is on screen" button is the important one — a CF default range
 * of 2-32 °C against surface water spanning 26-30 °C spends most of the ramp
 * on values that are not present, flattening every real gradient into one wash
 * of colour.
 */

import { useEffect, useMemo, useState } from "react";
import { RotateCcw, Wand2 } from "lucide-react";
import { useAppStore } from "@/state/store";
import { niceTicks, tickLabel, variableLabel } from "@/lib/format";
import type { VariableSpec } from "@/types/api";
import { Button, Field, IconButton } from "@/ui";

/** Turn the 256-entry LUT into a CSS gradient so the bar needs no canvas. */
export function gradientFromLut(lut: Uint8Array | undefined): string {
  if (!lut || lut.length < 4) return "linear-gradient(90deg, #1b3a5c, #d94f2b)";
  const stops: string[] = [];
  for (let i = 0; i <= 16; i++) {
    const index = Math.min(255, Math.round((i / 16) * 255)) * 4;
    stops.push(`rgb(${lut[index]}, ${lut[index + 1]}, ${lut[index + 2]}) ${(i / 16) * 100}%`);
  }
  return `linear-gradient(90deg, ${stops.join(", ")})`;
}

interface ColourLegendProps {
  spec: VariableSpec | undefined;
  lut: Uint8Array | undefined;
  /** Range actually present in the loaded field, for the fit control. */
  actualRange?: [number, number];
  editable?: boolean;
}

export function ColourLegend({ spec, lut, actualRange, editable = true }: ColourLegendProps) {
  const { colorScale, setColorScale, resetColorScale } = useAppStore();
  const [draftMin, setDraftMin] = useState(String(colorScale.vmin));
  const [draftMax, setDraftMax] = useState(String(colorScale.vmax));

  useEffect(() => {
    setDraftMin(String(colorScale.vmin));
    setDraftMax(String(colorScale.vmax));
  }, [colorScale.vmin, colorScale.vmax]);

  const gradient = useMemo(() => gradientFromLut(lut), [lut]);
  const ticks = useMemo(
    () => niceTicks(colorScale.vmin, colorScale.vmax, 5),
    [colorScale.vmin, colorScale.vmax],
  );

  const label = spec ? variableLabel(spec.name, spec.units, spec.long_name) : "Value";

  const commit = () => {
    const lo = Number(draftMin);
    const hi = Number(draftMax);
    if (Number.isFinite(lo) && Number.isFinite(hi) && hi > lo) {
      setColorScale({ vmin: lo, vmax: hi });
    } else {
      // Reject the edit rather than store an inverted or non-numeric range.
      setDraftMin(String(colorScale.vmin));
      setDraftMax(String(colorScale.vmax));
    }
  };

  const fitToData = () => {
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
    <div className="legend">
      <div className="row gap2">
        <span className="label grow">{label}</span>
        {editable && colorScale.custom && (
          <IconButton
            icon={<RotateCcw size={14} />}
            label="Restore the default range for this variable"
            onClick={restoreDefault}
          />
        )}
      </div>

      <div className="legend__ramp" style={{ background: gradient }} role="img" aria-label={`Colour scale for ${label} from ${colorScale.vmin} to ${colorScale.vmax}`} />

      <div className="legend__ticks" aria-hidden>
        {ticks.map((tick, index) => (
          <span key={index}>{tickLabel(tick)}</span>
        ))}
      </div>

      {editable && (
        <>
          <div className="legend__range">
            <Field label="Min" htmlFor="legend-min">
              <input
                id="legend-min"
                className="control mono"
                value={draftMin}
                inputMode="decimal"
                onChange={(event) => setDraftMin(event.target.value)}
                onBlur={commit}
                onKeyDown={(event) => event.key === "Enter" && commit()}
              />
            </Field>
            <Field label="Max" htmlFor="legend-max">
              <input
                id="legend-max"
                className="control mono"
                value={draftMax}
                inputMode="decimal"
                onChange={(event) => setDraftMax(event.target.value)}
                onBlur={commit}
                onKeyDown={(event) => event.key === "Enter" && commit()}
              />
            </Field>
          </div>
          <Button
            variant="secondary"
            size="sm"
            block
            onClick={fitToData}
            disabled={!actualRange}
            title={
              actualRange
                ? `Stretch the colours across ${actualRange[0].toFixed(2)} to ${actualRange[1].toFixed(2)}`
                : "No field loaded yet"
            }
          >
            <Wand2 size={14} aria-hidden />
            Fit colours to this field
          </Button>
        </>
      )}
    </div>
  );
}
