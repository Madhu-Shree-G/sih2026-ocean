import React from 'react';
import { Globe, Crosshair, Activity, Database, FileText, Settings } from 'lucide-react';

const BottomNav = () => {
  const navItems = [
    { label: 'OVERVIEW', icon: <Globe size={18} />, active: true },
    { label: 'OBSERVATIONS', icon: <Crosshair size={18} /> },
    { label: 'ANALYSIS', icon: <Activity size={18} /> },
    { label: 'DATA & SERVICES', icon: <Database size={18} /> },
    { label: 'REPORTS', icon: <FileText size={18} /> },
    { label: 'SETTINGS', icon: <Settings size={18} /> },
  ];

  return (
    <>
      <div className="flex gap-2">
        {navItems.map((item, i) => (
          <button key={i} className="flex items-center gap-2" style={{ 
            padding: '12px 24px', 
            borderRadius: 'var(--r-md)',
            background: item.active ? 'var(--bg-active)' : 'transparent',
            color: item.active ? 'var(--cyan)' : 'var(--text-secondary)',
            border: item.active ? '1px solid var(--border-focus)' : '1px solid transparent'
          }}>
            {item.icon}
            <span className="label" style={{ color: 'inherit' }}>{item.label}</span>
          </button>
        ))}
      </div>
      <div className="flex items-center gap-3">
        {/* Ministry of Earth Sciences Logo Placeholder */}
        <div style={{ width: 32, height: 32, background: 'var(--text-secondary)', borderRadius: '50%' }}></div>
        <div>
          <div style={{ fontSize: 'var(--fs-sm)', fontWeight: 500, color: 'var(--text-secondary)' }}>Ministry of Earth Sciences</div>
          <div style={{ fontSize: 'var(--fs-xs)', color: 'var(--text-muted)' }}>Government of India</div>
        </div>
      </div>
    </>
  );
};

export default BottomNav;
