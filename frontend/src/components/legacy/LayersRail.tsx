import { useMemo } from "react";
import { ChevronDown, ChevronsLeft, ChevronsRight, MoreVertical, Thermometer } from "lucide-react";
import { useAppStore, type LayerId } from "@/state/store";
import { formatDepth, variableLabel } from "@/lib/format";
import type { DatasetAxes, VariableSpec } from "@/types/api";
import { MonumentSkyline } from "./Insignia";
import "./LayersRail.css";

interface LayersRailProps {
  variables: VariableSpec[];
  axes: DatasetAxes | undefined;
  swatch: string[];
}

/** Layers that colour the globe surface get a swatch; overlays do not. */
const SWATCHED: LayerId = "surface";

export function LayersRail({ variables, axes, swatch }: LayersRailProps) {
  const {
    variable,
    setVariable,
    layers,
    toggleLayer,
    setLayerOpacity,
    depthIndex,
    setDepthIndex,
    verticalExaggeration,
    setVerticalExaggeration,
    railCollapsed,
    toggleRail,
  } = useAppStore();

  const depths = axes?.depths ?? [0];
  const currentDepth = depths[Math.min(depthIndex, depths.length - 1)] ?? 0;

  // Renderable variables only: bathymetry is static and has no time axis, so
  // it is offered as a layer rather than as the primary field.
  const selectable = useMemo(
    () => variables.filter((v) => v.name !== "bathymetry" && v.vector_group === null),
    [variables],
  );

  const depthTicks = useMemo(() => {
    if (depths.length < 2) return [];
    const max = depths[depths.length - 1];
    const step = max <= 500 ? 100 : max <= 2500 ? 500 : 1000;
    const ticks: number[] = [];
    for (let d = 0; d <= max + 1; d += step) ticks.push(d);
    return ticks;
  }, [depths]);

  if (railCollapsed) {
    return (
      <aside className="rail rail--collapsed">
        <button className="rail__expand" onClick={toggleRail} type="button" aria-label="Expand layers panel">
          <ChevronsRight size={16} />
        </button>
      </aside>
    );
  }

  return (
    <aside className="rail">
      <div className="rail__head">
        <h2 className="rail__title">LAYERS</h2>
        <button className="rail__collapse" onClick={toggleRail} type="button" aria-label="Collapse layers panel">
          <ChevronsLeft size={16} />
        </button>
      </div>

      <div className="rail__body scroll">
        {/* ---- Variable ---------------------------------------------------- */}
        <section className="rail__section">
          <p className="label rail__label">Variable</p>
          <div className="vselect">
            <Thermometer size={15} className="vselect__icon" aria-hidden />
            <select
              className="vselect__input"
              value={variable}
              onChange={(event) => setVariable(event.target.value)}
              aria-label="Primary variable"
            >
              {selectable.map((spec) => (
                <option key={spec.name} value={spec.name}>
                  {variableLabel(spec.name, spec.units, spec.long_name)}
                </option>
              ))}
            </select>
            <ChevronDown size={15} className="vselect__chevron" aria-hidden />
          </div>
        </section>

        {/* ---- Layer stack ------------------------------------------------- */}
        <section className="rail__section rail__section--layers">
          {layers.map((layer) => {
            const percent = Math.round(layer.opacity * 100);
            return (
              <div className={`layer${layer.enabled ? " layer--on" : ""}`} key={layer.id}>
                <div className="layer__row">
                  <label className="layer__check">
                    <input
                      type="checkbox"
                      checked={layer.enabled}
                      onChange={() => toggleLayer(layer.id)}
                    />
                    <span className="layer__box" aria-hidden />
                    <span className="layer__name">{layer.label}</span>
                  </label>

                  {layer.id === SWATCHED && swatch.length > 0 ? (
                    <span
                      className="layer__swatch"
                      style={{
                        background: `linear-gradient(90deg, ${swatch.join(", ")})`,
                      }}
                      aria-hidden
                    />
                  ) : (
                    <button className="layer__menu" type="button" aria-label={`${layer.label} options`}>
                      <MoreVertical size={14} />
                    </button>
                  )}
                </div>

                <div className="layer__slider">
                  <input
                    type="range"
                    min={0}
                    max={100}
                    value={percent}
                    disabled={!layer.enabled}
                    onChange={(event) =>
                      setLayerOpacity(layer.id, Number(event.target.value) / 100)
                    }
                    aria-label={`${layer.label} opacity`}
                    style={
                      {
                        "--accent": layer.id === SWATCHED ? "var(--amber)" : "var(--cyan)",
                      } as React.CSSProperties
                    }
                  />
                  <span className="layer__pct mono">{percent}%</span>
                </div>
              </div>
            );
          })}
        </section>

        {/* ---- Depth slice ------------------------------------------------- */}
        <section className="rail__section rail__section--divided">
          <div className="rail__rowhead">
            <p className="label rail__label">Depth Slice</p>
            <span className="rail__value mono">{formatDepth(currentDepth)}</span>
          </div>
          <input
            type="range"
            min={0}
            max={Math.max(0, depths.length - 1)}
            step={1}
            value={Math.min(depthIndex, depths.length - 1)}
            onChange={(event) => setDepthIndex(Number(event.target.value))}
            aria-label="Depth slice"
            style={{ "--accent": "var(--cyan)" } as React.CSSProperties}
          />
          <div className="rail__ticks mono">
            {depthTicks.map((tick) => (
              <span key={tick}>{tick === 0 ? "0 m" : `${tick} m`}</span>
            ))}
          </div>
        </section>

        {/* ---- Vertical exaggeration --------------------------------------- */}
        <section className="rail__section rail__section--divided">
          <div className="rail__rowhead">
            <p className="label rail__label">Vertical Exaggeration</p>
            <span className="rail__value mono">{verticalExaggeration}x</span>
          </div>
          <input
            type="range"
            min={1}
            max={50}
            step={1}
            value={verticalExaggeration}
            onChange={(event) => setVerticalExaggeration(Number(event.target.value))}
            aria-label="Vertical exaggeration"
            style={{ "--accent": "var(--amber)" } as React.CSSProperties}
          />
          <div className="rail__ticks rail__ticks--marked mono">
            {[1, 10, 20, 30, 50].map((tick) => (
              <span
                key={tick}
                className={verticalExaggeration === tick ? "is-current" : undefined}
              >
                {tick}x
              </span>
            ))}
          </div>
          {/* The ocean is ~5 km deep on a 6371 km sphere: without exaggeration
              the entire water column is an invisible film. */}
          <p className="rail__hint">
            Ocean depth is ~0.08% of Earth&apos;s radius — exaggeration makes the
            water column visible.
          </p>
        </section>
      </div>

      <MonumentSkyline className="rail__ornament" />
    </aside>
  );
}
