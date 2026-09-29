/**
 * Global UI state.
 *
 * Server data is owned by React Query and is never copied in here, so there is
 * exactly one source of truth for anything fetched. What lives here is the
 * things more than one view must agree on: which section is open, what the
 * user is slicing, and the presentation preferences that have to survive a
 * reload (language, theme, text size).
 *
 * Deep, the voice agent, drives this store through `applyAction` in
 * lib/deep-client.ts. Every field it touches is kept stable here.
 */

import { create } from "zustand";
import { persist, createJSONStorage } from "zustand/middleware";
import type { OceanAlert } from "@/types/api";
import type { Language } from "@/i18n/strings";

/* ========================================================================== */
/* Vocabulary                                                                 */
/* ========================================================================== */

export type LayerId =
  | "surface"
  | "currents"
  | "eddies"
  | "platforms"
  | "bias"
  | "graticule";

export interface LayerState {
  id: LayerId;
  /** Translation-independent label; views localise it at render time. */
  label: string;
  enabled: boolean;
  opacity: number;
  /** Layers whose opacity is meaningless (markers, graticule) hide the slider. */
  fixedOpacity?: boolean;
}

export type AnalysisLayer =
  | "none"
  | "anomaly"
  | "mixed_layer_depth"
  | "thermocline"
  | "eddies"
  | "bias";

/** Every section is a real destination that renders its own view. */
export type Section =
  | "today"
  | "map"
  | "observations"
  | "verification"
  | "analysis"
  | "data"
  | "reports"
  | "settings";

export type AppMode = "public" | "official";
export type ThemeChoice = "light" | "dark" | "system";
export type TextSize = "normal" | "large" | "xlarge";
export type Units = "metric" | "imperial";
export type Projection = "3d" | "2d" | "columbus";

export interface ColorScaleState {
  colormap: string;
  vmin: number;
  vmax: number;
  /** Set once the user has overridden the variable's default range. */
  custom: boolean;
}

/** A named stretch of coast, used by the public dashboard. */
export interface CoastRegion {
  id: string;
  name: string;
  nameHi: string;
  /**
   * The region's name with the preposition that reads correctly for it.
   * "off the Bay of Bengal" is wrong English; "off the Kerala coast" is
   * right. Carrying the whole phrase is simpler than inferring it, and it
   * keeps the Hindi natural rather than a word-for-word calque.
   */
  phrase: string;
  phraseHi: string;
  bbox: [number, number, number, number]; // west, south, east, north
  centre: { lat: number; lon: number };
}

export const REGIONS: CoastRegion[] = [
  {
    id: "all",
    name: "All Indian Ocean",
    nameHi: "सम्पूर्ण हिंद महासागर",
    phrase: "across the Indian Ocean",
    phraseHi: "सम्पूर्ण हिंद महासागर में",
    bbox: [55, -10, 100, 26],
    centre: { lat: 8, lon: 77 },
  },
  {
    id: "arabian",
    name: "Arabian Sea",
    nameHi: "अरब सागर",
    phrase: "in the Arabian Sea",
    phraseHi: "अरब सागर में",
    bbox: [55, 5, 78, 26],
    centre: { lat: 15, lon: 66 },
  },
  {
    id: "bengal",
    name: "Bay of Bengal",
    nameHi: "बंगाल की खाड़ी",
    phrase: "in the Bay of Bengal",
    phraseHi: "बंगाल की खाड़ी में",
    bbox: [80, 5, 95, 23],
    centre: { lat: 14, lon: 87 },
  },
  {
    id: "gujarat",
    name: "Gujarat & Maharashtra coast",
    nameHi: "गुजरात एवं महाराष्ट्र तट",
    phrase: "off the Gujarat and Maharashtra coast",
    phraseHi: "गुजरात एवं महाराष्ट्र तट के पास",
    bbox: [66, 15, 74, 24],
    centre: { lat: 20, lon: 70 },
  },
  {
    id: "kerala",
    name: "Kerala & Karnataka coast",
    nameHi: "केरल एवं कर्नाटक तट",
    phrase: "off the Kerala and Karnataka coast",
    phraseHi: "केरल एवं कर्नाटक तट के पास",
    bbox: [70, 7, 77, 16],
    centre: { lat: 11, lon: 74 },
  },
  {
    id: "tamilnadu",
    name: "Tamil Nadu & Andhra coast",
    nameHi: "तमिलनाडु एवं आंध्र तट",
    phrase: "off the Tamil Nadu and Andhra coast",
    phraseHi: "तमिलनाडु एवं आंध्र तट के पास",
    bbox: [78, 7, 87, 20],
    centre: { lat: 13, lon: 81 },
  },
  {
    id: "odisha",
    name: "Odisha & West Bengal coast",
    nameHi: "ओडिशा एवं पश्चिम बंगाल तट",
    phrase: "off the Odisha and West Bengal coast",
    phraseHi: "ओडिशा एवं पश्चिम बंगाल तट के पास",
    bbox: [84, 17, 92, 23],
    centre: { lat: 20, lon: 87 },
  },
  {
    id: "andaman",
    name: "Andaman & Nicobar",
    nameHi: "अंडमान एवं निकोबार",
    phrase: "around the Andaman and Nicobar Islands",
    phraseHi: "अंडमान एवं निकोबार द्वीपों के आसपास",
    bbox: [90, 5, 100, 15],
    centre: { lat: 10, lon: 93 },
  },
  {
    id: "lakshadweep",
    name: "Lakshadweep",
    nameHi: "लक्षद्वीप",
    phrase: "around Lakshadweep",
    phraseHi: "लक्षद्वीप के आसपास",
    bbox: [70, 7, 76, 14],
    centre: { lat: 10.5, lon: 72.6 },
  },
];

