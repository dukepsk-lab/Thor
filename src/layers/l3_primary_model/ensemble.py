import pandas as pd

class PrimaryEnsembleRouter:
    """
    Routes and dynamically weights predictions from the CNN and Tree models 
    based on the current market regime provided by Layer 2.
    """
    def __init__(self, tree_model, cnn_model):
        self.tree_model = tree_model
        self.cnn_model = cnn_model

    def predict_proba(self, features_flat: pd.DataFrame, features_seq, regimes: pd.Series) -> pd.DataFrame:
        """
        Combines predictions conditionally.
        features_flat: Dataframe for Tree model.
        features_seq: Tensor input for CNN model.
        regimes: Series containing regime labels ('trend', 'range', 'neutral', 'shock')
        """
        # Get raw probabilities
        tree_probas = self.tree_model.predict_proba(features_flat)
        cnn_probas = self.cnn_model.predict_proba(features_seq, features_flat.index)
        
        final_probas = pd.DataFrame(index=features_flat.index, columns=tree_probas.columns)
        
        # Example dynamic weighting logic:
        # If 'trend', rely more on Tree (momentum logic)
        # If 'range', rely more on CNN (structural logic)
        # If 'shock', stand down (force flat probability to 1.0)
        
        for idx in features_flat.index:
            regime = regimes.loc[idx]
            
            if regime == 'trend':
                w_tree, w_cnn = 0.8, 0.2
            elif regime == 'range':
                w_tree, w_cnn = 0.3, 0.7
            elif regime == 'shock':
                # Force flat
                final_probas.loc[idx] = [0.0, 1.0, 0.0]
                continue
            else:
                w_tree, w_cnn = 0.5, 0.5
                
            final_probas.loc[idx] = (tree_probas.loc[idx] * w_tree) + (cnn_probas.loc[idx] * w_cnn)
            
        return final_probas
