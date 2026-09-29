/**
 * Analysis — the derived products, each with its numbers on screen.
 *
 * Four of these endpoints existed in the backend and had no route into the
 * interface at all: mixed-layer depth, thermocline depth, and the drift
 * simulator. The drift tool in particular is the one a district disaster
 * officer would reach for, so it is a first-class panel rather than a
 * developer-only endpoint.
 */

import { useState } from "react";
import { useMutation } from "@tanstack/react-query";
import { Activity, Compass, Flame, Layers, LifeBuoy, Play, Waves } from "lucide-react";
import { useAppStore, regionById } from "@/state/store";
import {
  useAnomaly,
  useAxes,
  useEddies,
  useMixedLayerDepth,
  useThermocline,
} from "@/lib/queries";
import * as api from "@/lib/api";
import { ApiError } from "@/lib/api";
import { formatLatLon, formatSigned, formatUnits, formatUtc, formatValue } from "@/lib/format";
import { rampCss, DEPTH_RAMP, DIVERGING } from "@/lib/grid-render";
import {
  Badge,
  Button,
  Callout,
  Card,
  CardBody,
  CardHead,
  Disclosure,
  EmptyState,
  Field,
  Loading,
  SectionTitle,
  Stat,
  StatGrid,
  TableWrap,
} from "@/ui";
import type { DriftResult } from "@/types/api";
import "./views.css";

