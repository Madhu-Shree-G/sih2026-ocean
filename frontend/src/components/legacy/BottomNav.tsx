import {
  Activity,
  Database,
  FileText,
  Globe,
  Settings,
  Radar,
} from "lucide-react";
import { useAppStore, type NavSection } from "@/state/store";
import { Emblem } from "./Insignia";
import "./BottomNav.css";

const SECTIONS: { id: NavSection; label: string; Icon: typeof Globe }[] = [
  { id: "overview", label: "Overview", Icon: Globe },
  { id: "observations", label: "Observations", Icon: Radar },
  { id: "analysis", label: "Analysis", Icon: Activity },
  { id: "data", label: "Data & Services", Icon: Database },
  { id: "reports", label: "Reports", Icon: FileText },
  { id: "settings", label: "Settings", Icon: Settings },
];

export function BottomNav() {
  const navSection = useAppStore((s) => s.navSection);
  const setNavSection = useAppStore((s) => s.setNavSection);

  return (
    <nav className="bnav" aria-label="Primary">
      <div className="bnav__items">
        {SECTIONS.map(({ id, label, Icon }) => (
          <button
            key={id}
            className={`bnav__item${navSection === id ? " bnav__item--on" : ""}`}
            onClick={() => setNavSection(id)}
            type="button"
            aria-current={navSection === id ? "page" : undefined}
          >
            <Icon size={17} aria-hidden />
            <span>{label.toUpperCase()}</span>
          </button>
        ))}
      </div>

      <div className="bnav__ministry">
        <Emblem className="bnav__emblem" />
        <div className="bnav__ministryText">
          <p className="bnav__ministryName">Ministry of Earth Sciences</p>
          <p className="bnav__ministryGov">Government of India</p>
        </div>
      </div>
    </nav>
  );
}
