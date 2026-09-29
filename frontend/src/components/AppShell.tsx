/**
 * The application frame: masthead, section navigation, and the status strip.
 *
 * The old chrome was a header of mostly-decorative controls above a six-item
 * bottom bar where every item rendered the same screen. Here the navigation is
 * the router: `section` in the store decides what `App` renders, so a nav item
 * that appears is a place you can actually go.
 */

import type { ReactNode } from "react";
import {
  Activity,
  AlertTriangle,
  BarChart3,
  Bell,
  ChevronsLeft,
  ChevronsRight,
  Database,
  FileText,
  Globe2,
  Languages,
  Moon,
  Radio,
  Settings as SettingsIcon,
  Sun,
  Sparkles,
  Sunrise,
  Target,
} from "lucide-react";
import {
  sectionsForMode,
  useAppStore,
  type Section,
} from "@/state/store";
import { useT } from "@/i18n";
import { LANGUAGE_NAMES } from "@/i18n/strings";
import type { StringKey } from "@/i18n/strings";
import { formatUtc } from "@/lib/format";
import { IconButton, Segmented } from "@/ui";
import { Emblem } from "./Insignia";
import "./AppShell.css";

const SECTION_META: Record<Section, { key: StringKey; Icon: typeof Globe2 }> = {
  today: { key: "nav.today", Icon: Sunrise },
  map: { key: "nav.map", Icon: Globe2 },
  observations: { key: "nav.observations", Icon: Radio },
  verification: { key: "nav.verification", Icon: Target },
  analysis: { key: "nav.analysis", Icon: Activity },
  data: { key: "nav.data", Icon: Database },
  reports: { key: "nav.reports", Icon: FileText },
  settings: { key: "nav.settings", Icon: SettingsIcon },
};

interface AppShellProps {
  children: ReactNode;
  currentTime: string | null;
  status: "ready" | "degraded" | "offline";
  alertCount: number;
  busy?: boolean;
}

export function AppShell({ children, currentTime, status, alertCount, busy }: AppShellProps) {
  const t = useT();
  const {
    mode,
    setMode,
    section,
    setSection,
    language,
    setLanguage,
    theme,
    setTheme,
    sidebarCollapsed,
    toggleSidebar,
    alertsOpen,
    toggleAlerts,
    assistantOpen,
    setAssistantOpen,
  } = useAppStore();

  const sections = sectionsForMode(mode);

  const statusTone =
    status === "ready" ? "ok" : status === "degraded" ? "warn" : "danger";
  const statusLabel =
    status === "ready"
      ? t("status.live")
      : status === "degraded"
        ? t("status.degraded")
        : t("status.offline");

  // "system" is a real third state, but a single toggle only has two ends.
  // Clicking it commits to an explicit choice, which is what someone reaching
  // for the button in a bright room actually wants.
  const nextTheme = theme === "dark" ? "light" : "dark";

  return (
    <div className={`shell${sidebarCollapsed ? " shell--narrow" : ""}`}>
      <a className="skip" href="#main">
        {t("nav.skip")}
      </a>

      {/* ---- Masthead ------------------------------------------------------ */}
      <header className="mast">
        <div className="mast__brand">
          <Emblem className="mast__emblem" />
          <div className="mast__names">
            <p className="mast__gov">
              {t("app.ministry")} · {t("app.government")}
            </p>
            <h1 className="mast__title">
              {t("app.name")}
              <span className="mast__full">{t("app.full")}</span>
            </h1>
          </div>
        </div>

        <div className="mast__status">
          <span className={`mast__pill mast__pill--${statusTone}`}>
            <span className="mast__pulse" aria-hidden />
            {statusLabel}
          </span>
          {currentTime && (
            <span className="mast__clock mono" title="Model time step being displayed">
              {formatUtc(currentTime)}
            </span>
          )}
          {busy && <span className="mast__busy">{t("common.loading")}</span>}
        </div>

        <div className="mast__actions">
          <Segmented
            label="Audience mode"
            value={mode}
            onChange={setMode}
            options={[
              { value: "public", label: t("mode.public"), title: t("mode.public.title") },
              { value: "official", label: t("mode.official"), title: t("mode.official.title") },
            ]}
          />

          <IconButton
            icon={<Languages size={18} />}
            label={`${t("a11y.languageToggle")} — ${LANGUAGE_NAMES[language === "en" ? "hi" : "en"]}`}
            onClick={() => setLanguage(language === "en" ? "hi" : "en")}
          />
          <span className="mast__lang" aria-hidden>
            {language === "en" ? "EN" : "हिं"}
          </span>

          <IconButton
            icon={theme === "dark" ? <Sun size={18} /> : <Moon size={18} />}
            label={t("a11y.themeToggle")}
            onClick={() => setTheme(nextTheme)}
          />

          <IconButton
            icon={
              <span className="mast__bell">
                {alertCount > 0 ? <AlertTriangle size={18} /> : <Bell size={18} />}
                {alertCount > 0 && <span className="mast__badge">{alertCount}</span>}
              </span>
            }
            label={`${t("today.advisories")} (${alertCount})`}
            active={alertsOpen}
            onClick={toggleAlerts}
          />

          <IconButton
            icon={<Sparkles size={18} />}
            label="Ask Deep, the ocean assistant"
            active={assistantOpen}
            onClick={() => setAssistantOpen(!assistantOpen)}
          />
        </div>
      </header>

      {/* ---- Navigation ---------------------------------------------------- */}
      <nav className="side" aria-label={t("nav.section")}>
        <ul className="side__list">
          {sections.map((id) => {
            const { key, Icon } = SECTION_META[id];
            const current = section === id;
            return (
              <li key={id}>
                <button
                  type="button"
                  className={`side__item${current ? " side__item--on" : ""}`}
                  aria-current={current ? "page" : undefined}
                  onClick={() => setSection(id)}
                  title={sidebarCollapsed ? t(key) : undefined}
                >
                  <Icon size={19} aria-hidden />
                  <span className="side__label">{t(key)}</span>
                </button>
              </li>
            );
          })}
        </ul>

        <div className="side__foot">
          {mode === "public" && !sidebarCollapsed && (
            <p className="side__note">
              <BarChart3 size={14} aria-hidden /> More technical screens are available in{" "}
              <button type="button" className="side__link" onClick={() => setMode("official")}>
                {t("mode.official")}
              </button>{" "}
              mode.
            </p>
          )}
          <button
            type="button"
            className="side__collapse"
            onClick={toggleSidebar}
            aria-label={sidebarCollapsed ? t("nav.expand") : t("nav.collapse")}
          >
            {sidebarCollapsed ? <ChevronsRight size={17} /> : <ChevronsLeft size={17} />}
            {!sidebarCollapsed && <span>{t("nav.collapse")}</span>}
          </button>
        </div>
      </nav>

      <main className="shell__main" id="main" tabIndex={-1}>
        {children}
      </main>
    </div>
  );
}
