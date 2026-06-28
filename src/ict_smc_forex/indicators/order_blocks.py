"""Order block detection: the last opposing candle before a strong impulsive move."""
import pandas as pd


def detect_order_blocks(df: pd.DataFrame, impulse_threshold: float = 0.0015) -> pd.DataFrame:
    """Flag bullish/bearish order blocks preceding impulsive moves.

    A bullish order block is the last down-candle before a strong up-move;
    a bearish order block is the last up-candle before a strong down-move.
    `impulse_threshold` is the minimum fractional price move that qualifies as impulsive.
    """
    result = df.copy()
    result["bullish_ob"] = False
    result["bearish_ob"] = False

    for i in range(1, len(result)):
        move = (result["close"].iloc[i] - result["open"].iloc[i]) / result["open"].iloc[i]
        prev_is_down = result["close"].iloc[i - 1] < result["open"].iloc[i - 1]
        prev_is_up = result["close"].iloc[i - 1] > result["open"].iloc[i - 1]

        if move >= impulse_threshold and prev_is_down:
            result.loc[result.index[i - 1], "bullish_ob"] = True
        elif move <= -impulse_threshold and prev_is_up:
            result.loc[result.index[i - 1], "bearish_ob"] = True

    return result
