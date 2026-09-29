/**
 * Bilingual strings.
 *
 * Scope is deliberate. Everything a citizen reads — the public dashboard,
 * navigation, advisories, safety guidance, settings — is translated. The
 * specialist analysis and verification screens stay in English, which is how
 * INCOIS and MoES publish technical products today; translating "Okubo-Weiss
 * parameter" into Hindi would invent terminology rather than communicate.
 * Settings says this plainly rather than leaving the user to discover it.
 */

export type Language = "en" | "hi";

export const LANGUAGE_NAMES: Record<Language, string> = {
  en: "English",
  hi: "हिन्दी",
};

const en = {
  /* ---- Identity ---------------------------------------------------------- */
  "app.name": "INDO-FOS",
  "app.full": "Indian Ocean Forecasting & Observing System",
  "app.ministry": "Ministry of Earth Sciences",
  "app.government": "Government of India",

  /* ---- Modes ------------------------------------------------------------- */
  "mode.public": "Public",
  "mode.official": "Official",
  "mode.public.title": "Plain-language ocean information for everyone",
  "mode.official.title": "Full technical console for forecasting desks",

  /* ---- Navigation -------------------------------------------------------- */
  "nav.today": "Ocean Today",
  "nav.map": "Live Map",
  "nav.observations": "Observations",
  "nav.verification": "Model Accuracy",
  "nav.analysis": "Analysis",
  "nav.data": "Data & Services",
  "nav.reports": "Reports",
  "nav.settings": "Settings",
  "nav.section": "Sections",
  "nav.collapse": "Collapse menu",
  "nav.expand": "Expand menu",
  "nav.skip": "Skip to main content",

  /* ---- Common ------------------------------------------------------------ */
  "common.loading": "Loading…",
  "common.retry": "Try again",
  "common.close": "Close",
  "common.today": "Today",
  "common.region": "Region",
  "common.allRegions": "All Indian Ocean",
  "common.updated": "Updated",
  "common.source": "Source",
  "common.whatDoesThisMean": "What does this mean?",
  "common.howWeKnow": "How do we know this?",
  "common.viewOnMap": "View on map",
  "common.readMore": "Read more",
  "common.download": "Download",
  "common.print": "Print",
  "common.copy": "Copy",
  "common.copied": "Copied to clipboard",
  "common.none": "None",
  "common.noData": "No data",
  "common.depth": "Depth",
  "common.surface": "Surface",
  "common.time": "Time",
  "common.location": "Location",
  "common.search": "Search",

  /* ---- Public dashboard --------------------------------------------------- */
  "today.title": "The sea today",
  "today.subtitle": "What the ocean is doing right now, in plain language.",
  "today.pickRegion": "Choose your coast",
  "today.overall": "Overall situation",
  "today.seaTemp": "Sea surface temperature",
  "today.seaTempPlain": "How warm the top of the sea is",
  "today.vsNormal": "Compared with normal",
  "today.currents": "Currents",
  "today.currentsPlain": "How fast the water is moving",
  "today.heatwave": "Marine heatwave",
  "today.heatwavePlain": "Unusually warm sea for a long stretch",
  "today.eddies": "Ocean whirlpools (eddies)",
  "today.eddiesPlain": "Large circular currents that gather fish and debris",
  "today.advisories": "Advisories",
  "today.noAdvisories": "No advisories right now",
  "today.noAdvisoriesBody":
    "Nothing in the model output crosses an alert threshold for this area at this time step.",
  "today.forFishers": "If you go to sea",
  "today.forResidents": "If you live on the coast",
  "today.coverage": "How much we are measuring",
  "today.trust": "How far to trust this",

  /* ---- Severity ----------------------------------------------------------- */
  "sev.high": "High",
  "sev.moderate": "Moderate",
  "sev.low": "Low",
  "sev.normal": "Normal",
  "sev.watch": "Watch",

  /* ---- Status ------------------------------------------------------------- */
  "status.live": "Live",
  "status.connected": "Connected",
  "status.offline": "Backend offline",
  "status.degraded": "No dataset loaded",

  /* ---- Settings ----------------------------------------------------------- */
  "settings.title": "Settings",
  "settings.language": "Language",
  "settings.languageNote":
    "Public pages are fully translated. Analysis and verification pages stay in English, because their terms are technical standards rather than everyday words.",
  "settings.appearance": "Appearance",
  "settings.theme": "Theme",
  "settings.theme.light": "Light",
  "settings.theme.dark": "Dark",
  "settings.theme.system": "Match device",
  "settings.textSize": "Text size",
  "settings.textSize.normal": "Normal",
  "settings.textSize.large": "Large",
  "settings.textSize.xlarge": "Very large",
  "settings.contrast": "Higher contrast",
  "settings.contrastNote": "Stronger text and borders for bright rooms and low vision.",
  "settings.motion": "Reduce animation",
  "settings.units": "Units",
  "settings.about": "About this system",
  "settings.reset": "Reset all settings",

  /* ---- Accessibility ------------------------------------------------------ */
  "a11y.themeToggle": "Switch between light and dark theme",
  "a11y.languageToggle": "Change language",
  "a11y.alertsRegion": "Active ocean advisories",
} as const;

export type StringKey = keyof typeof en;

