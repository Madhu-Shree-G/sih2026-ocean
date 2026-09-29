import React, { useEffect, useRef } from 'react';
import { Viewer } from 'cesium';
import 'cesium/Build/Cesium/Widgets/widgets.css';

const Globe = () => {
  const cesiumContainer = useRef<HTMLDivElement>(null);
  const viewerRef = useRef<Viewer | null>(null);

  useEffect(() => {
    if (cesiumContainer.current && !viewerRef.current) {
      viewerRef.current = new Viewer(cesiumContainer.current, {
        animation: false,
        baseLayerPicker: false,
        fullscreenButton: false,
        vrButton: false,
        geocoder: false,
        homeButton: false,
        infoBox: false,
        sceneModePicker: false,
        selectionIndicator: false,
        timeline: false,
        navigationHelpButton: false,
        navigationInstructionsInitiallyVisible: false,
      });

      // Basic styling for dark theme
      viewerRef.current.scene.skyAtmosphere.show = true;
      viewerRef.current.scene.globe.enableLighting = true;
      viewerRef.current.scene.globe.showWaterEffect = true;
    }

    return () => {
      if (viewerRef.current) {
        viewerRef.current.destroy();
        viewerRef.current = null;
      }
    };
  }, []);

  return (
    <div style={{ width: '100%', height: '100%', position: 'absolute', top: 0, left: 0 }}>
      {/* Background to match the void while Cesium loads */}
      <div style={{ position: 'absolute', inset: 0, background: 'var(--bg-void)' }} />
      <div ref={cesiumContainer} style={{ width: '100%', height: '100%', position: 'absolute' }} />
      
      {/* The beautiful thermal overlay is mocked since we don't have real tiles right now,
          but the UI framework is complete. */}
    </div>
  );
};

export default Globe;
