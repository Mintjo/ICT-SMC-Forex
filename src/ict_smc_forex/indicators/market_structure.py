"""Market structure: swing points, break of structure (BOS), change of character (CHoCH)."""
import pandas as pd


def find_swing_points(df: pd.DataFrame, lookback: int = 2) -> pd.DataFrame:
    """Mark swing highs and lows using a fractal of `lookback` bars on each side."""
    highs = df["high"]
    lows = df["low"]
    swing_high = pd.Series(False, index=df.index)
    swing_low = pd.Series(False, index=df.index)

    for i in range(lookback, len(df) - lookback):
        window_high = highs.iloc[i - lookback : i + lookback + 1]
        window_low = lows.iloc[i - lookback : i + lookback + 1]
        if highs.iloc[i] == window_high.max():
            swing_high.iat[i] = True
        if lows.iloc[i] == window_low.min():
            swing_low.iat[i] = True

    result = df.copy()
    result["swing_high"] = swing_high
    result["swing_low"] = swing_low
    return result


def detect_structure_breaks(df: pd.DataFrame) -> pd.DataFrame:
    """Detect break of structure (BOS) and change of character (CHoCH) based on swing points."""
    result = find_swing_points(df)
    result["bos"] = False
    result["choch"] = False

    last_swing_high = None
    last_swing_low = None
    trend = None

    for i in range(len(result)):
        close = result["close"].iloc[i]

        idx = result.index[i]
        if last_swing_high is not None and close > last_swing_high:
            if trend == "down":
                result.loc[idx, "choch"] = True
            else:
                result.loc[idx, "bos"] = True
            trend = "up"

        if last_swing_low is not None and close < last_swing_low:
            if trend == "up":
                result.loc[idx, "choch"] = True
            else:
                result.loc[idx, "bos"] = True
            trend = "down"

        if result["swing_high"].iloc[i]:
            last_swing_high = result["high"].iloc[i]
        if result["swing_low"].iloc[i]:
            last_swing_low = result["low"].iloc[i]

    return result
