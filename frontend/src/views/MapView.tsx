/**
 * The live map.
 *
 * Left panel: what is drawn and how. Centre: the globe. Bottom: time.
 * Every switch in the panel maps onto something the renderer actually does —
 * the previous layer list had four entries wired to nothing at all.
 */

import { useCallback, useEffect, useMemo } from "react";
import { Layers, Sliders } from "lucide-react";
import { useAppStore, regionById, REGIONS, type AnalysisLayer, type LayerId } from "@/state/store";
import { useT } from "@/i18n";
import {
  useAnomaly,
  useAxes,
  useBiasMap,
  useDataset,
  useEddies,
  useField,
  useLut,
  useMixedLayerDepth,
  usePlatforms,
  useThermocline,
  useVelocity,
} from "@/lib/queries";
import { DIVERGING, DEPTH_RAMP, rampCss, symmetricRange } from "@/lib/grid-render";
import { formatDepth, formatUnits, variableLabel } from "@/lib/format";
import { OceanMap, type MapApi, type MapOverlay } from "@/components/OceanMap";
import { Timeline } from "@/components/Timeline";
import { ColourLegend } from "@/components/ColourLegend";
import {
  Callout,
  Checkbox,
  Field,
  IconButton,
  Select,
  Tabs,
  useToast,
} from "@/ui";
import "./views.css";

const ANALYSIS_OPTIONS: { value: AnalysisLayer; label: string; hint: string }[] = [
  { value: "none", label: "None — model field only", hint: "Just the coloured variable" },
  { value: "anomaly", label: "Anomaly & marine heatwave", hint: "This field minus climatology" },
  { value: "mixed_layer_depth", label: "Mixed layer depth", hint: "Depth of the well-stirred surface layer" },
  { value: "thermocline", label: "Thermocline depth", hint: "Where temperature falls fastest with depth" },
  { value: "eddies", label: "Eddy census", hint: "Okubo–Weiss closed circulations" },
  { value: "bias", label: "Model−observation bias", hint: "Where the model disagrees with floats" },
];

