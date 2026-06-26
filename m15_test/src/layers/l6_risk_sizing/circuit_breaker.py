import pandas as pd

class CircuitBreaker:
    """
    Monitors portfolio equity and triggers a halt if drawdown exceeds a critical threshold.
    """
    def __init__(self, max_drawdown_limit: float = 0.15):
        self.max_drawdown_limit = max_drawdown_limit
        self.peak_equity = 0.0
        self.is_halted = False

    def update(self, current_equity: float) -> bool:
        """
        Update peak equity and check for breach.
        Returns True if the system is halted.
        """
        if current_equity > self.peak_equity:
            self.peak_equity = current_equity
            
        drawdown = (self.peak_equity - current_equity) / self.peak_equity if self.peak_equity > 0 else 0.0
        
        if drawdown >= self.max_drawdown_limit:
            self.is_halted = True
            
        return self.is_halted

    def reset(self):
        """Manual override to reset the circuit breaker."""
        self.is_halted = False
        self.peak_equity = 0.0 # Will re-calibrate on next update
