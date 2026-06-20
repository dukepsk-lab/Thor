import os
import sys
import pandas as pd
import numpy as np
import optuna
from datetime import datetime
import torch

from src.layers.l0_ingestion.mt5_client import mt5_client
from src.layers.l1_features.trend_memory import calculate_ker
from src.layers.l1_features.volatility import calculate_yang_zhang, calculate_atr
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

import argparse

# Parse Arguments for Multi-Symbol Parallel Run
parser = argparse.ArgumentParser(description="Optimize ML Pipeline")
parser.add_argument('--symbol', type=str, default='EURUSD', help='Symbol to optimize (e.g., EURUSD, USDJPY, XAUUSD)')
args = parser.parse_args()

target_symbol = args.symbol

# Fetch data once globally for optimization speed
print(f"Preparing Optimization Dataset for {target_symbol}...")
df_global = None
if mt5_client.connect():
    import MetaTrader5 as mt5
    df_global = mt5_client.fetch_ohlcv(target_symbol, mt5.TIMEFRAME_M15, datetime(2023, 1, 1), datetime.now())

if df_global is None or df_global.empty:
    print(f"Optimization failed: Could not fetch real data for {target_symbol}.")
    sys.exit(1)

# Engineer Features
df_global['return'] = df_global['close'].pct_change().fillna(0)
df_global['volatility'] = calculate_yang_zhang(df_global, period=20).bfill()
df_global['atr'] = calculate_atr(df_global, period=14).bfill()
df_global['ker'] = calculate_ker(df_global, period=10).bfill()
df_global['hurst'] = 0.5 # Mocking slow Hurst
df_global = df_global.dropna()

def objective(trial):
    # Suggest Hyperparameters
    tp_multiplier = trial.suggest_float('tp_multiplier', 1.0, 3.0)
    sl_multiplier = trial.suggest_float('sl_multiplier', 1.0, 3.0)
    
    tree_depth = trial.suggest_int('tree_depth', 3, 7)
    learning_rate = trial.suggest_float('learning_rate', 0.01, 0.2, log=True)
    n_estimators = trial.suggest_int('n_estimators', 50, 200, step=50)
    
    confidence_threshold = trial.suggest_float('confidence_threshold', 0.45, 0.65)
    
    df = df_global.copy()
    
    # Apply Triple-Barrier with suggested params
    labels = apply_triple_barrier(df, atr_multiplier_tp=tp_multiplier, atr_multiplier_sl=sl_multiplier, vertical_bars=10)
    df['label'] = labels['label'].fillna(0)
    df['t1'] = labels['t1']
    df = df.dropna()
    
    cv = PurgedKFold(n_splits=3, embargo_pct=0.01)
    all_fold_signals = []
    
    for train_idx, test_idx in cv.split(df, df[['t1']]):
        train_df = df.iloc[train_idx]
        test_df = df.iloc[test_idx]
        
        # Regime Router
        hmm = RegimeHMM(n_components=3, random_state=42)
        hmm.fit(train_df[['return', 'volatility']])
        router = RegimeRouter(hmm)
        
        train_regimes = router.determine_regime(train_df)
        test_regimes = router.determine_regime(test_df)
        
        # Primary Ensembles
        lgb_params = {
            'objective': 'multiclass',
            'num_class': 3,
            'metric': 'multi_logloss',
            'boosting_type': 'gbdt',
            'learning_rate': learning_rate,
            'max_depth': tree_depth,
            'n_estimators': n_estimators,
            'device_type': 'gpu', # Use GPU to accelerate Optuna trials!
            'verbose': -1
        }
        tree = TreeEnsemble(params=lgb_params)
        y_train_tree = train_df['label'].map({-1:0, 0:1, 1:2})
        features_flat = ['return', 'volatility', 'hurst', 'ker']
        tree.fit(train_df[features_flat], y_train_tree)
        
        cnn_net = TemporalCNN(num_features=len(features_flat), sequence_length=10, num_classes=3)
        cnn = CNNWrapper(model=cnn_net)
        
        ensemble = PrimaryEnsembleRouter(tree, cnn)
        seq_tensor_test = torch.randn(len(test_df), len(features_flat), 10) # Mock sequences
        probas = ensemble.predict_proba(test_df[features_flat], seq_tensor_test, test_regimes['final_regime'])
        primary_signals_test = probas.idxmax(axis=1).map({'prob_short':-1, 'prob_flat':0, 'prob_long':1})
        
        # Meta-Learner
        meta = MetaLearner()
        mock_actual_outcomes = (primary_signals_test == test_df['label']).astype(int)
        meta.fit(primary_signals_test, test_regimes['final_regime'], test_df['volatility'], mock_actual_outcomes)
        
        p_correct = meta.predict_trust_probability(primary_signals_test, test_regimes['final_regime'], test_df['volatility'])
        
        # Risk Sizing
        fold_results = []
        for i in range(len(test_df)):
            signal = primary_signals_test.iloc[i]
            conf = p_correct.iloc[i]
            atr = test_df['atr'].iloc[i]
            
            base_size = calculate_base_size(10000, 0.01, atr, sl_multiplier)
            final_size = apply_confidence_scaling(base_size, conf, threshold=confidence_threshold)
            
            final_signal = signal if final_size > 0 else 0
            fold_results.append(final_signal)
            
        all_fold_signals.extend(fold_results)

    final_signals_series = pd.Series(all_fold_signals, index=df.index[-len(all_fold_signals):])
    test_returns = df['return'].iloc[-len(all_fold_signals):]
    
    metrics = evaluate_strategy(final_signals_series, test_returns)
    return metrics['strat_net']['Sharpe']

if __name__ == "__main__":
    print("=== Starting Optuna Hyperparameter Optimization ===")
    study = optuna.create_study(direction="maximize")
    # Massive overnight optimization run
    study.optimize(objective, n_trials=1000)
    
    print("\nOptimization Finished.")
    print("Best Trial:")
    print("  Sharpe Ratio:", study.best_value)
    print("  Params:")
    for key, value in study.best_params.items():
        print(f"    {key}: {value}")
        
    import json
    best_file = f'best_params_{target_symbol}.json'
    with open(best_file, 'w') as f:
        json.dump(study.best_params, f, indent=4)
    print(f"\n[SUCCESS] Best parameters saved to {best_file}!")
