/**
 * Cesium bootstrap.
 *
 * Configured for fully offline operation: no Ion token, no network imagery.
 * Cesium ships a Natural Earth II tileset in its own asset bundle, which we
 * darken heavily so the vivid thermal ramp reads as the primary signal and
 * the basemap recedes to context - matching the approved design.
 */

import {
  Color,
  Ion,
  TileMapServiceImageryProvider,
  Viewer,
  buildModuleUrl,
  Rectangle,
  Cartesian3,
  Math as CesiumMath,
  ScreenSpaceEventType,
  ShadowMode,
  type ImageryLayer,
} from "cesium";
import "cesium/Build/Cesium/Widgets/widgets.css";

/** Indian EEZ and surrounding basins - the dataset's own footprint. */
export const DOMAIN = {
  west: 55,
  south: -10,
  east: 100,
  north: 26,
} as const;

/**
 * Cesium refuses to start without *some* token value even when no Ion asset is
 * requested. An empty string keeps it quiet and guarantees no outbound call.
 */
Ion.defaultAccessToken = "";

/** Imagery-layer adjustments per theme, applied to the basemap. */
const BASEMAP_TONE = {
  dark: { brightness: 0.4, saturation: 0.3, contrast: 1.14, gamma: 0.76 },
  light: { brightness: 1.02, saturation: 0.62, contrast: 1.02, gamma: 1 },
} as const;

/** The basemap layer, kept so the theme can restyle it after creation. */
const basemapLayers = new WeakMap<Viewer, ImageryLayer>();

export function createViewer(container: HTMLDivElement): Viewer {
  const viewer = new Viewer(container, {
    // Offline basemap bundled with Cesium itself.
    baseLayer: false,
    baseLayerPicker: false,
    geocoder: false,
    homeButton: false,
    sceneModePicker: false,
    navigationHelpButton: false,
    animation: false,
    timeline: false,
    fullscreenButton: false,
    infoBox: false,
    selectionIndicator: false,
    shadows: false,
    terrainShadows: ShadowMode.DISABLED,
    requestRenderMode: false,
    contextOptions: {
      webgl: { alpha: false, antialias: true, preserveDrawingBuffer: true },
    },
  });

  // ---- Basemap ------------------------------------------------------------
  // Cesium 1.1xx exposes imagery providers through async factories.
  TileMapServiceImageryProvider.fromUrl(
    buildModuleUrl("Assets/Textures/NaturalEarthII"),
  )
    .then((natural) => {
      if (viewer.isDestroyed()) return;
      const layer = viewer.imageryLayers.addImageryProvider(natural);
      // Keep a handle so applySceneTheme can restyle it when the app theme
      // changes; the basemap has to follow the interface, not stay dark.
      basemapLayers.set(viewer, layer);
      applyBasemapTone(layer, true);
    })
    .catch(() => {
      // A missing basemap must not break the app: the data layer and the
      // globe's base colour still render a usable scene.
    });

  // ---- Scene styling ------------------------------------------------------
  const scene = viewer.scene;
  scene.globe.enableLighting = false;
  scene.globe.depthTestAgainstTerrain = false;
  scene.fog.enabled = false;
  scene.highDynamicRange = false;

  if (scene.sun) scene.sun.show = false;
  if (scene.moon) scene.moon.show = false;

  applySceneTheme(viewer, true);

  // Cesium's default double-click zoom fights with entity selection.
  viewer.screenSpaceEventHandler.removeInputAction(
    ScreenSpaceEventType.LEFT_DOUBLE_CLICK,
  );

  // Hide the credit bar; attribution lives in the About panel instead.
  const credits = viewer.cesiumWidget.creditContainer as HTMLElement;
  credits.style.display = "none";

  flyToDomain(viewer, 0);
  return viewer;
}

function applyBasemapTone(layer: ImageryLayer, dark: boolean): void {
  const tone = dark ? BASEMAP_TONE.dark : BASEMAP_TONE.light;
  layer.brightness = tone.brightness;
  layer.saturation = tone.saturation;
  layer.contrast = tone.contrast;
  layer.gamma = tone.gamma;
}

/**
 * Restyle the scene for the app's current theme.
 *
 * In dark mode the basemap is pushed right back so the data layer dominates.
 * In light mode it is left close to its natural colours, because a light
 * interface with a near-black globe reads as a rendering fault rather than a
 * design choice — and on a projector in a bright room the dark scene is the
 * one people cannot see at all.
 */
export function applySceneTheme(viewer: Viewer, dark: boolean): void {
  if (viewer.isDestroyed()) return;
  const scene = viewer.scene;

  scene.globe.baseColor = Color.fromCssColorString(dark ? "#050d18" : "#c9dcea");
  scene.backgroundColor = Color.fromCssColorString(dark ? "#04080f" : "#dde8f1");
  scene.globe.showGroundAtmosphere = dark;

  if (scene.skyAtmosphere) {
    scene.skyAtmosphere.show = dark;
    scene.skyAtmosphere.hueShift = -0.06;
    scene.skyAtmosphere.saturationShift = dark ? -0.32 : -0.1;
    scene.skyAtmosphere.brightnessShift = dark ? -0.26 : 0.1;
  }
  if (scene.skyBox) scene.skyBox.show = dark;

  const basemap = basemapLayers.get(viewer);
  if (basemap) applyBasemapTone(basemap, dark);
}

/** Frame the Indian Ocean domain. */
export function flyToDomain(viewer: Viewer, duration = 1.2): void {
  viewer.camera.flyTo({
    destination: Rectangle.fromDegrees(
      DOMAIN.west - 4,
      DOMAIN.south - 4,
      DOMAIN.east + 4,
      DOMAIN.north + 6,
    ),
    duration,
  });
}

/** Centre on a point, keeping the current viewing altitude. */
export function flyToPoint(
  viewer: Viewer,
  lat: number,
  lon: number,
  height = 2_600_000,
): void {
  viewer.camera.flyTo({
    destination: Cartesian3.fromDegrees(lon, lat, height),
    orientation: {
      heading: CesiumMath.toRadians(0),
      pitch: CesiumMath.toRadians(-90),
      roll: 0,
    },
    duration: 1.1,
  });
}

export const PLATFORM_COLORS: Record<string, string> = {
  argo_float: "#38bdf8",
  glider: "#2dd4bf",
  ctd: "#f0a12e",
  mooring: "#a78bfa",
  adcp: "#f472b6",
  drifter: "#94a3b8",
};

export function platformColor(type: string | null | undefined): Color {
  return Color.fromCssColorString(PLATFORM_COLORS[type ?? ""] ?? "#94a3b8");
}

/** Diverging red-blue ramp for model-minus-observation bias markers. */
export function biasColor(bias: number | null, spread: number): Color {
  if (bias === null || !Number.isFinite(bias)) return Color.fromCssColorString("#64809f");
  const t = Math.max(-1, Math.min(1, bias / (spread || 1)));
  return t >= 0
    ? Color.fromCssColorString("#ef4b52").withAlpha(0.45 + 0.55 * t)
    : Color.fromCssColorString("#38bdf8").withAlpha(0.45 + 0.55 * -t);
}