const hi: Record<StringKey, string> = {
  "app.name": "इंडो-फ़ॉस",
  "app.full": "हिंद महासागर पूर्वानुमान एवं प्रेक्षण प्रणाली",
  "app.ministry": "पृथ्वी विज्ञान मंत्रालय",
  "app.government": "भारत सरकार",

  "mode.public": "आम नागरिक",
  "mode.official": "आधिकारिक",
  "mode.public.title": "सभी के लिए सरल भाषा में समुद्र की जानकारी",
  "mode.official.title": "पूर्वानुमान केंद्रों के लिए पूर्ण तकनीकी कंसोल",

  "nav.today": "आज का समुद्र",
  "nav.map": "सजीव मानचित्र",
  "nav.observations": "प्रेक्षण",
  "nav.verification": "मॉडल सटीकता",
  "nav.analysis": "विश्लेषण",
  "nav.data": "डेटा एवं सेवाएँ",
  "nav.reports": "रिपोर्ट",
  "nav.settings": "सेटिंग्स",
  "nav.section": "अनुभाग",
  "nav.collapse": "मेनू छोटा करें",
  "nav.expand": "मेनू बड़ा करें",
  "nav.skip": "मुख्य सामग्री पर जाएँ",

  "common.loading": "लोड हो रहा है…",
  "common.retry": "पुनः प्रयास करें",
  "common.close": "बंद करें",
  "common.today": "आज",
  "common.region": "क्षेत्र",
  "common.allRegions": "सम्पूर्ण हिंद महासागर",
  "common.updated": "अद्यतन",
  "common.source": "स्रोत",
  "common.whatDoesThisMean": "इसका क्या अर्थ है?",
  "common.howWeKnow": "हमें यह कैसे पता है?",
  "common.viewOnMap": "मानचित्र पर देखें",
  "common.readMore": "और पढ़ें",
  "common.download": "डाउनलोड",
  "common.print": "प्रिंट",
  "common.copy": "कॉपी करें",
  "common.copied": "क्लिपबोर्ड पर कॉपी हो गया",
  "common.none": "कोई नहीं",
  "common.noData": "कोई डेटा नहीं",
  "common.depth": "गहराई",
  "common.surface": "सतह",
  "common.time": "समय",
  "common.location": "स्थान",
  "common.search": "खोजें",

  "today.title": "आज का समुद्र",
  "today.subtitle": "इस समय समुद्र में क्या हो रहा है, सरल भाषा में।",
  "today.pickRegion": "अपना तट चुनें",
  "today.overall": "समग्र स्थिति",
  "today.seaTemp": "समुद्र सतह का तापमान",
  "today.seaTempPlain": "समुद्र की ऊपरी सतह कितनी गर्म है",
  "today.vsNormal": "सामान्य की तुलना में",
  "today.currents": "धाराएँ",
  "today.currentsPlain": "पानी कितनी तेज़ी से बह रहा है",
  "today.heatwave": "समुद्री ऊष्मा लहर",
  "today.heatwavePlain": "लम्बे समय तक असामान्य रूप से गर्म समुद्र",
  "today.eddies": "समुद्री भँवर",
  "today.eddiesPlain": "बड़ी गोलाकार धाराएँ जो मछलियाँ और मलबा इकट्ठा करती हैं",
  "today.advisories": "परामर्श",
  "today.noAdvisories": "इस समय कोई परामर्श नहीं",
  "today.noAdvisoriesBody":
    "इस क्षेत्र और इस समय के लिए मॉडल में कोई भी मान चेतावनी सीमा से ऊपर नहीं है।",
  "today.forFishers": "यदि आप समुद्र में जा रहे हैं",
  "today.forResidents": "यदि आप तट पर रहते हैं",
  "today.coverage": "हम कितना माप रहे हैं",
  "today.trust": "इस पर कितना भरोसा करें",

  "sev.high": "उच्च",
  "sev.moderate": "मध्यम",
  "sev.low": "निम्न",
  "sev.normal": "सामान्य",
  "sev.watch": "निगरानी",

  "status.live": "सजीव",
  "status.connected": "जुड़ा हुआ",
  "status.offline": "सर्वर बंद है",
  "status.degraded": "कोई डेटासेट लोड नहीं",

  "settings.title": "सेटिंग्स",
  "settings.language": "भाषा",
  "settings.languageNote":
    "सार्वजनिक पृष्ठ पूरी तरह अनुवादित हैं। विश्लेषण एवं सत्यापन पृष्ठ अंग्रेज़ी में रहते हैं, क्योंकि उनके शब्द तकनीकी मानक हैं, रोज़मर्रा के शब्द नहीं।",
  "settings.appearance": "रूप-रंग",
  "settings.theme": "थीम",
  "settings.theme.light": "हल्की",
  "settings.theme.dark": "गहरी",
  "settings.theme.system": "डिवाइस के अनुसार",
  "settings.textSize": "अक्षर का आकार",
  "settings.textSize.normal": "सामान्य",
  "settings.textSize.large": "बड़ा",
  "settings.textSize.xlarge": "बहुत बड़ा",
  "settings.contrast": "अधिक स्पष्टता",
  "settings.contrastNote": "तेज़ रोशनी और कम दृष्टि के लिए गहरा पाठ और स्पष्ट किनारे।",
  "settings.motion": "एनिमेशन कम करें",
  "settings.units": "इकाइयाँ",
  "settings.about": "इस प्रणाली के बारे में",
  "settings.reset": "सभी सेटिंग्स रीसेट करें",

  "a11y.themeToggle": "हल्की और गहरी थीम बदलें",
  "a11y.languageToggle": "भाषा बदलें",
  "a11y.alertsRegion": "सक्रिय समुद्री परामर्श",
};

export const STRINGS: Record<Language, Record<StringKey, string>> = { en, hi };
