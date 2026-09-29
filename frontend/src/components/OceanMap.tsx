/**
 * The map.
 *
 * Every control on this surface does something. The previous version shipped
 * a toolbar of seven buttons where four had no handler at all, and a layer
 * list where four of six layers were not connected to the scene — so the
 * interface promised capability it did not have. Here, each toolbar button and
 * each layer switch is wired to the viewer, and anything that cannot act is
 * disabled with a reason rather than left looking live.
 */

import { useCallback, useEffect, useMemo, useRef, useState } from "react";
import {
  Cartesian2,
  Cartesian3,
  Color,
  Entity,
  GridImageryProvider,
  Rectangle,
  ScreenSpaceEventHandler,
  ScreenSpaceEventType,
  SceneMode,
  SingleTileImageryProvider,
  type ImageryLayer,
  type Viewer,
} from "cesium";
import {
  Box,
  Camera,
  Crosshair,
  Globe as GlobeIcon,
  Link2,
  Map as MapIcon,
  Minus,
  Plus,
  X,
} from "lucide-react";
import { useAppStore, type Projection } from "@/state/store";
import {
  applySceneTheme,
  createViewer,
  DOMAIN,
  flyToDomain,
  flyToPoint,
  platformColor,
} from "@/lib/cesium-setup";
import { ParticleLayer, type VelocityField } from "@/lib/particles";
import { planeToFloat32, renderPlaneToCanvas, sampleAt, type OcvolBlock } from "@/lib/ocvol";
import { volumeTimeIndex } from "@/lib/queries";
import { renderGridToCanvas, type Ramp } from "@/lib/grid-render";
import { formatLatLon, formatUnits, shortName } from "@/lib/format";
import { IconButton } from "@/ui";
import type { BiasMarker, Eddy, GridPayload, Platform } from "@/types/api";
import "./OceanMap.css";

/** A derived product painted over the model field. */
export interface MapOverlay {
  grid: GridPayload;
  range: [number, number];
  ramp: Ramp;
  label: string;
  units: string;
}

export interface MapPick {
  lat: number;
  lon: number;
  value: number;
  variable: string;
  units: string;
}

interface OceanMapProps {
  field: OcvolBlock | undefined;
  lut: Uint8Array | undefined;
  velocity: { u: OcvolBlock; v: OcvolBlock } | undefined;
  platforms: Platform[];
  eddies: Eddy[];
  biasMarkers: BiasMarker[];
  overlay?: MapOverlay;
  units: string;
  /**
   * Length of the dataset's own time axis. A long run comes back subsampled,
   * so the UI's step has to be mapped onto the block's axis rather than used
   * as a direct index — otherwise the map draws a different day from the one
   * the clock is showing.
   */
  timeAxisLength: number;
  onSelectProfile: (profileId: number, platformId: string) => void;
  onShare?: () => void;
  onReady?: (api: MapApi) => void;
}

export interface MapApi {
  flyTo: (lat: number, lon: number, heightKm: number) => void;
  resetView: () => void;
  camera: () => { lat: number; lon: number; heightKm: number } | null;
  screenshot: () => string | null;
}

const SCENE_MODE: Record<Projection, SceneMode> = {
  "3d": SceneMode.SCENE3D,
  "2d": SceneMode.SCENE2D,
  columbus: SceneMode.COLUMBUS_VIEW,
};

