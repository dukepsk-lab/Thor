import pandas as pd
from sklearn.calibration import CalibratedClassifierCV
from sklearn.ensemble import RandomForestClassifier

class CalibratedMetaEstimator:
    """
    Wraps a base classifier with Platt scaling (sigmoid) or Isotonic regression 
    to ensure output probabilities are strictly calibrated.
    """
    def __init__(self, base_estimator=None, method='isotonic', cv=5):
        if base_estimator is None:
            # Default to a random forest to capture non-linear meta interactions
            base_estimator = RandomForestClassifier(n_estimators=100, max_depth=5, random_state=42)
            
        self.calibrated_clf = CalibratedClassifierCV(
            estimator=base_estimator, 
            method=method, 
            cv=cv
        )

    def fit(self, X: pd.DataFrame, y: pd.Series):
        """
        Fits the base estimator and the calibration regressor using cross-validation.
        y should be binary: 1 if the primary model was correct, 0 if incorrect.
        """
        self.calibrated_clf.fit(X, y)

    def predict_proba(self, X: pd.DataFrame) -> pd.Series:
        """
        Returns the calibrated probability of the primary signal being correct (class 1).
        """
        probas = self.calibrated_clf.predict_proba(X)
        return pd.Series(probas[:, 1], index=X.index, name='p_correct')
