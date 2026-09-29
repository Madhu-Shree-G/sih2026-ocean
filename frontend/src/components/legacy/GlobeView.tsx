import { useEffect, useMemo, useRef, useState } from "react";
import {
  Cartesian3,
  Color,
  Entity,
  ImageMaterialProperty,
  Rectangle,
  ScreenSpaceEventHandler,
  ScreenSpaceEventType,
  SingleTileImageryProvider,
  type ImageryLayer,
  type Viewer,
} from "cesium";
import {
  Camera,
  Crosshair,
  Globe as GlobeIcon,
  Layers as LayersIcon,
  Link2,
  Minus,
  Plus,
  Search,
  Square,
  BarChart3,
} from "lucide-react";
import { useAppStore } from "@/state/store";
import {
  createViewer,
  DOMAIN,
  flyToDomain,
  flyToPoint,
  platformColor,
} from "@/lib/cesium-setup";
import { ParticleLayer, type VelocityField } from "@/lib/particles";
import { planeToFloat32, renderPlaneToCanvas, type OcvolBlock } from "@/lib/ocvol";
import type { BiasMarker, Eddy, Platform } from "@/types/api";
import "./GlobeView.css";

interface GlobeViewProps {
  field: OcvolBlock | undefined;
  lut: Uint8Array | undefined;
  velocity: { u: OcvolBlock; v: OcvolBlock } | undefined;
  platforms: Platform[];
  eddies: Eddy[];
  biasMarkers: BiasMarker[];
  biasSpread: number;
  onSelectProfile: (profileId: number, platformId: string) => void;
  /** Handed the camera controls once the viewer exists, so Deep can fly. */
  onReady?: (api: GlobeApi) => void;
}

export interface GlobeApi {
  flyTo: (lat: number, lon: number, heightKm: number) => void;
  resetView: () => void;
  camera: () => { lat: number; lon: number; heightKm: number } | null;
}

