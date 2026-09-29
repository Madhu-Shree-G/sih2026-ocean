/**
 * "Ocean Today" — the public dashboard.
 *
 * This screen exists because the old interface answered a question nobody
 * outside a forecasting desk was asking. A colorbar reading 23-30 °C over a
 * dark globe is a picture of data; it is not information. Everything here is
 * a sentence first and a number second, and every number can be expanded to
 * show exactly which model value produced it.
 */

import { useMemo } from "react";
import {
  AlertTriangle,
  CheckCircle2,
  Flame,
  Info,
  LifeBuoy,
  Map as MapIcon,
  Radio,
  Thermometer,
  Waves,
  Wind,
} from "lucide-react";
import { useAppStore, regionById, REGIONS } from "@/state/store";
import { useT } from "@/i18n";
import {
  assessCurrents,
  assessEddies,
  assessHeatwave,
  assessTemperature,
  alertsInRegion,
  eddiesInRegion,
  levelLabel,
  levelTone,
  overallLevel,
  overallStatement,
  regionAnomalyStats,
  regionName,
  regionSpeedStats,
  regionStats,
  type Finding,
} from "@/lib/ocean-plain";
import {
  useAnomaly,
  useAxes,
  useEddies,
  useField,
  useObservationStatistics,
  usePlatforms,
  useVelocity,
  volumeTimeIndex,
} from "@/lib/queries";
import { formatDate, formatUtc } from "@/lib/format";
import { SEVERITY_LABEL } from "@/lib/alerts";
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
  Stat,
  StatGrid,
} from "@/ui";
import type { OceanAlert } from "@/types/api";
import "./views.css";

const FINDING_ICON = {
  sst: Thermometer,
  heatwave: Flame,
  currents: Wind,
  eddies: Waves,
} as const;

const ALERT_ICON = {
  cyclone: Wind,
  heatwave: Flame,
  upwelling: Waves,
  eddy: Waves,
  bias: AlertTriangle,
} as const;

