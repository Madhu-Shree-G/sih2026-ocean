/**
 * Turning model output into sentences a non-specialist can act on.
 *
 * This is the module that answers the question the old interface never did:
 * *so what?* A number like "27.4 °C" is meaningless to a fisher in Kollam or
 * to a joint secretary preparing a note. "About 1.2 °C warmer than normal for
 * this week, over roughly a tenth of the Kerala coast" is not.
 *
 * Two rules hold everywhere below:
 *
 * 1. Nothing is invented. Every sentence is derived from a value the backend
 *    actually returned, and the caller can always see the number that produced
 *    it. Where a value is missing we say so instead of guessing.
 * 2. Thresholds are named constants with a stated basis, not magic numbers
 *    buried in a conditional, because an operational service has to be able to
 *    defend where a "moderate" ends and a "high" begins.
 */

import type { AnomalyResult, Eddy, EddyCensus, OceanAlert } from "@/types/api";
import { cellIndex, valueAt, type OcvolBlock } from "./ocvol";
import type { CoastRegion } from "@/state/store";
import type { Language } from "@/i18n/strings";

export type Level = "normal" | "watch" | "moderate" | "high";

/** Ordered worst-first so `overallLevel` can just take a maximum. */
const LEVEL_RANK: Record<Level, number> = { normal: 0, watch: 1, moderate: 2, high: 3 };

export function overallLevel(levels: Level[]): Level {
  return levels.reduce<Level>(
    (worst, level) => (LEVEL_RANK[level] > LEVEL_RANK[worst] ? level : worst),
    "normal",
  );
}

/* ==========================================================================
   Thresholds

   Sea-surface temperature anomaly bands follow the convention used for
   marine-heatwave reporting: half a degree is inside normal interannual
   spread, one degree is a departure worth watching, two degrees is a strong
   event. Current-speed bands are set where a small mechanised boat starts to
   lose station-keeping.
   ========================================================================== */

const ANOMALY_WATCH_C = 0.5;
const ANOMALY_MODERATE_C = 1.0;
const ANOMALY_HIGH_C = 2.0;

const HEATWAVE_AREA_MODERATE = 0.02; // 2% of the region's valid cells
const HEATWAVE_AREA_HIGH = 0.1; // 10%

const CURRENT_MODERATE_MS = 0.3;
const CURRENT_STRONG_MS = 0.6;
const CURRENT_VERY_STRONG_MS = 1.0;

/* ==========================================================================
   Regional statistics
   ========================================================================== */

export interface RegionStats {
  cells: number;
  mean: number | null;
  min: number | null;
  max: number | null;
}

const EMPTY: RegionStats = { cells: 0, mean: null, min: null, max: null };

/** Index bounds of a bbox inside a block's regular grid, clamped to it. */
function bounds(block: OcvolBlock, bbox: [number, number, number, number]) {
  const [west, south, east, north] = bbox;
  const [latMin, latMax] = block.header.lat_range;
  const [lonMin, lonMax] = block.header.lon_range;

  const latSpan = latMax - latMin || 1;
  const lonSpan = lonMax - lonMin || 1;

  const toY = (lat: number) =>
    Math.round(((lat - latMin) / latSpan) * (block.nLat - 1));
  const toX = (lon: number) =>
    Math.round(((lon - lonMin) / lonSpan) * (block.nLon - 1));

  const y0 = Math.max(0, Math.min(block.nLat - 1, toY(south)));
  const y1 = Math.max(0, Math.min(block.nLat - 1, toY(north)));
  const x0 = Math.max(0, Math.min(block.nLon - 1, toX(west)));
  const x1 = Math.max(0, Math.min(block.nLon - 1, toX(east)));

  return {
    y0: Math.min(y0, y1),
    y1: Math.max(y0, y1),
    x0: Math.min(x0, x1),
    x1: Math.max(x0, x1),
  };
}

