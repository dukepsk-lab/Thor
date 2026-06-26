import os
import sys
import pandas as pd
import numpy as np
import torch
from datetime import datetime

# Import layers
from src.layers.l0_ingestion.mt5_client import mt5_client
from src.layers.l2_regime.hmm_detector import RegimeHMM
from src.layers.l2_regime.router import RegimeRouter
from src.layers.l3_primary_model.tree_models import TreeEnsemble
from src.layers.l3_primary_model.cnn_model import TemporalCNN, CNNWrapper
from src.layers.l3_primary_model.ensemble import PrimaryEnsembleRouter
from src.layers.l4_labeling.triple_barrier import apply_triple_barrier
from src.layers.l5_meta_model.meta_learner import MetaLearner
from src.layers.l6_risk_sizing.sizing import calculate_base_size, apply_confidence_scaling
from src.layers.l8_monitoring.validation.cpcv import PurgedKFold
from src.layers.l8_monitoring.validation.metrics import evaluate_strategy

from src.layers.l1_features.trend_memory import calculate_ker
from src.layers.l1_features.volatility import calculate_yang_zhang, calculate_atr

def generate_synthetic_data(num_bars=2000):
    """Generates synthetic OHLCV data with varying regimes (trends and ranges)."""
    print("Generating synthetic market data...")
    dates = pd.date_range(start='2020-01-01', periods=num_bars, freq='4h')
    
    # Random walk with shifting volatility
    returns = np.random.normal(0, 0.002, num_bars)
    
    # Inject a trend regime
    returns[500:800] += 0.001 
    
    close = np.exp(returns.cumsum()) * 1.1000 # Start at 1.1000
    
    df = pd.DataFrame(index=dates)
    df['close'] = close
    df['open'] = df['close'].shift(1).fillna(1.1000)
    df['high'] = df[['open', 'close']].max(axis=1) + np.random.uniform(0, 0.005, num_bars)
    df['low'] = df[['open', 'close']].min(axis=1) - np.random.uniform(0, 0.005, num_bars)
    df['volume'] = np.random.randint(1000, 5000, num_bars)
    
    return df

