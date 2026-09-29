/**
 * Settings.
 *
 * These are accessibility settings before they are preferences. Text size,
 * contrast and language decide whether this application is usable at all for
 * a large share of the people it is meant to serve, so they are one screen,
 * plainly labelled, and they persist across visits.
 */

import { Contrast, Eye, Globe2, Info, Languages, Palette, RotateCcw, Ruler } from "lucide-react";
import { useAppStore, type TextSize, type ThemeChoice, type Units } from "@/state/store";
import { useT } from "@/i18n";
import { LANGUAGE_NAMES, type Language } from "@/i18n/strings";
import { useServiceInfo } from "@/lib/queries";
import {
  Button,
  Callout,
  Card,
  CardBody,
  CardHead,
  SectionTitle,
  Segmented,
  Switch,
  useToast,
} from "@/ui";
import "./views.css";

export function SettingsView() {
  const t = useT();
  const toast = useToast();
  const {
    language,
    setLanguage,
    theme,
    setTheme,
    textSize,
    setTextSize,
    highContrast,
    setHighContrast,
    units,
    setUnits,
    mode,
    setMode,
    resetPreferences,
  } = useAppStore();

  const info = useServiceInfo(true);

  return (
    <div className="view">
      <div className="view__inner">
        <header className="view__header">
          <div className="view__lede">
            <h1>{t("settings.title")}</h1>
            <p>
              These choices are stored on this device only. Nothing here is sent to the server or
              tied to an account.
            </p>
          </div>
        </header>

        {/* ---- Language ------------------------------------------------------- */}
        <Card>
          <CardHead
            title={<span className="row gap2"><Languages size={18} aria-hidden /> {t("settings.language")}</span>}
          />
          <CardBody>
            <Segmented
              large
              label={t("settings.language")}
              value={language}
              onChange={(value) => setLanguage(value as Language)}
              options={(Object.keys(LANGUAGE_NAMES) as Language[]).map((code) => ({
                value: code,
                label: LANGUAGE_NAMES[code],
              }))}
            />
            <div style={{ marginTop: "var(--s4)" }}>
              <Callout tone="neutral">{t("settings.languageNote")}</Callout>
            </div>
          </CardBody>
        </Card>

        {/* ---- Appearance ------------------------------------------------------ */}
        <Card>
          <CardHead
            title={<span className="row gap2"><Palette size={18} aria-hidden /> {t("settings.appearance")}</span>}
          />
          <CardBody>
            <div className="stack gap6">
              <div className="stack gap2">
                <span className="label">{t("settings.theme")}</span>
                <Segmented
                  large
                  label={t("settings.theme")}
                  value={theme}
                  onChange={(value) => setTheme(value as ThemeChoice)}
                  options={[
                    { value: "light", label: t("settings.theme.light") },
                    { value: "dark", label: t("settings.theme.dark") },
                    { value: "system", label: t("settings.theme.system") },
                  ]}
                />
              </div>

              <div className="stack gap2">
                <span className="label">
                  <Eye size={13} aria-hidden style={{ display: "inline", marginRight: 4 }} />
                  {t("settings.textSize")}
                </span>
                <Segmented
                  large
                  label={t("settings.textSize")}
                  value={textSize}
                  onChange={(value) => setTextSize(value as TextSize)}
                  options={[
                    { value: "normal", label: t("settings.textSize.normal") },
                    { value: "large", label: t("settings.textSize.large") },
                    { value: "xlarge", label: t("settings.textSize.xlarge") },
                  ]}
                />
                <p className="faint" style={{ fontSize: "var(--fs-xs)" }}>
                  Scales the whole interface, including the map controls — unlike browser zoom,
                  which reflows the map badly.
                </p>
              </div>

              <div className="stack gap2">
                <Switch
                  checked={highContrast}
                  onChange={setHighContrast}
                  label={
                    <span className="row gap2">
                      <Contrast size={15} aria-hidden />
                      {t("settings.contrast")}
                    </span>
                  }
                />
                <p className="faint" style={{ fontSize: "var(--fs-xs)" }}>
                  {t("settings.contrastNote")}
                </p>
              </div>
            </div>
          </CardBody>
        </Card>

        {/* ---- Units and mode --------------------------------------------------- */}
        <div className="grid2">
          <Card>
            <CardHead
              title={<span className="row gap2"><Ruler size={18} aria-hidden /> {t("settings.units")}</span>}
            />
            <CardBody>
              <Segmented
                large
                label={t("settings.units")}
                value={units}
                onChange={(value) => setUnits(value as Units)}
                options={[
                  { value: "metric", label: "Metric (°C, m/s, m)" },
                  { value: "imperial", label: "Knots & feet" },
                ]}
              />
              <p className="faint" style={{ fontSize: "var(--fs-xs)", marginTop: "var(--s3)" }}>
                Scientific readouts stay in SI units either way; this affects the plain-language
                cards, where knots are what a boat's instruments actually read.
              </p>
            </CardBody>
          </Card>

          <Card>
            <CardHead
              title={<span className="row gap2"><Globe2 size={18} aria-hidden /> Audience mode</span>}
            />
            <CardBody>
              <Segmented
                large
                label="Audience mode"
                value={mode}
                onChange={setMode}
                options={[
                  { value: "public", label: t("mode.public") },
                  { value: "official", label: t("mode.official") },
                ]}
              />
              <p className="muted" style={{ fontSize: "var(--fs-sm)", marginTop: "var(--s3)" }}>
                <strong>{t("mode.public")}</strong> shows the plain-language dashboard, the map and
                reports. <strong>{t("mode.official")}</strong> adds observations, model accuracy,
                analysis products and the service catalogue. Nothing is hidden from anyone — the
                split only decides what is on screen by default.
              </p>
            </CardBody>
          </Card>
        </div>

        {/* ---- About ------------------------------------------------------------ */}
        <section aria-labelledby="about-heading">
          <SectionTitle title={<span id="about-heading">{t("settings.about")}</span>} />
          <Card>
            <CardBody>
              <dl className="report" style={{ border: "none", padding: 0, background: "none" }}>
                <dt>Service</dt>
                <dd>{info.data?.service ?? "—"}</dd>
                <dt>Version</dt>
                <dd>{info.data?.version ?? "—"}</dd>
                <dt>Environment</dt>
                <dd>{info.data?.environment ?? "—"}</dd>
                <dt>Datasets</dt>
                <dd>{info.data?.datasets.join(", ") ?? "—"}</dd>
              </dl>

              <Callout tone="info" title="Attribution">
                Basemap: Natural Earth II, bundled with CesiumJS and rendered offline — this
                application makes no third-party network requests. Ocean fields and observations are
                served entirely by the local INDO-FOS backend.
              </Callout>

              <div style={{ marginTop: "var(--s5)" }}>
                <Button
                  variant="secondary"
                  onClick={() => {
                    resetPreferences();
                    toast("Settings reset");
                  }}
                >
                  <RotateCcw size={16} aria-hidden />
                  {t("settings.reset")}
                </Button>
              </div>
            </CardBody>
          </Card>
        </section>

        <Callout tone="neutral" icon={<Info size={18} aria-hidden />}>
          Keyboard: <kbd>Tab</kbd> moves between controls, <kbd>Space</kbd> plays and pauses the
          time animation, and the <kbd>←</kbd> <kbd>→</kbd> arrows step through time one model
          step at a time.
        </Callout>
      </div>
    </div>
  );
}
