"""Liquidity pools: equal highs/lows and liquidity sweeps."""
import pandas as pd


def detect_equal_levels(df: pd.DataFrame, tolerance: float = 0.0005) -> pd.DataFrame:
    """Flag equal highs and equal lows within a relative `tolerance`."""
    result = df.copy()
    result["equal_high"] = False
    result["equal_low"] = False

    for i in range(1, len(result)):
        prev_high = result["high"].iloc[i - 1]
        curr_high = result["high"].iloc[i]
        prev_low = result["low"].iloc[i - 1]
        curr_low = result["low"].iloc[i]

        idx = result.index[i]
        if abs(curr_high - prev_high) / prev_high <= tolerance:
            result.loc[idx, "equal_high"] = True
        if abs(curr_low - prev_low) / prev_low <= tolerance:
            result.loc[idx, "equal_low"] = True

    return result


def detect_liquidity_sweep(df: pd.DataFrame, lookback: int = 10) -> pd.DataFrame:
    """Detect liquidity sweeps: price breaks a recent high/low then closes back inside it."""
    result = df.copy()
    result["sweep_high"] = False
    result["sweep_low"] = False

    for i in range(lookback, len(result)):
        recent_high = result["high"].iloc[i - lookback : i].max()
        recent_low = result["low"].iloc[i - lookback : i].min()

        idx = result.index[i]
        if result["high"].iloc[i] > recent_high and result["close"].iloc[i] < recent_high:
            result.loc[idx, "sweep_high"] = True
        if result["low"].iloc[i] < recent_low and result["close"].iloc[i] > recent_low:
            result.loc[idx, "sweep_low"] = True

    return result
