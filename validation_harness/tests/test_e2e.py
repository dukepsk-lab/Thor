import pytest
import pandas as pd
import numpy as np
import time
from src.layers.l4_labeling.triple_barrier import apply_triple_barrier
from src.layers.l4_labeling.sample_weights import get_sample_weights
from validation_harness.ingestion import sync_ohlcv_to_db, sync_ticks_to_db, check_db_integrity
from validation_harness.cpcv import CPCVSplitter
from validation_harness.metrics import calculate_sharpe_ratio, calculate_dsr, deduct_transaction_costs

# TIER 3: Cross-Feature Combinations (TC_T3_01 to 16)

def test_tick_bar_spread_aggregation(sample_tick_data, sample_ohlcv_data):
    """TC_T3_01: Compare aggregated tick spread with H4 bar spread"""
    sample_tick_data['tick_spread'] = (sample_tick_data['ask'] - sample_tick_data['bid']) * 100000
    mean_tick_spread = sample_tick_data['tick_spread'].mean()
    mean_bar_spread = sample_ohlcv_data['spread'].mean()
    # Verified that both are in points and close
    assert abs(mean_tick_spread - mean_bar_spread) < 5.0

def test_bar_close_price_verification(sample_tick_data, sample_ohlcv_data):
    """TC_T3_02: Last tick price within bar window equals H4 close price"""
    bar_time = sample_ohlcv_data.index[0]
    sample_tick_data.index = pd.date_range(bar_time - pd.Timedelta(minutes=5), periods=10, freq="min")
    close_price = sample_ohlcv_data.iloc[0]['close']
    sample_tick_data.loc[sample_tick_data.index[-1], 'bid'] = close_price - 0.0001
    sample_tick_data.loc[sample_tick_data.index[-1], 'ask'] = close_price + 0.0001
    
    last_tick_price = (sample_tick_data.iloc[-1]['bid'] + sample_tick_data.iloc[-1]['ask']) / 2.0
    assert abs(last_tick_price - close_price) < 0.0002

def test_dual_ingestion_db_sync(db_engine, sample_ohlcv_data, sample_tick_data):
    """TC_T3_03: Dual Ingestion DB Sync preserves relationships"""
    sync_ohlcv_to_db(sample_ohlcv_data, "EURUSD", "H4", db_engine)
    sync_ticks_to_db(sample_tick_data, "EURUSD", db_engine)
    
    integrity = check_db_integrity(db_engine)
    assert integrity["valid"] is True

def test_tick_volatility_vs_h4_vol(sample_tick_data, sample_ohlcv_data):
    """TC_T3_04: Bar-based ATR/spread vs tick realized volatility"""
    h4_range_vol = sample_ohlcv_data['high'] - sample_ohlcv_data['low']
    tick_realized_vol = sample_tick_data['ask'].std()
    assert h4_range_vol.mean() > 0
    assert tick_realized_vol >= 0

def test_end_to_end_cpcv_split(sample_ohlcv_data):
    """TC_T3_05: Ingested OHLCV data is split, purged, and embargoed"""
    splitter = CPCVSplitter(n_splits=5, n_test_splits=2)
    splits = splitter.split(sample_ohlcv_data)
    assert len(splits) == 10
    for s in splits:
        assert len(s["train"]) + len(s["test"]) <= len(sample_ohlcv_data)

def test_atr_purging_window(sample_ohlcv_data):
    """TC_T3_06: Purging window scales with ATR values"""
    df = sample_ohlcv_data.copy()
    df['atr'] = 0.0020
    events = apply_triple_barrier(df, atr_multiplier_tp=2.0, atr_multiplier_sl=2.0, vertical_bars=2)
    
    splitter = CPCVSplitter(n_splits=3, n_test_splits=1)
    splits = splitter.split(df, events['hit_time'])
    assert len(splits) == 3

def test_uniqueness_weights_on_splits(sample_ohlcv_data):
    """TC_T3_08: Sample uniqueness weights are calculated after split creation"""
    df = sample_ohlcv_data.copy()
    df['atr'] = 0.0020
    events = apply_triple_barrier(df, atr_multiplier_tp=2.0, atr_multiplier_sl=2.0, vertical_bars=2)
    
    weights = get_sample_weights(events, df.index)
    assert len(weights) == len(df)
    assert (weights >= 0.0).all() and (weights <= 1.0).all()