export function AnalysisView() {
  const { timeIndex, focusOnMap, setAnalysisLayer, regionId } = useAppStore();
  const axes = useAxes();

  const anomaly = useAnomaly(true);
  const eddies = useEddies(true);
  const mld = useMixedLayerDepth(true);
  const thermocline = useThermocline(true);

  const times = axes.data?.times ?? [];
  const currentTime = times[Math.min(timeIndex, times.length - 1)] ?? null;

  return (
    <div className="view">
      <div className="view__inner">
        <header className="view__header">
          <div className="view__lede">
            <h1>Analysis</h1>
            <p>
              Products computed from the model field rather than stored in it. Each panel reports
              the numbers behind what the map draws, so an overlay is never only a picture.
            </p>
          </div>
          <Badge tone="neutral">{formatUtc(currentTime)}</Badge>
        </header>

        <div className="grid2">
          {/* ---- Anomaly ------------------------------------------------------ */}
          <Card>
            <CardHead
              title={<span className="row gap2"><Flame size={18} aria-hidden /> Anomaly & marine heatwave</span>}
              subtitle="This time step minus the seasonal climatology"
              actions={
                <Button variant="secondary" size="sm" onClick={() => setAnalysisLayer("anomaly")}>
                  Draw on map
                </Button>
              }
            />
            <CardBody>
              {anomaly.isLoading ? (
                <Loading label="Computing the anomaly field…" />
              ) : anomaly.data ? (
                <>
                  <StatGrid>
                    <Stat
                      label="Heatwave cells"
                      value={`${anomaly.data.heatwave.cells_flagged} / ${anomaly.data.heatwave.cells_valid}`}
                      small
                      tone={anomaly.data.heatwave.cells_flagged > 0 ? "warn" : "ok"}
                    />
                    <Stat
                      label="Area affected"
                      value={`${(anomaly.data.heatwave.area_fraction * 100).toFixed(2)}%`}
                      small
                    />
                    <Stat
                      label="Warmest anomaly"
                      value={formatSigned(anomaly.data.heatwave.max_anomaly, 2)}
                      note={formatUnits(anomaly.data.units)}
                      small
                    />
                    <Stat
                      label="Coolest anomaly"
                      value={formatSigned(anomaly.data.heatwave.min_anomaly, 2)}
                      note={formatUnits(anomaly.data.units)}
                      small
                    />
                  </StatGrid>

                  <div className="legend" style={{ marginTop: "var(--s4)" }}>
                    <span className="label">Colour scale</span>
                    <div className="legend__ramp" style={{ background: rampCss(DIVERGING) }} />
                    <div className="legend__ticks">
                      <span>cooler than normal</span>
                      <span>normal</span>
                      <span>warmer than normal</span>
                    </div>
                  </div>

                  <p className="muted" style={{ fontSize: "var(--fs-sm)", marginTop: "var(--s3)" }}>
                    Reference: <span className="mono">{anomaly.data.reference}</span>. A cell is
                    flagged once it runs {anomaly.data.heatwave.threshold.toFixed(1)}{" "}
                    {formatUnits(anomaly.data.units)} or more above that average.
                  </p>
                  {anomaly.data.reference_note && (
                    <Callout tone="neutral">{anomaly.data.reference_note}</Callout>
                  )}
                </>
              ) : (
                <EmptyState icon={<Flame size={22} />} title="No climatology loaded" body="Anomalies need a reference dataset." />
              )}
            </CardBody>
          </Card>

          {/* ---- Eddies -------------------------------------------------------- */}
          <Card>
            <CardHead
              title={<span className="row gap2"><Waves size={18} aria-hidden /> Eddy census</span>}
              subtitle={eddies.data ? `${eddies.data.method} at ${eddies.data.depth_m} m` : undefined}
              actions={
                <Button variant="secondary" size="sm" onClick={() => setAnalysisLayer("eddies")}>
                  Draw on map
                </Button>
              }
            />
            <CardBody>
              {eddies.isLoading ? (
                <Loading label="Detecting eddies…" />
              ) : eddies.data ? (
                <>
                  <StatGrid>
                    <Stat label="Detected" value={eddies.data.count} small />
                    <Stat label="Cyclonic" value={eddies.data.cyclonic} small />
                    <Stat label="Anticyclonic" value={eddies.data.anticyclonic} small />
                  </StatGrid>

                  <div style={{ marginTop: "var(--s4)" }}>
                    <TableWrap maxHeight={230}>
                      <table className="table table--clickable">
                        <thead>
                          <tr>
                            <th scope="col">Centre</th>
                            <th scope="col">Spin</th>
                            <th className="num" scope="col">Radius</th>
                            <th className="num" scope="col">Peak speed</th>
                          </tr>
                        </thead>
                        <tbody>
                          {[...eddies.data.eddies]
                            .sort((a, b) => b["max_speed_ms-1"] - a["max_speed_ms-1"])
                            .map((eddy) => (
                              <tr
                                key={eddy.id}
                                onClick={() => focusOnMap(eddy.centre.lat, eddy.centre.lon)}
                                tabIndex={0}
                                onKeyDown={(event) =>
                                  event.key === "Enter" && focusOnMap(eddy.centre.lat, eddy.centre.lon)
                                }
                              >
                                <td className="mono">{formatLatLon(eddy.centre.lat, eddy.centre.lon, 1)}</td>
                                <td>
                                  <Badge tone={eddy.polarity === "cyclonic" ? "info" : "warn"}>
                                    {eddy.polarity === "cyclonic" ? "Anticlockwise" : "Clockwise"}
                                  </Badge>
                                </td>
                                <td className="num">{eddy.radius_km.toFixed(0)} km</td>
                                <td className="num">{eddy["max_speed_ms-1"].toFixed(2)} m/s</td>
                              </tr>
                            ))}
                        </tbody>
                      </table>
                    </TableWrap>
                  </div>
                </>
              ) : (
                <EmptyState icon={<Waves size={22} />} title="No eddy census available" />
              )}
            </CardBody>
          </Card>

          {/* ---- Mixed layer --------------------------------------------------- */}
          <DepthProduct
            icon={<Layers size={18} aria-hidden />}
            title="Mixed layer depth"
            subtitle="How deep the wind and waves stir the surface"
            query={mld}
            explain="The mixed layer is the slab of water at the top of the ocean that wind and waves keep stirred, so it is nearly uniform in temperature. A shallow mixed layer heats up fast and can trigger a heatwave; a deep one spreads the same heat through far more water. It also bounds where surface-feeding fish can find food."
            onDraw={() => setAnalysisLayer("mixed_layer_depth")}
          />

          {/* ---- Thermocline --------------------------------------------------- */}
          <DepthProduct
            icon={<Activity size={18} aria-hidden />}
            title="Thermocline depth"
            subtitle="Where temperature falls fastest with depth"
            query={thermocline}
            explain="The thermocline is the sharp temperature step below the mixed layer. It acts as a lid: nutrients below it cannot easily reach sunlit water above, so a shallow thermocline usually means a more productive sea. Sonar behaves differently across it too, which is why fishing and naval operations both track it."
            onDraw={() => setAnalysisLayer("thermocline")}
          />
        </div>

        {/* ---- Drift ------------------------------------------------------------ */}
        <section aria-labelledby="drift-heading">
          <SectionTitle
            title={<span id="drift-heading">Drift and search area</span>}
            subtitle="Where something released into the water is likely to travel."
          />
          <DriftSimulator defaultRegion={regionId} />
        </section>
      </div>
    </div>
  );
}

