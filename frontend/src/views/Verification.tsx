/**
 * Model Accuracy.
 *
 * A forecasting product that will not show where it is wrong is asking to be
 * trusted rather than earning it. This screen puts the model beside the
 * instruments that measured the same water at the same time, states the
 * disagreement in plain words as well as in statistics, and lists the floats
 * where the gap is largest.
 */

import { useMemo } from "react";
import { AlertTriangle, MapPin, Target, TrendingDown, TrendingUp } from "lucide-react";
import { useAppStore } from "@/state/store";
import { useBiasMap, useCollocation, useComparableVariables } from "@/lib/queries";
import { ApiError } from "@/lib/api";
import {
  formatLatLon,
  formatSigned,
  formatUnits,
  formatUtc,
  formatValue,
  shortName,
} from "@/lib/format";
import { CollocationChart } from "@/components/CollocationChart";
import {
  Badge,
  Button,
  Callout,
  Card,
  CardBody,
  CardHead,
  Disclosure,
  EmptyState,
  Loading,
  SectionTitle,
  Select,
  SortHeader,
  Stat,
  StatGrid,
  TableWrap,
  useSort,
} from "@/ui";
import "./views.css";

type Column = "platform_id" | "bias" | "rmsd" | "n_levels" | "time";

export function VerificationView() {
  const {
    selectedProfileId,
    collocationVariable,
    setCollocationVariable,
    focusOnMap,
    setSection,
  } = useAppStore();

  const collocation = useCollocation();
  const biasMap = useBiasMap(true);
  const comparable = useComparableVariables(true);
  const sort = useSort<Column>("bias", "desc");

  const stats = collocation.data?.statistics ?? null;
  const units = formatUnits(collocation.data?.units);
  const error = collocation.error instanceof ApiError ? collocation.error.message : null;

  const markers = useMemo(() => {
    const list = biasMap.data?.markers ?? [];
    return [...list].sort((a, b) => {
      // Rank by magnitude, so a large negative bias is as interesting as a
      // large positive one — sorting by signed value buries half the problem.
      if (sort.key === "bias" || sort.key === "rmsd") {
        const av = Math.abs(a[sort.key] ?? 0);
        const bv = Math.abs(b[sort.key] ?? 0);
        return sort.direction === "asc" ? av - bv : bv - av;
      }
      return sort.compare(a[sort.key], b[sort.key]);
    });
  }, [biasMap.data, sort]);

  const comparableOptions = (comparable.data?.comparable ?? ["temperature"]).map((name) => ({
    value: name,
    label: shortName(name),
  }));

  return (
    <div className="view">
      <div className="view__inner">
        <header className="view__header">
          <div className="view__lede">
            <h1>Model accuracy</h1>
            <p>
              How closely the model matches what instruments actually measured, at the same place
              and the same time. Nothing here is smoothed or hidden.
            </p>
          </div>
          <Select
            label="Compare"
            value={collocationVariable}
            onChange={setCollocationVariable}
            options={comparableOptions}
          />
        </header>

        {/* ---- Basin-wide summary --------------------------------------------- */}
        <section aria-labelledby="summary-heading">
          <SectionTitle
            title={<span id="summary-heading">Across the whole basin</span>}
            subtitle={
              biasMap.data
                ? `${biasMap.data.summary.profiles_matched} profiles matched down to ${biasMap.data.depth_max_m} m`
                : undefined
            }
          />
          {biasMap.isLoading ? (
            <Card><Loading label="Matching profiles against the model…" /></Card>
          ) : biasMap.data ? (
            <>
              <StatGrid>
                <Stat
                  label="Mean bias"
                  value={formatSigned(biasMap.data.summary.mean_bias, 3)}
                  note={`${formatUnits(biasMap.data.units)} — model minus observed`}
                  tone={Math.abs(biasMap.data.summary.mean_bias ?? 0) > 0.5 ? "warn" : "ok"}
                />
                <Stat
                  label="Mean RMSD"
                  value={formatValue(biasMap.data.summary.mean_rmsd, 3)}
                  note={formatUnits(biasMap.data.units)}
                />
                <Stat label="Profiles matched" value={biasMap.data.summary.profiles_matched} />
                <Stat
                  label="Largest deviation"
                  value={
                    biasMap.data.summary.worst_platform
                      ? formatSigned(biasMap.data.summary.worst_platform.bias, 2)
                      : "—"
                  }
                  note={biasMap.data.summary.worst_platform?.platform_id}
                  small
                />
              </StatGrid>

              <div style={{ marginTop: "var(--s4)" }}>
                <Callout
                  tone={Math.abs(biasMap.data.summary.mean_bias ?? 0) > 0.5 ? "warn" : "ok"}
                  title="What this means"
                >
                  {plainBias(biasMap.data.summary.mean_bias, formatUnits(biasMap.data.units))}
                </Callout>
              </div>
            </>
          ) : (
            <Card><EmptyState icon={<Target size={24} />} title="No bias map available" /></Card>
          )}
        </section>

        {/* ---- One profile ------------------------------------------------------ */}
        <section aria-labelledby="profile-heading">
          <SectionTitle
            title={<span id="profile-heading">One instrument, level by level</span>}
            subtitle="Select a float on the map or in Observations to compare its cast against the model."
          />

          {selectedProfileId === null ? (
            <Card>
              <EmptyState
                icon={<Target size={24} />}
                title="No instrument selected"
                body="Pick a platform to see its measured profile drawn against the model at the same point in space and time."
                action={
                  <Button variant="primary" onClick={() => setSection("observations")}>
                    Browse platforms
                  </Button>
                }
              />
            </Card>
          ) : collocation.isLoading ? (
            <Card><Loading label="Collocating…" /></Card>
          ) : error ? (
            <Card>
              <EmptyState
                icon={<AlertTriangle size={24} />}
                title="Could not collocate this profile"
                body={error}
                tone="warn"
              />
            </Card>
          ) : collocation.data ? (
            <div className="split">
              <Card>
                <CardHead
                  title={
                    <span className="row gap3">
                      <span className="mono">{collocation.data.platform_id}</span>
                      <Badge tone="info">{shortName(collocation.data.variable)}</Badge>
                    </span>
                  }
                  subtitle={`${formatLatLon(
                    collocation.data.location.lat,
                    collocation.data.location.lon,
                  )} · observed ${formatUtc(collocation.data.observation_time)}`}
                  actions={
                    <Button
                      variant="secondary"
                      size="sm"
                      onClick={() =>
                        focusOnMap(collocation.data!.location.lat, collocation.data!.location.lon)
                      }
                    >
                      <MapPin size={14} aria-hidden />
                      Map
                    </Button>
                  }
                />
                <CardBody>
                  <CollocationChart data={collocation.data} />
                  <p className="faint" style={{ fontSize: "var(--fs-xs)", marginTop: "var(--s3)" }}>
                    Model step {formatUtc(collocation.data.model_time)} · Δt{" "}
                    {formatSigned(collocation.data.time_offset_hours, 1, " h")} · Δx{" "}
                    {formatValue(collocation.data.grid_distance_km, 1, " km")} from the nearest grid
                    point.
                  </p>
                  {collocation.data.warnings.length > 0 && (
                    <div style={{ marginTop: "var(--s3)" }}>
                      <Callout tone="warn" title="Caveats on this match">
                        <ul>
                          {collocation.data.warnings.map((warning) => (
                            <li key={warning}>{warning}</li>
                          ))}
                        </ul>
                      </Callout>
                    </div>
                  )}
                </CardBody>
              </Card>

              <Card>
                <CardHead title="Statistics" subtitle="Model against this cast" />
                <CardBody>
                  <StatGrid>
                    <Stat
                      label="Bias"
                      value={formatSigned(stats?.bias, 2)}
                      note={units}
                      small
                      tone={Math.abs(stats?.bias ?? 0) > 0.5 ? "warn" : "ok"}
                    />
                    <Stat label="RMSD" value={formatValue(stats?.rmsd, 2)} note={units} small />
                    <Stat label="MAE" value={formatValue(stats?.mae, 2)} note={units} small />
                    <Stat
                      label="Correlation"
                      value={formatValue(stats?.correlation, 3)}
                      note="1.0 is a perfect match"
                      small
                    />
                    <Stat
                      label="Max difference"
                      value={formatValue(stats?.max_abs_difference, 2)}
                      note={
                        stats?.depth_of_max_difference_m != null
                          ? `at ${Math.round(stats.depth_of_max_difference_m)} m`
                          : units
                      }
                      small
                    />
                    <Stat label="Levels compared" value={stats?.n_levels ?? "—"} small />
                  </StatGrid>

                  <Disclosure summary="What do these numbers mean?">
                    <p>
                      <strong>Bias</strong> is the average signed difference: positive means the
                      model runs warmer (or saltier) than the instrument, negative means cooler. A
                      bias near zero with a large RMSD means the model is right on average but
                      noisy.
                    </p>
                    <p>
                      <strong>RMSD</strong> is the typical size of the error at any one level, with
                      large errors weighted more heavily. <strong>MAE</strong> is the same idea
                      without that weighting, so a big gap between the two points to a few bad
                      levels rather than a uniform offset.
                    </p>
                    <p>
                      <strong>Correlation</strong> measures shape rather than value: a correlation
                      of 0.99 with a bias of 2 °C means the model has the structure of the water
                      column right and is simply offset.
                    </p>
                  </Disclosure>
                </CardBody>
              </Card>
            </div>
          ) : null}
        </section>

        {/* ---- Worst offenders --------------------------------------------------- */}
        {markers.length > 0 && (
          <section aria-labelledby="markers-heading">
            <SectionTitle
              title={<span id="markers-heading">Where the model disagrees most</span>}
              subtitle="Sorted by the size of the disagreement, not its direction."
            />
            <TableWrap maxHeight={420}>
              <table className="table table--clickable">
                <thead>
                  <tr>
                    <SortHeader columnKey="platform_id" active={sort.key === "platform_id"} direction={sort.direction} onSort={sort.onSort}>
                      Platform
                    </SortHeader>
                    <SortHeader columnKey="bias" active={sort.key === "bias"} direction={sort.direction} onSort={sort.onSort} numeric>
                      Bias
                    </SortHeader>
                    <SortHeader columnKey="rmsd" active={sort.key === "rmsd"} direction={sort.direction} onSort={sort.onSort} numeric>
                      RMSD
                    </SortHeader>
                    <SortHeader columnKey="n_levels" active={sort.key === "n_levels"} direction={sort.direction} onSort={sort.onSort} numeric>
                      Levels
                    </SortHeader>
                    <SortHeader columnKey="time" active={sort.key === "time"} direction={sort.direction} onSort={sort.onSort}>
                      Observed
                    </SortHeader>
                    <th scope="col">Position</th>
                  </tr>
                </thead>
                <tbody>
                  {markers.slice(0, 60).map((marker) => (
                    <tr
                      key={marker.profile_id}
                      onClick={() => focusOnMap(marker.lat, marker.lon)}
                      tabIndex={0}
                      onKeyDown={(event) => {
                        if (event.key === "Enter") focusOnMap(marker.lat, marker.lon);
                      }}
                    >
                      <td className="mono strong">{marker.platform_id}</td>
                      <td className="num">
                        <span className="row gap2" style={{ justifyContent: "flex-end" }}>
                          {(marker.bias ?? 0) >= 0 ? (
                            <TrendingUp size={14} aria-label="model warmer" style={{ color: "var(--danger)" }} />
                          ) : (
                            <TrendingDown size={14} aria-label="model cooler" style={{ color: "var(--model-color)" }} />
                          )}
                          {formatSigned(marker.bias, 2)}
                        </span>
                      </td>
                      <td className="num">{formatValue(marker.rmsd, 2)}</td>
                      <td className="num">{marker.n_levels}</td>
                      <td className="mono muted">{formatUtc(marker.time)}</td>
                      <td className="mono muted">{formatLatLon(marker.lat, marker.lon, 1)}</td>
                    </tr>
                  ))}
                </tbody>
              </table>
            </TableWrap>
          </section>
        )}
      </div>
    </div>
  );
}

function plainBias(bias: number | null | undefined, units: string): string {
  if (bias === null || bias === undefined || !Number.isFinite(bias)) {
    return "Not enough matched profiles to state an average bias.";
  }
  const magnitude = Math.abs(bias);
  const direction = bias >= 0 ? "warmer" : "cooler";

  if (magnitude < 0.1) {
    return `Averaged over every matched profile, the model is within ${magnitude.toFixed(3)} ${units} of what the instruments measured. That is close agreement — differences at individual floats are noise around a well-centred model rather than a systematic offset.`;
  }
  if (magnitude < 0.5) {
    return `The model runs ${magnitude.toFixed(2)} ${units} ${direction} than the instruments on average. That is a small, consistent offset: usable for guidance, but worth subtracting if you are reading absolute values rather than patterns.`;
  }
  return `The model runs ${magnitude.toFixed(2)} ${units} ${direction} than the instruments on average. That is large enough to matter for any decision keyed to an absolute threshold, and the per-float table below shows whether it is uniform or concentrated in one region.`;
}
