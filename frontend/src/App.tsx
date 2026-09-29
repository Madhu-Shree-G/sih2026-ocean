/**
 * Application root: preferences, service discovery, and routing.
 *
 * The store decides which section is on screen; this file owns the handful of
 * effects that have to happen once for the whole app — applying the display
 * preferences to the document, picking a dataset, keeping the colour range
 * honest, deriving the advisories, and restoring a shared link.
 */

import { useCallback, useEffect, useMemo, useRef } from "react";
import { AlertTriangle, Bell, Loader2, ServerCrash } from "lucide-react";
import { ApiError } from "@/lib/api";
import { deriveAlerts, SEVERITY_LABEL } from "@/lib/alerts";
import { planePercentileRange, roundRange } from "@/lib/ocvol";
import {
  useAnomaly,
  useAxes,
  useBiasMap,
  useCollocation,
  useDataset,
  useEddies,
  useField,
  usePlatforms,
  useReady,
  useVelocity,
} from "@/lib/queries";
import { useAppStore, type Section } from "@/state/store";
import { useT } from "@/i18n";
import { AppShell } from "@/components/AppShell";
import { Assistant } from "@/components/Assistant";
import type { MapApi } from "@/components/OceanMap";
import { TodayView } from "@/views/Today";
import { MapView } from "@/views/MapView";
import { ObservationsView } from "@/views/Observations";
import { VerificationView } from "@/views/Verification";
import { AnalysisView } from "@/views/Analysis";
import { DataServicesView } from "@/views/DataServices";
import { ReportsView } from "@/views/Reports";
import { SettingsView } from "@/views/Settings";
import { Badge, Button, EmptyState, Modal } from "@/ui";
import type { ActionHandlers, SnapshotInputs } from "@/lib/deep-client";

