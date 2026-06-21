"""
Single source of truth for turning OHLCV bars into trade decisions.

Every code path -- training (to build meta-learner inputs), backtesting, the live
bot, and the dashboard -- must call these functions so that the regime label, the
primary signal, and the meta confidence are computed identically. Historically each
path reimplemented this logic slightly differently (different regime encodings,
different primary-signal producers), which made live trading diverge from the
backtest. Centralising it here removes that class of bug by construction.
"""
import os
import json
import joblib
import numpy as np
import pandas as pd
from types import SimpleNamespace

from src.layers.l1_features.trend_memory import calculate_ker
from src.layers.l1_features.volatility import calculate_yang_zhang, calculate_atr
from src.layers.l2_regime.hmm_detector import RegimeHMM
from src.layers.l2_regime.router import RegimeRouter
from src.layers.l5_meta_model.meta_learner import MetaLearner

# Flat feature set fed to the LightGBM tree (order matters).
FEATURES_FLAT = ['return', 'volatility', 'hurst', 'ker']

# The most recent N days are held out of training and used as the out-of-sample
# backtest window, so reported backtest metrics are never measured on data the
# models were trained on. Shared by train_and_save.py and the backtester.
HOLDOUT_DAYS = 90


def compute_features(df: pd.DataFrame) -> pd.DataFrame:
    """Canonical feature computation shared by every code path."""
    out = df.copy()
    out['return'] = out['close'].pct_change().fillna(0)
    out['volatility'] = calculate_yang_zhang(out, period=20).bfill()
    out['atr'] = calculate_atr(out, period=14).bfill()
    out['hurst'] = 0.5  # static placeholder; kept identical across train/live
    out['ker'] = calculate_ker(out, period=10).bfill()
    return out


def wrap_hmm(hmm, n_components: int = 3) -> RegimeHMM:
    """
    Return a RegimeHMM wrapper so the router can be used uniformly.

    ``hmm`` may already be a RegimeHMM (training) or a raw GaussianHMM loaded from
    disk (live / backtest, which joblib-dump only the underlying ``hmm.model``).
    """
    if isinstance(hmm, RegimeHMM):
        return hmm
    wrapper = RegimeHMM(n_components=n_components)
    wrapper.model = hmm
    wrapper.is_fitted = True
    return wrapper


def compute_regime(hmm, df_feats: pd.DataFrame) -> pd.Series:
    """Canonical regime label: router.final_regime, computed the same way everywhere."""
    router = RegimeRouter(wrap_hmm(hmm))
    return router.determine_regime(df_feats)['final_regime']


def _tree_probas(tree, X: pd.DataFrame) -> np.ndarray:
    """Normalise tree output to an (N, 3) ndarray, accepting a TreeEnsemble or raw Booster."""
    if hasattr(tree, 'predict_proba'):
        return np.asarray(tree.predict_proba(X))
    return np.asarray(tree.predict(X))


def compute_primary_signal(tree, df_feats: pd.DataFrame) -> pd.Series:
    """
    Canonical primary signal: LightGBM tree argmax mapped to {-1, 0, 1}.

    Tree-only -- the CNN is intentionally excluded so the producer is identical in
    training, backtest, and live (the CNN is not trained, see train_and_save.py).
    """
    probas = _tree_probas(tree, df_feats[FEATURES_FLAT])
    classes = np.argmax(probas, axis=1)
    return pd.Series(classes - 1, index=df_feats.index)


def generate_decisions(models, df_feats: pd.DataFrame, confidence_threshold: float = None) -> pd.DataFrame:
    """
    Produce the full decision frame for an already-featurised DataFrame.

    ``models`` must expose ``hmm``, ``tree`` and ``meta`` (a fitted MetaLearner).
    Returns columns: regime, primary_signal, p_correct, final_signal.

    The trade rule is the canonical one used by the backtest:
        final_signal = primary_signal  if p_correct >= threshold  else 0
    """
    if confidence_threshold is None:
        confidence_threshold = getattr(models, 'confidence_threshold', 0.5)

    regime = compute_regime(models.hmm, df_feats)
    primary = compute_primary_signal(models.tree, df_feats)

    p_correct = models.meta.predict_trust_probability(primary, regime, df_feats['volatility'])
    p_correct = pd.Series(np.asarray(p_correct), index=df_feats.index)

    final = primary.where(p_correct >= confidence_threshold, 0)

    return pd.DataFrame({
        'regime': regime,
        'primary_signal': primary,
        'p_correct': p_correct,
        'final_signal': final,
    }, index=df_feats.index)


def _load_threshold(symbol: str) -> float:
    for path in (f'models/{symbol}/best_params_{symbol}.json', f'best_params_{symbol}.json'):
        if os.path.exists(path):
            with open(path) as f:
                return json.load(f).get('confidence_threshold', 0.5)
    return 0.5


def load_models(symbol: str, load_cnn: bool = False) -> SimpleNamespace:
    """
    Load the trained models for a symbol into a namespace usable by generate_decisions.

    Raises a clear error if meta_model.pkl predates the MetaLearner-wrapper format,
    so an out-of-contract model can never silently produce divergent live signals.
    """
    model_dir = f'models/{symbol}'
    if not os.path.exists(f'{model_dir}/hmm_model.pkl'):
        raise FileNotFoundError(
            f"Models for {symbol} not found in {model_dir}. Run train_and_save.py first."
        )

    import lightgbm as lgb
    hmm = joblib.load(f'{model_dir}/hmm_model.pkl')
    tree = lgb.Booster(model_file=f'{model_dir}/lgb_model.txt')
    meta = joblib.load(f'{model_dir}/meta_model.pkl')

    if not isinstance(meta, MetaLearner):
        raise TypeError(
            f"{model_dir}/meta_model.pkl is an outdated format ({type(meta).__name__}). "
            "Retrain with train_and_save.py so the live/backtest feature contract matches."
        )

    ns = SimpleNamespace(
        symbol=symbol,
        hmm=hmm,
        tree=tree,
        meta=meta,
        confidence_threshold=_load_threshold(symbol),
        cnn=None,
    )

    if load_cnn:
        import torch
        from src.layers.l3_primary_model.cnn_model import TemporalCNN
        cnn = TemporalCNN(num_features=4, sequence_length=10, num_classes=3)
        cnn.load_state_dict(torch.load(f'{model_dir}/cnn_model.pt', weights_only=True))
        cnn.eval()
        ns.cnn = cnn

    return ns
