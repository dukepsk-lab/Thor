import numpy as np
import pandas as pd

from src.inference import decision

class SymbolPredictor:
    """
    Wraps the trained models (HMM, LGBM, MetaLearner) for a single symbol to perform
    vectorized/batch inference for backtesting. Uses the shared decision path
    (src/inference/decision.py) so backtest signals match live trading exactly.
    """
    def __init__(self, symbol: str):
        self.symbol = symbol
        self.model_dir = f'models/{symbol}'
        self.loaded = False
        self.models = None

    def load_models(self):
        print(f"[{self.symbol}] Loading models...")
        self.models = decision.load_models(self.symbol, load_cnn=False)
        # Expose individual handles for backwards compatibility.
        self.hmm = self.models.hmm
        self.tree = self.models.tree
        self.meta = self.models.meta
        self.loaded = True

    def generate_predictions(self, df: pd.DataFrame) -> pd.DataFrame:
        """
        Takes raw OHLCV DataFrame, calculates features, and returns a DF with:
        ['signal', 'confidence', 'volatility', 'return', 'close', 'atr']
        """
        if not self.loaded:
            self.load_models()

        print(f"[{self.symbol}] Calculating features...")
        df_feats = decision.compute_features(df).dropna()

        regime = decision.compute_regime(self.models.hmm, df_feats)
        primary = decision.compute_primary_signal(self.models.tree, df_feats)
        confidence = self.models.meta.predict_trust_probability(
            primary, regime, df_feats['volatility']
        )

        out = pd.DataFrame(index=df_feats.index)
        out['signal'] = primary
        out['confidence'] = np.asarray(confidence)
        out['volatility'] = df_feats['volatility']
        out['return'] = df_feats['return']
        out['close'] = df_feats['close']
        out['atr'] = df_feats['atr']
        return out