export function regionById(id: string): CoastRegion {
  return REGIONS.find((region) => region.id === id) ?? REGIONS[0];
}

/* ========================================================================== */
/* Shape                                                                      */
/* ========================================================================== */

interface AppState {
  /* ---- Chrome ----------------------------------------------------------- */
  mode: AppMode;
  section: Section;
  language: Language;
  theme: ThemeChoice;
  textSize: TextSize;
  highContrast: boolean;
  units: Units;
  sidebarCollapsed: boolean;
  setMode: (mode: AppMode) => void;
  setSection: (section: Section) => void;
  setLanguage: (language: Language) => void;
  setTheme: (theme: ThemeChoice) => void;
  setTextSize: (size: TextSize) => void;
  setHighContrast: (on: boolean) => void;
  setUnits: (units: Units) => void;
  toggleSidebar: () => void;
  resetPreferences: () => void;

  /* ---- Region (public dashboard) ---------------------------------------- */
  regionId: string;
  setRegion: (id: string) => void;

  /* ---- Dataset ---------------------------------------------------------- */
  datasetId: string | null;
  variable: string;
  setDataset: (id: string) => void;
  setVariable: (variable: string) => void;

  /* ---- Slicing ---------------------------------------------------------- */
  depthIndex: number;
  timeIndex: number;
  verticalExaggeration: number;
  setDepthIndex: (index: number) => void;
  setTimeIndex: (index: number) => void;
  setVerticalExaggeration: (value: number) => void;

  /* ---- Playback --------------------------------------------------------- */
  playing: boolean;
  playbackRate: number;
  togglePlaying: () => void;
  setPlaying: (playing: boolean) => void;
  setPlaybackRate: (rate: number) => void;

  /* ---- Map -------------------------------------------------------------- */
  layers: LayerState[];
  toggleLayer: (id: LayerId) => void;
  setLayerEnabled: (id: LayerId, enabled: boolean) => void;
  setLayerOpacity: (id: LayerId, opacity: number) => void;
  projection: Projection;
  setProjection: (projection: Projection) => void;
  mapPanel: "layers" | "legend" | "none";
  setMapPanel: (panel: "layers" | "legend" | "none") => void;

  /* ---- Colour ----------------------------------------------------------- */
  colorScale: ColorScaleState;
  setColorScale: (patch: Partial<ColorScaleState>) => void;
  resetColorScale: (colormap: string, vmin: number, vmax: number) => void;

  /* ---- Selection -------------------------------------------------------- */
  selectedProfileId: number | null;
  selectedPlatformId: string | null;
  collocationVariable: string;
  selectProfile: (profileId: number | null, platformId?: string | null) => void;
  setCollocationVariable: (variable: string) => void;

