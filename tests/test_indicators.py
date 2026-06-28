import pandas as pd

from ict_smc_forex.indicators.market_structure import find_swing_points, detect_structure_breaks
from ict_smc_forex.indicators.order_blocks import detect_order_blocks
from ict_smc_forex.indicators.fair_value_gap import detect_fvg
from ict_smc_forex.indicators.liquidity import detect_equal_levels, detect_liquidity_sweep
from ict_smc_forex.indicators.premium_discount import classify_zones


def make_df(rows):
    idx = pd.date_range("2024-01-01", periods=len(rows), freq="h")
    return pd.DataFrame(rows, index=idx, columns=["open", "high", "low", "close"])


def test_find_swing_points():
    rows = [
        [1.0, 1.0, 1.0, 1.0],
        [1.1, 1.2, 1.0, 1.1],
        [1.3, 1.5, 1.2, 1.4],
        [1.2, 1.3, 1.0, 1.1],
        [1.0, 1.1, 0.9, 1.0],
    ]
    result = find_swing_points(make_df(rows), lookback=2)
    assert result["swing_high"].iloc[2]


def test_detect_structure_breaks_runs():
    rows = [[1.0, 1.1, 0.9, 1.0 + i * 0.01] for i in range(20)]
    result = detect_structure_breaks(make_df(rows))
    assert "bos" in result.columns
    assert "choch" in result.columns


def test_detect_order_blocks():
    rows = [
        [1.10, 1.10, 1.05, 1.06],
        [1.06, 1.20, 1.05, 1.19],
    ]
    result = detect_order_blocks(make_df(rows), impulse_threshold=0.001)
    assert result["bullish_ob"].iloc[0]


def test_detect_fvg_bullish():
    rows = [
        [1.00, 1.05, 0.95, 1.00],
        [1.10, 1.20, 1.08, 1.15],
        [1.20, 1.30, 1.10, 1.25],
    ]
    result = detect_fvg(make_df(rows))
    assert result["bullish_fvg"].iloc[2]


def test_detect_equal_levels():
    rows = [
        [1.00, 1.10, 0.95, 1.00],
        [1.00, 1.10, 0.96, 1.02],
    ]
    result = detect_equal_levels(make_df(rows))
    assert result["equal_high"].iloc[1]


def test_detect_liquidity_sweep_runs():
    rows = [[1.0, 1.0 + 0.001 * i, 0.99, 1.0] for i in range(15)]
    result = detect_liquidity_sweep(make_df(rows), lookback=5)
    assert "sweep_high" in result.columns


def test_classify_zones():
    rows = [[1.0, 1.0, 1.0, c] for c in [1.0, 1.5, 2.0]]
    result = classify_zones(make_df(rows), range_high=2.0, range_low=1.0)
    assert result["zone"].iloc[0] == "discount"
    assert result["zone"].iloc[2] == "premium"
