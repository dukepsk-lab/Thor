import pandas as pd
import numpy as np
import scipy.stats as stats

def calculate_sharpe_ratio(returns: pd.Series, risk_free_rate=0.0, periods=252) -> float:
    """
    Calculate annualized Sharpe ratio.
    """
    if returns is None or returns.empty:
        return 0.0
    
    # Clean NaNs
    clean_returns = returns.dropna()
    if clean_returns.empty:
        return 0.0
        
    std = clean_returns.std()
    if std == 0 or np.isnan(std):
        return 0.0
        
    mean_excess = clean_returns.mean() - risk_free_rate
    sharpe = (mean_excess / std) * np.sqrt(periods)
    return float(sharpe)

def calculate_sortino_ratio(returns: pd.Series, risk_free_rate=0.0, periods=252) -> float:
    """
    Calculate annualized Sortino ratio.
    """
    if returns is None or returns.empty:
        return 0.0
        
    clean_returns = returns.dropna()
    if clean_returns.empty:
        return 0.0
        
    # Downside returns (only negative returns relative to risk-free rate)
    downside_returns = clean_returns[clean_returns < risk_free_rate]
    
    if downside_returns.empty:
        # If no downside returns, downside deviation is 0.
        # But we return 0.0 or handle division by zero.
        return 0.0
        
    # Downside deviation is calculated relative to 0 or target rate
    # Using sample standard deviation formula on downside returns or relative to N
    downside_deviation = np.sqrt(np.mean(downside_returns ** 2))
    
    if downside_deviation == 0 or np.isnan(downside_deviation):
        return 0.0
        
    mean_excess = clean_returns.mean() - risk_free_rate
    sortino = (mean_excess / downside_deviation) * np.sqrt(periods)
    return float(sortino)

def deduct_transaction_costs(returns: pd.Series, trades: pd.Series = None, spread: float = 0.0, commission: float = 0.0) -> pd.Series:
    """
    Deducts transaction costs (spread in return units + commission in return units) from returns.
    """
    if returns is None or returns.empty:
        return pd.Series(dtype=float)
        
    net_returns = returns.copy()
    if trades is None:
        # Assume a trade occurs on every non-zero return bar
        trades = (returns != 0).astype(int)
        
    # net_ret = raw_ret - spread_costs - commissions
    # Adjust for spread + commission per trade
    cost_series = (spread + commission) * trades
    net_returns = net_returns - cost_series
    return net_returns

def calculate_dsr(observed_sr: float, sr_variance: float, num_trials: int, num_samples: int, skewness: float = 0.0, kurtosis: float = 3.0) -> float:
    """
    Calculate Deflated Sharpe Ratio.
    observed_sr: Daily or annualized Sharpe ratio (must match scale).
    sr_variance: Variance of Sharpe ratios across all trials.
    num_trials: Number of trials (M).
    num_samples: Length of the returns series (T).
    """
    if num_samples <= 2:
        return 0.0
        
    if num_trials <= 1 or sr_variance <= 0:
        # No multi-testing penalty, standard Sharpe probability
        z = observed_sr * np.sqrt(num_samples - 1)
        return float(stats.norm.cdf(z))
        
    # Expected maximum Sharpe ratio under the null hypothesis (independent trials)
    euler_gamma = 0.5772156649
    m_term = 1 - 1.0 / num_trials
    m_e_term = 1 - 1.0 / (num_trials * np.e)
    
    # Safeguard stats.norm.ppf inputs
    m_term = max(0.0001, min(0.9999, m_term))
    m_e_term = max(0.0001, min(0.9999, m_e_term))
    
    e_max = (1 - euler_gamma) * stats.norm.ppf(m_term) + euler_gamma * stats.norm.ppf(m_e_term)
    sr_star = np.sqrt(sr_variance) * e_max
    
    # Variance of the Sharpe ratio estimator
    numerator_var = 1.0 - skewness * observed_sr + (kurtosis - 1.0) / 4.0 * (observed_sr ** 2)
    sr_estimator_var = numerator_var / (num_samples - 1)
    
    if sr_estimator_var <= 0:
        return 0.0
        
    z = (observed_sr - sr_star) / np.sqrt(sr_estimator_var)
    dsr_prob = stats.norm.cdf(z)
    return float(dsr_prob)

def majority_class_baseline(y_true: pd.Series, y_pred: pd.Series) -> dict:
    """
    Compares model predictions against majority class baseline.
    """
    if y_true is None or y_true.empty:
        return {"model_accuracy": 0.0, "baseline_accuracy": 0.0, "relative_accuracy": 0.0}
        
    majority_val = y_true.mode()[0] if not y_true.empty else 0
    baseline_pred = pd.Series(majority_val, index=y_true.index)
    
    model_acc = (y_pred == y_true).mean()
    baseline_acc = (baseline_pred == y_true).mean()
    
    return {
        "model_accuracy": float(model_acc),
        "baseline_accuracy": float(baseline_acc),
        "relative_accuracy": float(model_acc - baseline_acc)
    }

def buy_and_hold_baseline(strategy_returns: pd.Series, prices: pd.Series) -> dict:
    """
    Compares strategy returns with long-only Buy-and-Hold benchmark.
    """
    if strategy_returns is None or strategy_returns.empty or prices is None or prices.empty:
        return {
            "strategy_cumulative_return": 0.0,
            "bah_cumulative_return": 0.0,
            "relative_cumulative_return": 0.0,
            "strategy_sharpe": 0.0,
            "bah_sharpe": 0.0,
            "relative_sharpe": 0.0
        }
        
    bah_returns = prices.pct_change().fillna(0)
    
    # Align indices
    common_idx = strategy_returns.index.intersection(bah_returns.index)
    strat = strategy_returns.loc[common_idx]
    bah = bah_returns.loc[common_idx]
    
    cum_strategy = (1 + strat).prod() - 1
    cum_bah = (1 + bah).prod() - 1
    
    # Sharpe calculations
    std_strat = strat.std()
    sr_strat = strat.mean() / std_strat * np.sqrt(252) if std_strat > 0 else 0.0
    
    std_bah = bah.std()
    sr_bah = bah.mean() / std_bah * np.sqrt(252) if std_bah > 0 else 0.0
    
    return {
        "strategy_cumulative_return": float(cum_strategy),
        "bah_cumulative_return": float(cum_bah),
        "relative_cumulative_return": float(cum_strategy - cum_bah),
        "strategy_sharpe": float(sr_strat),
        "bah_sharpe": float(sr_bah),
        "relative_sharpe": float(sr_strat - sr_bah)
    }
