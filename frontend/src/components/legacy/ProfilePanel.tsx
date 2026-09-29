import { AlertTriangle, Flame, Waves, Wind, X, Loader2, MousePointerClick } from "lucide-react";
import { useAppStore } from "@/state/store";
import {
  formatLatLon,
  formatSigned,
  formatUnits,
  formatUtc,
  formatValue,
} from "@/lib/format";
import { SEVERITY_LABEL } from "@/lib/alerts";
import type { CollocationResult, OceanAlert } from "@/types/api";
import { CollocationChart } from "./CollocationChart";
import "./ProfilePanel.css";

interface ProfilePanelProps {
  collocation: CollocationResult | undefined;
  loading: boolean;
  error: string | null;
  alerts: OceanAlert[];
  comparableVariables: string[];
  onFocusAlert: (alert: OceanAlert) => void;
}

const ALERT_ICON = {
  cyclone: Wind,
  heatwave: Flame,
  upwelling: Waves,
  eddy: Waves,
  bias: AlertTriangle,
} as const;

export function ProfilePanel({
  collocation,
  loading,
  error,
  alerts,
  comparableVariables,
  onFocusAlert,
}: ProfilePanelProps) {
  const {
    selectedProfileId,
    selectProfile,
    collocationVariable,
    setCollocationVariable,
  } = useAppStore();

  const stats = collocation?.statistics ?? null;
  const units = formatUnits(collocation?.units);

  return (
    <aside className="ppanel">
      {/* ---- Profile / collocation ------------------------------------------ */}
      <section className="ppanel__block">
        <header className="ppanel__head">
          <h2 className="ppanel__title">
            PROFILE
            {collocation ? ` / FLOAT ID: ${collocation.platform_id}` : ""}
          </h2>
          {selectedProfileId !== null && (
            <button
              className="ppanel__close"
              type="button"
              onClick={() => selectProfile(null)}
              aria-label="Clear selection"
            >
              <X size={15} />
            </button>
          )}
        </header>

        {selectedProfileId === null && (
          <div className="ppanel__empty">
            <MousePointerClick size={26} aria-hidden />
            <p className="ppanel__emptyTitle">Select a platform</p>
            <p className="ppanel__emptyBody">
              Click any float, glider or CTD marker on the globe to compare its
              measured profile against the model at the same point in space and
              time.
            </p>
          </div>
        )}

        {selectedProfileId !== null && loading && (
          <div className="ppanel__loading">
            <Loader2 size={17} className="spin" aria-hidden />
            <span>Collocating…</span>
          </div>
        )}

        {selectedProfileId !== null && error && (
          <div className="ppanel__error">
            <AlertTriangle size={15} aria-hidden />
            <span>{error}</span>
          </div>
        )}

        {collocation && !loading && (
          <>
            <div className="meta">
              <div className="meta__cell">
                <p className="label">Location</p>
                <p className="meta__value mono">
                  {formatLatLon(collocation.location.lat, collocation.location.lon)}
                </p>
              </div>
              <div className="meta__cell">
                <p className="label">Time</p>
                <p className="meta__value mono">
                  {formatUtc(collocation.observation_time)}
                </p>
              </div>
              <div className="meta__cell">
                <p className="label">Depth</p>
                <p className="meta__value mono">
                  0 – {Math.round(Math.max(...collocation.profile.depth_m))} m
                </p>
              </div>
              <div className="meta__cell">
                <p className="label">Variable</p>
                <select
                  className="meta__select"
                  value={collocationVariable}
                  onChange={(event) => setCollocationVariable(event.target.value)}
                  aria-label="Collocation variable"
                >
                  {comparableVariables.map((name) => (
                    <option key={name} value={name}>
                      {name}
                    </option>
                  ))}
                </select>
              </div>
            </div>

            <CollocationChart data={collocation} />

            {/* The numbers that turn a picture into a verification result. */}
            <div className="stats">
              <Stat label="Bias" value={formatSigned(stats?.bias, 2, units ? ` ${units}` : "")} />
              <Stat label="RMSD" value={formatValue(stats?.rmsd, 2, units ? ` ${units}` : "")} />
              <Stat label="MAE" value={formatValue(stats?.mae, 2, units ? ` ${units}` : "")} />
              <Stat label="Correlation (r)" value={formatValue(stats?.correlation, 2)} />
              <Stat
                label="Max |Diff|"
                value={formatValue(stats?.max_abs_difference, 2, units ? ` ${units}` : "")}
                note={
                  stats?.depth_of_max_difference_m != null
                    ? `@ ${Math.round(stats.depth_of_max_difference_m)} m`
                    : undefined
                }
              />
              <Stat label="Levels" value={String(stats?.n_levels ?? "—")} />
            </div>

            <div className="ppanel__footnote mono">
              <span>Model step {formatUtc(collocation.model_time)}</span>
              <span>
                Δt {formatSigned(collocation.time_offset_hours, 1, " h")} · Δx{" "}
                {formatValue(collocation.grid_distance_km, 1, " km")}
              </span>
            </div>

            {collocation.warnings.length > 0 && (
              <ul className="ppanel__warnings">
                {collocation.warnings.map((warning) => (
                  <li key={warning}>{warning}</li>
                ))}
              </ul>
            )}
          </>
        )}
      </section>

      {/* ---- Alerts --------------------------------------------------------- */}
      <section className="ppanel__block ppanel__block--alerts">
        <header className="ppanel__head">
          <h2 className="ppanel__title">ACTIVE ALERTS</h2>
          <button className="ppanel__link" type="button">
            View all
          </button>
        </header>

        {alerts.length === 0 ? (
          <p className="ppanel__quiet">
            No anomalies above threshold at this timestep.
          </p>
        ) : (
          <ul className="alerts">
            {alerts.map((alert) => {
              const Icon = ALERT_ICON[alert.kind] ?? AlertTriangle;
              return (
                <li key={alert.id}>
                  <button
                    className="alert"
                    type="button"
                    onClick={() => onFocusAlert(alert)}
                    title={alert.detail}
                  >
                    <span className={`alert__icon alert__icon--${alert.severity}`}>
                      <Icon size={14} />
                    </span>
                    <span className="alert__text">
                      <span className="alert__title">{alert.title}</span>
                      <span className="alert__where">{alert.location}</span>
                    </span>
                    <span className={`alert__sev alert__sev--${alert.severity}`}>
                      {SEVERITY_LABEL[alert.severity]}
                    </span>
                  </button>
                </li>
              );
            })}
          </ul>
        )}
      </section>
    </aside>
  );
}

function Stat({
  label,
  value,
  note,
}: {
  label: string;
  value: string;
  note?: string;
}) {
  return (
    <div className="stat">
      <p className="label">{label}</p>
      <p className="stat__value mono">{value}</p>
      {note && <p className="stat__note mono">{note}</p>}
    </div>
  );
}