/** Mean, min and max of one (time, depth) plane over a bounding box. */
export function regionStats(
  block: OcvolBlock | undefined,
  bbox: [number, number, number, number],
  time = 0,
  depth = 0,
): RegionStats {
  if (!block) return EMPTY;

  const t = Math.min(Math.max(time, 0), block.nTime - 1);
  const z = Math.min(Math.max(depth, 0), block.nDepth - 1);
  const { y0, y1, x0, x1 } = bounds(block, bbox);

  let sum = 0;
  let cells = 0;
  let min = Infinity;
  let max = -Infinity;

  for (let y = y0; y <= y1; y++) {
    for (let x = x0; x <= x1; x++) {
      const value = valueAt(block, cellIndex(block, t, z, y, x));
      if (!Number.isFinite(value)) continue;
      sum += value;
      cells++;
      if (value < min) min = value;
      if (value > max) max = value;
    }
  }

  if (cells === 0) return EMPTY;
  return { cells, mean: sum / cells, min, max };
}

/** Speed statistics from the eastward and northward components. */
export function regionSpeedStats(
  velocity: { u: OcvolBlock; v: OcvolBlock } | undefined,
  bbox: [number, number, number, number],
  time = 0,
  depth = 0,
): RegionStats {
  if (!velocity) return EMPTY;
  const { u, v } = velocity;
  if (u.nLat !== v.nLat || u.nLon !== v.nLon) return EMPTY;

  const t = Math.min(Math.max(time, 0), u.nTime - 1);
  const z = Math.min(Math.max(depth, 0), u.nDepth - 1);
  const { y0, y1, x0, x1 } = bounds(u, bbox);

  let sum = 0;
  let cells = 0;
  let min = Infinity;
  let max = -Infinity;

  for (let y = y0; y <= y1; y++) {
    for (let x = x0; x <= x1; x++) {
      const index = cellIndex(u, t, z, y, x);
      const eastward = valueAt(u, index);
      const northward = valueAt(v, index);
      if (!Number.isFinite(eastward) || !Number.isFinite(northward)) continue;
      const speed = Math.hypot(eastward, northward);
      sum += speed;
      cells++;
      if (speed < min) min = speed;
      if (speed > max) max = speed;
    }
  }

  if (cells === 0) return EMPTY;
  return { cells, mean: sum / cells, min, max };
}

export interface RegionAnomaly extends RegionStats {
  /** Cells at or above the backend's heatwave threshold, within the region. */
  hotCells: number;
  areaFraction: number;
  threshold: number;
  units: string;
  reference: string;
}

/**
 * Anomaly statistics restricted to a region.
 *
 * The backend reports heatwave coverage across the whole domain; a reader on
 * the Odisha coast needs the number for their own water, so the mask is
 * re-counted here over the region's cells only.
 */
export function regionAnomalyStats(
  anomaly: AnomalyResult | undefined,
  bbox: [number, number, number, number],
): RegionAnomaly | null {
  if (!anomaly) return null;

  const [west, south, east, north] = bbox;
  const { lats, lons, values } = anomaly.grid;
  const mask = anomaly.heatwave.mask;

  let sum = 0;
  let cells = 0;
  let min = Infinity;
  let max = -Infinity;
  let hotCells = 0;

  for (let y = 0; y < values.length; y++) {
    const lat = lats[y];
    if (lat < south || lat > north) continue;
    const row = values[y];
    if (!row) continue;

    for (let x = 0; x < row.length; x++) {
      const lon = lons[x];
      if (lon < west || lon > east) continue;
      const value = row[x];
      if (value === null || !Number.isFinite(value)) continue;

      sum += value;
      cells++;
      if (value < min) min = value;
      if (value > max) max = value;
      if (mask?.[y]?.[x]) hotCells++;
    }
  }

  if (cells === 0) return null;

  return {
    cells,
    mean: sum / cells,
    min,
    max,
    hotCells,
    areaFraction: hotCells / cells,
    threshold: anomaly.heatwave.threshold,
    units: anomaly.units,
    reference: anomaly.reference,
  };
}

export function eddiesInRegion(
  census: EddyCensus | undefined,
  bbox: [number, number, number, number],
): Eddy[] {
  if (!census) return [];
  const [west, south, east, north] = bbox;
  return census.eddies.filter(
    (eddy) =>
      eddy.centre.lon >= west &&
      eddy.centre.lon <= east &&
      eddy.centre.lat >= south &&
      eddy.centre.lat <= north,
  );
}

export function alertsInRegion(
  alerts: OceanAlert[],
  bbox: [number, number, number, number],
): OceanAlert[] {
  const [west, south, east, north] = bbox;
  return alerts.filter((alert) => {
    if (!alert.focus) return true; // undirected alerts apply everywhere
    const { lat, lon } = alert.focus;
    return lon >= west && lon <= east && lat >= south && lat <= north;
  });
}

