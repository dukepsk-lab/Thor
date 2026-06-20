import pandas as pd
import numpy as np

def calculate_drawdown(returns: pd.Series) -> pd.Series:
    """Calculate drawdown series."""
    cum_returns = (1 + returns).cumprod()
    rolling_max = cum_returns.cummax()
    drawdown = (cum_returns - rolling_max) / rolling_max
    return drawdown

def evaluate_strategy(signals: pd.Series, returns: pd.Series, spread_bps: float = 1.0, comm_bps: float = 0.5) -> dict:
    """
    Evaluates a strategy against baselines with cost adjustment.
    
    Args:
        signals: Series of target positions (-1, 0, 1) aligned with returns.
        returns: Series of bar returns.
        spread_bps: Spread cost in basis points per trade.
        comm_bps: Commission cost in basis points per trade.
    """
    df = pd.DataFrame({'signal': signals, 'return': returns})
    
    # Calculate trades (turnover)
    df['trade'] = df['signal'].diff().abs().fillna(0)
    
    # Cost per trade in decimal (e.g., 1.5 bps = 0.00015)
    cost_per_trade = (spread_bps + comm_bps) / 10000.0
    
    # Strategy Return = Signal_prev * Return_current - Cost * Trades_current
    df['strat_gross'] = df['signal'].shift(1) * df['return']
    df['strat_net'] = df['strat_gross'] - (df['trade'] * cost_per_trade)
    
    # Buy & Hold Baseline
    df['bnh'] = df['return']
    
    # Random Control
    np.random.seed(42)
    random_signals = pd.Series(np.random.choice([-1, 0, 1], size=len(df)), index=df.index)
    df['random'] = random_signals.shift(1) * df['return']
    # Apply costs to random
    random_trades = random_signals.diff().abs().fillna(0)
    df['random_net'] = df['random'] - (random_trades * cost_per_trade)
    
    metrics = {}
    for col in ['strat_net', 'bnh', 'random_net']:
        rets = df[col].dropna()
        if len(rets) == 0:
            continue
            
        ann_factor = 252 * 6 # 6 H4 bars per day * 252 days
        ann_return = rets.mean() * ann_factor
        ann_vol = rets.std() * np.sqrt(ann_factor)
        
        sharpe = ann_return / ann_vol if ann_vol > 0 else 0
        
        downside_rets = rets[rets < 0]
        sortino = ann_return / (downside_rets.std() * np.sqrt(ann_factor)) if len(downside_rets) > 0 and downside_rets.std() > 0 else 0
        
        mdd = calculate_drawdown(rets).min()
        
        metrics[col] = {
            'Ann Return': ann_return,
            'Ann Volatility': ann_vol,
            'Sharpe': sharpe,
            'Sortino': sortino,
            'Max Drawdown': mdd
        }
        
    return metrics