export function OceanMap({
  field,
  lut,
  velocity,
  platforms,
  eddies,
  biasMarkers,
  overlay,
  units,
  timeAxisLength,
  onSelectProfile,
  onShare,
  onReady,
}: OceanMapProps) {
  const containerRef = useRef<HTMLDivElement>(null);
  const overlayCanvasRef = useRef<HTMLCanvasElement>(null);
  const viewerRef = useRef<Viewer | null>(null);
  const particlesRef = useRef<ParticleLayer | null>(null);
  const fieldLayerRef = useRef<ImageryLayer | null>(null);
  const overlayLayerRef = useRef<ImageryLayer | null>(null);
  const graticuleLayerRef = useRef<ImageryLayer | null>(null);
  const entitiesRef = useRef<Entity[]>([]);
  const [ready, setReady] = useState(false);
  const [pick, setPick] = useState<MapPick | null>(null);

  const onReadyRef = useRef(onReady);
  useEffect(() => {
    onReadyRef.current = onReady;
  }, [onReady]);

  const {
    depthIndex,
    timeIndex,
    colorScale,
    layers,
    projection,
    setProjection,
    selectedProfileId,
    theme,
    variable,
  } = useAppStore();

  const layerOf = useCallback(
    (id: string) => layers.find((layer) => layer.id === id),
    [layers],
  );

  const surface = layerOf("surface");
  const currents = layerOf("currents");
  const showPlatforms = layerOf("platforms")?.enabled ?? true;
  const showEddies = layerOf("eddies")?.enabled ?? false;
  const showBias = layerOf("bias")?.enabled ?? false;
  const showGraticule = layerOf("graticule")?.enabled ?? true;

  const dark = useIsDark(theme);

  /* ---------------------------------------------------------------------- */
  /* Viewer lifecycle                                                        */
  /* ---------------------------------------------------------------------- */
  useEffect(() => {
    if (!containerRef.current || !overlayCanvasRef.current) return;

    let viewer: Viewer;
    try {
      viewer = createViewer(containerRef.current);
    } catch (error) {
      console.error("Cesium failed to initialise", error);
      return;
    }
    viewerRef.current = viewer;

    if (import.meta.env.DEV) {
      (window as unknown as { __viewer?: Viewer }).__viewer = viewer;
    }

    const particles = new ParticleLayer(viewer, overlayCanvasRef.current);
    particlesRef.current = particles;

    const resize = () => {
      const rect = containerRef.current?.getBoundingClientRect();
      // A zero-size measurement happens before first layout and in a hidden
      // tab; sizing to it would leave a 1x1 buffer forever.
      if (rect && rect.width > 0 && rect.height > 0) {
        particles.resize(rect.width, rect.height);
      }
    };
    resize();
    requestAnimationFrame(resize);
    particles.start();

    const observer = new ResizeObserver(resize);
    observer.observe(containerRef.current);

    setReady(true);

    onReadyRef.current?.({
      flyTo: (lat, lon, heightKm) => {
        const current = viewerRef.current;
        if (current && !current.isDestroyed()) flyToPoint(current, lat, lon, heightKm * 1000);
      },
      resetView: () => {
        const current = viewerRef.current;
        if (current && !current.isDestroyed()) flyToDomain(current);
      },
      camera: () => {
        const current = viewerRef.current;
        if (!current || current.isDestroyed()) return null;
        const carto = current.camera.positionCartographic;
        return {
          lat: (carto.latitude * 180) / Math.PI,
          lon: (carto.longitude * 180) / Math.PI,
          heightKm: carto.height / 1000,
        };
      },
      screenshot: () => {
        const current = viewerRef.current;
        if (!current || current.isDestroyed()) return null;
        current.render();
        return current.canvas.toDataURL("image/png");
      },
    });

    return () => {
      observer.disconnect();
      particles.stop();
      particlesRef.current = null;
      viewerRef.current = null;
      fieldLayerRef.current = null;
      overlayLayerRef.current = null;
      graticuleLayerRef.current = null;
      entitiesRef.current = [];
      if (!viewer.isDestroyed()) viewer.destroy();
    };
  }, []);

  /* Theme — the scene has to follow the app, not stay dark forever. */
  useEffect(() => {
    const viewer = viewerRef.current;
    if (viewer && !viewer.isDestroyed() && ready) applySceneTheme(viewer, dark);
  }, [dark, ready]);

  /* ---------------------------------------------------------------------- */
  /* Projection — this is what the 3D / 2D / Columbus buttons never did      */
  /* ---------------------------------------------------------------------- */
  useEffect(() => {
    const viewer = viewerRef.current;
    if (!viewer || viewer.isDestroyed() || !ready) return;

    const target = SCENE_MODE[projection];
    if (viewer.scene.mode === target) return;

    const duration = 0.9;
    if (target === SceneMode.SCENE2D) viewer.scene.morphTo2D(duration);
    else if (target === SceneMode.COLUMBUS_VIEW) viewer.scene.morphToColumbusView(duration);
    else viewer.scene.morphTo3D(duration);

    // The morph is a tween advanced by render frames. A hidden or backgrounded
    // tab throttles requestAnimationFrame, so a projection switched just before
    // the user tabs away never finishes and the scene stays wedged in
    // SceneMode.MORPHING — the buttons then look dead on return. Snap it to the
    // target if the animation has not landed shortly after it should have.
    const settle = window.setTimeout(
      () => {
        const current = viewerRef.current;
        if (current && !current.isDestroyed() && current.scene.mode !== target) {
          current.scene.completeMorph();
        }
      },
      duration * 1000 + 400,
    );

    return () => window.clearTimeout(settle);
  }, [projection, ready]);

  /* ---------------------------------------------------------------------- */
  /* Field layer — recoloured from memory, never re-fetched                  */
  /* ---------------------------------------------------------------------- */
  useEffect(() => {
    const viewer = viewerRef.current;
    if (!viewer || viewer.isDestroyed() || !ready) return;

    if (fieldLayerRef.current) {
      viewer.imageryLayers.remove(fieldLayerRef.current, true);
      fieldLayerRef.current = null;
    }
    if (!field || !lut || !surface?.enabled) return;

    const time = volumeTimeIndex(timeIndex, timeAxisLength, field);
    const depth = Math.min(depthIndex, field.nDepth - 1);

    const canvas = renderPlaneToCanvas(field, lut, {
      time,
      depth,
      vmin: colorScale.vmin,
      vmax: colorScale.vmax,
    });

    let cancelled = false;
    SingleTileImageryProvider.fromUrl(canvas.toDataURL("image/png"), {
      rectangle: Rectangle.fromDegrees(
        field.header.lon_range[0],
        field.header.lat_range[0],
        field.header.lon_range[1],
        field.header.lat_range[1],
      ),
    })
      .then((provider) => {
        if (cancelled || viewer.isDestroyed()) return;
        const layer = viewer.imageryLayers.addImageryProvider(provider);
        layer.alpha = surface.opacity;
        fieldLayerRef.current = layer;
      })
      .catch((error) => console.error("Could not add the field layer", error));

    return () => {
      cancelled = true;
    };
  }, [field, lut, depthIndex, timeIndex, timeAxisLength, colorScale.vmin, colorScale.vmax, surface?.enabled, ready]);

  useEffect(() => {
    if (fieldLayerRef.current && surface) fieldLayerRef.current.alpha = surface.opacity;
  }, [surface?.opacity, surface]);

  /* ---------------------------------------------------------------------- */
  /* Derived-product overlay (anomaly, mixed layer, thermocline)             */
  /* ---------------------------------------------------------------------- */
  useEffect(() => {
    const viewer = viewerRef.current;
    if (!viewer || viewer.isDestroyed() || !ready) return;

    if (overlayLayerRef.current) {
      viewer.imageryLayers.remove(overlayLayerRef.current, true);
      overlayLayerRef.current = null;
    }
    if (!overlay) return;

    const canvas = renderGridToCanvas(overlay.grid, overlay.range, overlay.ramp);
    if (!canvas) return;

    const lats = overlay.grid.lats;
    const lons = overlay.grid.lons;
    let cancelled = false;

    SingleTileImageryProvider.fromUrl(canvas.toDataURL("image/png"), {
      rectangle: Rectangle.fromDegrees(
        Math.min(lons[0], lons[lons.length - 1]),
        Math.min(lats[0], lats[lats.length - 1]),
        Math.max(lons[0], lons[lons.length - 1]),
        Math.max(lats[0], lats[lats.length - 1]),
      ),
    })
      .then((provider) => {
        if (cancelled || viewer.isDestroyed()) return;
        overlayLayerRef.current = viewer.imageryLayers.addImageryProvider(provider);
      })
      .catch((error) => console.error("Could not add the overlay layer", error));

    return () => {
      cancelled = true;
    };
  }, [overlay, ready]);

  /* ---------------------------------------------------------------------- */
  /* Graticule — a real grid drawn by the renderer, not painted-on labels    */
  /* ---------------------------------------------------------------------- */
  useEffect(() => {
    const viewer = viewerRef.current;
    if (!viewer || viewer.isDestroyed() || !ready) return;

    if (graticuleLayerRef.current) {
      viewer.imageryLayers.remove(graticuleLayerRef.current, true);
      graticuleLayerRef.current = null;
    }
    if (!showGraticule) return;

    const layer = viewer.imageryLayers.addImageryProvider(
      new GridImageryProvider({
        cells: 4,
        color: Color.fromCssColorString(dark ? "#7ba3c9" : "#33608c").withAlpha(0.35),
        glowColor: Color.TRANSPARENT,
        glowWidth: 0,
        backgroundColor: Color.TRANSPARENT,
      }),
    );
    graticuleLayerRef.current = layer;
  }, [showGraticule, dark, ready]);

  /* ---------------------------------------------------------------------- */
  /* Current streamlines                                                     */
  /* ---------------------------------------------------------------------- */
  const velocityField = useMemo<VelocityField | null>(() => {
    if (!velocity) return null;
    const { u, v } = velocity;
    const time = volumeTimeIndex(timeIndex, timeAxisLength, u);
    const depth = Math.min(depthIndex, u.nDepth - 1);
    return {
      u: planeToFloat32(u, time, depth),
      v: planeToFloat32(v, time, depth),
      nLat: u.nLat,
      nLon: u.nLon,
      latMin: u.header.lat_range[0],
      latMax: u.header.lat_range[1],
      lonMin: u.header.lon_range[0],
      lonMax: u.header.lon_range[1],
    };
  }, [velocity, timeIndex, timeAxisLength, depthIndex]);

  useEffect(() => {
    const particles = particlesRef.current;
    if (!particles) return;
    const enabled = currents?.enabled ?? false;
    particles.setField(enabled ? velocityField : null);
    particles.setOpacity(enabled ? (currents?.opacity ?? 0.75) : 0);
    if (!enabled) particles.clear();
  }, [velocityField, currents?.enabled, currents?.opacity, currents]);

  /* ---------------------------------------------------------------------- */
  /* Entities                                                                */
  /* ---------------------------------------------------------------------- */
  useEffect(() => {
    const viewer = viewerRef.current;
    if (!viewer || viewer.isDestroyed() || !ready) return;

    for (const entity of entitiesRef.current) viewer.entities.remove(entity);
    entitiesRef.current = [];
    const added: Entity[] = [];

    if (showPlatforms) {
      for (const platform of platforms) {
        const position = platform.last_position;
        if (!position) continue;

        const track = platform.trajectory ?? [];
        const latest = track.length > 0 ? track[track.length - 1] : null;
        const isSelected = latest !== null && latest.profile_id === selectedProfileId;

        if (track.length > 1) {
          added.push(
            viewer.entities.add({
              id: `track-${platform.platform_id}`,
              polyline: {
                positions: track.map((point) => Cartesian3.fromDegrees(point.lon, point.lat, 0)),
                width: isSelected ? 2.8 : 1.4,
                material: platformColor(platform.platform_type).withAlpha(isSelected ? 0.95 : 0.4),
                clampToGround: false,
              },
            }),
          );
        }

        added.push(
          viewer.entities.add({
            id: `platform-${platform.platform_id}`,
            position: Cartesian3.fromDegrees(position.lon, position.lat),
            point: {
              pixelSize: isSelected ? 16 : 9,
              color: platformColor(platform.platform_type),
              outlineColor: isSelected
                ? Color.fromCssColorString("#e07a1f")
                : Color.fromCssColorString(dark ? "#060f1c" : "#ffffff"),
              outlineWidth: isSelected ? 3 : 1.6,
            },
            properties: {
              kind: "platform",
              profileId: latest?.profile_id ?? null,
              platformId: platform.platform_id,
            },
          }),
        );
      }
    }

    if (showBias) {
      for (const marker of biasMarkers) {
        const magnitude = Math.abs(marker.bias ?? 0);
        added.push(
          viewer.entities.add({
            id: `bias-${marker.profile_id}`,
            position: Cartesian3.fromDegrees(marker.lon, marker.lat),
            point: {
              pixelSize: 9 + Math.min(10, magnitude * 14),
              color:
                (marker.bias ?? 0) >= 0
                  ? Color.fromCssColorString("#c0392b")
                  : Color.fromCssColorString("#1a4d81"),
              outlineColor: Color.fromCssColorString(dark ? "#060f1c" : "#ffffff"),
              outlineWidth: 1.6,
            },
            properties: {
              kind: "bias",
              profileId: marker.profile_id,
              platformId: marker.platform_id,
            },
          }),
        );
      }
    }

    if (showEddies) {
      for (const eddy of eddies) {
        const cyclonic = eddy.polarity === "cyclonic";
        const colour = cyclonic
          ? Color.fromCssColorString("#0891b2")
          : Color.fromCssColorString("#e07a1f");
        added.push(
          viewer.entities.add({
            id: `eddy-${eddy.id}`,
            position: Cartesian3.fromDegrees(eddy.centre.lon, eddy.centre.lat),
            ellipse: {
              semiMajorAxis: eddy.radius_km * 1000,
              semiMinorAxis: eddy.radius_km * 1000,
              material: colour.withAlpha(0.16),
              outline: true,
              outlineColor: colour,
              outlineWidth: 2,
              height: 0,
            },
          }),
        );
      }
    }

    entitiesRef.current = added;
  }, [
    platforms,
    eddies,
    biasMarkers,
    showPlatforms,
    showEddies,
    showBias,
    selectedProfileId,
    dark,
    ready,
  ]);

  /* ---------------------------------------------------------------------- */
  /* Picking — an instrument if you hit one, a value reading if you do not   */
  /* ---------------------------------------------------------------------- */
  useEffect(() => {
    const viewer = viewerRef.current;
    if (!viewer || viewer.isDestroyed() || !ready) return;

    const handler = new ScreenSpaceEventHandler(viewer.scene.canvas);

    handler.setInputAction((movement: ScreenSpaceEventHandler.PositionedEvent) => {
      const picked = viewer.scene.pick(movement.position);
      const entity = picked?.id;

      if (entity instanceof Entity && entity.properties) {
        const profileId = entity.properties.profileId?.getValue();
        const platformId = entity.properties.platformId?.getValue();
        if (typeof profileId === "number" && typeof platformId === "string") {
          onSelectProfile(profileId, platformId);
          return;
        }
      }

      // Nothing picked: read the field where the user clicked. Being able to
      // ask "what is it here?" anywhere on the map is the difference between
      // a picture of the ocean and a usable instrument.
      readValueAt(viewer, movement.position);
    }, ScreenSpaceEventType.LEFT_CLICK);

    function readValueAt(current: Viewer, position: Cartesian2) {
      if (!field) return;
      const ray = current.camera.getPickRay(position);
      const cartesian = ray ? current.scene.globe.pick(ray, current.scene) : undefined;
      if (!cartesian) {
        setPick(null);
        return;
      }
      const carto = current.scene.globe.ellipsoid.cartesianToCartographic(cartesian);
      const lat = (carto.latitude * 180) / Math.PI;
      const lon = (carto.longitude * 180) / Math.PI;

      const value = sampleAt(
        field,
        lat,
        lon,
        volumeTimeIndex(timeIndex, timeAxisLength, field),
        Math.min(depthIndex, field.nDepth - 1),
      );
      setPick(
        Number.isFinite(value)
          ? { lat, lon, value, variable: field.header.variable, units: field.header.units }
          : null,
      );
    }

    return () => handler.destroy();
  }, [onSelectProfile, field, timeIndex, timeAxisLength, depthIndex, ready]);

  /* Clear a stale reading when the slice underneath it changes. */
  useEffect(() => {
    setPick(null);
  }, [variable, timeIndex, depthIndex]);

  /* ---------------------------------------------------------------------- */
  /* Toolbar                                                                 */
  /* ---------------------------------------------------------------------- */
  const zoom = (factor: number) => {
    const viewer = viewerRef.current;
    if (!viewer || viewer.isDestroyed()) return;
    viewer.camera.zoomIn(viewer.camera.positionCartographic.height * factor);
  };

  const screenshot = () => {
    const viewer = viewerRef.current;
    if (!viewer || viewer.isDestroyed()) return;
    viewer.render();
    const anchor = document.createElement("a");
    anchor.href = viewer.canvas.toDataURL("image/png");
    anchor.download = `indofos-map-${new Date().toISOString().slice(0, 10)}.png`;
    anchor.click();
  };

  return (
    <div className="omap">
      <div ref={containerRef} className="omap__scene" />
      <canvas ref={overlayCanvasRef} className="omap__particles" />

      {/* Projection. Morphs the scene for real — 2D is the projection most
          people can actually read a coastline on. */}
      <div className="omap__tools omap__tools--tl">
        <IconButton
          icon={<GlobeIcon size={17} />}
          label="Globe view (3D)"
          bordered
          active={projection === "3d"}
          onClick={() => setProjection("3d")}
        />
        <IconButton
          icon={<MapIcon size={17} />}
          label="Flat map (2D)"
          bordered
          active={projection === "2d"}
          onClick={() => setProjection("2d")}
        />
        <IconButton
          icon={<Box size={17} />}
          label="Columbus view (2.5D)"
          bordered
          active={projection === "columbus"}
          onClick={() => setProjection("columbus")}
        />
      </div>

      <div className="omap__tools omap__tools--tr">
        <IconButton
          icon={<Crosshair size={17} />}
          label="Reset to the Indian Ocean"
          bordered
          onClick={() => viewerRef.current && flyToDomain(viewerRef.current)}
        />
        <IconButton icon={<Plus size={17} />} label="Zoom in" bordered onClick={() => zoom(0.35)} />
        <IconButton icon={<Minus size={17} />} label="Zoom out" bordered onClick={() => zoom(-0.55)} />
        <IconButton icon={<Camera size={17} />} label="Save map as image" bordered onClick={screenshot} />
        {onShare && (
          <IconButton icon={<Link2 size={17} />} label="Copy a link to this view" bordered onClick={onShare} />
        )}
      </div>

      {/* Point reading. Appears where a click landed on water. */}
      {pick && (
        <div className="omap__pick" role="status">
          <div className="omap__pickHead">
            <span className="label">{shortName(pick.variable)}</span>
            <IconButton icon={<X size={14} />} label="Dismiss reading" onClick={() => setPick(null)} />
          </div>
          <p className="omap__pickValue mono">
            {pick.value.toFixed(2)}
            <span className="omap__pickUnits">{formatUnits(pick.units || units)}</span>
          </p>
          <p className="omap__pickWhere mono">{formatLatLon(pick.lat, pick.lon)}</p>
        </div>
      )}

      <p className="omap__hint">Click anywhere on the water to read its value. Click a marker to open its profile.</p>
    </div>
  );
}

/** Resolve "system" against the OS preference, and keep following it. */
function useIsDark(theme: "light" | "dark" | "system"): boolean {
  const [systemDark, setSystemDark] = useState(
    () => window.matchMedia?.("(prefers-color-scheme: dark)").matches ?? false,
  );

  useEffect(() => {
    const query = window.matchMedia?.("(prefers-color-scheme: dark)");
    if (!query) return;
    const onChange = (event: MediaQueryListEvent) => setSystemDark(event.matches);
    query.addEventListener("change", onChange);
    return () => query.removeEventListener("change", onChange);
  }, []);

  return theme === "system" ? systemDark : theme === "dark";
}

export { DOMAIN };
