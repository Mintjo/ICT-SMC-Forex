"""Fair Value Gap (FVG): imbalance between candle 1's wick and candle 3's wick."""
import pandas as pd


def detect_fvg(df: pd.DataFrame) -> pd.DataFrame:
    """Detect bullish/bearish fair value gaps using a 3-candle pattern."""
    result = df.copy()
    result["bullish_fvg"] = False
    result["bearish_fvg"] = False
    result["fvg_top"] = float("nan")
    result["fvg_bottom"] = float("nan")

    for i in range(2, len(result)):
        candle1_high = result["high"].iloc[i - 2]
        candle1_low = result["low"].iloc[i - 2]
        candle3_high = result["high"].iloc[i]
        candle3_low = result["low"].iloc[i]

        idx = result.index[i]
        if candle3_low > candle1_high:
            result.loc[idx, "bullish_fvg"] = True
            result.loc[idx, "fvg_bottom"] = candle1_high
            result.loc[idx, "fvg_top"] = candle3_low
        elif candle3_high < candle1_low:
            result.loc[idx, "bearish_fvg"] = True
            result.loc[idx, "fvg_top"] = candle1_low
            result.loc[idx, "fvg_bottom"] = candle3_high

    return result
