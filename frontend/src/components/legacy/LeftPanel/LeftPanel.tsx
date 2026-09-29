import React from 'react';

const LeftPanel = () => {
  return (
    <div className="flex" style={{ flexDirection: 'column', height: '100%', padding: '24px 16px' }}>
      <div className="flex items-center justify-between" style={{ marginBottom: 24 }}>
        <h2 className="label" style={{ margin: 0 }}>LAYERS</h2>
        <button>&lt;&lt;</button>
      </div>

      <div style={{ marginBottom: 16 }}>
        <h3 className="label" style={{ marginBottom: 8 }}>VARIABLE</h3>
        {/* Placeholder for variable selector dropdown */}
        <div style={{ background: 'var(--bg-raised)', padding: '12px', borderRadius: 'var(--r-md)', border: '1px solid var(--border)', display: 'flex', justifyContent: 'space-between' }}>
          <span style={{ fontSize: 'var(--fs-sm)' }}>🌡️ Temperature (°C)</span>
          <span>v</span>
        </div>
      </div>

      <div className="scroll" style={{ flex: 1, display: 'flex', flexDirection: 'column', gap: '16px' }}>
        {/* Layer Item Placeholders */}
        {[
          { name: 'Surface Temp.', value: 100, active: true },
          { name: 'Currents', value: 70, active: true },
          { name: 'Chlorophyll', value: 50, active: false },
          { name: 'Sea Surface Height', value: 60, active: false },
          { name: 'Salinity', value: 50, active: false },
          { name: 'Bathymetry', value: 80, active: true }
        ].map((layer, i) => (
          <div key={i} style={{ display: 'flex', flexDirection: 'column', gap: 8 }}>
            <div className="flex items-center justify-between">
              <label className="flex items-center gap-2" style={{ fontSize: 'var(--fs-sm)', color: layer.active ? 'var(--text-primary)' : 'var(--text-muted)' }}>
                <input type="checkbox" checked={layer.active} readOnly />
                {layer.name}
              </label>
              <span>...</span>
            </div>
            <div className="flex items-center gap-2">
              <input type="range" min="0" max="100" value={layer.value} readOnly style={{ flex: 1 }} />
              <span className="mono" style={{ fontSize: 'var(--fs-xs)', color: 'var(--text-secondary)' }}>{layer.value}%</span>
            </div>
          </div>
        ))}
      </div>

      <div style={{ marginTop: 24, display: 'flex', flexDirection: 'column', gap: 16 }}>
        <div>
          <div className="flex justify-between items-center" style={{ marginBottom: 8 }}>
            <span className="label">DEPTH SLICE</span>
            <span className="mono" style={{ fontSize: 'var(--fs-sm)' }}>125 m</span>
          </div>
          <input type="range" min="0" max="2000" defaultValue="125" />
          <div className="flex justify-between" style={{ fontSize: 'var(--fs-micro)', color: 'var(--text-faint)', marginTop: 4 }}>
            <span>0 m</span><span>500 m</span><span>1000 m</span><span>1500 m</span><span>2000 m</span>
          </div>
        </div>
        
        <div>
          <div className="flex justify-between items-center" style={{ marginBottom: 8 }}>
            <span className="label">VERTICAL EXAGGERATION</span>
            <span className="mono" style={{ fontSize: 'var(--fs-sm)' }}>20x</span>
          </div>
          <input type="range" min="1" max="50" defaultValue="20" />
          <div className="flex justify-between" style={{ fontSize: 'var(--fs-micro)', color: 'var(--text-faint)', marginTop: 4 }}>
            <span>1x</span><span>10x</span><span>20x</span><span>30x</span><span>50x</span>
          </div>
        </div>
      </div>
    </div>
  );
};

export default LeftPanel;
