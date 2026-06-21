import pandas as pd
from src.layers.l5_meta_model.calibration import CalibratedMetaEstimator

class MetaLearner:
    """
    The 'Self-Trust' layer. Consumes primary model outputs, regime states,
    and volatility features to predict P(Primary Signal is Correct).
    """
    def __init__(self, estimator: CalibratedMetaEstimator = None):
        self.estimator = estimator or CalibratedMetaEstimator()
        # Columns seen at fit time. Persisted so that single-row / partial-category
        # inference (e.g. one live bar that only contains one regime value) is
        # reindexed to the exact training matrix instead of silently producing a
        # different set of one-hot columns.
        self.feature_columns_ = None

    def _prepare_features(self, primary_signals: pd.Series, regimes: pd.Series, volatility: pd.Series) -> pd.DataFrame:
        """
        Constructs the meta-feature matrix.

        When ``feature_columns_`` is known (i.e. after fit), the result is reindexed
        to those exact columns so inference always matches the trained contract.
        """
        df = pd.DataFrame(index=primary_signals.index)
        df['primary_signal'] = primary_signals
        df['volatility'] = volatility

        # One-hot encode regimes
        regime_dummies = pd.get_dummies(regimes, prefix='regime')
        df = pd.concat([df, regime_dummies], axis=1)
        df = df.fillna(0)

        if self.feature_columns_ is not None:
            # Add any missing trained columns as 0, drop unseen ones, and enforce order.
            df = df.reindex(columns=self.feature_columns_, fill_value=0)

        return df

    def fit(self, primary_signals: pd.Series, regimes: pd.Series, volatility: pd.Series, actual_outcomes: pd.Series):
        """
        actual_outcomes: 1 if primary signal hit take-profit/made money, 0 if it hit stop-loss/timed out.
        """
        X = self._prepare_features(primary_signals, regimes, volatility)
        self.feature_columns_ = list(X.columns)
        self.estimator.fit(X, actual_outcomes)

    def predict_trust_probability(self, primary_signals: pd.Series, regimes: pd.Series, volatility: pd.Series) -> pd.Series:
        """
        Returns the calibrated P(correct).
        """
        X = self._prepare_features(primary_signals, regimes, volatility)
        return self.estimator.predict_proba(X)
