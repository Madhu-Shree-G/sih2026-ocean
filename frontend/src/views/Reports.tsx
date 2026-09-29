/**
 * Reports — a briefing note that can leave the screen.
 *
 * Everything else in this application dies when the tab closes. A government
 * user's actual deliverable is a page they can attach to a file, so this view
 * renders one: dated, sourced, with its caveats stated, and printable to PDF
 * through the browser without any of the interface furniture coming with it.
 */

import { useMemo } from "react";
import { Download, Printer } from "lucide-react";
import { useAppStore, regionById, REGIONS } from "@/state/store";
import { useT } from "@/i18n";
import {
  useAnomaly,
  useAxes,
  useBiasMap,
  useDataset,
  useEddies,
  useField,
  useObservationStatistics,
  usePlatforms,
  useVelocity,
  volumeTimeIndex,
} from "@/lib/queries";
import {
  assessCurrents,
  assessEddies,
  assessHeatwave,
  assessTemperature,
  alertsInRegion,
  eddiesInRegion,
  levelLabel,
  overallLevel,
  overallStatement,
  regionAnomalyStats,
  regionName,
  regionSpeedStats,
  regionStats,
} from "@/lib/ocean-plain";
import { formatDate, formatSigned, formatUnits, formatUtc, formatValue } from "@/lib/format";
import { Button, Card, Loading, Select, useToast } from "@/ui";
import { Emblem } from "@/components/Insignia";
import "./views.css";

