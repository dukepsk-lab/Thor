import { useState } from 'react';
import { Power } from 'lucide-react';
import type { RiskState } from '../lib/types';
import './KillSwitch.css';

export default function KillSwitch({
  breaker,
  onFlatten,
}: {
  breaker: RiskState['circuitBreaker'];
  onFlatten: () => void;
}) {
  const [confirming, setConfirming] = useState(false);
  const tripped = breaker.status === 'TRIGGERED';

  const handleClick = () => {
    if (!confirming) {
      setConfirming(true);
      setTimeout(() => setConfirming(false), 3000);
      return;
    }
    setConfirming(false);
    onFlatten();
  };

  return (
    <button
      className={`kill-switch ${tripped ? 'kill-switch-tripped' : ''} ${confirming ? 'kill-switch-confirm' : ''}`}
      onClick={handleClick}
      aria-label="Emergency flatten all positions"
    >
      <Power size={14} strokeWidth={2.5} />
      {confirming ? 'CONFIRM FLATTEN ALL' : tripped ? 'BREAKER TRIPPED' : 'FLATTEN ALL'}
    </button>
  );
}