  /* ---- Analysis --------------------------------------------------------- */
  analysisLayer: AnalysisLayer;
  setAnalysisLayer: (layer: AnalysisLayer) => void;
  analysisOpen: boolean;
  toggleAnalysis: () => void;

  /* ---- Alerts ----------------------------------------------------------- */
  alerts: OceanAlert[];
  setAlerts: (alerts: OceanAlert[]) => void;
  alertsOpen: boolean;
  toggleAlerts: () => void;
  setAlertsOpen: (open: boolean) => void;

  /* ---- Assistant -------------------------------------------------------- */
  assistantOpen: boolean;
  setAssistantOpen: (open: boolean) => void;

  /* ---- Cross-view navigation -------------------------------------------- */
  /** Set by "view on map" links; the map consumes it once and clears it. */
  mapFocus: { lat: number; lon: number } | null;
  focusOnMap: (lat: number, lon: number) => void;
  clearMapFocus: () => void;
}

const DEFAULT_LAYERS: LayerState[] = [
  { id: "surface", label: "Coloured field", enabled: true, opacity: 1 },
  { id: "currents", label: "Current streamlines", enabled: true, opacity: 0.75 },
  { id: "platforms", label: "Floats & instruments", enabled: true, opacity: 1, fixedOpacity: true },
  { id: "eddies", label: "Eddy rings", enabled: false, opacity: 0.6 },
  { id: "bias", label: "Model−observation bias", enabled: false, opacity: 1, fixedOpacity: true },
  { id: "graticule", label: "Latitude / longitude grid", enabled: true, opacity: 1, fixedOpacity: true },
];

/** Preferences that survive a reload; session state deliberately does not. */
const PERSISTED_KEYS = [
  "mode",
  "language",
  "theme",
  "textSize",
  "highContrast",
  "units",
  "sidebarCollapsed",
  "regionId",
] as const;

const PREFERENCE_DEFAULTS = {
  mode: "public" as AppMode,
  language: "en" as Language,
  theme: "system" as ThemeChoice,
  textSize: "normal" as TextSize,
  highContrast: false,
  units: "metric" as Units,
  sidebarCollapsed: false,
  regionId: "all",
};

