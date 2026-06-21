import os
import json
import joblib
import sklearn
import pandas as pd
import numpy as np
import torch
from datetime import datetime

from src.layers.l0_ingestion.mt5_client import mt5_client
from src.layers.l1_features.trend_memory import calculate_ker
from src.layers.l1_features.volatility import calculate_yang_zhang, calculate_atr
from src.layers.l2_regime.hmm_detector import RegimeHMM
from src.layers.l3_primary_model.tree_models import TreeEnsemble
from src.layers.l3_primary_model.cnn_model import TemporalCNN
from src.layers.l4_labeling.triple_barrier import apply_triple_barrier
from src.layers.l5_meta_model.meta_learner import MetaLearner
from src.inference import decision

import argparse

def main():
    parser = argparse.ArgumentParser(description="Train and Save ML Models")
    parser.add_argument('--symbol', type=str, default='EURUSD', help='Symbol to train (e.g., EURUSD)')
    args = parser.parse_args()
    
    target_symbol = args.symbol
    print(f"=== Training & Saving Final Production Models for {target_symbol} ===")
    
    # Create models directory for this symbol
    model_dir = f'models/{target_symbol}'
    os.makedirs(model_dir, exist_ok=True)
    
    # 1. Load optimized parameters
    tp_multiplier = 2.0
    sl_multiplier = 2.0
    tree_depth = 4
    learning_rate = 0.05
    n_estimators = 100
    
    param_file = f'best_params_{target_symbol}.json'
    if os.path.exists(param_file):
        with open(param_file, 'r') as f:
            params = json.load(f)
            tp_multiplier = params.get('tp_multiplier', tp_multiplier)
            sl_multiplier = params.get('sl_multiplier', sl_multiplier)
            tree_depth = params.get('tree_depth', tree_depth)
            learning_rate = params.get('learning_rate', learning_rate)
            n_estimators = params.get('n_estimators', n_estimators)
        print(f"[!] Loaded optimized parameters from {param_file}.")
    else:
        print(f"[-] No {param_file} found. Using default architecture.")

    # 2. Ingest Data
    if not mt5_client.connect():
        print("Failed to connect to MT5.")
        return
        
    import MetaTrader5 as mt5
    print(f"Fetching historical data for {target_symbol}...")
    df = mt5_client.fetch_ohlcv(target_symbol, mt5.TIMEFRAME_H4, datetime(2023, 1, 1), datetime.now())
    if df is None or df.empty:
        print("Data fetch failed.")
        return
        
    # 3. Features
    print("Computing features...")
    df['return'] = df['close'].pct_change().fillna(0)
    df['volatility'] = calculate_yang_zhang(df, period=20).bfill()
    df['atr'] = calculate_atr(df, period=14).bfill()
    df['hurst'] = 0.5
    df['ker'] = calculate_ker(df, period=10).bfill()
    df = df.dropna()
    
    # 4. Labels
    print("Generating labels...")
    labels = apply_triple_barrier(df, atr_multiplier_tp=tp_multiplier, atr_multiplier_sl=sl_multiplier, vertical_bars=10)
    df['label'] = labels['label'].fillna(0)
    df['t1'] = labels['t1']
    df = df.dropna()
    
    features_flat = ['return', 'volatility', 'hurst', 'ker']
    
    # 5. Train Regime HMM
    print("Training Regime HMM...")
    hmm = RegimeHMM(n_components=3, random_state=42)
    hmm.fit(df[['return', 'volatility']])

    # 6. Train Primary Model (LightGBM tree)
    print("Training Primary Tree Model...")
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
    y_tree = df['label'].map({-1:0, 0:1, 1:2})
    tree.fit(df[features_flat], y_tree)

    # CNN is kept for dashboard display only; it is NOT trained and is intentionally
    # excluded from the primary signal so that the producer is identical in
    # training, backtest, and live (see src/inference/decision.py).
    cnn_net = TemporalCNN(num_features=len(features_flat), sequence_length=10, num_classes=3)

    # 7. Train Meta-Learner using the SHARED decision path, so the meta-feature
    # contract is byte-for-byte identical to what live_bot / backtest will feed it.
    print("Training Meta-Learner...")
    regime_labels = decision.compute_regime(hmm, df)
    primary_signals = decision.compute_primary_signal(tree, df)

    meta = MetaLearner()
    actual_outcomes = (primary_signals == df['label']).astype(int)
    meta.fit(primary_signals, regime_labels, df['volatility'], actual_outcomes)

    # 8. Save Models
    print(f"Saving models to disk ({model_dir}/)...")
    # Save HMM (raw GaussianHMM; decision.wrap_hmm re-wraps it for the router)
    joblib.dump(hmm.model, f'{model_dir}/hmm_model.pkl')
    # Save Tree
    tree.model.save_model(f'{model_dir}/lgb_model.txt')
    # Save CNN (display-only)
    torch.save(cnn_net.state_dict(), f'{model_dir}/cnn_model.pt')
    # Save the full MetaLearner wrapper (carries the trained feature columns) so
    # single-row live inference reindexes to the exact training contract.
    joblib.dump(meta, f'{model_dir}/meta_model.pkl')

    # Provenance / staleness metadata
    metadata = {
        'symbol': target_symbol,
        'trained_at': datetime.now().isoformat(timespec='seconds'),
        'train_start': '2023-01-01',
        'train_end': datetime.now().strftime('%Y-%m-%d'),
        'n_train_rows': int(len(df)),
        'sklearn_version': sklearn.__version__,
        'meta_feature_columns': list(meta.feature_columns_),
        'features_flat': features_flat,
        'primary_producer': 'tree_only',
    }
    with open(f'{model_dir}/model_metadata.json', 'w') as f:
        json.dump(metadata, f, indent=2)

    print(f"\n[SUCCESS] All models trained and saved to '{model_dir}' directory!")
    print(f"  meta feature columns: {meta.feature_columns_}")
    print(f"  sklearn version: {sklearn.__version__}")
    print("The system is now ready for live deployment via live_bot.py")

if __name__ == "__main__":
    main()