/* ==========================================================================
   Narrative
   ========================================================================== */

export interface Finding {
  id: string;
  level: Level;
  /** One short sentence: the answer. */
  headline: string;
  /** One or two sentences: the reasoning, with the numbers in it. */
  detail: string;
  /** What a reader should actually do, when there is something to do. */
  action?: string;
}

function say(language: Language, en: string, hi: string): string {
  return language === "hi" ? hi : en;
}

/** Format a number for prose, not for a table. */
function n(value: number, digits = 1): string {
  return value.toFixed(digits);
}

function signed(value: number, digits = 1): string {
  return `${value > 0 ? "+" : ""}${value.toFixed(digits)}`;
}

export function regionName(region: CoastRegion, language: Language): string {
  return language === "hi" ? region.nameHi : region.name;
}

/**
 * The region with its own correct preposition — "in the Bay of Bengal",
 * "off the Kerala coast", "across the Indian Ocean". Sentences are built from
 * this rather than from the bare name, because one preposition cannot be
 * right for a sea, a coastline and an island group at the same time.
 */
export function placePhrase(region: CoastRegion, language: Language): string {
  return language === "hi" ? region.phraseHi : region.phrase;
}

/* ---- Sea surface temperature --------------------------------------------- */

export function assessTemperature(
  sst: RegionStats,
  anomaly: RegionAnomaly | null,
  region: CoastRegion,
  language: Language,
): Finding {
  const place = placePhrase(region, language);
  const here = regionName(region, language);

  if (sst.mean === null) {
    return {
      id: "sst",
      level: "normal",
      headline: say(language, "Sea temperature is not available", "समुद्र का तापमान उपलब्ध नहीं"),
      detail: say(
        language,
        `The model has no valid surface cells for ${here} at this time step.`,
        `इस समय ${here} के लिए मॉडल में कोई मान्य सतही आँकड़ा नहीं है।`,
      ),
    };
  }

  const warm = n(sst.mean);

  if (!anomaly || anomaly.mean === null) {
    return {
      id: "sst",
      level: "normal",
      headline: say(
        language,
        `The sea ${place} is about ${warm} °C at the surface`,
        `${place} समुद्र की सतह का तापमान लगभग ${warm} °C है`,
      ),
      detail: say(
        language,
        `Range across the area is ${n(sst.min ?? 0)} to ${n(sst.max ?? 0)} °C. No climatology is loaded, so there is nothing to compare it against yet.`,
        `क्षेत्र में तापमान ${n(sst.min ?? 0)} से ${n(sst.max ?? 0)} °C के बीच है। तुलना के लिए जलवायु-औसत उपलब्ध नहीं है।`,
      ),
    };
  }

  const departure = anomaly.mean;
  const magnitude = Math.abs(departure);
  const level: Level =
    magnitude >= ANOMALY_HIGH_C
      ? "high"
      : magnitude >= ANOMALY_MODERATE_C
        ? "moderate"
        : magnitude >= ANOMALY_WATCH_C
          ? "watch"
          : "normal";

  const warmer = departure > 0;

  if (level === "normal") {
    return {
      id: "sst",
      level,
      headline: say(
        language,
        `Sea temperature ${place} is normal for this time of year`,
        `${place} समुद्र का तापमान इस मौसम के लिए सामान्य है`,
      ),
      detail: say(
        language,
        `The surface is averaging ${warm} °C, which is ${signed(departure)} °C against the long-term average for this week. Anything inside half a degree is ordinary year-to-year variation.`,
        `सतह का औसत तापमान ${warm} °C है, जो इस सप्ताह के दीर्घकालिक औसत से ${signed(departure)} °C अलग है। आधे डिग्री तक का अंतर सामान्य वार्षिक उतार-चढ़ाव है।`,
      ),
    };
  }

  const direction = warmer
    ? say(language, "warmer", "अधिक गर्म")
    : say(language, "cooler", "अधिक ठंडा");

  return {
    id: "sst",
    level,
    headline: say(
      language,
      `The sea ${place} is ${n(magnitude)} °C ${direction} than usual`,
      `${place} समुद्र सामान्य से ${n(magnitude)} °C ${direction} है`,
    ),
    detail: say(
      language,
      `Surface water is averaging ${warm} °C against a long-term average of about ${n(sst.mean - departure)} °C for this week, measured against ${anomaly.reference}. The strongest departure in the area is ${signed(warmer ? anomaly.max ?? 0 : anomaly.min ?? 0)} °C.`,
      `सतही जल का औसत ${warm} °C है, जबकि इस सप्ताह का दीर्घकालिक औसत लगभग ${n(sst.mean - departure)} °C है (संदर्भ: ${anomaly.reference})। क्षेत्र में सर्वाधिक अंतर ${signed(warmer ? anomaly.max ?? 0 : anomaly.min ?? 0)} °C है।`,
    ),
    action: warmer
      ? say(
          language,
          "Warm surface water holds less oxygen and pushes many food fish deeper. Expect poorer catches in the top few metres and consider fishing deeper or further offshore.",
          "गर्म सतही जल में ऑक्सीजन कम होती है और कई मछलियाँ गहराई में चली जाती हैं। ऊपरी कुछ मीटर में पकड़ कम हो सकती है; अधिक गहराई या दूर समुद्र में जाने पर विचार करें।",
        )
      : say(
          language,
          "Cooler-than-normal water at the surface usually means deeper, nutrient-rich water is rising. Catches often improve a few days after this appears.",
          "सामान्य से ठंडा सतही जल प्रायः गहरे, पोषक-तत्व युक्त जल के ऊपर आने का संकेत है। इसके कुछ दिन बाद प्रायः पकड़ बेहतर होती है।",
        ),
  };
}

