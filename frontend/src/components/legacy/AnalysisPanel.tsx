import { Activity, Flame, Layers, Target, Waves, X } from "lucide-react";
import { useAppStore, type AnalysisLayer } from "@/state/store";
import { formatSigned, formatUnits, formatValue } from "@/lib/format";
import type { AnomalyResult, BiasMap, EddyCensus } from "@/types/api";
import "./AnalysisPanel.css";

interface AnalysisPanelProps {
  anomaly: AnomalyResult | undefined;
  eddies: EddyCensus | undefined;
  bias: BiasMap | undefined;
}

const OPTIONS: {
  id: AnalysisLayer;
  label: string;
  hint: string;
  Icon: typeof Activity;
}[] = [
  { id: "none", label: "None", hint: "Model fields only", Icon: Layers },
  {
    id: "anomaly",
    label: "Anomaly & Heatwave",
    hint: "Field minus climatology",
    Icon: Flame,
  },
  {
    id: "eddies",
    label: "Eddy Census",
    hint: "Okubo–Weiss cores",
    Icon: Waves,
  },
  {
    id: "bias",
    label: "Model Bias Map",
    hint: "Model minus observations",
    Icon: Target,
  },
];

export function AnalysisPanel({ anomaly, eddies, bias }: AnalysisPanelProps) {
  const { analysisLayer, setAnalysisLayer, toggleAnalysis } = useAppStore();

  return (
    <div className="apanel" role="dialog" aria-label="Analysis layers">
      <header className="apanel__head">
        <h2 className="apanel__title">ANALYSIS</h2>
        <button
          className="apanel__close"
          type="button"
          onClick={toggleAnalysis}
          aria-label="Close analysis panel"
        >
          <X size={15} />
        </button>
      </header>

      <div className="apanel__options">
        {OPTIONS.map(({ id, label, hint, Icon }) => (
          <button
            key={id}
            className={`aopt${analysisLayer === id ? " aopt--on" : ""}`}
            type="button"
            onClick={() => setAnalysisLayer(id)}
          >
            <Icon size={15} aria-hidden />
            <span className="aopt__text">
              <span className="aopt__label">{label}</span>
              <span className="aopt__hint">{hint}</span>
            </span>
          </button>
        ))}
      </div>

      {/* Each layer reports the numbers behind what is being drawn, so the
          overlay is never just a picture. */}
      {analysisLayer === "anomaly" && anomaly && (
        <div className="apanel__readout">
          <Readout label="Reference" value={anomaly.reference} />
          <Readout
            label="Heatwave cells"
            value={`${anomaly.heatwave.cells_flagged} / ${anomaly.heatwave.cells_valid}`}
          />
          <Readout
            label="Area affected"
            value={`${(anomaly.heatwave.area_fraction * 100).toFixed(2)}%`}
          />
          <Readout
            label="Anomaly range"
            value={`${formatSigned(anomaly.heatwave.min_anomaly, 2)} … ${formatSigned(
              anomaly.heatwave.max_anomaly,
              2,
            )} ${formatUnits(anomaly.units)}`}
          />
          {anomaly.reference_note && (
            <p className="apanel__note">{anomaly.reference_note}</p>
          )}
        </div>
      )}

      {analysisLayer === "eddies" && eddies && (
        <div className="apanel__readout">
          <Readout label="Detected" value={String(eddies.count)} />
          <Readout label="Cyclonic" value={String(eddies.cyclonic)} />
          <Readout label="Anticyclonic" value={String(eddies.anticyclonic)} />
          <Readout label="Method" value={eddies.method} />
        </div>
      )}

      {analysisLayer === "bias" && bias && (
        <div className="apanel__readout">
          <Readout label="Profiles matched" value={String(bias.summary.profiles_matched)} />
          <Readout
            label="Mean bias"
            value={`${formatSigned(bias.summary.mean_bias, 3)} ${formatUnits(bias.units)}`}
          />
          <Readout
            label="Mean RMSD"
            value={`${formatValue(bias.summary.mean_rmsd, 3)} ${formatUnits(bias.units)}`}
          />
          {bias.summary.worst_platform && (
            <Readout
              label="Largest deviation"
              value={`${bias.summary.worst_platform.platform_id} (${formatSigned(
                bias.summary.worst_platform.bias,
                2,
              )})`}
            />
          )}
          <div className="apanel__biaskey">
            <span><i className="dot dot--cool" /> Model cooler</span>
            <span><i className="dot dot--warm" /> Model warmer</span>
          </div>
        </div>
      )}
    </div>
  );
}

function Readout({ label, value }: { label: string; value: string }) {
  return (
    <div className="areadout">
      <span className="label">{label}</span>
      <span className="areadout__value mono">{value}</span>
    </div>
  );
}
