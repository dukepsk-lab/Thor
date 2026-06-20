import pandas as pd

def calculate_rolling_correlation(df1: pd.DataFrame, df2: pd.DataFrame, period: int = 20) -> pd.Series:
    """
    Calculate rolling correlation between two pairs (e.g. EURUSD and GBPUSD).
    Assumes df1 and df2 have 'close' prices and are time-aligned.
    """
    return df1['close'].rolling(window=period).corr(df2['close'])

def calculate_spread_ratio(df1: pd.DataFrame, df2: pd.DataFrame) -> pd.Series:
    """
    Calculate ratio or spread between two correlated pairs.
    """
    return df1['close'] / df2['close']

def calculate_lead_lag(df1: pd.DataFrame, df2: pd.DataFrame, lag: int = 1) -> pd.Series:
    """
    Calculate cross-correlation with a lag to identify lead-lag relationships.
    """
    return df1['close'].rolling(window=20).corr(df2['close'].shift(lag))
