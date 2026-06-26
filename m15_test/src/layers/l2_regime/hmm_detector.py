import numpy as np
import pandas as pd
from hmmlearn.hmm import GaussianHMM
import joblib
import os

class RegimeHMM:
    """
    Hidden Markov Model to classify market regimes into:
    0: Trending, 1: Ranging, 2: Shock
    """
    def __init__(self, n_components: int = 3, random_state: int = 42):
        self.n_components = n_components
        self.model = GaussianHMM(n_components=self.n_components, covariance_type="diag", random_state=random_state)
        self.is_fitted = False

    def fit(self, features: pd.DataFrame):
        """
        Fit the HMM on historical features.
        Expected features typically include Returns, Log Volatility, etc.
        """
        X = features.values
        self.model.fit(X)
        self.is_fitted = True

    def predict(self, features: pd.DataFrame) -> pd.Series:
        """
        Predict the most likely hidden state sequence.
        Returns a Series of state labels.
        """
        if not self.is_fitted:
            raise ValueError("HMM is not fitted yet.")
        
        X = features.values
        states = self.model.predict(X)
        return pd.Series(states, index=features.index)

    def predict_proba(self, features: pd.DataFrame) -> pd.DataFrame:
        """
        Predict the probability of each hidden state.
        """
        if not self.is_fitted:
            raise ValueError("HMM is not fitted yet.")
        
        X = features.values
        probas = self.model.predict_proba(X)
        return pd.DataFrame(probas, index=features.index, columns=[f'state_{i}' for i in range(self.n_components)])

    def save(self, filepath: str):
        joblib.dump(self.model, filepath)

    def load(self, filepath: str):
        if os.path.exists(filepath):
            self.model = joblib.load(filepath)
            self.is_fitted = True
        else:
            raise FileNotFoundError(f"Model file not found: {filepath}")