export function MapView({ mapApiRef }: { mapApiRef: React.MutableRefObject<MapApi | null> }) {
  const t = useT();
  const toast = useToast();
  const {
    variable,
    setVariable,
    depthIndex,
    setDepthIndex,
    timeIndex,
    layers,
    toggleLayer,
    setLayerOpacity,
    analysisLayer,
    setAnalysisLayer,
    colorScale,
    selectProfile,
    mapPanel,
    setMapPanel,
    mapFocus,
    clearMapFocus,
    regionId,
    setRegion,
  } = useAppStore();

  const dataset = useDataset();
  const axes = useAxes();
  const nTimes = axes.data?.times.length ?? 1;

  const field = useField(nTimes);
  const velocity = useVelocity(nTimes);
  const lut = useLut(colorScale.colormap);
  const platforms = usePlatforms(true);
  const eddies = useEddies(true);
  const biasMap = useBiasMap(analysisLayer === "bias" || (layers.find((l) => l.id === "bias")?.enabled ?? false));
  const anomaly = useAnomaly(analysisLayer === "anomaly");
  const mld = useMixedLayerDepth(analysisLayer === "mixed_layer_depth");
  const thermocline = useThermocline(analysisLayer === "thermocline");

  const spec = useMemo(
    () => dataset.data?.variables.find((entry) => entry.name === variable),
    [dataset.data, variable],
  );

  const selectable = useMemo(
    () =>
      (dataset.data?.variables ?? [])
        .filter((entry) => entry.vector_group === null && entry.name !== "bathymetry")
        .map((entry) => ({
          value: entry.name,
          label: variableLabel(entry.name, entry.units, entry.long_name),
        })),
    [dataset.data],
  );

  const depths = axes.data?.depths ?? [0];
  const currentDepth = depths[Math.min(depthIndex, depths.length - 1)] ?? 0;

  /* ---- Overlay ---------------------------------------------------------- */
  const overlay = useMemo<MapOverlay | undefined>(() => {
    if (analysisLayer === "anomaly" && anomaly.data) {
      const scale = anomaly.data.suggested_scale;
      return {
        grid: anomaly.data.grid,
        range: symmetricRange([scale.vmin, scale.vmax]),
        ramp: DIVERGING,
        label: "Temperature anomaly",
        units: anomaly.data.units,
      };
    }
    if (analysisLayer === "mixed_layer_depth" && mld.data) {
      return {
        grid: mld.data.grid,
        range: [mld.data.value_range[0] ?? 0, mld.data.value_range[1] ?? 100],
        ramp: DEPTH_RAMP,
        label: "Mixed layer depth",
        units: mld.data.units ?? "m",
      };
    }
    if (analysisLayer === "thermocline" && thermocline.data) {
      return {
        grid: thermocline.data.grid,
        range: [thermocline.data.value_range[0] ?? 0, thermocline.data.value_range[1] ?? 300],
        ramp: DEPTH_RAMP,
        label: "Thermocline depth",
        units: thermocline.data.units ?? "m",
      };
    }
    return undefined;
  }, [analysisLayer, anomaly.data, mld.data, thermocline.data]);

  /* ---- Map handle -------------------------------------------------------- */
  const handleReady = useCallback(
    (api: MapApi) => {
      mapApiRef.current = api;
    },
    [mapApiRef],
  );

  /* A "view on map" link from another screen lands here. */
  useEffect(() => {
    if (!mapFocus) return;
    mapApiRef.current?.flyTo(mapFocus.lat, mapFocus.lon, 1500);
    clearMapFocus();
  }, [mapFocus, clearMapFocus, mapApiRef]);

  const handleSelectProfile = useCallback(
    (profileId: number, platformId: string) => selectProfile(profileId, platformId),
    [selectProfile],
  );

  /* ---- Share ------------------------------------------------------------- */
  const share = useCallback(() => {
    const camera = mapApiRef.current?.camera();
    const params = new URLSearchParams({
      section: "map",
      variable,
      time: String(timeIndex),
      depth: String(depthIndex),
      analysis: analysisLayer,
    });
    if (camera) {
      params.set("lat", camera.lat.toFixed(3));
      params.set("lon", camera.lon.toFixed(3));
      params.set("km", camera.heightKm.toFixed(0));
    }
    const url = `${window.location.origin}${window.location.pathname}?${params}`;
    navigator.clipboard
      ?.writeText(url)
      .then(() => toast(t("common.copied")))
      .catch(() => toast("Could not copy the link"));
  }, [variable, timeIndex, depthIndex, analysisLayer, toast, t, mapApiRef]);

  const times = axes.data?.times ?? [];
  const panelOpen = mapPanel !== "none";

  return (
    <div className={`mapview${panelOpen ? "" : " mapview--nopanel"}`}>
      {panelOpen && (
        <aside className="mappanel" aria-label="Map controls">
          <Tabs
            label="Map control groups"
            value={mapPanel}
            onChange={(value) => setMapPanel(value)}
            options={[
              { value: "layers", label: "Layers", icon: <Layers size={15} aria-hidden /> },
              { value: "legend", label: "Colours & slices", icon: <Sliders size={15} aria-hidden /> },
            ]}
          />

          <div className="mappanel__body scroll">
            {mapPanel === "layers" ? (
              <>
                <section className="stack gap2">
                  <p className="label">Drawn on the map</p>
                  {layers.map((layer) => (
                    <LayerRow
                      key={layer.id}
                      id={layer.id}
                      label={layer.label}
                      enabled={layer.enabled}
                      opacity={layer.opacity}
                      fixedOpacity={layer.fixedOpacity}
                      swatch={layer.id === "surface" ? gradientForField(lut.data) : undefined}
                      onToggle={() => toggleLayer(layer.id)}
                      onOpacity={(value) => setLayerOpacity(layer.id, value)}
                    />
                  ))}
                </section>

                <section className="stack gap3">
                  <Select
                    label="Analysis overlay"
                    value={analysisLayer}
                    onChange={(value) => setAnalysisLayer(value)}
                    options={ANALYSIS_OPTIONS.map((option) => ({
                      value: option.value,
                      label: option.label,
                    }))}
                    hint={ANALYSIS_OPTIONS.find((option) => option.value === analysisLayer)?.hint}
                  />

                  {overlay && (
                    <div className="legend">
                      <span className="label">
                        {overlay.label} ({formatUnits(overlay.units)})
                      </span>
                      <div className="legend__ramp" style={{ background: rampCss(overlay.ramp) }} />
                      <div className="legend__ticks">
                        <span>{overlay.range[0].toFixed(1)}</span>
                        <span>{((overlay.range[0] + overlay.range[1]) / 2).toFixed(1)}</span>
                        <span>{overlay.range[1].toFixed(1)}</span>
                      </div>
                    </div>
                  )}

                  {analysisLayer === "bias" && biasMap.data && (
                    <Callout tone="info" title="Reading the bias markers">
                      Red means the model is warmer than the float measured; blue means cooler.
                      Marker size is the size of the disagreement. Mean bias across{" "}
                      {biasMap.data.summary.profiles_matched} matched profiles is{" "}
                      {(biasMap.data.summary.mean_bias ?? 0).toFixed(3)}{" "}
                      {formatUnits(biasMap.data.units)}.
                    </Callout>
                  )}

                  {analysisLayer === "eddies" && eddies.data && (
                    <Callout tone="info" title="Reading the eddy rings">
                      Blue rings turn anticlockwise (cyclonic), orange clockwise. {eddies.data.count}{" "}
                      found at this step by the {eddies.data.method} method.
                    </Callout>
                  )}
                </section>
              </>
            ) : (
              <>
                <Select
                  label="Coloured variable"
                  value={variable}
                  onChange={setVariable}
                  options={selectable.length ? selectable : [{ value: variable, label: variable }]}
                />

                <ColourLegend
                  spec={spec}
                  lut={lut.data}
                  actualRange={field.data?.header.actual_range}
                />

                <Field
                  label={`${t("common.depth")} — ${formatDepth(currentDepth)}`}
                  htmlFor="depth-slice"
                  hint={
                    depths.length > 1
                      ? `${depths.length} levels, ${formatDepth(depths[0])} to ${formatDepth(depths[depths.length - 1])}`
                      : "This dataset has a single level"
                  }
                >
                  <input
                    id="depth-slice"
                    type="range"
                    min={0}
                    max={Math.max(0, depths.length - 1)}
                    step={1}
                    value={Math.min(depthIndex, depths.length - 1)}
                    disabled={depths.length < 2}
                    onChange={(event) => setDepthIndex(Number(event.target.value))}
                    aria-valuetext={formatDepth(currentDepth)}
                  />
                </Field>

                <Select
                  label={t("common.region")}
                  value={regionId}
                  onChange={(value) => {
                    setRegion(value);
                    const region = regionById(value);
                    mapApiRef.current?.flyTo(region.centre.lat, region.centre.lon, value === "all" ? 3200 : 1400);
                  }}
                  options={REGIONS.map((region) => ({ value: region.id, label: region.name }))}
                  hint="Moves the camera; it does not filter the data."
                />
              </>
            )}
          </div>
        </aside>
      )}

      <div className="mapstage">
        <div className="mapstage__canvas">
          <OceanMap
            field={field.data}
            lut={lut.data}
            velocity={velocity.data}
            platforms={platforms.data?.platforms ?? []}
            eddies={eddies.data?.eddies ?? []}
            biasMarkers={biasMap.data?.markers ?? []}
            overlay={overlay}
            units={spec?.units ?? ""}
            timeAxisLength={nTimes}
            onSelectProfile={handleSelectProfile}
            onShare={share}
            onReady={handleReady}
          />

          <div style={{ position: "absolute", top: "var(--s4)", left: "50%", transform: "translateX(-50%)", zIndex: 6 }}>
            <IconButton
              icon={<Layers size={17} />}
              label={panelOpen ? "Hide the control panel" : "Show the control panel"}
              bordered
              active={panelOpen}
              onClick={() => setMapPanel(panelOpen ? "none" : "layers")}
            />
          </div>
        </div>

        <Timeline times={times} />
      </div>
    </div>
  );
}

