import { AlertTriangle, CheckCircle2, OctagonAlert } from 'lucide-react';
import type { Status } from '../lib/types';
import './StatusBadge.css';

const CONFIG: Record<Status, { icon: typeof CheckCircle2; label: string; cls: string }> = {
  healthy: { icon: CheckCircle2, label: 'OK', cls: 'st-healthy' },
  caution: { icon: AlertTriangle, label: 'CAUTION', cls: 'st-caution' },
  critical: { icon: OctagonAlert, label: 'CRITICAL', cls: 'st-critical' },
};

export default function StatusBadge({ status, text }: { status: Status; text?: string }) {
  const { icon: Icon, label, cls } = CONFIG[status];
  return (
    <span className={`status-badge ${cls}`}>
      <Icon size={11} strokeWidth={2.5} />
      {text ?? label}
    </span>
  );
}
