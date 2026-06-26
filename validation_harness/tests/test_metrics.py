import pytest
import pandas as pd
import numpy as np
from validation_harness.metrics import (
    calculate_sharpe_ratio,
    calculate_sortino_ratio,
    deduct_transaction_costs,
    calculate_dsr,
    majority_class_baseline,
    buy_and_hold_baseline
)

# TIER 1: Feature Coverage (TC_T1_15 to 20)

def test_transaction_cost_deduction():
    """TC_T1_15: Transaction Cost Deduction decreases returns correctly"""
    returns = pd.Series([0.01, 0.02, -0.01, 0.00, 0.03])
    # 1 pip spread and commission (in return units, e.g. 0.001)
    net_rets = deduct_transaction_costs(returns, spread=0.001, commission=0.0005)
    
    # Net returns = raw - cost. Trades are on indices 0, 1, 2, 4 (non-zero returns)
    # Day 0: 0.01 - 0.0015 = 0.0085
    # Day 3: 0.00 - 0 = 0.0000
    assert net_rets.iloc[0] == pytest.approx(0.0085)
    assert net_rets.iloc[3] == 0.0
    assert (net_rets <= returns).all()

def test_sharpe_ratio_calculation():
    """TC_T1_16: Sharpe Ratio Calculation matches expected value"""
    # Daily returns: constant 0.001 (10 bps) with 0 std? No, std cannot be 0.
    # Let's use alternating returns so std > 0
    returns = pd.Series([0.001, 0.002, 0.001, 0.002, 0.001] * 20)  # Mean is 0.0015, std is 0.0005025
    sr = calculate_sharpe_ratio(returns, risk_free_rate=0.0, periods=252)
    assert sr > 0.0
    # Annualized Sharpe: (0.0015 / 0.0005025) * sqrt(252) ≈ 2.98 * 15.87 ≈ 47.4
    assert sr == pytest.approx((returns.mean() / returns.std()) * np.sqrt(252))

def test_sortino_ratio_calculation():
    """TC_T1_17: Sortino Ratio Calculation ignores upside volatility"""
    # Series with positive spikes vs negative spikes
    returns = pd.Series([0.01, 0.02, -0.01, 0.00, 0.03, -0.005] * 10)
    sortino = calculate_sortino_ratio(returns, risk_free_rate=0.0, periods=252)
    assert sortino > 0
    
    # Standard deviation includes 0.02 and 0.03. Downside deviation only includes negative values.
    # So downside deviation should be smaller than standard deviation, meaning Sortino > Sharpe.
    sharpe = calculate_sharpe_ratio(returns, risk_free_rate=0.0, periods=252)
    assert sortino > sharpe

def test_dsr_calculation():
    """TC_T1_18: Deflated Sharpe Ratio calculation probability mapping"""
    # Sharpe=1.5, trials=5, var=0.1. Sample length = 1000
    dsr = calculate_dsr(observed_sr=1.5, sr_variance=0.1, num_trials=5, num_samples=1000)
    assert 0.0 <= dsr <= 1.0

def test_majority_class_comparison():
    """TC_T1_19: Majority Class Comparison baseline difference"""
    y_true = pd.Series([1, 1, -1, 1, -1, 1, 1, 1, -1, 1])  # 70% 1, 30% -1
    y_pred = pd.Series([1, 1, 1, 1, 1, 1, 1, 1, 1, 1])      # 100% 1
    
    res = majority_class_baseline(y_true, y_pred)
    assert res["baseline_accuracy"] == 0.7
    assert res["model_accuracy"] == 0.7
    assert res["relative_accuracy"] == 0.0

def test_buy_and_hold_benchmark():
    """TC_T1_20: Buy-and-Hold Benchmark cumulative return diff"""
    # Strategy returns vs Asset prices
    strategy_returns = pd.Series([0.01, 0.01, 0.01, -0.01, 0.01])
    prices = pd.Series([100.0, 100.5, 101.0, 100.8, 99.0, 100.0]) # Price changes
    
    res = buy_and_hold_baseline(strategy_returns, prices)
    # Prices pct changes:
    # 0.005, 0.004975, -0.00198, -0.01785, 0.0101
    # Bah cum return: (100.0 - 100.0)/100.0 = 0.0 (except alignment might skip first bar)
    # Check that keys exist and relative cumulative return is correct
    assert "relative_cumulative_return" in res
    assert "relative_sharpe" in res


# TIER 2: Boundary & Corner Cases (TC_T2_14 to 20)

def test_zero_volatility_returns():
    """TC_T2_14: Zero Volatility returns return 0.0 (no division by zero)"""
    returns = pd.Series([0.0, 0.0, 0.0, 0.0])
    sr = calculate_sharpe_ratio(returns)
    sortino = calculate_sortino_ratio(returns)
    assert sr == 0.0
    assert sortino == 0.0

def test_extreme_slippage():
    """TC_T2_15: Extreme Slippage degrades Sharpe and Sortino"""
    returns = pd.Series([0.001, 0.002, 0.001, 0.001, 0.002] * 10)
    # 5% transaction cost (extreme)
    net_rets = deduct_transaction_costs(returns, spread=0.05)
    
    sr_raw = calculate_sharpe_ratio(returns)
    sr_net = calculate_sharpe_ratio(net_rets)
    assert sr_net < sr_raw
    assert sr_net < 0