/** A CSS gradient preview of the active palette, for the layer row. */
function gradientForField(lut: Uint8Array | undefined): string | undefined {
  if (!lut || lut.length < 4) return undefined;
  const stops: string[] = [];
  for (let i = 0; i <= 8; i++) {
    const index = Math.min(255, Math.round((i / 8) * 255)) * 4;
    stops.push(`rgb(${lut[index]}, ${lut[index + 1]}, ${lut[index + 2]})`);
  }
  return `linear-gradient(90deg, ${stops.join(", ")})`;
}

function LayerRow({
  id,
  label,
  enabled,
  opacity,
  fixedOpacity,
  swatch,
  onToggle,
  onOpacity,
}: {
  id: LayerId;
  label: string;
  enabled: boolean;
  opacity: number;
  fixedOpacity?: boolean;
  swatch?: string;
  onToggle: () => void;
  onOpacity: (value: number) => void;
}) {
  const percent = Math.round(opacity * 100);
  return (
    <div className="layerrow">
      <div className="layerrow__top">
        <Checkbox checked={enabled} onChange={onToggle} label={label} />
        {swatch && <span className="layerrow__swatch" style={{ background: swatch }} aria-hidden />}
      </div>
      {!fixedOpacity && (
        <div className="layerrow__slider">
          <input
            type="range"
            min={0}
            max={100}
            value={percent}
            disabled={!enabled}
            onChange={(event) => onOpacity(Number(event.target.value) / 100)}
            aria-label={`${label} opacity`}
            aria-valuetext={`${percent} percent`}
            id={`opacity-${id}`}
          />
          <span className="layerrow__pct">{percent}%</span>
        </div>
      )}
    </div>
  );
}