export function GlobeView({
  field,
  lut,
  velocity,
  platforms,
  eddies,
  biasMarkers,
  biasSpread,
  onSelectProfile,
  onReady,
}: GlobeViewProps) {
  const containerRef = useRef<HTMLDivElement>(null);
  const overlayRef = useRef<HTMLCanvasElement>(null);
  const viewerRef = useRef<Viewer | null>(null);
  const particlesRef = useRef<ParticleLayer | null>(null);
  const fieldLayerRef = useRef<ImageryLayer | null>(null);
  const entitiesRef = useRef<Entity[]>([]);
  const [ready, setReady] = useState(false);
  const onReadyRef = useRef(onReady);
  useEffect(() => {
    onReadyRef.current = onReady;
  }, [onReady]);

  const {
    depthIndex,
    timeIndex,
    colorScale,
    layers,
    analysisLayer,
    selectedProfileId,
  } = useAppStore();

  const surfaceLayer = layers.find((l) => l.id === "surface");
  const currentsLayer = layers.find((l) => l.id === "currents");
  const showBias = analysisLayer === "bias";
  const showEddies = analysisLayer === "eddies";

  /* ---------------------------------------------------------------------- */
  /* Viewer lifecycle                                                        */
  /* ---------------------------------------------------------------------- */
  useEffect(() => {
    if (!containerRef.current || !overlayRef.current) return;

    let viewer: Viewer;
    try {
      viewer = createViewer(containerRef.current);
    } catch (error) {
      console.error("Cesium failed to initialise", error);
      return;
    }
    viewerRef.current = viewer;

    // Dev-only handle so the viewer can be driven from the console or an
    // automated check. Never attached in a production build.
    if (import.meta.env.DEV) {
      (window as unknown as { __viewer?: Viewer }).__viewer = viewer;
    }

    const particles = new ParticleLayer(viewer, overlayRef.current);
    particlesRef.current = particles;

    const resize = () => {
      const rect = containerRef.current?.getBoundingClientRect();
      // A zero-size measurement happens before first layout (and in a hidden
      // tab); sizing the canvas to it would leave a 1x1 buffer forever.
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
        if (current && !current.isDestroyed()) {
          flyToPoint(current, lat, lon, heightKm * 1000);
        }
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
    });

    return () => {
      observer.disconnect();
      particles.stop();
      particlesRef.current = null;
      viewerRef.current = null;
      fieldLayerRef.current = null;
      entitiesRef.current = [];
      if (!viewer.isDestroyed()) viewer.destroy();
    };
  }, []);

  /* ---------------------------------------------------------------------- */
  /* Field layer — recoloured locally, never re-fetched                      */
  /* ---------------------------------------------------------------------- */
  useEffect(() => {
    const viewer = viewerRef.current;
    if (!viewer || viewer.isDestroyed() || !ready) return;

    // Remove the previous field before adding the new one.
    if (fieldLayerRef.current) {
      viewer.imageryLayers.remove(fieldLayerRef.current, true);
      fieldLayerRef.current = null;
    }

    if (!field || !lut || !surfaceLayer?.enabled) return;

    const time = Math.min(timeIndex, field.nTime - 1);
    const depth = Math.min(depthIndex, field.nDepth - 1);

    // This is the whole point of the quantised volume: changing depth, time or
    // the colour range repaints from memory with no network round trip.
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
        layer.alpha = surfaceLayer.opacity;
        fieldLayerRef.current = layer;
      })
      .catch((error) => console.error("Could not add the field layer", error));

    return () => {
      cancelled = true;
    };
  }, [field, lut, depthIndex, timeIndex, colorScale.vmin, colorScale.vmax, surfaceLayer?.enabled, ready]);

  /* Opacity is a cheap property change, so it gets its own effect. */
  useEffect(() => {
    if (fieldLayerRef.current && surfaceLayer) {
      fieldLayerRef.current.alpha = surfaceLayer.opacity;
    }
  }, [surfaceLayer?.opacity, surfaceLayer]);

  /* ---------------------------------------------------------------------- */
  /* Current streamlines                                                     */
  /* ---------------------------------------------------------------------- */
  const velocityField = useMemo<VelocityField | null>(() => {
    if (!velocity) return null;
    const { u, v } = velocity;
    const time = Math.min(timeIndex, u.nTime - 1);
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
  }, [velocity, timeIndex, depthIndex]);

  useEffect(() => {
    const particles = particlesRef.current;
    if (!particles) return;
    const enabled = currentsLayer?.enabled ?? false;
    particles.setField(enabled ? velocityField : null);
    particles.setOpacity(enabled ? (currentsLayer?.opacity ?? 0.7) : 0);
    if (!enabled) particles.clear();
  }, [velocityField, currentsLayer?.enabled, currentsLayer?.opacity, currentsLayer]);

  /* ---------------------------------------------------------------------- */
  /* Entities: platforms, trajectories, eddies, bias markers                 */
  /* ---------------------------------------------------------------------- */
  useEffect(() => {
    const viewer = viewerRef.current;
    if (!viewer || viewer.isDestroyed() || !ready) return;

    for (const entity of entitiesRef.current) viewer.entities.remove(entity);
    entitiesRef.current = [];

    const added: Entity[] = [];

    if (showBias) {
      // Verification mode: every platform coloured by model-observation bias.
      for (const marker of biasMarkers) {
        const magnitude = Math.abs(marker.bias ?? 0);
        added.push(
          viewer.entities.add({
            id: `bias-${marker.profile_id}`,
            position: Cartesian3.fromDegrees(marker.lon, marker.lat),
            point: {
              pixelSize: 9 + Math.min(9, magnitude * 14),
              color:
                (marker.bias ?? 0) >= 0
                  ? Color.fromCssColorString("#ef4b52")
                  : Color.fromCssColorString("#38bdf8"),
              outlineColor: Color.fromCssColorString("#04080f"),
              outlineWidth: 1.5,
            },
            properties: {
              kind: "bias",
              profileId: marker.profile_id,
              platformId: marker.platform_id,
            },
          }),
        );
      }
    } else {
      for (const platform of platforms) {
        const position = platform.last_position;
        if (!position) continue;

        const track = platform.trajectory ?? [];
        const latest = track.length > 0 ? track[track.length - 1] : null;
        const isSelected =
          latest !== null && latest.profile_id === selectedProfileId;

        // The float's drift path, drawn as a true 3-D polyline.
        if (track.length > 1) {
          added.push(
            viewer.entities.add({
              id: `track-${platform.platform_id}`,
              polyline: {
                positions: track.map((p) => Cartesian3.fromDegrees(p.lon, p.lat, 0)),
                width: isSelected ? 2.6 : 1.3,
                material: platformColor(platform.platform_type).withAlpha(
                  isSelected ? 0.95 : 0.42,
                ),
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
              pixelSize: isSelected ? 15 : 8,
              color: platformColor(platform.platform_type),
              outlineColor: isSelected
                ? Color.fromCssColorString("#ffb951")
                : Color.fromCssColorString("#04080f"),
              outlineWidth: isSelected ? 3 : 1.4,
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

    if (showEddies) {
      for (const eddy of eddies) {
        const isCyclonic = eddy.polarity === "cyclonic";
        added.push(
          viewer.entities.add({
            id: `eddy-${eddy.id}`,
            position: Cartesian3.fromDegrees(eddy.centre.lon, eddy.centre.lat),
            ellipse: {
              semiMajorAxis: eddy.radius_km * 1000,
              semiMinorAxis: eddy.radius_km * 1000,
              material: (isCyclonic
                ? Color.fromCssColorString("#38bdf8")
                : Color.fromCssColorString("#f0a12e")
              ).withAlpha(0.14),
              outline: true,
              outlineColor: isCyclonic
                ? Color.fromCssColorString("#38bdf8")
                : Color.fromCssColorString("#f0a12e"),
              outlineWidth: 1.6,
              height: 0,
            },
          }),
        );
      }
    }

    entitiesRef.current = added;
  }, [platforms, eddies, biasMarkers, biasSpread, showBias, showEddies, selectedProfileId, ready]);

  /* ---------------------------------------------------------------------- */
  /* Picking                                                                 */
  /* ---------------------------------------------------------------------- */
  useEffect(() => {
    const viewer = viewerRef.current;
    if (!viewer || viewer.isDestroyed() || !ready) return;

    const handler = new ScreenSpaceEventHandler(viewer.scene.canvas);
    handler.setInputAction((movement: ScreenSpaceEventHandler.PositionedEvent) => {
      const picked = viewer.scene.pick(movement.position);
      const entity = picked?.id;
      if (!(entity instanceof Entity) || !entity.properties) return;

      const profileId = entity.properties.profileId?.getValue();
      const platformId = entity.properties.platformId?.getValue();
      if (typeof profileId === "number" && typeof platformId === "string") {
        onSelectProfile(profileId, platformId);
      }
    }, ScreenSpaceEventType.LEFT_CLICK);

    return () => handler.destroy();
  }, [onSelectProfile, ready]);

  /* ---------------------------------------------------------------------- */
  /* Toolbar actions                                                         */
  /* ---------------------------------------------------------------------- */
  const zoom = (factor: number) => {
    const viewer = viewerRef.current;
    if (!viewer || viewer.isDestroyed()) return;
    const height = viewer.camera.positionCartographic.height;
    viewer.camera.zoomIn(height * factor);
  };

  const captureScreenshot = () => {
    const viewer = viewerRef.current;
    if (!viewer || viewer.isDestroyed()) return;
    viewer.render();
    const url = viewer.canvas.toDataURL("image/png");
    const anchor = document.createElement("a");
    anchor.href = url;
    anchor.download = `indofos-${Date.now()}.png`;
    anchor.click();
  };

  return (
    <div className="globe">
      <div ref={containerRef} className="globe__cesium" />
      <canvas ref={overlayRef} className="globe__overlay" />

      <div className="globe__tools globe__tools--left">
        <button className="gtool gtool--on" type="button" title="3D globe">
          <GlobeIcon size={16} />
        </button>
        <button className="gtool" type="button" title="2D map">
          <Square size={16} />
        </button>
        <button className="gtool" type="button" title="Columbus view">
          <LayersIcon size={16} />
        </button>
        <button className="gtool" type="button" title="Layer manager">
          <LayersIcon size={16} />
        </button>
        <button className="gtool" type="button" title="Charts">
          <BarChart3 size={16} />
        </button>
        <button className="gtool" type="button" title="Copy shareable link">
          <Link2 size={16} />
        </button>
        <button className="gtool" type="button" title="Screenshot" onClick={captureScreenshot}>
          <Camera size={16} />
        </button>
      </div>

      <div className="globe__tools globe__tools--right">
        <button className="gtool" type="button" title="Search">
          <Search size={16} />
        </button>
        <button
          className="gtool"
          type="button"
          title="Reset view"
          onClick={() => viewerRef.current && flyToDomain(viewerRef.current)}
        >
          <Crosshair size={16} />
        </button>
        <button className="gtool" type="button" title="Zoom in" onClick={() => zoom(0.35)}>
          <Plus size={16} />
        </button>
        <button className="gtool" type="button" title="Zoom out" onClick={() => zoom(-0.55)}>
          <Minus size={16} />
        </button>
      </div>

      <GraticuleLabels />
    </div>
  );
}

/** Static latitude and longitude guides, matching the mockup's framing. */
function GraticuleLabels() {
  const lats = [25, 15, 5, -5, -15, -25];
  const lons = [65, 75, 85, 95, 105];

  return (
    <>
      <div className="globe__lats mono" aria-hidden>
        {lats.map((lat) => (
          <span key={lat}>
            {Math.abs(lat)}°{lat >= 0 ? "N" : "S"}
          </span>
        ))}
      </div>
      <div className="globe__lons mono" aria-hidden>
        {lons.map((lon) => (
          <span key={lon}>{lon}°E</span>
        ))}
      </div>
    </>
  );
}

export { DOMAIN, flyToPoint, ImageMaterialProperty };