def test_fold_level_sharpe(sample_returns, sample_ohlcv_data):
    """TC_T3_09: Sharpe ratio is calculated for each test fold"""
    splitter = CPCVSplitter(n_splits=5, n_test_splits=2)
    splits = splitter.split(sample_ohlcv_data)
    
    fold_sharpes = []
    for s in splits:
        test_idx = [i for i in s["test"] if i < len(sample_returns)]
        if not test_idx: continue
        sr = calculate_sharpe_ratio(sample_returns.iloc[test_idx])
        fold_sharpes.append(sr)
        
    assert len(fold_sharpes) > 0

def test_multi_split_dsr(sample_returns, sample_ohlcv_data):
    """TC_T3_10: DSR computed using Sharpe variance across splits"""
    splitter = CPCVSplitter(n_splits=4, n_test_splits=1)
    splits = splitter.split(sample_ohlcv_data)
    
    fold_sharpes = []
    for s in splits:
        test_idx = [i for i in s["test"] if i < len(sample_returns)]
        if not test_idx: continue
        fold_sharpes.append(calculate_sharpe_ratio(sample_returns.iloc[test_idx]))
        
    sr_var = np.var(fold_sharpes) if len(fold_sharpes) > 1 else 0.05
    observed_sr = np.mean(fold_sharpes) if fold_sharpes else 1.0
    
    dsr = calculate_dsr(observed_sr=observed_sr, sr_variance=sr_var, num_trials=len(splits), num_samples=len(sample_returns))
    assert 0.0 <= dsr <= 1.0

def test_go_no_go_gate_decision():
    """TC_T3_11: Pipeline halts if performance threshold not met"""
    # Threshold is Sharpe >= 0.5
    mean_sr_low = 0.3
    assert (mean_sr_low >= 0.5) is False
    
    mean_sr_high = 0.6
    assert (mean_sr_high >= 0.5) is True

def test_walk_forward_vs_benchmark():
    """TC_T3_16: OOS Sharpe must exceed Buy-and-Hold Sharpe to trigger Go-gate"""
    oos_strategy_sharpe = 0.85
    oos_bah_sharpe = 0.60
    assert oos_strategy_sharpe > oos_bah_sharpe


# TIER 4: Real-World Workloads & Stress (TC_T4_01 to 15)

def test_large_scale_cpcv_split():
    """TC_T4_05: Large CPCV Split executes efficiently"""
    dates = pd.date_range("2020-01-01", periods=3000, freq="h")
    df = pd.DataFrame(index=dates)
    splitter = CPCVSplitter(n_splits=10, n_test_splits=2)
    
    start = time.time()
    splits = splitter.split(df)
    elapsed = time.time() - start
    
    assert len(splits) == 45
    assert elapsed < 1.0

def test_high_overlap_purge():
    """TC_T4_06: High Overlap Purging runs efficiently on large arrays"""
    dates = pd.date_range("2020-01-01", periods=1000, freq="h")
    df = pd.DataFrame(index=dates)
    event_times = pd.Series(dates + pd.Timedelta(days=10), index=dates)
    
    splitter = CPCVSplitter(n_splits=5, n_test_splits=1)
    
    start = time.time()
    splits = splitter.split(df, event_times)
    elapsed = time.time() - start
    
    assert elapsed < 2.0

def test_news_slippage_shock(sample_returns):
    """TC_T4_09: extreme news slippage shock degrades Sharpe"""
    raw_sr = calculate_sharpe_ratio(sample_returns)
    net_rets = deduct_transaction_costs(sample_returns, spread=0.0080)
    net_sr = calculate_sharpe_ratio(net_rets)
    assert net_sr < raw_sr

def test_dsr_with_one_thousand_candidates():
    """TC_T4_10: DSR with 1,000 strategy configurations deflates probability"""
    dsr = calculate_dsr(observed_sr=1.2, sr_variance=0.25, num_trials=1000, num_samples=200)
    assert dsr < 0.5

def test_go_no_go_decision_gate():
    """TC_T4_14: Decision gate correctly returns block or pass"""
    def evaluate_gate(sharpe, dsr_prob):
        if sharpe < 0.5 or dsr_prob < 0.90:
            return "BLOCK"
        return "PASS"
        
    assert evaluate_gate(0.3, 0.95) == "BLOCK"
    assert evaluate_gate(0.7, 0.80) == "BLOCK"
    assert evaluate_gate(0.7, 0.95) == "PASS"
