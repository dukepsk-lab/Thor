import os
import joblib
import torch
import numpy as np
import pandas as pd
from typing import Dict, Any

from src.layers.l1_features.trend_memory import calculate_ker
from src.layers.l1_features.volatility import calculate_yang_zhang, calculate_atr
from src.layers.l3_primary_model.cnn_model import TemporalCNN

class SymbolPredictor:
    """
    Wraps the trained models (HMM, LGBM, CNN, MetaLearner) for a single symbol
    to perform vectorized/batch inference for backtesting.
    """
    def __init__(self, symbol: str):
        self.symbol = symbol
        self.model_dir = f'models/{symbol}'
        self.loaded = False
        
    def load_models(self):
        if not os.path.exists(f'{self.model_dir}/hmm_model.pkl'):
            raise FileNotFoundError(f"Models for {self.symbol} not found in {self.model_dir}")
            
        print(f"[{self.symbol}] Loading models...")
        self.hmm = joblib.load(f'{self.model_dir}/hmm_model.pkl')
        
        import lightgbm as lgb
        self.tree = lgb.Booster(model_file=f'{self.model_dir}/lgb_model.txt')
        
        # Load CNN
        if self.symbol == 'XAUUSD':
            num_feats = 3
        elif self.symbol == 'EURUSD':
            num_feats = 4
        else:
            num_feats = 2
        self.cnn = TemporalCNN(num_features=num_feats, sequence_length=10, num_classes=3)
        self.cnn.load_state_dict(torch.load(f'{self.model_dir}/cnn_model.pt', weights_only=True))
        self.cnn.eval()
        
        self.meta = joblib.load(f'{self.model_dir}/meta_model.pkl')
        self.loaded = True
        
    def generate_predictions(self, df: pd.DataFrame) -> pd.DataFrame:
        """
        Takes raw OHLCV DataFrame, calculates features, and returns a DF with:
        ['signal', 'confidence', 'volatility', 'return']
        """
        if not self.loaded:
            self.load_models()
            
        print(f"[{self.symbol}] Calculating features...")
        df_feats = df.copy()
        df_feats['return'] = df_feats['close'].pct_change().fillna(0)
        df_feats['volatility'] = calculate_yang_zhang(df_feats, period=20).bfill()
        df_feats['atr'] = calculate_atr(df_feats, period=14).bfill()
        df_feats['hurst'] = 0.5  # Static for now as in training
        df_feats['ker'] = calculate_ker(df_feats, period=10).bfill()
        
        # Must drop NA to ensure clean inference
        df_feats = df_feats.dropna()
        
        # 1. Regime Prediction
        regime_features = df_feats[['return', 'volatility']].values
        regimes = self.hmm.predict(regime_features)
        df_feats['regime'] = regimes
        
        # 2. Primary Signal (LGBM)
        if self.symbol == 'XAUUSD':
            lgbm_features = df_feats[['return', 'volatility', 'hurst']]
        elif self.symbol == 'EURUSD':
            lgbm_features = df_feats[['return', 'volatility', 'hurst', 'ker']]
        else:
            lgbm_features = df_feats[['return', 'volatility']]
        # predict() returns probabilities for multiclass. shape: (N, 3)
        lgbm_probs = self.tree.predict(lgbm_features)
        # Convert class indices 0,1,2 back to -1,0,1
        lgbm_preds = np.argmax(lgbm_probs, axis=1) - 1
        df_feats['primary_signal'] = lgbm_preds
        
        # 3. Meta-Learner Confidence
        # _prepare_features in MetaLearner expects pd.Series for primary_signal, regime, volatility
        # We can just call predict_proba directly if we bypass the class wrapper, but better use the wrapper
        # The meta model saved is CalibratedClassifierCV or whatever we used as estimator
        # We need to construct X the same way _prepare_features did:
        # df['primary_signal'], df['volatility'], one-hot regimes.
        
        # Reconstruct Meta Features manually because we only dumped the estimator
        meta_X = pd.DataFrame(index=df_feats.index)
        meta_X['primary_signal'] = df_feats['primary_signal']
        meta_X['volatility'] = df_feats['volatility']
        
        # One-hot encode regimes (must match training which had regime_state_0, etc.)
        regime_dummies = pd.get_dummies(df_feats['regime'], prefix='regime_state')
        # Ensure all 3 regimes exist
        for r in range(3):
            col = f'regime_state_{r}'
            if col not in regime_dummies.columns:
                regime_dummies[col] = 0
                
        # Reorder columns to match training exactly
        regime_dummies = regime_dummies[[f'regime_state_{r}' for r in range(3)]]
        meta_X = pd.concat([meta_X, regime_dummies], axis=1)
        
        # Meta returns pd.Series of class 1 probabilities
        confidences = self.meta.predict_proba(meta_X)
        df_feats['confidence'] = confidences.values
        
        # Select only required output columns
        out = df_feats[['primary_signal', 'confidence', 'volatility', 'return', 'close', 'atr']].copy()
        out.rename(columns={'primary_signal': 'signal'}, inplace=True)
        return out
