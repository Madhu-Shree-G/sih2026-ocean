import { Bell, ChevronDown, LineChart, Radio, Sun } from "lucide-react";
import { useAppStore } from "@/state/store";
import { formatUtc } from "@/lib/format";
import { Emblem, IncoisMark } from "./Insignia";
import "./Header.css";

interface HeaderProps {
  currentTime: string | null;
  alertCount: number;
}

export function Header({ currentTime, alertCount }: HeaderProps) {
  const toggleAlerts = useAppStore((s) => s.toggleAlerts);
  const toggleAnalysis = useAppStore((s) => s.toggleAnalysis);
  const analysisOpen = useAppStore((s) => s.analysisOpen);

  return (
    <header className="hdr">
      <div className="hdr__brand">
        <Emblem className="hdr__emblem" />
        <div>
          <h1 className="hdr__title">INDO-FOS</h1>
          <p className="hdr__subtitle">Indian Ocean Forecasting &amp; Observing System</p>
        </div>
      </div>

      <div className="hdr__centre">
        <div className="mode-pill">
          <Radio size={15} className="mode-pill__icon" aria-hidden />
          <div className="mode-pill__text">
            <span className="mode-pill__mode">REAL-TIME MODE</span>
            <span className="mode-pill__time mono">{formatUtc(currentTime)}</span>
          </div>
        </div>
      </div>

      <div className="hdr__actions">
        <button className="hdr__btn" onClick={toggleAlerts} type="button">
          <Bell size={14} aria-hidden />
          <span>Alerts</span>
          {alertCount > 0 && <span className="hdr__badge">{alertCount}</span>}
        </button>

        <button
          className={`hdr__btn${analysisOpen ? " hdr__btn--on" : ""}`}
          onClick={toggleAnalysis}
          type="button"
        >
          <LineChart size={14} aria-hidden />
          <span>Analysis</span>
        </button>

        <button className="hdr__icon" type="button" aria-label="Notifications">
          <Bell size={16} aria-hidden />
        </button>
        <button className="hdr__icon" type="button" aria-label="Toggle theme">
          <Sun size={16} aria-hidden />
        </button>

        <button className="hdr__lang" type="button">
          <span>EN</span>
          <ChevronDown size={13} aria-hidden />
        </button>

        <IncoisMark className="hdr__incois" />
      </div>
    </header>
  );
}
