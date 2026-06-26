import sys
import os

sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), '..')))
from src.layers.l6_risk_sizing.sizing import calculate_base_size, apply_confidence_scaling
from src.layers.l6_risk_sizing.correlation_cap import apply_correlation_cap
from src.layers.l6_risk_sizing.circuit_breaker import CircuitBreaker

def test_l6_risk():
    print("Testing L6 Risk & Position Sizing...")
    
    # 1. Base Size
    balance = 10000.0
    risk_pct = 0.01 # 1% risk = $100
    atr = 0.0050 # 50 pips
    multiplier = 2.0 # stop at 100 pips
    
    base_size = calculate_base_size(balance, risk_pct, atr, multiplier)
    print(f"\nBase Size (Risk $100, Stop 100 pips): {base_size}")
    assert base_size == 100.0 / (0.0100), "Base size math incorrect."
    
    # 2. Confidence Scaling
    # High confidence
    high_conf_size = apply_confidence_scaling(base_size, p_correct=0.8, threshold=0.5)
    print(f"Scaled Size (80% confidence): {high_conf_size}")
    assert high_conf_size > 0
    
    # Low confidence (below threshold)
    low_conf_size = apply_confidence_scaling(base_size, p_correct=0.4, threshold=0.5)
    print(f"Scaled Size (40% confidence): {low_conf_size}")
    assert low_conf_size == 0.0
    
    # 3. Correlation Cap
    sizes = {'EURUSD': 150.0, 'GBPUSD': 100.0} # Total 250
    cap = 200.0
    capped = apply_correlation_cap(sizes, None, cap, balance)
    print(f"\nCapped Sizes (Limit 200): {capped}")
    assert sum(capped.values()) <= 200.0001, "Correlation cap failed to scale down."
    
    # 4. Circuit Breaker
    cb = CircuitBreaker(max_drawdown_limit=0.15)
    cb.update(10000) # Peak 10k
    cb.update(9000)  # DD 10% -> OK
    print(f"\nCircuit Breaker status at 10% DD: {'Halted' if cb.is_halted else 'Active'}")
    assert not cb.is_halted
    
    cb.update(8000)  # DD 20% -> Halt
    print(f"Circuit Breaker status at 20% DD: {'Halted' if cb.is_halted else 'Active'}")
    assert cb.is_halted
    
    print("\nL6 Risk Sizing Test Passed.")

if __name__ == "__main__":
    test_l6_risk()