/* ========================================================================== */
/* Depth products                                                             */
/* ========================================================================== */

function DepthProduct({
  icon,
  title,
  subtitle,
  query,
  explain,
  onDraw,
}: {
  icon: React.ReactNode;
  title: string;
  subtitle: string;
  query: ReturnType<typeof useMixedLayerDepth>;
  explain: string;
  onDraw: () => void;
}) {
  return (
    <Card>
      <CardHead
        title={<span className="row gap2">{icon} {title}</span>}
        subtitle={subtitle}
        actions={
          <Button variant="secondary" size="sm" onClick={onDraw}>
            Draw on map
          </Button>
        }
      />
      <CardBody>
        {query.isLoading ? (
          <Loading label="Computing…" />
        ) : query.data ? (
          <>
            <StatGrid>
              <Stat
                label="Shallowest"
                value={formatValue(query.data.value_range[0], 0)}
                note={query.data.units ?? "m"}
                small
              />
              <Stat
                label="Deepest"
                value={formatValue(query.data.value_range[1], 0)}
                note={query.data.units ?? "m"}
                small
              />
              <Stat label="Grid" value={`${query.data.grid.shape[0]}×${query.data.grid.shape[1]}`} small />
            </StatGrid>

            <div className="legend" style={{ marginTop: "var(--s4)" }}>
              <div className="legend__ramp" style={{ background: rampCss(DEPTH_RAMP) }} />
              <div className="legend__ticks">
                <span>{formatValue(query.data.value_range[0], 0)} m</span>
                <span>{formatValue(query.data.value_range[1], 0)} m</span>
              </div>
            </div>

            {query.data.method && (
              <p className="faint" style={{ fontSize: "var(--fs-xs)", marginTop: "var(--s3)" }}>
                Method: {query.data.method}
              </p>
            )}

            <Disclosure summary="What is this?">
              <p>{explain}</p>
            </Disclosure>
          </>
        ) : (
          <EmptyState icon={<Layers size={22} />} title="Not available" />
        )}
      </CardBody>
    </Card>
  );
}

/* ========================================================================== */
/* Drift simulator                                                            */
/* ========================================================================== */

