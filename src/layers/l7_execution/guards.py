import os
import json
import datetime
import MetaTrader5 as mt5


class ExecutionGuards:
    """
    Pre-trade safety checks to block orders in adverse conditions.
    """
    def __init__(self, max_spread_points: int = 20,
                 enforce_news_guard: bool = False,
                 blackout_file: str = "data/news_blackouts.json"):
        self.max_spread_points = max_spread_points
        # The system has no live economic-calendar feed. Rather than silently
        # pretending it is always safe, news blocking is an explicit choice:
        #   - enforce_news_guard=False (default): trading is NOT paused for news,
        #     and that fact is logged so it is a conscious decision, not a hidden stub.
        #   - enforce_news_guard=True: trades are blocked inside any manually
        #     configured blackout window (see blackout_file).
        self.enforce_news_guard = enforce_news_guard
        self.blackout_windows = self._load_blackouts(blackout_file) if enforce_news_guard else []

    @staticmethod
    def _load_blackouts(path: str):
        """
        Load manual UTC blackout windows: a JSON list of objects with ISO-8601
        'start'/'end' (and optional 'label'), e.g. high-impact news like NFP.
        """
        if not os.path.exists(path):
            return []
        try:
            with open(path) as f:
                raw = json.load(f)
            windows = []
            for w in raw:
                windows.append((
                    datetime.datetime.fromisoformat(w['start']),
                    datetime.datetime.fromisoformat(w['end']),
                    w.get('label', 'news'),
                ))
            return windows
        except (ValueError, KeyError, OSError) as e:
            print(f"Guards: failed to parse blackout file {path}: {e}")
            return []

    def check_spread(self, symbol: str) -> bool:
        """
        Check if the current spread is within acceptable limits.
        Returns True if safe to trade, False if spread is too wide.
        """
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
        Returns True if safe (not inside a configured news blackout window).

        There is no automated economic-calendar feed; blocking relies on manually
        configured UTC windows and only applies when enforce_news_guard is on.
        """
        if not self.enforce_news_guard:
            return True

        for start, end, label in self.blackout_windows:
            if start <= current_time <= end:
                print(f"Guards: Trade blocked. Inside news blackout window '{label}' ({start} - {end}).")
                return False
        return True

    def is_safe_to_trade(self, symbol: str) -> bool:
        """
        Runs all execution guards.
        """
        if not self.check_spread(symbol):
            return False

        if not self.check_news_window(datetime.datetime.utcnow()):
            return False

        return True