export const useAppStore = create<AppState>()(
  persist(
    (set) => ({
      /* ---- Chrome --------------------------------------------------------- */
      ...PREFERENCE_DEFAULTS,
      // A citizen lands on the plain-language dashboard; an official switches
      // mode once and the preference is remembered from then on.
      section: "today",
      setMode: (mode) =>
        set((state) => ({
          mode,
          // Sections that only exist in one mode must not survive the switch.
          section: sectionForMode(mode, state.section),
        })),
      setSection: (section) => set({ section }),
      setLanguage: (language) => set({ language }),
      setTheme: (theme) => set({ theme }),
      setTextSize: (textSize) => set({ textSize }),
      setHighContrast: (highContrast) => set({ highContrast }),
      setUnits: (units) => set({ units }),
      toggleSidebar: () => set((state) => ({ sidebarCollapsed: !state.sidebarCollapsed })),
      resetPreferences: () => set({ ...PREFERENCE_DEFAULTS }),

      /* ---- Region --------------------------------------------------------- */
      setRegion: (regionId) => set({ regionId }),

      /* ---- Dataset -------------------------------------------------------- */
      datasetId: null,
      variable: "temperature",
      setDataset: (datasetId) => set({ datasetId }),
      setVariable: (variable) =>
        set((state) => ({
          variable,
          // A new variable invalidates a range hand-tuned for the previous one.
          colorScale: { ...state.colorScale, custom: false },
        })),

      /* ---- Slicing -------------------------------------------------------- */
      depthIndex: 0,
      timeIndex: 0,
      verticalExaggeration: 20,
      setDepthIndex: (depthIndex) => set({ depthIndex }),
      setTimeIndex: (timeIndex) => set({ timeIndex }),
      setVerticalExaggeration: (verticalExaggeration) => set({ verticalExaggeration }),

      /* ---- Playback ------------------------------------------------------- */
      playing: false,
      playbackRate: 1,
      togglePlaying: () => set((state) => ({ playing: !state.playing })),
      setPlaying: (playing) => set({ playing }),
      setPlaybackRate: (playbackRate) => set({ playbackRate }),

      /* ---- Map ------------------------------------------------------------ */
      layers: DEFAULT_LAYERS,
      toggleLayer: (id) =>
        set((state) => ({
          layers: state.layers.map((layer) =>
            layer.id === id ? { ...layer, enabled: !layer.enabled } : layer,
          ),
        })),
      setLayerEnabled: (id, enabled) =>
        set((state) => ({
          layers: state.layers.map((layer) => (layer.id === id ? { ...layer, enabled } : layer)),
        })),
      setLayerOpacity: (id, opacity) =>
        set((state) => ({
          layers: state.layers.map((layer) => (layer.id === id ? { ...layer, opacity } : layer)),
        })),
      projection: "3d",
      setProjection: (projection) => set({ projection }),
      mapPanel: "layers",
      setMapPanel: (mapPanel) => set({ mapPanel }),

      /* ---- Colour --------------------------------------------------------- */
      colorScale: { colormap: "thermal", vmin: 2, vmax: 32, custom: false },
      setColorScale: (patch) =>
        set((state) => ({ colorScale: { ...state.colorScale, ...patch, custom: true } })),
      resetColorScale: (colormap, vmin, vmax) =>
        set({ colorScale: { colormap, vmin, vmax, custom: false } }),

      /* ---- Selection ------------------------------------------------------ */
      selectedProfileId: null,
      selectedPlatformId: null,
      collocationVariable: "temperature",
      selectProfile: (selectedProfileId, selectedPlatformId = null) =>
        set({ selectedProfileId, selectedPlatformId }),
      setCollocationVariable: (collocationVariable) => set({ collocationVariable }),

      /* ---- Analysis ------------------------------------------------------- */
      analysisLayer: "none",
      setAnalysisLayer: (analysisLayer) =>
        set((state) => ({
          analysisLayer,
          // Selecting the bias or eddy product turns its map layer on, so the
          // choice is visible immediately instead of silently doing nothing.
          layers: state.layers.map((layer) => {
            if (layer.id === "bias") return { ...layer, enabled: analysisLayer === "bias" };
            if (layer.id === "eddies") return { ...layer, enabled: analysisLayer === "eddies" };
            return layer;
          }),
        })),
      analysisOpen: false,
      toggleAnalysis: () => set((state) => ({ analysisOpen: !state.analysisOpen })),

      /* ---- Alerts --------------------------------------------------------- */
      alerts: [],
      setAlerts: (alerts) => set({ alerts }),
      alertsOpen: false,
      toggleAlerts: () => set((state) => ({ alertsOpen: !state.alertsOpen })),
      setAlertsOpen: (alertsOpen) => set({ alertsOpen }),

      /* ---- Assistant ------------------------------------------------------ */
      assistantOpen: false,
      setAssistantOpen: (assistantOpen) => set({ assistantOpen }),

      /* ---- Cross-view navigation ------------------------------------------ */
      mapFocus: null,
      focusOnMap: (lat, lon) => set({ section: "map", mapFocus: { lat, lon } }),
      clearMapFocus: () => set({ mapFocus: null }),
    }),
    {
      name: "indofos.preferences",
      version: 2,
      storage: createJSONStorage(() => localStorage),
      partialize: (state) =>
        Object.fromEntries(PERSISTED_KEYS.map((key) => [key, state[key]])) as Partial<AppState>,
    },
  ),
);

/* ========================================================================== */
/* Section visibility                                                         */
/* ========================================================================== */

/** Sections a citizen sees. The rest are specialist tools, not hidden secrets:
    Settings explains that Official mode exposes them. */
export const PUBLIC_SECTIONS: Section[] = ["today", "map", "reports", "settings"];

export const OFFICIAL_SECTIONS: Section[] = [
  "today",
  "map",
  "observations",
  "verification",
  "analysis",
  "data",
  "reports",
  "settings",
];

export function sectionsForMode(mode: AppMode): Section[] {
  return mode === "public" ? PUBLIC_SECTIONS : OFFICIAL_SECTIONS;
}

/** Keep the current section if the new mode still has it; otherwise go home. */
function sectionForMode(mode: AppMode, current: Section): Section {
  return sectionsForMode(mode).includes(current) ? current : "today";
}
