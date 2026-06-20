import sys
import os
import pandas as pd
import numpy as np
import torch

sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), '..')))
from src.layers.l3_primary_model.tree_models import TreeEnsemble
from src.layers.l3_primary_model.cnn_model import TemporalCNN, CNNWrapper
from src.layers.l3_primary_model.ensemble import PrimaryEnsembleRouter

# Mock LightGBM tree ensemble since training LightGBM on dummy data without real targets might crash or be meaningless
class MockTreeEnsemble:
    def predict_proba(self, X):
        # returns equal probas
        probas = np.ones((X.shape[0], 3)) / 3.0
        return pd.DataFrame(probas, index=X.index, columns=['prob_short', 'prob_flat', 'prob_long'])

def test_l3_primary():
    print("Testing L3 Primary Ensemble Router...")
    
    seq_len = 20
    num_features = 10
    batch_size = 50
    
    dates = pd.date_range(start='2023-01-01', periods=batch_size, freq='4h')
    
    # Dummy flat features for Tree
    df_flat = pd.DataFrame(np.random.randn(batch_size, num_features), index=dates)
    
    # Dummy sequence tensor for CNN (batch, channels, seq_len)
    X_tensor = torch.randn(batch_size, num_features, seq_len)
    
    # Dummy regime states
    regimes = pd.Series(np.random.choice(['trend', 'range', 'shock', 'neutral'], batch_size), index=dates)
    
    # Instantiate models
    tree = MockTreeEnsemble()
    
    cnn_net = TemporalCNN(num_features=num_features, sequence_length=seq_len, num_classes=3)
    cnn = CNNWrapper(model=cnn_net)
    
    router = PrimaryEnsembleRouter(tree_model=tree, cnn_model=cnn)
    
    # Predict
    final_probas = router.predict_proba(df_flat, X_tensor, regimes)
    
    print("\nFinal Probabilities Head:")
    print(final_probas.head())
    
    # Assertions
    assert final_probas.shape == (batch_size, 3)
    assert np.allclose(final_probas.sum(axis=1), 1.0) # Probas must sum to 1
    
    # Check shock override logic
    shock_indices = regimes[regimes == 'shock'].index
    if len(shock_indices) > 0:
        shock_probas = final_probas.loc[shock_indices]
        assert (shock_probas['prob_flat'] == 1.0).all(), "Shock regime did not override to 100% flat."
        
    print("\nL3 Primary Signal Test Passed.")

if __name__ == "__main__":
    test_l3_primary()