export function ReportsView() {
  const t = useT();
  const toast = useToast();
  const { language, regionId, setRegion, timeIndex, alerts } = useAppStore();

  const region = regionById(regionId);
  const axes = useAxes();
  const dataset = useDataset();
  const nTimes = axes.data?.times.length ?? 1;

  const field = useField(nTimes);
  const velocity = useVelocity(nTimes);
  const anomaly = useAnomaly(true);
  const eddies = useEddies(true);
  const biasMap = useBiasMap(true);
  const platforms = usePlatforms(true);
  const observations = useObservationStatistics(true);

  const times = axes.data?.times ?? [];
  const currentTime = times[Math.min(timeIndex, times.length - 1)] ?? null;

  const fieldTime = volumeTimeIndex(timeIndex, nTimes, field.data);
  const velocityTime = volumeTimeIndex(timeIndex, nTimes, velocity.data?.u);

  const findings = useMemo(() => {
    const surface = regionStats(field.data, region.bbox, fieldTime, 0);
    const speed = regionSpeedStats(velocity.data, region.bbox, velocityTime, 0);
    const anomalyStats = regionAnomalyStats(anomaly.data, region.bbox);
    const regionEddies = eddiesInRegion(eddies.data, region.bbox);

    return [
      assessTemperature(surface, anomalyStats, region, language),
      assessHeatwave(anomalyStats, region, language),
      assessCurrents(speed, region, language),
      assessEddies(regionEddies, region, language),
    ];
  }, [field.data, velocity.data, anomaly.data, eddies.data, region, language, fieldTime, velocityTime]);

  const level = overallLevel(findings.map((finding) => finding.level));
  const verdict = overallStatement(level, region, language);
  const regionAlerts = alertsInRegion(alerts, region.bbox);

  const platformsHere = useMemo(() => {
    const [west, south, east, north] = region.bbox;
    return (platforms.data?.platforms ?? []).filter((platform) => {
      const position = platform.last_position;
      return (
        position !== null &&
        position !== undefined &&
        position.lon >= west &&
        position.lon <= east &&
        position.lat >= south &&
        position.lat <= north
      );
    });
  }, [platforms.data, region.bbox]);

  const issued = new Date();

  const downloadText = () => {
    const lines = [
      `${t("app.name")} — Ocean Situation Report`,
      `${t("app.ministry")}, ${t("app.government")}`,
      "",
      `Area: ${regionName(region, language)}`,
      `Model time step: ${formatUtc(currentTime)}`,
      `Issued: ${issued.toISOString()}`,
      `Dataset: ${dataset.data?.id ?? "—"} (${dataset.data?.source ?? "—"})`,
      "",
      `ASSESSMENT — ${levelLabel(level, language)}`,
      verdict.headline,
      verdict.detail,
      "",
      "FINDINGS",
      ...findings.flatMap((finding) => [
        `• ${finding.headline}`,
        `  ${finding.detail}`,
        finding.action ? `  Action: ${finding.action}` : "",
      ]),
      "",
      "ADVISORIES",
      ...(regionAlerts.length
        ? regionAlerts.map(
            (alert) => `• [${alert.severity}] ${alert.title} — ${alert.location}. ${alert.detail ?? ""}`,
          )
        : ["• None above threshold for this area and time step."]),
      "",
      "VERIFICATION",
      `Mean model bias: ${formatSigned(biasMap.data?.summary.mean_bias, 3)} ${formatUnits(biasMap.data?.units)} across ${biasMap.data?.summary.profiles_matched ?? 0} matched profiles.`,
      `Instruments in area: ${platformsHere.length} of ${observations.data?.platforms ?? 0}.`,
      "",
      "CAVEAT",
      "Model-based guidance, not an official warning. Cross-check INCOIS and IMD bulletins before operational use.",
    ];

    const blob = new Blob([lines.filter(Boolean).join("\n")], {
      type: "text/plain;charset=utf-8",
    });
    const url = URL.createObjectURL(blob);
    const anchor = document.createElement("a");
    anchor.href = url;
    anchor.download = `indofos-report-${region.id}-${issued.toISOString().slice(0, 10)}.txt`;
    anchor.click();
    URL.revokeObjectURL(url);
    toast("Report downloaded");
  };

  if (field.isLoading) return <Loading label="Assembling the report…" />;

  return (
    <div className="view">
      <div className="view__inner">
        <header className="view__header no-print">
          <div className="view__lede">
            <h1>Reports</h1>
            <p>
              A dated situation report for one stretch of coast, built from the same values shown
              everywhere else in this application.
            </p>
          </div>
          <div className="row gap3 wrap">
            <Select
              label={t("common.region")}
              value={regionId}
              onChange={setRegion}
              options={REGIONS.map((option) => ({
                value: option.id,
                label: regionName(option, language),
              }))}
            />
            <Button variant="secondary" onClick={downloadText}>
              <Download size={16} aria-hidden />
              {t("common.download")}
            </Button>
            <Button variant="primary" onClick={() => window.print()}>
              <Printer size={16} aria-hidden />
              {t("common.print")}
            </Button>
          </div>
        </header>

        <Card as="article" className="report">
          <header className="report__mast">
            <Emblem />
            <div>
              <p className="label">
                {t("app.ministry")} · {t("app.government")}
              </p>
              <h2 style={{ borderBottom: "none", margin: 0, padding: 0 }}>
                Ocean Situation Report
              </h2>
              <p className="muted" style={{ fontSize: "var(--fs-sm)" }}>
                {regionName(region, language)} · {formatUtc(currentTime)}
              </p>
            </div>
          </header>

          <dl>
            <dt>Issued</dt>
            <dd>{issued.toISOString().replace("T", " ").slice(0, 19)} UTC</dd>
            <dt>Area</dt>
            <dd>
              {region.bbox[0]}–{region.bbox[2]}°E, {region.bbox[1]}–{region.bbox[3]}°N
            </dd>
            <dt>Dataset</dt>
            <dd>{dataset.data?.id ?? "—"}</dd>
            <dt>Source</dt>
            <dd>{dataset.data?.source || dataset.data?.institution || "—"}</dd>
            <dt>Time coverage</dt>
            <dd>
              {times.length
                ? `${formatDate(times[0])} – ${formatDate(times[times.length - 1])} (${times.length} steps)`
                : "—"}
            </dd>
          </dl>

          <h2>1. Assessment</h2>
          <p>
            <strong>{levelLabel(level, language)}. </strong>
            {verdict.headline}. {verdict.detail}
          </p>

          <h2>2. Findings</h2>
          {findings.map((finding) => (
            <div key={finding.id}>
              <p>
                <strong>{finding.headline}.</strong> {finding.detail}
              </p>
              {finding.action && (
                <p className="muted">
                  <em>Guidance:</em> {finding.action}
                </p>
              )}
            </div>
          ))}

          <h2>3. Advisories in force</h2>
          {regionAlerts.length === 0 ? (
            <p>No derived advisory crosses its alert threshold for this area at this time step.</p>
          ) : (
            <ul>
              {regionAlerts.map((alert) => (
                <li key={alert.id}>
                  <strong>{alert.title}</strong> — {alert.location} ({alert.severity}).{" "}
                  {alert.detail}
                </li>
              ))}
            </ul>
          )}

          <h2>4. Observing network</h2>
          <p>
            {platformsHere.length} instrument{platformsHere.length === 1 ? "" : "s"} reported inside
            this area, out of {observations.data?.platforms ?? 0} across the basin, contributing to{" "}
            {observations.data?.profiles?.toLocaleString("en-IN") ?? "—"} profiles and{" "}
            {observations.data?.measurement_levels?.toLocaleString("en-IN") ?? "—"} measurement
            levels in the archive.
          </p>

          <h2>5. Model verification</h2>
          <p>
            Against every profile the model could be matched to, the mean bias is{" "}
            <strong>{formatSigned(biasMap.data?.summary.mean_bias, 3)}{" "}
            {formatUnits(biasMap.data?.units)}</strong> with a mean RMSD of{" "}
            {formatValue(biasMap.data?.summary.mean_rmsd, 3)}{" "}
            {formatUnits(biasMap.data?.units)}, over{" "}
            {biasMap.data?.summary.profiles_matched ?? 0} matched profiles.
            {biasMap.data?.summary.worst_platform &&
              ` The largest single deviation is at platform ${biasMap.data.summary.worst_platform.platform_id} (${formatSigned(biasMap.data.summary.worst_platform.bias, 2)}).`}
          </p>

          <h2>6. Caveats</h2>
          <ul>
            <li>
              This is model-derived guidance produced automatically. It is not an official warning
              and does not replace INCOIS or IMD bulletins.
            </li>
            <li>
              Thresholds used: marine heatwave at{" "}
              {anomaly.data?.heatwave.threshold?.toFixed(1) ?? "—"}{" "}
              {formatUnits(anomaly.data?.units)} above the seasonal average; anomalies referenced
              against <span className="mono">{anomaly.data?.reference ?? "—"}</span>.
            </li>
            <li>
              Statements about a region are computed over the model cells inside the bounding box
              above; a value at any single point may differ from the regional average.
            </li>
          </ul>

          <p className="faint" style={{ fontSize: "var(--fs-xs)", marginTop: "var(--s6)" }}>
            Generated by {t("app.name")} — {t("app.full")}. Every figure in this report can be
            reproduced from the REST endpoints listed under Data &amp; Services.
          </p>
        </Card>
      </div>
    </div>
  );
}
