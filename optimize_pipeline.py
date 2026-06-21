import os
import sys
import json
import pandas as pd
import numpy as np
import optuna
from datetime import datetime, timedelta

from src.layers.l0_ingestion.mt5_client import mt5_client
from src.layers.l1_features.volatility import calculate_yang_zhang, calculate_atr
from src.layers.l1_features.trend_memory import calculate_ker
from src.layers.l2_regime.hmm_detector import RegimeHMM
from src.layers.l4_labeling.triple_barrier import apply_triple_barrier
from src.layers.l5_meta_model.meta_learner import MetaLearner
from src.layers.l8_monitoring.validation.cpcv import PurgedKFold
from src.layers.l8_monitoring.validation.metrics import evaluate_strategy
from src.inference import decision

import argparse

parser = argparse.ArgumentParser(description="Optimize ML Pipeline")
parser.add_argument('--symbol', type=str, default='EURUSD', help='Symbol to optimize (e.g., EURUSD, USDJPY, XAUUSD)')
parser.add_argument('--trials', type=int, default=1000, help='Number of Optuna trials')
parser.add_argument('--gpu', action='store_true',
                     help='Use GPU for LightGBM during tuning. Requires a GPU-enabled LightGBM build '
                          '(the default pip wheel is CPU-only). Falls back to CPU automatically if GPU init fails. '
                          'Note: on a dataset this size (a few thousand rows) GPU is unlikely to be faster than CPU '
                          '-- the actual bottleneck is the number of Optuna trials, which GPU does not parallelize.')
args = parser.parse_args()

target_symbol = args.symbol

print(f"Preparing Optimization Dataset for {target_symbol}...")
df_global = None
if mt5_client.connect():
    import MetaTrader5 as mt5
    df_global = mt5_client.fetch_ohlcv(target_symbol, mt5.TIMEFRAME_H4, datetime(2023, 1, 1), datetime.now())

if df_global is None or df_global.empty:
    print(f"Optimization failed: Could not fetch real data for {target_symbol}.")
    sys.exit(1)

# Exclude the same most-recent HOLDOUT_DAYS that train_and_save.py excludes, so
# hyperparameter tuning never sees the window later reported as the out-of-sample
# backtest. Tuning on that window would make "best_params" look good purely because
# they were chosen to fit data the backtest then re-measures on.
holdout_cutoff = datetime.now() - timedelta(days=decision.HOLDOUT_DAYS)
df_global = df_global[df_global.index < pd.Timestamp(holdout_cutoff)]
print(f"Tuning on data before {holdout_cutoff.date()} "
      f"(last {decision.HOLDOUT_DAYS} days held out, matching train_and_save.py / the backtest window). "
      f"{len(df_global)} bars available.")

# Engineer Features (identical to decision.compute_features)
df_global = decision.compute_features(df_global)
df_global = df_global.dropna()

FEATURES_FLAT = decision.FEATURES_FLAT

# GPU support is opt-in and falls back to CPU on failure -- see --gpu help text above
# for why it is unlikely to actually speed up tuning on this dataset/model combination.
USE_GPU = args.gpu
_gpu_warned = False


def _fit_tree(params, X_train, y_train):
    global _gpu_warned
    from src.layers.l3_primary_model.tree_models import TreeEnsemble
    tree = TreeEnsemble(params=params)
    try:
        tree.fit(X_train, y_train)
        return tree
    except Exception as e:
        if params.get('device_type') == 'gpu':
            if not _gpu_warned:
                print(f"[!] GPU LightGBM training failed ({e}); falling back to CPU for the rest of this run.")
                _gpu_warned = True
            cpu_params = dict(params)
            cpu_params.pop('device_type', None)
            tree = TreeEnsemble(params=cpu_params)
            tree.fit(X_train, y_train)
            return tree
        raise


