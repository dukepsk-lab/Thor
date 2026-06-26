import { useState, useEffect } from 'react'
import { LineChart, Line, XAxis, YAxis, CartesianGrid, Tooltip, ResponsiveContainer } from 'recharts'
import './index.css'

interface SymbolConfig {
  risk_per_trade: number;
  confidence_threshold: number;
  tp_multiplier: number;
  sl_multiplier: number;
}

interface MultiConfig {
  configs: Record<string, SymbolConfig>;
}

const initialConfig: MultiConfig = {
  configs: {}
};

function App() {
  const [mainTab, setMainTab] = useState<"LIVE" | "CONFIG">("LIVE");

  const [activeTab, setActiveTab] = useState<string>("");
  const [multiConfig, setMultiConfig] = useState<MultiConfig>(initialConfig);
  const [combinedData, setCombinedData] = useState<any[]>([]);
  const [individualData, setIndividualData] = useState<Record<string, any[]>>({});
  const [stats, setStats] = useState<any>({});
  const [loading, setLoading] = useState(false);

  const [liveAccount, setLiveAccount] = useState<any>(null);
  const [livePositions, setLivePositions] = useState<any[]>([]);
  const [liveHistory, setLiveHistory] = useState<any[]>([]);

  useEffect(() => {
    fetchConfig();
    fetchStats();
    fetchLiveData();
    const interval = setInterval(fetchLiveData, 5000);
    return () => clearInterval(interval);
  }, []);

  useEffect(() => {
    if (Object.keys(multiConfig.configs).length > 0) {
      generateForecast();
    }
  }, [multiConfig]);

  const fetchConfig = async () => {
    try {
      const res = await fetch('/api/config');
      const data = await res.json();
      if(data.configs) {
        setMultiConfig(data);
        if(Object.keys(data.configs).length > 0) {
            setActiveTab(Object.keys(data.configs)[0]);
        }
      }
    } catch (e) {
      console.error(e);
    }
  };

  const fetchStats = async () => {
    try {
      const res = await fetch('/api/stats');
      const data = await res.json();
      setStats(data);
    } catch (e) {
      console.error(e);
    }
  };

  const fetchLiveData = async () => {
    try {
      const [accRes, posRes, histRes] = await Promise.all([
        fetch('/api/live/account'),
        fetch('/api/live/positions'),
        fetch('/api/live/history')
      ]);
      setLiveAccount(await accRes.json());
      setLivePositions(await posRes.json());
      setLiveHistory(await histRes.json());
    } catch (e) {
      console.error("Live data fetch error", e);
    }
  };

  const generateForecast = async () => {
    try {
      const res = await fetch('/api/forecast', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify(multiConfig)
      });
      const data = await res.json();
      setCombinedData(data.combined || []);
      setIndividualData(data.individuals || {});
    } catch (e) {
      console.error(e);
    }
  };

  const handleConfigChange = (param: keyof SymbolConfig, value: number) => {
    setMultiConfig(prev => ({
      configs: {
        ...prev.configs,
        [activeTab]: {
          ...prev.configs[activeTab],
          [param]: value
        }
      }
    }));
  };

  const handleSave = async () => {
    setLoading(true);
    try {
      await fetch('/api/config', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify(multiConfig)
      });
      alert('Portfolio configurations saved to live bot!');
    } catch (e) {
      console.error(e);
    }
    setLoading(false);
  };

  const CustomTooltip = ({ active, payload, label }: any) => {
    if (active && payload && payload.length) {
      return (
        <div style={{ backgroundColor: '#1e293b', padding: '10px', border: '1px solid #3b82f6', borderRadius: '5px' }}>
          <p style={{ margin: 0, color: '#94a3b8' }}>{label}</p>
          <p style={{ margin: 0, color: '#10b981', fontWeight: 'bold' }}>
            ${payload[0].value.toLocaleString()}
          </p>
        </div>
      );
    }
    return null;
  };

  const renderLiveMonitor = () => {
    if (!liveAccount) return <div className="loading">Loading Live Data...</div>;
    if (liveAccount.error) return <div className="loading">MT5 Not Connected: {liveAccount.error}</div>;

    return (
      <div className="live-monitor">
        <div className="kpi-grid">
          <div className="kpi-card">
            <div className="kpi-title">Account Balance</div>
            <div className="kpi-value">${liveAccount.balance?.toLocaleString(undefined, {minimumFractionDigits: 2})}</div>
          </div>
          <div className="kpi-card">
            <div className="kpi-title">Account Equity</div>
            <div className="kpi-value">${liveAccount.equity?.toLocaleString(undefined, {minimumFractionDigits: 2})}</div>
          </div>
          <div className="kpi-card">
            <div className="kpi-title">Margin Level</div>
            <div className="kpi-value">{liveAccount.margin_level?.toFixed(2)}%</div>
          </div>
          <div className="kpi-card">
            <div className="kpi-title">Floating PnL</div>
            <div className={`kpi-value ${liveAccount.profit >= 0 ? 'positive' : 'negative'}`}>
              {liveAccount.profit >= 0 ? '+' : ''}${liveAccount.profit?.toFixed(2)}
            </div>
          </div>
        </div>

        <div className="panel main-chart" style={{ marginTop: '20px' }}>
          <h2>Realized Equity Curve (30 Days)</h2>
          <ResponsiveContainer width="100%" height={300}>
            <LineChart data={liveHistory}>
              <CartesianGrid strokeDasharray="3 3" stroke="#1e293b" />
              <XAxis dataKey="date" stroke="#94a3b8" tick={{fontSize: 12}} />
              <YAxis domain={['auto', 'auto']} stroke="#94a3b8" tick={{fontSize: 12}} />
              <Tooltip content={<CustomTooltip />} />
              <Line type="stepAfter" dataKey="pnl" stroke="#3b82f6" strokeWidth={3} dot={true} />
            </LineChart>
          </ResponsiveContainer>
        </div>

        <div className="panel" style={{ marginTop: '20px' }}>
          <h2>Active Positions</h2>
          <div className="table-container">
            <table className="positions-table">
              <thead>
                <tr>
                  <th>Ticket</th>
                  <th>Symbol</th>
                  <th>Type</th>
                  <th>Volume</th>
                  <th>Open Price</th>
                  <th>Current Price</th>
                  <th>SL</th>
                  <th>TP</th>
                  <th>Floating PnL</th>
                </tr>
              </thead>
              <tbody>
                {livePositions.length === 0 ? (
                  <tr><td colSpan={9} style={{textAlign: 'center', padding: '20px', color: '#94a3b8'}}>No active positions</td></tr>
                ) : (
                  livePositions.map(pos => (
                    <tr key={pos.ticket}>
                      <td>{pos.ticket}</td>
                      <td><strong>{pos.symbol}</strong></td>
                      <td className={pos.type === 'BUY' ? 'positive' : 'negative'}>{pos.type}</td>
                      <td>{pos.volume}</td>
                      <td>{pos.open_price}</td>
                      <td>{pos.current_price}</td>
                      <td>{pos.sl}</td>
                      <td>{pos.tp}</td>
                      <td className={pos.profit >= 0 ? 'positive' : 'negative'}>
                        {pos.profit >= 0 ? '+' : ''}${pos.profit.toFixed(2)}
                      </td>
                    </tr>
                  ))
                )}
              </tbody>
            </table>
          </div>
        </div>
      </div>
    );
  };

  const renderConfiguration = () => {
    const symbols = Object.keys(multiConfig.configs);
    const currentCfg = multiConfig.configs[activeTab] || { risk_per_trade: 0.01, confidence_threshold: 0.6, tp_multiplier: 2, sl_multiplier: 1.5 };

    return (
      <div className="main-grid">
        {/* Left Panel: Controls */}
        <div className="panel">
          <h2>Asset Configuration</h2>
          
          <div className="tabs">
            {symbols.map(sym => (
              <button 
                key={sym} 
                className={`tab ${activeTab === sym ? 'active' : ''}`}
                onClick={() => setActiveTab(sym)}
              >
                {sym}
              </button>
            ))}
          </div>

          <div className="control-group">
            <div className="control-header">
              <span className="control-label">Risk Per Trade</span>
              <span className="control-value">{(currentCfg.risk_per_trade * 100).toFixed(1)}%</span>
            </div>
            <input 
              type="range" min="0.005" max="0.05" step="0.005" 
              value={currentCfg.risk_per_trade}
              onChange={(e) => handleConfigChange('risk_per_trade', parseFloat(e.target.value))}
            />
          </div>

          <div className="control-group">
            <div className="control-header">
              <span className="control-label">Meta-Confidence Threshold</span>
              <span className="control-value">{(currentCfg.confidence_threshold * 100).toFixed(1)}%</span>
            </div>
            <input 
              type="range" min="0.5" max="0.8" step="0.01" 
              value={currentCfg.confidence_threshold}
              onChange={(e) => handleConfigChange('confidence_threshold', parseFloat(e.target.value))}
            />
          </div>

          <div className="control-group">
            <div className="control-header">
              <span className="control-label">Take Profit (ATR)</span>
              <span className="control-value">{currentCfg.tp_multiplier.toFixed(1)}x</span>
            </div>
            <input 
              type="range" min="1" max="5" step="0.1" 
              value={currentCfg.tp_multiplier}
              onChange={(e) => handleConfigChange('tp_multiplier', parseFloat(e.target.value))}
            />
          </div>

          <div className="control-group">
            <div className="control-header">
              <span className="control-label">Stop Loss (ATR)</span>
              <span className="control-value">{currentCfg.sl_multiplier.toFixed(1)}x</span>
            </div>
            <input 
              type="range" min="0.5" max="3" step="0.1" 
              value={currentCfg.sl_multiplier}
              onChange={(e) => handleConfigChange('sl_multiplier', parseFloat(e.target.value))}
            />
          </div>

          <button className="save-btn" onClick={handleSave} disabled={loading}>
            {loading ? "Saving..." : "Deploy Portfolio Settings"}
          </button>
        </div>

        {/* Center Panel: Charts */}
        <div className="chart-container">
          <div className="panel main-chart">
            <h2>Combined Portfolio Equity Forecast (1 Year)</h2>
            <ResponsiveContainer width="100%" height="100%">
              <LineChart data={combinedData}>
                <CartesianGrid strokeDasharray="3 3" stroke="#1e293b" />
                <XAxis dataKey="date" stroke="#94a3b8" tick={{fontSize: 12}} minTickGap={30} />
                <YAxis domain={['auto', 'auto']} stroke="#94a3b8" tick={{fontSize: 12}} />
                <Tooltip content={<CustomTooltip />} />
                <Line type="monotone" dataKey="equity" stroke="#10b981" strokeWidth={3} dot={false} />
              </LineChart>
            </ResponsiveContainer>
          </div>
          
          <div className="sparklines-grid">
            {symbols.map(sym => (
              <div className="sparkline-box" key={sym}>
                <div className="sparkline-title">{sym} Component</div>
                <div className="sparkline-chart">
                  <ResponsiveContainer width="100%" height="100%">
                    <LineChart data={individualData[sym] || []}>
                      <YAxis domain={['auto', 'auto']} hide />
                      <Line type="monotone" dataKey="equity" stroke="#3b82f6" strokeWidth={2} dot={false} />
                    </LineChart>
                  </ResponsiveContainer>
                </div>
              </div>
            ))}
          </div>
        </div>

        {/* Right Panel: Stats */}
        <div className="panel">
          <h2>Portfolio Stats</h2>
          <div className="stat-box">
            <div className="stat-label">Projected Annual Return</div>
            <div className="stat-value positive">{stats.annual_return}</div>
          </div>
          <div className="stat-box">
            <div className="stat-label">Max Drawdown</div>
            <div className="stat-value negative">{stats.max_drawdown}</div>
          </div>
          <div className="stat-box">
            <div className="stat-label">Sharpe Ratio</div>
            <div className="stat-value">{stats.sharpe_ratio}</div>
          </div>
          <div className="stat-box">
            <div className="stat-label">Aggregated Win Rate</div>
            <div className="stat-value">{stats.win_rate}</div>
          </div>
          <div className="stat-box">
            <div className="stat-label">Total Simulated Trades</div>
            <div className="stat-value" style={{color: '#e2e8f0'}}>{stats.total_trades}</div>
          </div>
        </div>
      </div>
    );
  };

  return (
    <div className="dashboard-container">
      <header className="dash-header">
        <div style={{ display: 'flex', alignItems: 'center', gap: '20px' }}>
            <h1>Thor ML Framework <span className="badge">LIVE</span></h1>
            <div className="main-tabs">
                <button 
                    className={`main-tab ${mainTab === 'LIVE' ? 'active' : ''}`}
                    onClick={() => setMainTab('LIVE')}
                >
                    📊 Live Monitor
                </button>
                <button 
                    className={`main-tab ${mainTab === 'CONFIG' ? 'active' : ''}`}
                    onClick={() => setMainTab('CONFIG')}
                >
                    ⚙️ Configuration
                </button>
            </div>
        </div>
        <div style={{ color: '#94a3b8', fontSize: '14px' }}>
            Next AI Evaluation: 03:45:00
        </div>
      </header>

      {mainTab === 'LIVE' ? renderLiveMonitor() : renderConfiguration()}
    </div>
  )
}

export default App
