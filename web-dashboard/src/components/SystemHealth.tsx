import { Wifi, WifiOff } from 'lucide-react';
import type { SystemHealth as SystemHealthT } from '../lib/types';
import StatusBadge from './StatusBadge';
import './SystemHealth.css';

function latencyStatus(ms: number) {
  if (ms > 150) return 'critical' as const;
  if (ms > 60) return 'caution' as const;
  return 'healthy' as const;
}

export default function SystemHealth({ system }: { system: SystemHealthT }) {
  return (
    <div className="panel system-panel">
      <div className="sys-row">
        <div className="sys-cell">
          {system.mt5Connected ? <Wifi size={14} className="pos" /> : <WifiOff size={14} className="alarm" />}
          <span className="label">MT5</span>
          <StatusBadge status={system.mt5Connected ? 'healthy' : 'critical'} text={system.mt5Connected ? 'CONNECTED' : 'DISCONNECTED'} />
        </div>
        <div className="sys-cell">
          <span className="label">Latency</span>
          <StatusBadge status={latencyStatus(system.latencyMs)} text={`${system.latencyMs.toFixed(0)}ms`} />
        </div>
        <div className="sys-cell">
          <span className="label">VPS CPU</span>
          <span className="mono">{system.vpsCpuPct.toFixed(0)}%</span>
        </div>
        <div className="sys-cell">
          <span className="label">VPS Mem</span>
          <span className="mono">{system.vpsMemPct.toFixed(0)}%</span>
        </div>
      </div>
      <div className="sys-log">
        {system.executionLog.map((e, i) => (
          <div key={i} className={`sys-log-line sys-log-${e.level}`}>
            <span className="mono ink-dim sys-log-time">{new Date(e.t).toLocaleTimeString()}</span>
            <span>{e.msg}</span>
          </div>
        ))}
      </div>
    </div>
  );
}
