import React from 'react';
import { Bell, Settings, User } from 'lucide-react';

const Header = () => {
  return (
    <div className="flex items-center justify-between" style={{ width: '100%' }}>
      <div className="flex items-center gap-4">
        {/* Logo Placeholder */}
        <div style={{ width: 40, height: 40, borderRadius: '50%', background: 'var(--amber)' }} />
        <div>
          <h1 style={{ fontSize: 'var(--fs-lg)', margin: 0, fontWeight: 600 }}>INDO-FOS</h1>
          <div style={{ fontSize: 'var(--fs-xs)', color: 'var(--text-muted)' }}>
            Indian Ocean Forecasting & Observing System
          </div>
        </div>
      </div>

      <div className="flex items-center gap-4">
        <div className="flex items-center gap-2" style={{ background: 'var(--bg-raised)', padding: '6px 12px', borderRadius: 'var(--r-pill)', border: '1px solid var(--border)' }}>
          <div style={{ width: 8, height: 8, borderRadius: '50%', background: 'var(--cyan)' }} />
          <span className="label" style={{ color: 'var(--cyan)' }}>REAL-TIME MODE</span>
          <span style={{ fontSize: 'var(--fs-sm)', color: 'var(--text-secondary)' }}>15 Mar 2024, 12:00 UTC</span>
        </div>
      </div>

      <div className="flex items-center gap-3">
        <button className="flex items-center gap-2" style={{ background: 'var(--bg-raised)', padding: '6px 12px', borderRadius: 'var(--r-pill)', border: '1px solid var(--border)' }}>
          <Bell size={16} color="var(--amber)" />
          <span style={{ fontSize: 'var(--fs-sm)' }}>Alerts <span style={{ background: 'var(--amber)', color: 'var(--bg-void)', padding: '2px 6px', borderRadius: 'var(--r-pill)', fontWeight: 'bold' }}>3</span></span>
        </button>
        <button className="flex items-center gap-2" style={{ background: 'var(--bg-raised)', padding: '6px 12px', borderRadius: 'var(--r-pill)', border: '1px solid var(--border)' }}>
          <span style={{ fontSize: 'var(--fs-sm)' }}>Analysis</span>
        </button>
        <button style={{ padding: 8, borderRadius: '50%', background: 'var(--bg-raised)', border: '1px solid var(--border)' }}>
          <Bell size={16} />
        </button>
        <button style={{ padding: 8, borderRadius: '50%', background: 'var(--bg-raised)', border: '1px solid var(--border)' }}>
          <Settings size={16} />
        </button>
        <div className="flex items-center gap-2">
          <span>EN</span>
        </div>
        <div style={{ width: 32, height: 32, borderRadius: '50%', background: 'var(--border)' }}>
          <User size={20} style={{ margin: 6 }} />
        </div>
      </div>
    </div>
  );
};

export default Header;