/* ---- Marine heatwave ------------------------------------------------------ */

export function assessHeatwave(
  anomaly: RegionAnomaly | null,
  region: CoastRegion,
  language: Language,
): Finding {
  const place = placePhrase(region, language);

  if (!anomaly) {
    return {
      id: "heatwave",
      level: "normal",
      headline: say(language, "Marine heatwave status unknown", "समुद्री ऊष्मा लहर की स्थिति अज्ञात"),
      detail: say(
        language,
        "No climatology is loaded, so departures from normal cannot be computed.",
        "जलवायु-औसत उपलब्ध न होने के कारण सामान्य से अंतर की गणना संभव नहीं है।",
      ),
    };
  }

  const percent = anomaly.areaFraction * 100;

  if (anomaly.hotCells === 0) {
    return {
      id: "heatwave",
      level: "normal",
      headline: say(language, "No marine heatwave here", "यहाँ कोई समुद्री ऊष्मा लहर नहीं"),
      detail: say(
        language,
        `Nowhere ${place} is running ${n(anomaly.threshold)} °C or more above the seasonal average, which is the threshold this service uses to flag a heatwave.`,
        `${place} कहीं भी तापमान मौसमी औसत से ${n(anomaly.threshold)} °C या अधिक ऊपर नहीं है, जो इस सेवा की ऊष्मा-लहर सीमा है।`,
      ),
    };
  }

  const level: Level =
    anomaly.areaFraction >= HEATWAVE_AREA_HIGH
      ? "high"
      : anomaly.areaFraction >= HEATWAVE_AREA_MODERATE
        ? "moderate"
        : "watch";

  return {
    id: "heatwave",
    level,
    headline: say(
      language,
      `Marine heatwave conditions over ${n(percent)}% of the water ${place}`,
      `${place} लगभग ${n(percent)}% जल में समुद्री ऊष्मा लहर की स्थिति`,
    ),
    detail: say(
      language,
      `${anomaly.hotCells} of ${anomaly.cells} model cells in this area are at least ${n(anomaly.threshold)} °C above the seasonal average, peaking at ${signed(anomaly.max ?? 0)} °C. Sustained warmth of this kind bleaches coral and drives fish stocks away from the coast.`,
      `इस क्षेत्र की ${anomaly.cells} में से ${anomaly.hotCells} मॉडल कोशिकाएँ मौसमी औसत से कम-से-कम ${n(anomaly.threshold)} °C ऊपर हैं, अधिकतम ${signed(anomaly.max ?? 0)} °C। इस प्रकार की लगातार गर्मी प्रवाल को क्षति पहुँचाती है और मछलियों को तट से दूर कर देती है।`,
    ),
    action: say(
      language,
      "Coral reef and aquaculture operators in this stretch should check for bleaching and reduce handling stress on stock.",
      "इस क्षेत्र में प्रवाल भित्ति और मत्स्य-पालन संचालकों को विरंजन की जाँच करनी चाहिए तथा मछलियों पर दबाव कम करना चाहिए।",
    ),
  };
}