def objective(trial):
    tp_multiplier = trial.suggest_float('tp_multiplier', 1.0, 3.0)
    sl_multiplier = trial.suggest_float('sl_multiplier', 1.0, 3.0)

    tree_depth = trial.suggest_int('tree_depth', 3, 7)
    learning_rate = trial.suggest_float('learning_rate', 0.01, 0.2, log=True)
    n_estimators = trial.suggest_int('n_estimators', 50, 200, step=50)

    confidence_threshold = trial.suggest_float('confidence_threshold', 0.45, 0.65)

    df = df_global.copy()

    labels = apply_triple_barrier(df, atr_multiplier_tp=tp_multiplier, atr_multiplier_sl=sl_multiplier, vertical_bars=10)
    df['label'] = labels['label'].fillna(0)
    df['t1'] = labels['t1']
    df = df.dropna()

    lgb_params = {
        'objective': 'multiclass',
        'num_class': 3,
        'metric': 'multi_logloss',
        'boosting_type': 'gbdt',
        'learning_rate': learning_rate,
        'max_depth': tree_depth,
        'n_estimators': n_estimators,
        'verbose': -1,
    }
    if USE_GPU:
        lgb_params['device_type'] = 'gpu'

    cv = PurgedKFold(n_splits=3, embargo_pct=0.01)
    all_fold_signals = []

    for train_idx, test_idx in cv.split(df, df[['t1']]):
        train_df = df.iloc[train_idx]
        test_df = df.iloc[test_idx]
        if train_df.empty or test_df.empty:
            continue

        # Regime: same RegimeHMM + router path as decision.py, fit on the train fold only.
        hmm = RegimeHMM(n_components=3, random_state=42)
        hmm.fit(train_df[['return', 'volatility']])
        train_regimes = decision.compute_regime(hmm, train_df)
        test_regimes = decision.compute_regime(hmm, test_df)

        # Primary signal: tree-only, matching decision.compute_primary_signal exactly
        # (the live/backtest producer). No CNN, no ensemble -- using a different
        # producer here than the one actually traded is what made earlier tuned
        # params not transfer to live/backtest performance.
        y_train_tree = train_df['label'].map({-1: 0, 0: 1, 1: 2})
        tree = _fit_tree(lgb_params, train_df[FEATURES_FLAT], y_train_tree)
        primary_train = decision.compute_primary_signal(tree, train_df)
        primary_test = decision.compute_primary_signal(tree, test_df)

        # Meta-learner: fit ONLY on the train fold, then evaluate on the held-out test
        # fold. Fitting and predicting on the same fold (as the old code did) leaks the
        # test fold's own labels into its confidence estimate, inflating the reported
        # Sharpe and picking thresholds that do not generalize.
        meta = MetaLearner()
        actual_outcomes_train = (primary_train == train_df['label']).astype(int)
        meta.fit(primary_train, train_regimes, train_df['volatility'], actual_outcomes_train)

        p_correct = meta.predict_trust_probability(primary_test, test_regimes, test_df['volatility'])
        p_correct = pd.Series(np.asarray(p_correct), index=test_df.index)

        final_signal = primary_test.where(p_correct >= confidence_threshold, 0)
        all_fold_signals.append(final_signal)

    if not all_fold_signals:
        return -10.0

    final_signals_series = pd.concat(all_fold_signals).sort_index()
    test_returns = df['return'].reindex(final_signals_series.index)

    metrics = evaluate_strategy(final_signals_series, test_returns)
    return metrics['strat_net']['Sharpe']


if __name__ == "__main__":
    print(f"=== Starting Optuna Hyperparameter Optimization ({args.trials} trials, GPU={'on' if USE_GPU else 'off'}) ===")
    study = optuna.create_study(direction="maximize")
    study.optimize(objective, n_trials=args.trials)

    print("\nOptimization Finished.")
    print("Best Trial:")
    print("  Sharpe Ratio:", study.best_value)
    print("  Params:")
    for key, value in study.best_params.items():
        print(f"    {key}: {value}")

    best_file = f'best_params_{target_symbol}.json'
    with open(best_file, 'w') as f:
        json.dump(study.best_params, f, indent=4)
    print(f"\n[SUCCESS] Best parameters saved to {best_file}!")
