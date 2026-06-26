import pandas as pd
from typing import Dict, Any

from src.layers.l2_regime.hmm_detector import RegimeHMM
from src.layers.l2_regime.gating import calculate_gating_signals

class RegimeRouter:
    """
    Synthesizes HMM probabilities and hard gating logic to output a definitive regime state.
    """
    def __init__(self, hmm_model: RegimeHMM):
        self.hmm = hmm_model

    def determine_regime(self, features: pd.DataFrame) -> pd.DataFrame:
        """
        Outputs the combined regime state.
        Returns a DataFrame with the HMM probabilities, the hard gating signal, and the final synthetic regime.
        """
        out = pd.DataFrame(index=features.index)
        
        # 1. Get HMM Probabilities
        if self.hmm.is_fitted:
            hmm_probas = self.hmm.predict_proba(features[['return', 'volatility']]) # Assuming these cols exist
            out = pd.concat([out, hmm_probas], axis=1)
            # Assign base regime based on highest prob
            out['hmm_state'] = hmm_probas.idxmax(axis=1)
        else:
            out['hmm_state'] = 'unknown'
            
        # 2. Get Hard Gating Signals
        out['gate_state'] = calculate_gating_signals(features)
        
        # 3. Synthesize Final Regime
        # Simple logic: If gate is strong ('trend' or 'range'), override HMM. Else, use HMM.
        out['final_regime'] = out['hmm_state']
        
        # Override logic
        mask_override = out['gate_state'] != 'neutral'
        out.loc[mask_override, 'final_regime'] = out.loc[mask_override, 'gate_state']
        
        return out