export default function App() {
  const t = useT();
  const store = useAppStore();
  const {
    datasetId,
    setDataset,
    variable,
    timeIndex,
    colorScale,
    resetColorScale,
    section,
    alerts,
    setAlerts,
    alertsOpen,
    setAlertsOpen,
    selectProfile,
    focusOnMap,
  } = store;

  usePreferenceEffects();

  /* ---------------------------------------------------------------------- */
  /* Service discovery                                                       */
  /* ---------------------------------------------------------------------- */
  const ready = useReady();

  useEffect(() => {
    const first = ready.data?.datasets?.[0];
    if (first && !datasetId) setDataset(first);
  }, [ready.data, datasetId, setDataset]);

  const dataset = useDataset();
  const axes = useAxes();
  const nTimes = axes.data?.times.length ?? 1;

  const field = useField(nTimes);
  const velocity = useVelocity(nTimes);
  const platforms = usePlatforms(ready.data?.status === "ready");
  const anomaly = useAnomaly(ready.data?.status === "ready");
  const eddies = useEddies(ready.data?.status === "ready");
  const biasMap = useBiasMap(false);
  const collocation = useCollocation();

  const spec = useMemo(
    () => dataset.data?.variables.find((entry) => entry.name === variable),
    [dataset.data, variable],
  );

  /* Adopt each variable's canonical palette unless the user overrode it. */
  useEffect(() => {
    if (!spec || colorScale.custom) return;
    if (colorScale.colormap !== spec.default_colormap) {
      const [lo, hi] = spec.default_range ?? [0, 1];
      resetColorScale(spec.default_colormap, lo, hi);
    }
  }, [spec, colorScale.custom, colorScale.colormap, resetColorScale]);

  /* Fit the colour range to what is actually in the surface field. A CF
     default of 2-32 °C against water spanning 26-30 °C spends most of the ramp
     on values that are not present, flattening every gradient into one wash.
     Percentiles, not min/max, so one anomalous cell cannot stretch the scale. */
  useEffect(() => {
    if (!field.data || colorScale.custom || !spec) return;
    const range = planePercentileRange(field.data, { time: 0, depth: 0 });
    if (!range) return;
    const [lo, hi] = roundRange(range);
    if (Math.abs(lo - colorScale.vmin) > 1e-6 || Math.abs(hi - colorScale.vmax) > 1e-6) {
      resetColorScale(spec.default_colormap, lo, hi);
    }
  }, [field.data, spec, colorScale.custom, colorScale.vmin, colorScale.vmax, resetColorScale]);

  /* Advisories are derived from real responses, so they change with time. */
  useEffect(() => {
    setAlerts(deriveAlerts(anomaly.data, eddies.data));
  }, [anomaly.data, eddies.data, setAlerts]);

  /* ---------------------------------------------------------------------- */
  /* Shared links                                                            */
  /* ---------------------------------------------------------------------- */
  const mapApiRef = useRef<MapApi | null>(null);
  useSharedLink(mapApiRef);

  /* ---------------------------------------------------------------------- */
  /* Deep                                                                    */
  /* ---------------------------------------------------------------------- */
  const deepInputs = useMemo<SnapshotInputs>(
    () => ({
      axes: axes.data,
      spec,
      variables: dataset.data?.variables ?? [],
      alerts,
      collocation: collocation.data,
      visiblePlatforms: platforms.data?.count ?? 0,
      dataRange: field.data?.header.actual_range,
      eddyCount: eddies.data?.count,
      heatwaveCells: anomaly.data?.heatwave.cells_flagged,
      meanBias: biasMap.data?.summary.mean_bias ?? null,
      camera: mapApiRef.current?.camera() ?? undefined,
    }),
    [
      axes.data,
      spec,
      dataset.data,
      alerts,
      collocation.data,
      platforms.data,
      field.data,
      eddies.data,
      anomaly.data,
      biasMap.data,
    ],
  );

  const deepHandlers = useMemo<ActionHandlers>(
    () => ({
      flyTo: (lat, lon, heightKm) => {
        // Deep can be asked to fly from any screen, so make sure the map is
        // the screen the user ends up looking at.
        useAppStore.getState().setSection("map");
        mapApiRef.current?.flyTo(lat, lon, heightKm);
      },
      resetView: () => mapApiRef.current?.resetView(),
      autofitColorRange: () => {
        const range = field.data?.header.actual_range;
        if (range) {
          useAppStore.getState().setColorScale({
            vmin: Number(range[0].toFixed(2)),
            vmax: Number(range[1].toFixed(2)),
          });
        }
      },
      selectPlatformById: (platformId) => {
        const platform = platforms.data?.platforms.find(
          (entry) => entry.platform_id === platformId,
        );
        const track = platform?.trajectory;
        const latest = track && track.length > 0 ? track[track.length - 1] : null;
        if (latest) selectProfile(latest.profile_id, platformId);
      },
      dismiss: () => useAppStore.getState().setAssistantOpen(false),
    }),
    [field.data, platforms.data, selectProfile],
  );

  /* ---------------------------------------------------------------------- */
  /* Boot states                                                             */
  /* ---------------------------------------------------------------------- */
  if (ready.isLoading) {
    return (
      <div className="view">
        <div className="view__inner">
          <EmptyState
            icon={<Loader2 size={26} className="spin" />}
            title={t("common.loading")}
            body="Connecting to the INDO-FOS services on this host."
          />
        </div>
      </div>
    );
  }

  if (ready.isError && !ready.data) {
    return (
      <div className="view">
        <div className="view__inner">
          <EmptyState
            icon={<ServerCrash size={26} />}
            tone="danger"
            title={t("status.offline")}
            body={
              <>
                <p>The backend is not answering on this host. Start it, then reload this page.</p>
                <code>cd backend &amp;&amp; .venv/Scripts/python -m uvicorn app.main:app --reload</code>
              </>
            }
            action={
              <Button variant="primary" onClick={() => ready.refetch()}>
                {t("common.retry")}
              </Button>
            }
          />
        </div>
      </div>
    );
  }

  const dataMissing =
    ready.data?.status === "degraded" ||
    (ready.error instanceof ApiError && ready.error.isDataUnavailable);

  const times = axes.data?.times ?? [];
  const currentTime = times[Math.min(timeIndex, times.length - 1)] ?? null;
  const busy = field.isFetching || velocity.isFetching;

  return (
    <AppShell
      currentTime={currentTime}
      status={ready.data?.status === "ready" ? "ready" : "degraded"}
      alertCount={alerts.length}
      busy={busy}
    >
      {dataMissing ? (
        <div className="view">
          <div className="view__inner">
            <EmptyState
              icon={<AlertTriangle size={26} />}
              tone="warn"
              title={t("status.degraded")}
              body={
                <>
                  <p>{ready.data?.hint ?? "Generate the demo dataset, then reload this page."}</p>
                  <code>python scripts/generate_sample_data.py</code>
                </>
              }
            />
          </div>
        </div>
      ) : (
        <SectionView section={section} mapApiRef={mapApiRef} />
      )}

      {alertsOpen && (
        <Modal title={t("today.advisories")} onClose={() => setAlertsOpen(false)} closeLabel={t("common.close")}>
          {alerts.length === 0 ? (
            <EmptyState
              icon={<Bell size={24} />}
              title={t("today.noAdvisories")}
              body={t("today.noAdvisoriesBody")}
            />
          ) : (
            <ul className="stack gap3">
              {alerts.map((alert) => (
                <li key={alert.id}>
                  <button
                    type="button"
                    className="advisory"
                    disabled={!alert.focus}
                    onClick={() => {
                      if (alert.focus) focusOnMap(alert.focus.lat, alert.focus.lon);
                      setAlertsOpen(false);
                    }}
                  >
                    <span className={`advisory__icon advisory__icon--${alert.severity}`}>
                      <AlertTriangle size={17} aria-hidden />
                    </span>
                    <span className="grow">
                      <span className="advisory__title">{alert.title}</span>
                      <span className="advisory__where"> · {alert.location}</span>
                      {alert.detail && <span className="advisory__detail">{alert.detail}</span>}
                    </span>
                    <Badge
                      tone={
                        alert.severity === "high"
                          ? "danger"
                          : alert.severity === "moderate"
                            ? "warn"
                            : "info"
                      }
                    >
                      {SEVERITY_LABEL[alert.severity]}
                    </Badge>
                  </button>
                </li>
              ))}
            </ul>
          )}
        </Modal>
      )}

      <Assistant snapshotInputs={deepInputs} handlers={deepHandlers} />
    </AppShell>
  );
}

