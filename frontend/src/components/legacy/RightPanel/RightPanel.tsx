import React from 'react';

const RightPanel = () => {
  return (
    <div className="flex" style={{ flexDirection: 'column', height: '100%', padding: '24px 16px' }}>
      <div className="flex items-center justify-between" style={{ marginBottom: 24 }}>
        <h2 className="label" style={{ margin: 0 }}>PROFILE / FLOAT ID: 2902346</h2>
        <button>&times;</button>
      </div>

      <div className="flex justify-between" style={{ fontSize: 'var(--fs-xs)', marginBottom: 16 }}>
        <div>
          <div className="label">LOCATION</div>
          <div className="mono">12.85° N, 80.33° E</div>
          <div className="label" style={{ marginTop: 8 }}>DEPTH</div>
          <div className="mono">0 - 2000 m</div>
        </div>
        <div style={{ textAlign: 'right' }}>
          <div className="label">TIME</div>
          <div className="mono">15 Mar 2024, 12:00 UTC</div>
        </div>
      </div>

      <div style={{ height: 200, background: 'var(--bg-raised)', border: '1px solid var(--border)', borderRadius: 'var(--r-md)', marginBottom: 16, display: 'flex', alignItems: 'center', justifyContent: 'center' }}>
        <span style={{ color: 'var(--text-muted)' }}>[Chart Placeholder]</span>
      </div>

      <div className="flex justify-between" style={{ fontSize: 'var(--fs-sm)', borderBottom: '1px solid var(--border)', paddingBottom: 16, marginBottom: 16 }}>
        <div>
          <div className="label">Bias</div>
          <div className="mono">-0.18 °C</div>
        </div>
        <div>
          <div className="label">RMSD</div>
          <div className="mono">0.62 °C</div>
        </div>
        <div>
          <div className="label">MAE</div>
          <div className="mono">0.48 °C</div>
        </div>
      </div>
      
      <div className="flex justify-between" style={{ fontSize: 'var(--fs-sm)', marginBottom: 24 }}>
        <div>
          <div className="label">Correlation (r)</div>
          <div className="mono">0.97</div>
        </div>
        <div style={{ textAlign: 'right' }}>
          <div className="label">Max |Diff|</div>
          <div className="mono">2.31 °C<br/>@ 156 m</div>
        </div>
      </div>

      <div>
        <div className="flex justify-between items-center" style={{ marginBottom: 16 }}>
          <h3 className="label" style={{ margin: 0 }}>ACTIVE ALERTS</h3>
          <span style={{ fontSize: 'var(--fs-xs)', color: 'var(--cyan)' }}>View all</span>
        </div>
        <div style={{ display: 'flex', flexDirection: 'column', gap: 8 }}>
          <div className="flex items-center gap-3" style={{ background: 'var(--bg-raised)', padding: 12, borderRadius: 'var(--r-md)', border: '1px solid var(--border)' }}>
            <div style={{ background: 'var(--danger-bg)', color: 'var(--danger)', padding: 8, borderRadius: '50%' }}>🌀</div>
            <div style={{ flex: 1 }}>
              <div style={{ fontSize: 'var(--fs-sm)', fontWeight: 500 }}>Cyclone Cold Wake</div>
              <div style={{ fontSize: 'var(--fs-xs)', color: 'var(--text-muted)' }}>Bay of Bengal</div>
            </div>
            <span style={{ fontSize: 'var(--fs-xs)', color: 'var(--danger)', fontWeight: 600 }}>High</span>
          </div>
          
          <div className="flex items-center gap-3" style={{ background: 'var(--bg-raised)', padding: 12, borderRadius: 'var(--r-md)', border: '1px solid var(--border)' }}>
            <div style={{ background: 'var(--warn-bg)', color: 'var(--warn)', padding: 8, borderRadius: '50%' }}>🌊</div>
            <div style={{ flex: 1 }}>
              <div style={{ fontSize: 'var(--fs-sm)', fontWeight: 500 }}>Marine Heatwave</div>
              <div style={{ fontSize: 'var(--fs-xs)', color: 'var(--text-muted)' }}>Arabian Sea (68.5°E, 14.5°N)</div>
            </div>
            <span style={{ fontSize: 'var(--fs-xs)', color: 'var(--warn)', fontWeight: 600 }}>Moderate</span>
          </div>

          <div className="flex items-center gap-3" style={{ background: 'var(--bg-raised)', padding: 12, borderRadius: 'var(--r-md)', border: '1px solid var(--border)' }}>
            <div style={{ background: 'var(--warn-bg)', color: 'var(--warn)', padding: 8, borderRadius: '50%' }}>⬆️</div>
            <div style={{ flex: 1 }}>
              <div style={{ fontSize: 'var(--fs-sm)', fontWeight: 500 }}>Upwelling Event</div>
              <div style={{ fontSize: 'var(--fs-xs)', color: 'var(--text-muted)' }}>Somali Coast</div>
            </div>
            <span style={{ fontSize: 'var(--fs-xs)', color: 'var(--warn)', fontWeight: 600 }}>Moderate</span>
          </div>
        </div>
      </div>

    </div>
  );
};

export default RightPanel;
