"""
Parity test: the shared decision path must produce identical meta-feature columns
and identical confidence whether it is called on a full batch (backtest) or one row
at a time (live bot / dashboard). This is the regression guard for the live-vs-backtest
divergence that previously came from each path building meta features differently.

Uses lightweight stand-ins for the HMM and tree so it runs without MT5, LightGBM, or
trained model files, but exercises the REAL RegimeRouter + MetaLearner code.
"""
import sys
import os
import numpy as np
import pandas as pd
from types import SimpleNamespace

sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), '..')))

from src.layers.l5_meta_model.meta_learner import MetaLearner
from src.inference import decision


class DummyHMMModel:
    """Stands in for a fitted GaussianHMM: deterministic 3-state probabilities."""
    def predict_proba(self, X):
        X = np.asarray(X)
        out = np.zeros((len(X), 3))
        for i, row in enumerate(X):
            r = row[0]
            if r > 0:
                out[i] = [0.7, 0.2, 0.1]
            elif r < 0:
                out[i] = [0.1, 0.2, 0.7]
            else:
                out[i] = [0.2, 0.6, 0.2]
        return out

    def predict(self, X):
        return np.argmax(self.predict_proba(X), axis=1)


class DummyTree:
    """Stands in for a LightGBM Booster: deterministic directional probabilities."""
    def predict(self, X):
        X = np.asarray(X)
        out = np.zeros((len(X), 3))
        for i, row in enumerate(X):
            r = row[0]
            if r > 0.001:
                out[i] = [0.1, 0.2, 0.7]
            elif r < -0.001:
                out[i] = [0.7, 0.2, 0.1]
            else:
                out[i] = [0.2, 0.6, 0.2]
        return out


def _make_feats(n=200, seed=0):
    rng = np.random.default_rng(seed)
    idx = pd.date_range('2023-01-01', periods=n, freq='4h')
    df = pd.DataFrame(index=idx)
    df['return'] = rng.normal(0, 0.003, n)
    df['volatility'] = rng.uniform(0.05, 0.3, n)
    df['atr'] = rng.uniform(0.0005, 0.002, n)
    df['hurst'] = 0.5
    df['ker'] = rng.uniform(0.1, 0.9, n)
    return df


def test_meta_columns_stable_single_row():
    """A single-row prediction must reindex to the exact trained columns."""
    feats = _make_feats()
    hmm = DummyHMMModel()
    tree = DummyTree()

    regime = decision.compute_regime(hmm, feats)
    primary = decision.compute_primary_signal(tree, feats)
    outcomes = (primary.values == np.sign(feats['return'].values)).astype(int)

    meta = MetaLearner()
    meta.fit(primary, regime, feats['volatility'], pd.Series(outcomes, index=feats.index))

    trained_cols = list(meta.feature_columns_)
    # Single-row prep must yield exactly the trained columns, in order.
    one = feats.iloc[[10]]
    X1 = meta._prepare_features(
        decision.compute_primary_signal(tree, one),
        decision.compute_regime(hmm, one),
        one['volatility'],
    )
    assert list(X1.columns) == trained_cols, (list(X1.columns), trained_cols)
    assert len(X1) == 1
    print("trained meta columns:", trained_cols)


def test_batch_vs_single_row_identical():
    """generate_decisions must give the same p_correct/final whether batch or per-row."""
    feats = _make_feats()
    hmm = DummyHMMModel()
    tree = DummyTree()

    regime = decision.compute_regime(hmm, feats)
    primary = decision.compute_primary_signal(tree, feats)
    outcomes = (primary.values == np.sign(feats['return'].values)).astype(int)

    meta = MetaLearner()
    meta.fit(primary, regime, feats['volatility'], pd.Series(outcomes, index=feats.index))

    models = SimpleNamespace(hmm=hmm, tree=tree, meta=meta, confidence_threshold=0.5)

    batch = decision.generate_decisions(models, feats)

    # Re-run one bar at a time (the live path) and compare.
    for k in (5, 50, 123, 199):
        one = feats.iloc[[k]]
        single = decision.generate_decisions(models, one)
        assert abs(single['p_correct'].iloc[0] - batch['p_correct'].iloc[k]) < 1e-9, k
        assert single['final_signal'].iloc[0] == batch['final_signal'].iloc[k], k
        assert single['regime'].iloc[0] == batch['regime'].iloc[k], k
        assert single['primary_signal'].iloc[0] == batch['primary_signal'].iloc[k], k

    print("batch vs single-row parity OK across sampled bars")


if __name__ == "__main__":
    test_meta_columns_stable_single_row()
    test_batch_vs_single_row_identical()
    print("\nAll inference-parity tests passed.")