function DriftSimulator({ defaultRegion }: { defaultRegion: string }) {
  const { datasetId, timeIndex, focusOnMap } = useAppStore();
  const centre = regionById(defaultRegion).centre;

  const [lat, setLat] = useState(String(centre.lat));
  const [lon, setLon] = useState(String(centre.lon));
  const [hours, setHours] = useState(48);
  const [particles, setParticles] = useState(500);

  const run = useMutation<DriftResult, Error>({
    mutationFn: () =>
      api.simulateDrift({
        lat: Number(lat),
        lon: Number(lon),
        dataset: datasetId ?? undefined,
        time_index: timeIndex,
        duration_hours: hours,
        n_particles: particles,
      }),
  });

  const invalid =
    !Number.isFinite(Number(lat)) || !Number.isFinite(Number(lon)) || datasetId === null;

  return (
    <Card>
      <CardHead
        title={<span className="row gap2"><LifeBuoy size={18} aria-hidden /> Drift simulator</span>}
        subtitle="Release virtual particles at a point and follow the currents forward."
      />
      <CardBody>
        <div className="grid3">
          <Field label="Latitude (°N)" htmlFor="drift-lat">
            <input
              id="drift-lat"
              className="control mono"
              inputMode="decimal"
              value={lat}
              onChange={(event) => setLat(event.target.value)}
            />
          </Field>
          <Field label="Longitude (°E)" htmlFor="drift-lon">
            <input
              id="drift-lon"
              className="control mono"
              inputMode="decimal"
              value={lon}
              onChange={(event) => setLon(event.target.value)}
            />
          </Field>
          <Field label={`Duration — ${hours} hours`} htmlFor="drift-hours">
            <input
              id="drift-hours"
              type="range"
              min={6}
              max={120}
              step={6}
              value={hours}
              onChange={(event) => setHours(Number(event.target.value))}
              aria-valuetext={`${hours} hours`}
            />
          </Field>
          <Field label={`Particles — ${particles}`} htmlFor="drift-particles">
            <input
              id="drift-particles"
              type="range"
              min={50}
              max={2000}
              step={50}
              value={particles}
              onChange={(event) => setParticles(Number(event.target.value))}
              aria-valuetext={`${particles} particles`}
            />
          </Field>
        </div>

        <div className="row gap3" style={{ marginTop: "var(--s4)" }}>
          <Button variant="primary" onClick={() => run.mutate()} disabled={invalid || run.isPending}>
            <Play size={16} aria-hidden />
            {run.isPending ? "Running…" : "Run simulation"}
          </Button>
          <Button
            variant="secondary"
            onClick={() => focusOnMap(Number(lat), Number(lon))}
            disabled={invalid}
          >
            <Compass size={16} aria-hidden />
            Show release point
          </Button>
        </div>

        {run.isError && (
          <div style={{ marginTop: "var(--s4)" }}>
            <Callout tone="danger" title="The simulation could not run">
              {run.error instanceof ApiError ? run.error.message : run.error.message}
            </Callout>
          </div>
        )}

        {run.data && (
          <div style={{ marginTop: "var(--s5)" }}>
            <StatGrid>
              <Stat
                label="Search radius"
                value={`${run.data.final_search_radius_km.toFixed(1)} km`}
                note={`after ${run.data.duration_hours} h`}
                small
              />
              <Stat
                label="Centre of mass"
                value={
                  run.data.final_centroid
                    ? formatLatLon(run.data.final_centroid[1], run.data.final_centroid[0], 2)
                    : "—"
                }
                small
              />
              <Stat
                label="Stranded"
                value={`${run.data.particles_stranded} / ${run.data.n_particles}`}
                note="reached land"
                small
                tone={run.data.particles_stranded > 0 ? "warn" : undefined}
              />
              <Stat label="Model step" value={formatUtc(run.data.model_time)} small />
            </StatGrid>

            <div style={{ marginTop: "var(--s4)" }}>
              <Callout tone="warn" title="Read this before using the result">
                {run.data.disclaimer}
              </Callout>
            </div>

            <Disclosure summary="How the search radius grows over time">
              <TableWrap maxHeight={220}>
                <table className="table">
                  <thead>
                    <tr>
                      <th className="num" scope="col">Hours</th>
                      <th className="num" scope="col">Search radius (km)</th>
                      <th scope="col">Centre</th>
                    </tr>
                  </thead>
                  <tbody>
                    {run.data.times_hours.map((hour, index) => (
                      <tr key={hour}>
                        <td className="num">{hour.toFixed(0)}</td>
                        <td className="num">{run.data!.search_radius_km[index]?.toFixed(2) ?? "—"}</td>
                        <td className="mono muted">
                          {run.data!.centroid[index]
                            ? formatLatLon(run.data!.centroid[index][1], run.data!.centroid[index][0], 2)
                            : "—"}
                        </td>
                      </tr>
                    ))}
                  </tbody>
                </table>
              </TableWrap>
            </Disclosure>
          </div>
        )}
      </CardBody>
    </Card>
  );
}