/* ========================================================================== */
/* Routing                                                                    */
/* ========================================================================== */

function SectionView({
  section,
  mapApiRef,
}: {
  section: Section;
  mapApiRef: React.MutableRefObject<MapApi | null>;
}) {
  switch (section) {
    case "map":
      return <MapView mapApiRef={mapApiRef} />;
    case "observations":
      return <ObservationsView />;
    case "verification":
      return <VerificationView />;
    case "analysis":
      return <AnalysisView />;
    case "data":
      return <DataServicesView />;
    case "reports":
      return <ReportsView />;
    case "settings":
      return <SettingsView />;
    case "today":
    default:
      return <TodayView />;
  }
}

/* ========================================================================== */
/* Preferences                                                                */
/* ========================================================================== */

/**
 * Push the display preferences onto the document element.
 *
 * The tokens are keyed off `data-theme`, `data-textsize`, `data-contrast` and
 * `lang`, so setting these four attributes restyles the entire application and
 * switches the Devanagari font stack in one place.
 */
function usePreferenceEffects() {
  const { theme, textSize, highContrast, language } = useAppStore();

  useEffect(() => {
    const root = document.documentElement;

    const apply = () => {
      const prefersDark = window.matchMedia?.("(prefers-color-scheme: dark)").matches ?? false;
      const resolved = theme === "system" ? (prefersDark ? "dark" : "light") : theme;
      root.setAttribute("data-theme", resolved);
    };
    apply();

    // "Match device" has to keep matching after the OS flips at sunset.
    if (theme !== "system") return;
    const query = window.matchMedia?.("(prefers-color-scheme: dark)");
    query?.addEventListener("change", apply);
    return () => query?.removeEventListener("change", apply);
  }, [theme]);

  useEffect(() => {
    document.documentElement.setAttribute("data-textsize", textSize);
  }, [textSize]);

  useEffect(() => {
    document.documentElement.setAttribute("data-contrast", highContrast ? "high" : "normal");
  }, [highContrast]);

  useEffect(() => {
    document.documentElement.setAttribute("lang", language);
  }, [language]);
}

/**
 * Restore state from a shared URL, once, on first load.
 *
 * The camera cannot move until the map exists, so that part waits for the map
 * handle to appear rather than firing into a null ref.
 */
function useSharedLink(mapApiRef: React.MutableRefObject<MapApi | null>) {
  const applied = useRef(false);

  const restore = useCallback(() => {
    if (applied.current) return;
    const params = new URLSearchParams(window.location.search);
    if ([...params.keys()].length === 0) {
      applied.current = true;
      return;
    }

    const store = useAppStore.getState();
    const section = params.get("section");
    const variable = params.get("variable");
    const time = params.get("time");
    const depth = params.get("depth");
    const analysis = params.get("analysis");

    if (section) store.setSection(section as Section);
    if (variable) store.setVariable(variable);
    if (time !== null && Number.isFinite(Number(time))) store.setTimeIndex(Number(time));
    if (depth !== null && Number.isFinite(Number(depth))) store.setDepthIndex(Number(depth));
    if (analysis) store.setAnalysisLayer(analysis as never);

    const lat = Number(params.get("lat"));
    const lon = Number(params.get("lon"));
    const km = Number(params.get("km"));
    if (Number.isFinite(lat) && Number.isFinite(lon) && mapApiRef.current) {
      mapApiRef.current.flyTo(lat, lon, Number.isFinite(km) ? km : 2600);
    }

    applied.current = true;
  }, [mapApiRef]);

  useEffect(() => {
    restore();
    // The map mounts a tick later; try once more so a shared camera lands.
    const id = window.setTimeout(restore, 1200);
    return () => window.clearTimeout(id);
  }, [restore]);
}
