import MetaTrader5 as mt5
import datetime

class ExecutionGuards:
    """
    Pre-trade safety checks to block orders in adverse conditions.
    """
    def __init__(self, max_spread_points: int = 20):
        self.max_spread_points = max_spread_points

    def check_spread(self, symbol: str) -> bool:
        """
        Check if the current spread is within acceptable limits.
        Returns True if safe to trade, False if spread is too wide.
        """
        # In a real environment, mt5 needs to be initialized. 
        # We rely on the MT5Client from L0 for the connection state.
        symbol_info = mt5.symbol_info(symbol)
        if symbol_info is None:
            print(f"Guards: Failed to get symbol info for {symbol}")
            return False
            
        current_spread = symbol_info.spread
        if current_spread > self.max_spread_points:
            print(f"Guards: Trade blocked. Spread ({current_spread}) exceeds max allowed ({self.max_spread_points}).")
            return False
            
        return True

    def check_news_window(self, current_time: datetime.datetime) -> bool:
        """
        Placeholder for an economic calendar API check.
        Returns True if safe (no tier-1 news nearby).
        """
        # TODO: Implement ForexFactory or Finnhub API fetch
        # For now, always return True
        return True

    def is_safe_to_trade(self, symbol: str) -> bool:
        """
        Runs all execution guards.
        """
        if not self.check_spread(symbol):
            return False
            
        if not self.check_news_window(datetime.datetime.now()):
            return False
            
        return True
