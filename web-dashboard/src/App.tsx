import { useMockFeed } from './lib/mockFeed';
import MarketStrip from './components/MarketStrip';
import AccountHealth from './components/AccountHealth';
import PositionsTable from './components/PositionsTable';
import RiskLayer from './components/RiskLayer';
import ModelState from './components/ModelState';
import SystemHealth from './components/SystemHealth';
import KillSwitch from './components/KillSwitch';
import './App.css';

function App() {
  const feed = useMockFeed();

  const handleFlatten = () => {
    // Wire to POST /api/execution/flatten-all — see data-binding notes.
    console.warn('Emergency flatten requested (mock — not wired to MT5).');
  };

  return (
    <div className="terminal">
      <header className="terminal-header">
        <div className="terminal-brand">
          <span className="terminal-logo">THOR</span>
          <span className="label">EURUSD · GBPUSD · USDJPY · XAUUSD — H4</span>
        </div>
        <KillSwitch breaker={feed.risk.circuitBreaker} onFlatten={handleFlatten} />
      </header>

      <div className="terminal-grid">
        <div className="area-market">
          <MarketStrip prices={feed.prices} barCloseAt={feed.barCloseAt} now={feed.now} />
        </div>
        <div className="area-account">
          <AccountHealth account={feed.account} />
        </div>
        <div className="area-positions">
          <PositionsTable positions={feed.positions} />
        </div>
        <div className="area-risk">
          <RiskLayer risk={feed.risk} />
        </div>
        <div className="area-model">
          <ModelState signals={feed.signals} />
        </div>
        <div className="area-system">
          <SystemHealth system={feed.system} />
        </div>
      </div>
    </div>
  );
}

export default App;
