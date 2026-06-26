import pandas as pd
import numpy as np

def calculate_atr(df: pd.DataFrame, period: int = 14) -> pd.Series:
    """
    Calculate Average True Range (ATR).
    ATR = max(H-L, |H-C_prev|, |L-C_prev|) smoothed.
    """
    high = df['high']
    low = df['low']
    close_prev = df['close'].shift(1)
    
    tr1 = high - low
    tr2 = (high - close_prev).abs()
    tr3 = (low - close_prev).abs()
    
    tr = pd.concat([tr1, tr2, tr3], axis=1).max(axis=1)
    # Wilder's Smoothing
    atr = tr.ewm(alpha=1/period, adjust=False).mean()
    return atr

def calculate_yang_zhang(df: pd.DataFrame, period: int = 20) -> pd.Series:
    """
    Calculate Yang-Zhang Historical Volatility.
    Captures overnight jumps and intraday volatility.
    """
    # Placeholder for complete YZ calculation
    # Requires open, high, low, close over 'period'
    log_ho = np.log(df['high'] / df['open'])
    log_lo = np.log(df['low'] / df['open'])
    log_co = np.log(df['close'] / df['open'])
    
    log_oc = np.log(df['open'] / df['close'].shift(1))
    log_oc_sq = log_oc ** 2
    
    log_cc = np.log(df['close'] / df['close'].shift(1))
    log_cc_sq = log_cc ** 2
    
    rs = log_ho * (log_ho - log_co) + log_lo * (log_lo - log_co)
    
    close_vol = log_cc_sq.rolling(window=period).mean()
    open_vol = log_oc_sq.rolling(window=period).mean()
    window_rs = rs.rolling(window=period).mean()
    
    k = 0.34 / (1.34 + (period + 1) / (period - 1))
    
    yz_var = open_vol + k * close_vol + (1 - k) * window_rs
    yz_vol = np.sqrt(yz_var) * np.sqrt(252) # Annualized, adjust 252 for crypto/FX H4
    return yz_vol

def calculate_realized_volatility(df: pd.DataFrame, period: int = 20) -> pd.Series:
    """
    Calculate standard realized volatility.
    """
    log_ret = np.log(df['close'] / df['close'].shift(1))
    return log_ret.rolling(window=period).std() * np.sqrt(252) # Adjust for timeframe

def calculate_atr_percentile(df: pd.DataFrame, period: int = 14, lookback: int = 252) -> pd.Series:
    """
    Calculate ATR percentile over a longer lookback for regime context.
    """
    atr = calculate_atr(df, period)
    return atr.rolling(window=lookback).apply(lambda x: pd.Series(x).rank(pct=True).iloc[-1])