/* ---- Currents -------------------------------------------------------------- */

export function assessCurrents(
  speed: RegionStats,
  region: CoastRegion,
  language: Language,
): Finding {
  const place = placePhrase(region, language);
  const here = regionName(region, language);

  if (speed.mean === null || speed.max === null) {
    return {
      id: "currents",
      level: "normal",
      headline: say(language, "Current speed is not available", "धारा की गति उपलब्ध नहीं"),
      detail: say(
        language,
        `The model has no valid velocity cells for ${here} at this time step.`,
        `इस समय ${here} के लिए मॉडल में कोई मान्य वेग आँकड़ा नहीं है।`,
      ),
    };
  }

  const peak = speed.max;
  const average = speed.mean;

  // Severity comes from the typical speed across the area, not from the single
  // fastest cell in it. Over a basin this size some cell is always fast, so a
  // peak-driven level would read "unusual" every single day and mean nothing.
  const level: Level =
    average >= CURRENT_STRONG_MS
      ? "moderate"
      : average >= CURRENT_MODERATE_MS
        ? "watch"
        : "normal";

  const descriptor =
    average >= CURRENT_VERY_STRONG_MS
      ? say(language, "very strong", "बहुत तेज़")
      : average >= CURRENT_STRONG_MS
        ? say(language, "strong", "तेज़")
        : average >= CURRENT_MODERATE_MS
          ? say(language, "moderate", "मध्यम")
          : say(language, "gentle", "मंद");

  // Knots are what a boat's instruments read, so give both.
  const knots = peak * 1.94384;

  return {
    id: "currents",
    level,
    headline: say(
      language,
      `Currents ${place} are ${descriptor}`,
      `${place} धाराएँ ${descriptor} हैं`,
    ),
    detail: say(
      language,
      `Water is moving at ${n(average, 2)} m/s across this area on average. The fastest flow anywhere in it reaches ${n(peak, 2)} m/s — about ${n(knots)} knots — so one spot can be well above the average.`,
      `इस क्षेत्र में जल की औसत गति ${n(average, 2)} मी/से है। कहीं-कहीं सर्वाधिक गति ${n(peak, 2)} मी/से — लगभग ${n(knots)} नॉट — तक पहुँचती है, इसलिए किसी एक स्थान पर स्थिति औसत से कहीं अधिक तेज़ हो सकती है।`,
    ),
    action:
      peak >= CURRENT_STRONG_MS
        ? say(
            language,
            "A small boat will drift noticeably off course at this speed. Allow extra fuel for the return leg and keep a fix on your position.",
            "इस गति पर छोटी नाव मार्ग से स्पष्ट रूप से भटक सकती है। वापसी के लिए अतिरिक्त ईंधन रखें और अपनी स्थिति पर नज़र बनाए रखें।",
          )
        : undefined,
  };
}

/* ---- Eddies ---------------------------------------------------------------- */