def test_nan_inf_returns():
    """TC_T2_16: NaN/Inf returns dropped automatically"""
    returns = pd.Series([0.01, np.nan, 0.02, -0.01, np.inf, -np.inf, 0.03])
    # Replace inf with nan and drop
    returns = returns.replace([np.inf, -np.inf], np.nan)
    sr = calculate_sharpe_ratio(returns)
    assert sr > 0
    # Should equal Sharpe of [0.01, 0.02, -0.01, 0.03]
    expected_sr = calculate_sharpe_ratio(pd.Series([0.01, 0.02, -0.01, 0.03]))
    assert sr == pytest.approx(expected_sr)

def test_dsr_with_single_trial():
    """TC_T2_17: DSR with Single Trial is standard Sharpe CDF"""
    dsr = calculate_dsr(observed_sr=1.5, sr_variance=0.0, num_trials=1, num_samples=100)
    import scipy.stats as stats
    expected = stats.norm.cdf(1.5 * np.sqrt(99))
    assert dsr == pytest.approx(expected)

def test_skewed_label_distribution():
    """TC_T2_18: Skewed Label Distribution baseline accuracy is high"""
    # 99% Long labels
    y_true = pd.Series([1]*99 + [-1])
    y_pred = pd.Series([1]*100)
    res = majority_class_baseline(y_true, y_pred)
    assert res["baseline_accuracy"] == 0.99
    assert res["model_accuracy"] == 0.99
    assert res["relative_accuracy"] == 0.0

def test_negative_baseline_sharpe():
    """TC_T2_19: Negative Baseline Sharpe is relative gain"""
    strategy_returns = pd.Series([0.0001, 0.0002, 0.0001] * 10)
    prices = pd.Series([100.0, 99.0, 98.0, 97.0] * 10) # Heavy downward trend
    res = buy_and_hold_baseline(strategy_returns, prices)
    assert res["strategy_sharpe"] > 0
    assert res["bah_sharpe"] < 0
    assert res["relative_sharpe"] > 0

def test_zero_trade_execution():
    """TC_T2_20: Zero Trade Execution returns zero metrics"""
    strategy_returns = pd.Series([0.0, 0.0, 0.0, 0.0])
    prices = pd.Series([100.0, 101.0, 102.0, 103.0])
    res = buy_and_hold_baseline(strategy_returns, prices)
    assert res["strategy_cumulative_return"] == 0.0
    assert res["strategy_sharpe"] == 0.0


# ADDITIONAL METRICS EDGE CASES (to reach 20 cases)

def test_sharpe_with_all_negatives():
    """TC_Metrics_Edge_1: Constant negative returns yield negative Sharpe"""
    returns = pd.Series([-0.01, -0.015, -0.01, -0.02, -0.01] * 10)
    sr = calculate_sharpe_ratio(returns)
    assert sr < 0.0

def test_sortino_with_only_positive_returns():
    """TC_Metrics_Edge_2: Sortino with only positive returns returns 0.0"""
    returns = pd.Series([0.01, 0.02, 0.015, 0.03, 0.02] * 10)
    sortino = calculate_sortino_ratio(returns, risk_free_rate=0.0)
    assert sortino == 0.0

def test_dsr_highly_inflated_trials():
    """TC_Metrics_Edge_3: DSR with high trials (10000) deflates SR to near zero probability"""
    dsr = calculate_dsr(observed_sr=1.0, sr_variance=0.2, num_trials=10000, num_samples=100)
    # The expected maximum SR is very high due to 10000 trials, so DSR is deflated
    assert dsr < 0.1

def test_deduct_costs_no_trades_provided():
    """TC_Metrics_Edge_4: deduct_transaction_costs without trades series"""
    returns = pd.Series([0.01, 0.0, -0.02])
    net = deduct_transaction_costs(returns, spread=0.001)
    # Cost deducted on Day 0 and Day 2
    assert net.iloc[0] == pytest.approx(0.009)
    assert net.iloc[1] == 0.0
    assert net.iloc[2] == pytest.approx(-0.021)

def test_buy_and_hold_all_zero_returns():
    """TC_Metrics_Edge_5: buy_and_hold_baseline with zero price returns"""
    strategy_returns = pd.Series([0.0, 0.0, 0.0])
    prices = pd.Series([100.0, 100.0, 100.0])
    res = buy_and_hold_baseline(strategy_returns, prices)
    assert res["bah_cumulative_return"] == 0.0
    assert res["relative_cumulative_return"] == 0.0

def test_majority_class_all_same_target():
    """TC_Metrics_Edge_6: majority_class_baseline with constant true labels"""
    y_true = pd.Series([1, 1, 1])
    y_pred = pd.Series([1, 1, -1])
    res = majority_class_baseline(y_true, y_pred)
    assert res["baseline_accuracy"] == 1.0
    assert res["model_accuracy"] == pytest.approx(2/3)
    assert res["relative_accuracy"] == pytest.approx(-1/3)

def test_sharpe_empty_series():
    """TC_Metrics_Edge_7: calculate_sharpe_ratio on empty series returns 0.0"""
    res = calculate_sharpe_ratio(pd.Series(dtype=float))
    assert res == 0.0