export function TodayView() {
  const t = useT();
  const { language, regionId, setRegion, timeIndex, focusOnMap, setSection } = useAppStore();

  const region = regionById(regionId);
  const axes = useAxes();
  const nTimes = axes.data?.times.length ?? 1;

  const field = useField(nTimes);
  const velocity = useVelocity(nTimes);
  const anomaly = useAnomaly(true);
  const eddies = useEddies(true);
  const platforms = usePlatforms(true);
  const observations = useObservationStatistics(true);
  const alerts = useAppStore((state) => state.alerts);

  const times = axes.data?.times ?? [];
  const currentTime = times[Math.min(timeIndex, times.length - 1)] ?? null;

  /* The temperature card must describe temperature even when the map is
     showing salinity, so this reads the surface plane of whichever field is
     loaded and says which variable it is. */
  const fieldTime = volumeTimeIndex(timeIndex, nTimes, field.data);
  const velocityTime = volumeTimeIndex(timeIndex, nTimes, velocity.data?.u);

  const findings = useMemo<Finding[]>(() => {
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
  const tone = levelTone(level);

  const regionAlerts = useMemo(
    () => alertsInRegion(alerts, region.bbox),
    [alerts, region.bbox],
  );

  const platformsHere = useMemo(() => {
    const list = platforms.data?.platforms ?? [];
    const [west, south, east, north] = region.bbox;
    return list.filter((platform) => {
      const position = platform.last_position;
      if (!position) return false;
      return (
        position.lon >= west && position.lon <= east && position.lat >= south && position.lat <= north
      );
    });
  }, [platforms.data, region.bbox]);

  const loading = field.isLoading || anomaly.isLoading;

  return (
    <div className="view">
      <div className="view__inner">
        <header className="view__header">
          <div className="view__lede">
            <h1>{t("today.title")}</h1>
            <p>{t("today.subtitle")}</p>
          </div>
          <Button variant="secondary" onClick={() => setSection("map")}>
            <MapIcon size={16} aria-hidden />
            {t("nav.map")}
          </Button>
        </header>

        {/* ---- Region -------------------------------------------------------- */}
        <section aria-labelledby="region-heading">
          <SectionTitle title={<span id="region-heading">{t("today.pickRegion")}</span>} />
          <div className="regionbar" role="group" aria-label={t("today.pickRegion")}>
            {REGIONS.map((option) => (
              <button
                key={option.id}
                type="button"
                className="regionchip"
                aria-pressed={option.id === regionId}
                onClick={() => setRegion(option.id)}
              >
                {regionName(option, language)}
              </button>
            ))}
          </div>
        </section>

        {loading ? (
          <Loading label={t("common.loading")} />
        ) : (
          <>
            {/* ---- Verdict --------------------------------------------------- */}
            <section
              className="verdict"
              aria-live="polite"
              style={
                {
                  "--verdict-color": `var(--${tone === "ok" ? "ok" : tone})`,
                  "--verdict-soft": `var(--${tone === "ok" ? "ok" : tone}-soft)`,
                } as React.CSSProperties
              }
            >
              <span className="verdict__mark">
                {level === "normal" ? <CheckCircle2 size={28} /> : <AlertTriangle size={28} />}
              </span>
              <div>
                <p className="label">{t("today.overall")}</p>
                <h2 className="verdict__headline">{verdict.headline}</h2>
                <p className="verdict__detail">{verdict.detail}</p>
                <div className="verdict__meta">
                  <span>
                    {t("common.updated")}: {formatUtc(currentTime)}
                  </span>
                  <span>
                    {t("common.region")}: {regionName(region, language)}
                  </span>
                  <span>
                    {t("today.coverage")}: {platformsHere.length}{" "}
                    {language === "hi" ? "उपकरण" : "instruments"}
                  </span>
                </div>
              </div>
            </section>

            {/* ---- Findings --------------------------------------------------- */}
            <section aria-label={t("today.overall")}>
              <div className="grid2">
                {findings.map((finding) => (
                  <FindingCard key={finding.id} finding={finding} language={language} />
                ))}
              </div>
            </section>

            {/* ---- Advisories -------------------------------------------------- */}
            <section aria-labelledby="advisories-heading">
              <SectionTitle
                title={<span id="advisories-heading">{t("today.advisories")}</span>}
                subtitle={
                  language === "hi"
                    ? "मॉडल आउटपुट से स्वतः निकाले गए; समय बदलने पर ये भी बदलते हैं।"
                    : "Derived automatically from this time step — they change as you move through time."
                }
              />
              {regionAlerts.length === 0 ? (
                <Card>
                  <EmptyState
                    icon={<CheckCircle2 size={24} />}
                    title={t("today.noAdvisories")}
                    body={t("today.noAdvisoriesBody")}
                  />
                </Card>
              ) : (
                <ul className="stack gap3" aria-label={t("a11y.alertsRegion")}>
                  {regionAlerts.map((alert) => (
                    <li key={alert.id}>
                      <AdvisoryRow alert={alert} onFocus={focusOnMap} />
                    </li>
                  ))}
                </ul>
              )}
            </section>

            {/* ---- Guidance ----------------------------------------------------- */}
            <section className="grid2">
              <Card>
                <CardHead
                  title={
                    <span className="row gap2">
                      <LifeBuoy size={18} aria-hidden /> {t("today.forFishers")}
                    </span>
                  }
                />
                <CardBody>
                  <ul className="stack gap3">
                    {findings
                      .filter((finding) => finding.action)
                      .map((finding) => (
                        <li key={finding.id} className="row gap3" style={{ alignItems: "flex-start" }}>
                          <Info size={16} aria-hidden style={{ flex: "none", marginTop: 3 }} />
                          <span>{finding.action}</span>
                        </li>
                      ))}
                    {findings.every((finding) => !finding.action) && (
                      <li className="muted">
                        {language === "hi"
                          ? "इस समय कोई विशेष सावधानी आवश्यक नहीं। सामान्य समुद्री सुरक्षा नियमों का पालन करें।"
                          : "Nothing specific to add right now. Normal sea-safety practice applies."}
                      </li>
                    )}
                  </ul>
                  <Callout tone="warn" title={language === "hi" ? "महत्वपूर्ण" : "Important"}>
                    {language === "hi"
                      ? "यह एक मॉडल आधारित सूचना सेवा है, आधिकारिक चेतावनी नहीं। समुद्र में जाने से पहले INCOIS और IMD की आधिकारिक चेतावनियाँ अवश्य देखें।"
                      : "This is a model-based information service, not an official warning. Always check the INCOIS and IMD bulletins before going to sea."}
                  </Callout>
                </CardBody>
              </Card>

              <Card>
                <CardHead
                  title={
                    <span className="row gap2">
                      <Radio size={18} aria-hidden /> {t("today.trust")}
                    </span>
                  }
                  subtitle={
                    language === "hi"
                      ? "यह जानकारी किन मापों पर आधारित है"
                      : "What this information is actually based on"
                  }
                />
                <CardBody>
                  <StatGrid>
                    <Stat
                      label={language === "hi" ? "इस क्षेत्र में उपकरण" : "Instruments here"}
                      value={platformsHere.length}
                      note={
                        language === "hi"
                          ? `कुल ${observations.data?.platforms ?? "—"} में से`
                          : `of ${observations.data?.platforms ?? "—"} across the basin`
                      }
                    />
                    <Stat
                      label={language === "hi" ? "कुल प्रोफ़ाइल" : "Profiles measured"}
                      value={observations.data?.profiles?.toLocaleString("en-IN") ?? "—"}
                      note={
                        observations.data
                          ? `${observations.data.measurement_levels.toLocaleString("en-IN")} levels`
                          : undefined
                      }
                    />
                    <Stat
                      label={language === "hi" ? "समय सीमा" : "Data covers"}
                      value={times.length ? `${times.length} steps` : "—"}
                      note={
                        times.length
                          ? `${formatDate(times[0])} – ${formatDate(times[times.length - 1])}`
                          : undefined
                      }
                      small
                    />
                  </StatGrid>

                  <Disclosure summary={t("common.howWeKnow")}>
                    <p>
                      {language === "hi"
                        ? "ऊपर दी गई हर संख्या एक समुद्री मॉडल के आउटपुट से आती है, जिसे Argo फ़्लोट, ग्लाइडर और CTD मापों के विरुद्ध जाँचा जाता है। 'सामान्य से अंतर' की गणना उसी क्षेत्र के दीर्घकालिक जलवायु-औसत से तुलना करके की जाती है।"
                        : "Every number above comes from an ocean model, checked against real measurements from Argo floats, gliders and CTD casts drifting in the same water. 'Compared with normal' means this week's model field minus a long-term climatology for the same week of the year."}
                    </p>
                    <p>
                      {language === "hi"
                        ? "मॉडल और वास्तविक मापों के बीच का अंतर छिपाया नहीं जाता — 'मॉडल सटीकता' पृष्ठ पर उसे खुले तौर पर दिखाया जाता है।"
                        : "Where the model and the measurements disagree, the difference is not hidden: the Model Accuracy screen publishes it, float by float."}
                    </p>
                  </Disclosure>
                </CardBody>
              </Card>
            </section>
          </>
        )}
      </div>
    </div>
  );
}

/* ========================================================================== */
/* Pieces                                                                     */
/* ========================================================================== */

function FindingCard({ finding, language }: { finding: Finding; language: "en" | "hi" }) {
  const t = useT();
  const Icon = FINDING_ICON[finding.id as keyof typeof FINDING_ICON] ?? Info;
  const tone = levelTone(finding.level);

  const KICKER: Record<string, [string, string]> = {
    sst: [t("today.seaTemp"), t("today.seaTempPlain")],
    heatwave: [t("today.heatwave"), t("today.heatwavePlain")],
    currents: [t("today.currents"), t("today.currentsPlain")],
    eddies: [t("today.eddies"), t("today.eddiesPlain")],
  };
  const [kicker, plain] = KICKER[finding.id] ?? [finding.id, ""];

  return (
    <Card className="finding">
      <div className="finding__top">
        <span className="finding__icon">
          <Icon size={19} aria-hidden />
        </span>
        <div className="grow">
          <p className="finding__kicker">{kicker}</p>
          <p className="finding__plain">{plain}</p>
        </div>
        <Badge tone={tone}>{levelLabel(finding.level, language)}</Badge>
      </div>

      <h3 className="finding__headline">{finding.headline}</h3>
      <p className="finding__detail">{finding.detail}</p>

      {finding.action && (
        <p className="finding__action">
          <Info size={16} aria-hidden />
          <span>{finding.action}</span>
        </p>
      )}

      <div className="finding__foot">
        <Disclosure summary={t("common.whatDoesThisMean")}>
          <p>{EXPLAINERS[finding.id]?.[language] ?? finding.detail}</p>
        </Disclosure>
      </div>
    </Card>
  );
}

/** Background a reader needs once, not a restatement of the current value. */
const EXPLAINERS: Record<string, { en: string; hi: string }> = {
  sst: {
    en: "Sea surface temperature is the warmth of roughly the top metre of water. It drives how much moisture the air above can hold, which is why an unusually warm sea in the pre-monsoon months often precedes heavier rain and stronger cyclones. It also decides where fish can comfortably live: most food species have a narrow temperature band and simply move when the surface warms past it.",
    hi: "समुद्र सतह का तापमान लगभग ऊपरी एक मीटर पानी की गर्माहट है। यह तय करता है कि ऊपर की हवा कितनी नमी रख सकती है — इसीलिए मानसून से पहले असामान्य रूप से गर्म समुद्र प्रायः भारी वर्षा और प्रबल चक्रवातों से पहले दिखाई देता है। यह यह भी तय करता है कि मछलियाँ कहाँ रह सकती हैं, क्योंकि अधिकांश प्रजातियाँ एक सीमित तापमान सीमा में ही रहती हैं।",
  },
  heatwave: {
    en: "A marine heatwave is a stretch of sea that stays much warmer than its seasonal average for days or weeks at a time. Unlike a hot day on land it does not cool overnight, so corals bleach, seagrass dies back and fish stocks shift away from the coast. This service flags a cell when it runs at or above the stated threshold over the climatological average for the same week of the year.",
    hi: "समुद्री ऊष्मा लहर वह स्थिति है जब समुद्र का कोई भाग कई दिनों या सप्ताहों तक अपने मौसमी औसत से बहुत अधिक गर्म बना रहता है। ज़मीन की गर्मी के विपरीत यह रात में ठंडा नहीं होता, इसलिए प्रवाल विरंजित होते हैं, समुद्री घास नष्ट होती है और मछलियाँ तट से दूर चली जाती हैं।",
  },
  currents: {
    en: "Ocean currents are the steady movement of water, driven by wind, by the Earth's rotation and by differences in temperature and saltiness. They matter practically: a current running across your course pushes a boat sideways for the whole trip, and the same flow carries an oil spill or a person overboard away from where they entered the water.",
    hi: "समुद्री धाराएँ जल की निरंतर गति हैं, जो हवा, पृथ्वी के घूर्णन तथा तापमान एवं लवणता के अंतर से चलती हैं। इनका व्यावहारिक महत्व है: मार्ग के आर-पार बहती धारा पूरी यात्रा में नाव को बग़ल में धकेलती है, और यही प्रवाह तेल रिसाव या समुद्र में गिरे व्यक्ति को दूर बहा ले जाता है।",
  },
  eddies: {
    en: "An eddy is a rotating body of water, often a hundred kilometres or more across, that breaks away from a larger current and travels on its own for weeks. Anticlockwise eddies in the northern hemisphere pull deep, nutrient-rich water upward and are usually good fishing ground; clockwise ones push warm surface water downward and are usually poor. Search and rescue planning uses them too, because a drifting object caught in an eddy circles rather than travels.",
    hi: "भँवर घूमते हुए जल का एक पिंड है, जो प्रायः सौ किलोमीटर या उससे अधिक चौड़ा होता है, किसी बड़ी धारा से अलग होकर हफ़्तों तक स्वतंत्र रूप से चलता रहता है। उत्तरी गोलार्ध में वामावर्त भँवर गहरे, पोषक-तत्व युक्त जल को ऊपर खींचते हैं और प्रायः अच्छे मत्स्य क्षेत्र होते हैं; दक्षिणावर्त भँवर गर्म सतही जल को नीचे धकेलते हैं।",
  },
};

function AdvisoryRow({
  alert,
  onFocus,
}: {
  alert: OceanAlert;
  onFocus: (lat: number, lon: number) => void;
}) {
  const t = useT();
  const Icon = ALERT_ICON[alert.kind] ?? AlertTriangle;
  const disabled = !alert.focus;

  return (
    <button
      type="button"
      className="advisory"
      disabled={disabled}
      onClick={() => alert.focus && onFocus(alert.focus.lat, alert.focus.lon)}
      title={disabled ? undefined : t("common.viewOnMap")}
    >
      <span className={`advisory__icon advisory__icon--${alert.severity}`}>
        <Icon size={17} aria-hidden />
      </span>
      <span className="grow">
        <span className="advisory__title">{alert.title}</span>
        <span className="advisory__where"> · {alert.location}</span>
        {alert.detail && <span className="advisory__detail">{alert.detail}</span>}
      </span>
      <Badge tone={alert.severity === "high" ? "danger" : alert.severity === "moderate" ? "warn" : "info"}>
        {SEVERITY_LABEL[alert.severity]}
      </Badge>
    </button>
  );
}