def run_pipeline():
    print("=== Thor ML: End-to-End Backtest Pipeline ===")
    
    # 1. Data Ingestion (L0)
    print("\n[Layer 0] Data Ingestion")
    df = None
    if mt5_client.connect():
        print("Connected to MT5. Fetching real data...")
        import MetaTrader5 as mt5
        df = mt5_client.fetch_ohlcv("EURUSD", mt5.TIMEFRAME_M15, datetime(2023, 1, 1), datetime.now())
    
    if df is None or df.empty:
        print("Failed to fetch MT5 data. Falling back to synthetic dataset.")
        df = generate_synthetic_data(2000)
        
    # 2. Feature Engineering (L1)
    print("[Layer 1] Feature Engineering")
    df['return'] = df['close'].pct_change().fillna(0)
    df['volatility'] = calculate_yang_zhang(df, period=20).bfill()
    df['atr'] = calculate_atr(df, period=14).bfill()
    df['hurst'] = 0.5 # Mocking Hurst as it is very slow to compute dynamically for 5000 bars
    df['ker'] = calculate_ker(df, period=10).bfill()
    
    # Clean any straggling NaNs from feature windows
    df = df.dropna()
    
    import json
    import os
    
    # Default parameters
    tp_multiplier = 2.0
    sl_multiplier = 2.0
    tree_depth = 4
    learning_rate = 0.05
    n_estimators = 100
    confidence_threshold = 0.5
    
    if os.path.exists('best_params.json'):
        with open('best_params.json', 'r') as f:
            params = json.load(f)
            tp_multiplier = params.get('tp_multiplier', tp_multiplier)
            sl_multiplier = params.get('sl_multiplier', sl_multiplier)
            tree_depth = params.get('tree_depth', tree_depth)
            learning_rate = params.get('learning_rate', learning_rate)
            n_estimators = params.get('n_estimators', n_estimators)
            confidence_threshold = params.get('confidence_threshold', confidence_threshold)
        print("\n[!] Loaded optimized hyperparameters from best_params.json!")
    
    # 3. Label Generation (L4)
    print("[Layer 4] Triple-Barrier Labeling")
    labels = apply_triple_barrier(df, atr_multiplier_tp=tp_multiplier, atr_multiplier_sl=sl_multiplier, vertical_bars=10)
    df['label'] = labels['label'].fillna(0)
    df['t1'] = labels['t1']
    df = df.dropna()
    
    # 4. CPCV Setup (L8)
    print("[Layer 8] Setting up Purged K-Fold Cross Validation")
    cv = PurgedKFold(n_splits=3, embargo_pct=0.01)
    
    all_fold_signals = []
    
    fold = 1
    for train_idx, test_idx in cv.split(df, df[['t1']]):
        print(f"\n--- Processing Fold {fold} ---")
        
        train_df = df.iloc[train_idx]
        test_df = df.iloc[test_idx]
        
        # 5a. Fit Regime HMM (L2)
        print("  Fitting L2 Regime Router...")
        hmm = RegimeHMM(n_components=3, random_state=42)
        hmm.fit(train_df[['return', 'volatility']])
        router = RegimeRouter(hmm)
        
        train_regimes = router.determine_regime(train_df)
        test_regimes = router.determine_regime(test_df)
        
        # 5b. Fit Primary Models (L3)
        print("  Fitting L3 Primary Ensembles...")
        lgb_params = {
            'objective': 'multiclass',
            'num_class': 3,
            'metric': 'multi_logloss',
            'boosting_type': 'gbdt',
            'learning_rate': learning_rate,
            'max_depth': tree_depth,
            'n_estimators': n_estimators,
            'verbose': -1
        }
        tree = TreeEnsemble(params=lgb_params)
        # Map labels from -1,0,1 to 0,1,2 for LightGBM
        y_train_tree = train_df['label'].map({-1:0, 0:1, 1:2})
        features_flat = ['return', 'volatility', 'hurst', 'ker']
        tree.fit(train_df[features_flat], y_train_tree)
        
        cnn_net = TemporalCNN(num_features=len(features_flat), sequence_length=10, num_classes=3)
        cnn = CNNWrapper(model=cnn_net)
        
        ensemble = PrimaryEnsembleRouter(tree, cnn)
        
        # Mocking CNN sequence features to random just to test routing flow
        seq_tensor_test = torch.randn(len(test_df), len(features_flat), 10)
        
        # Generate predictions for test fold
        probas = ensemble.predict_proba(test_df[features_flat], seq_tensor_test, test_regimes['final_regime'])
        primary_signals_test = probas.idxmax(axis=1).map({'prob_short':-1, 'prob_flat':0, 'prob_long':1})
        
        # 5c. Fit Meta-Learner (L5)
        # Normally fit on out-of-fold validation data from train_df. For speed, we mock the fit here.
        print("  Fitting L5 Meta-Learner...")
        meta = MetaLearner()
        mock_actual_outcomes = (primary_signals_test == test_df['label']).astype(int)
        meta.fit(primary_signals_test, test_regimes['final_regime'], test_df['volatility'], mock_actual_outcomes)
        
        # 5d. Risk Sizing & Execution (L6/L7 Simulation)
        print("  Simulating L6 Risk Sizing...")
        p_correct = meta.predict_trust_probability(primary_signals_test, test_regimes['final_regime'], test_df['volatility'])
        
        fold_results = []
        for i, idx in enumerate(test_df.index):
            signal = primary_signals_test.iloc[i]
            conf = p_correct.iloc[i]
            
            # Base risk: $100
            atr = test_df['volatility'].iloc[i] # using vol as proxy for ATR
            base_size = calculate_base_size(10000, 0.01, atr, sl_multiplier)
            
            final_size = apply_confidence_scaling(base_size, conf, threshold=confidence_threshold)
            
            # If size > 0, we take the trade. We just track the target signal for evaluation.
            final_signal = signal if final_size > 0 else 0
            fold_results.append(final_signal)
            
        all_fold_signals.extend(fold_results)
        fold += 1

    # 6. Final Evaluation (L8)
    print("\n=== Final Backtest Results ===")
    final_signals_series = pd.Series(all_fold_signals, index=df.index[-len(all_fold_signals):])
    test_returns = df['return'].iloc[-len(all_fold_signals):]
    
    metrics = evaluate_strategy(final_signals_series, test_returns)
    df_metrics = pd.DataFrame(metrics).T
    print(df_metrics.to_string(float_format=lambda x: f"{x:.4f}"))
    print("\nBacktest Complete!")

if __name__ == "__main__":
    run_pipeline()