export function assessEddies(
  eddies: Eddy[],
  region: CoastRegion,
  language: Language,
): Finding {
  const place = placePhrase(region, language);
  const here = regionName(region, language);

  if (eddies.length === 0) {
    return {
      id: "eddies",
      level: "normal",
      headline: say(language, "No significant eddies detected here", "यहाँ कोई उल्लेखनीय भँवर नहीं"),
      detail: say(
        language,
        `The eddy detector found no closed circulation ${place} at this time step.`,
        `इस समय ${here} में कोई बंद परिसंचरण नहीं मिला।`,
      ),
    };
  }

  const strongest = eddies.reduce((best, current) =>
    current["max_speed_ms-1"] > best["max_speed_ms-1"] ? current : best,
  );
  const cyclonic = eddies.filter((eddy) => eddy.polarity === "cyclonic").length;

  return {
    id: "eddies",
    level: strongest["max_speed_ms-1"] >= CURRENT_VERY_STRONG_MS ? "watch" : "normal",
    headline: say(
      language,
      `${eddies.length} ocean ${eddies.length === 1 ? "eddy" : "eddies"} ${place}`,
      `${place} ${eddies.length} समुद्री भँवर`,
    ),
    detail: say(
      language,
      `${cyclonic} turn anticlockwise and ${eddies.length - cyclonic} clockwise. The strongest is about ${n(strongest.radius_km, 0)} km across the radius with rim speeds near ${n(strongest["max_speed_ms-1"], 2)} m/s, centred at ${n(Math.abs(strongest.centre.lat))}° ${strongest.centre.lat >= 0 ? "N" : "S"}, ${n(Math.abs(strongest.centre.lon))}° E.`,
      `${cyclonic} वामावर्त और ${eddies.length - cyclonic} दक्षिणावर्त घूम रहे हैं। सबसे प्रबल भँवर की त्रिज्या लगभग ${n(strongest.radius_km, 0)} किमी है और किनारे की गति लगभग ${n(strongest["max_speed_ms-1"], 2)} मी/से है, केंद्र ${n(Math.abs(strongest.centre.lat))}° ${strongest.centre.lat >= 0 ? "उ" : "द"}, ${n(Math.abs(strongest.centre.lon))}° पू पर है।`,
    ),
    action: say(
      language,
      "Anticlockwise eddies lift nutrients upward and often concentrate fish along their edge. Clockwise eddies push warm surface water down and are usually poorer ground.",
      "वामावर्त भँवर पोषक तत्वों को ऊपर लाते हैं और प्रायः किनारों पर मछलियाँ एकत्र करते हैं। दक्षिणावर्त भँवर गर्म सतही जल को नीचे धकेलते हैं और प्रायः कम उपजाऊ होते हैं।",
    ),
  };
}

/* ---- Overall ---------------------------------------------------------------- */

export function overallStatement(
  level: Level,
  region: CoastRegion,
  language: Language,
): { headline: string; detail: string } {
  const place = placePhrase(region, language);

  switch (level) {
    case "high":
      return {
        headline: say(language, "Conditions need attention", "स्थिति पर ध्यान देने की आवश्यकता"),
        detail: say(
          language,
          `At least one measurement ${place} is well outside its normal range right now. Read the cards below before going to sea.`,
          `इस समय ${place} कम-से-कम एक माप अपनी सामान्य सीमा से काफ़ी बाहर है। समुद्र में जाने से पहले नीचे दिए विवरण पढ़ें।`,
        ),
      };
    case "moderate":
      return {
        headline: say(language, "Some unusual conditions", "कुछ असामान्य स्थितियाँ"),
        detail: say(
          language,
          `Conditions ${place} are outside the usual range for this time of year, though not severely. The details are below.`,
          `${place} स्थितियाँ इस मौसम की सामान्य सीमा से बाहर हैं, यद्यपि गंभीर नहीं। विवरण नीचे है।`,
        ),
      };
    case "watch":
      return {
        headline: say(language, "Mostly normal, worth a look", "अधिकतर सामान्य, ध्यान देने योग्य"),
        detail: say(
          language,
          `Nothing ${place} is alarming, but one or two values are drifting from their seasonal average.`,
          `${place} कुछ भी चिंताजनक नहीं है, परंतु एक-दो मान अपने मौसमी औसत से हट रहे हैं।`,
        ),
      };
    default:
      return {
        headline: say(language, "Conditions are normal", "स्थिति सामान्य है"),
        detail: say(
          language,
          `Everything the model reports ${place} is within its usual range for this time of year.`,
          `${place} मॉडल द्वारा बताई गई सभी स्थितियाँ इस मौसम की सामान्य सीमा में हैं।`,
        ),
      };
  }
}

export function levelLabel(level: Level, language: Language): string {
  switch (level) {
    case "high":
      return say(language, "Needs attention", "ध्यान दें");
    case "moderate":
      return say(language, "Unusual", "असामान्य");
    case "watch":
      return say(language, "Watch", "निगरानी");
    default:
      return say(language, "Normal", "सामान्य");
  }
}

/** Maps a level onto the design system's status tones. */
export function levelTone(level: Level): "ok" | "info" | "warn" | "danger" {
  switch (level) {
    case "high":
      return "danger";
    case "moderate":
      return "warn";
    case "watch":
      return "info";
    default:
      return "ok";
  }
}
