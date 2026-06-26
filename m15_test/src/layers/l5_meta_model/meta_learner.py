import pandas as pd
from src.layers.l5_meta_model.calibration import CalibratedMetaEstimator

class MetaLearner:
    """
    The 'Self-Trust' layer. Consumes primary model outputs, regime states, 
    and volatility features to predict P(Primary Signal is Correct).
    """
    def __init__(self, estimator: CalibratedMetaEstimator = None):
        self.estimator = estimator or CalibratedMetaEstimator()
        
    def _prepare_features(self, primary_signals: pd.Series, regimes: pd.Series, volatility: pd.Series) -> pd.DataFrame:
        """
        Constructs the meta-feature matrix.
        """
        df = pd.DataFrame(index=primary_signals.index)
        df['primary_signal'] = primary_signals
        df['volatility'] = volatility
        
        # One-hot encode regimes
        regime_dummies = pd.get_dummies(regimes, prefix='regime')
        df = pd.concat([df, regime_dummies], axis=1)
        
        return df.fillna(0)

    def fit(self, primary_signals: pd.Series, regimes: pd.Series, volatility: pd.Series, actual_outcomes: pd.Series):
        """
        actual_outcomes: 1 if primary signal hit take-profit/made money, 0 if it hit stop-loss/timed out.
        """
        X = self._prepare_features(primary_signals, regimes, volatility)
        self.estimator.fit(X, actual_outcomes)

    def predict_trust_probability(self, primary_signals: pd.Series, regimes: pd.Series, volatility: pd.Series) -> pd.Series:
        """
        Returns the calibrated P(correct).
        """
        X = self._prepare_features(primary_signals, regimes, volatility)
        return self.estimator.predict_proba(X)
