import React from 'react';
import { Play, SkipBack } from 'lucide-react';

const BottomTimeline = () => {
  return (
    <div className="flex items-center gap-4" style={{ width: '100%', background: 'rgba(10, 20, 32, 0.85)', backdropFilter: 'blur(12px)', padding: '12px 24px', borderRadius: 'var(--r-xl)', border: '1px solid var(--border)' }}>
      <button style={{ width: 40, height: 40, borderRadius: '50%', background: 'var(--amber-glow)', color: 'var(--amber)', display: 'flex', alignItems: 'center', justifyContent: 'center', border: '1px solid var(--amber)' }}>
        <Play fill="currentColor" size={20} style={{ marginLeft: 4 }} />
      </button>
      <button style={{ color: 'var(--text-secondary)' }}>
        <SkipBack size={20} />
      </button>
      
      <div style={{ flex: 1, display: 'flex', flexDirection: 'column', padding: '0 16px' }}>
        <div className="flex justify-between" style={{ fontSize: 'var(--fs-xs)', color: 'var(--text-secondary)', marginBottom: 8 }}>
          <span>01 Mar 2024</span>
          <span>15 Mar 2024</span>
        </div>
        <div style={{ position: 'relative', height: 4, background: 'var(--border)', borderRadius: 'var(--r-pill)' }}>
          <div style={{ position: 'absolute', left: 0, right: '10%', height: '100%', background: 'var(--cyan)', borderRadius: 'var(--r-pill)' }} />
          <div style={{ position: 'absolute', right: '10%', top: '50%', transform: 'translate(50%, -50%)', width: 12, height: 12, borderRadius: '50%', background: 'var(--cyan)', border: '2px solid var(--bg-panel)' }} />
        </div>
      </div>
      
      <div style={{ background: 'var(--bg-raised)', padding: '6px 12px', borderRadius: 'var(--r-md)', border: '1px solid var(--border)' }}>
        <span style={{ fontSize: 'var(--fs-sm)' }}>1x v</span>
      </div>
    </div>
  );
};

export default BottomTimeline;
