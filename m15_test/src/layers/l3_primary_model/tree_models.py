import pandas as pd
import lightgbm as lgb
from typing import Dict, Any

class TreeEnsemble:
    """
    Wrapper for LightGBM/CatBoost models tailored for directional prediction (SIDE).
    """
    def __init__(self, params: Dict[str, Any] = None):
        self.params = params or {
            'objective': 'multiclass',
            'num_class': 3, # -1, 0, 1 mapped to 0, 1, 2
            'metric': 'multi_logloss',
            'boosting_type': 'gbdt',
            'learning_rate': 0.05,
            'num_leaves': 31,
            'verbose': -1
        }
        self.model = None

    def fit(self, X_train: pd.DataFrame, y_train: pd.Series, X_val: pd.DataFrame = None, y_val: pd.Series = None):
        """
        Fit the tree model. Expects labels to be 0 (short), 1 (flat), 2 (long).
        """
        train_data = lgb.Dataset(X_train, label=y_train)
        valid_sets = [train_data]
        if X_val is not None and y_val is not None:
            val_data = lgb.Dataset(X_val, label=y_val, reference=train_data)
            valid_sets.append(val_data)
            
        self.model = lgb.train(
            self.params,
            train_data,
            num_boost_round=1000,
            valid_sets=valid_sets,
            callbacks=[lgb.early_stopping(stopping_rounds=50)] if X_val is not None else []
        )

    def predict_proba(self, X: pd.DataFrame) -> pd.DataFrame:
        """
        Output probabilities for each class.
        """
        if self.model is None:
            raise ValueError("Model not fitted.")
            
        probas = self.model.predict(X)
        return pd.DataFrame(probas, index=X.index, columns=['prob_short', 'prob_flat', 'prob_long'])
