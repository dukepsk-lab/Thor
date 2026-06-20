import { useMockFeed, type MockFeedState } from './lib/mockFeed';
import { useLiveFeed } from './lib/liveFeed';
import MarketStrip from './components/MarketStrip';
import AccountHealth from './components/AccountHealth';
import PositionsTable from './components/PositionsTable';
import RiskLayer from './components/RiskLayer';
import ModelState from './components/ModelState';
import SystemHealth from './components/SystemHealth';
import KillSwitch from './components/KillSwitch';
import './App.css';

// Append ?mock=1 to the URL to fall back to the simulated data engine
// (useful when no MT5-connected backend is reachable).
const USE_MOCK = new URLSearchParams(window.location.search).get('mock') === '1';

const API_BASE = import.meta.env.VITE_API_BASE ?? '';

function MockTerminal() {
  return <Terminal feed={useMockFeed()} />;
}

function LiveTerminal() {
  return <Terminal feed={useLiveFeed()} />;
}

function Terminal({ feed }: { feed: MockFeedState }) {
  const handleFlatten = async () => {
    try {
      const res = await fetch(`${API_BASE}/api/execution/flatten-all`, { method: 'POST' });
      const data = await res.json();
      console.warn('Emergency flatten requested:', data);
    } catch (err) {
      console.error('Flatten request failed:', err);
    }
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

function App() {
  return USE_MOCK ? <MockTerminal /> : <LiveTerminal />;
}

export default App;
