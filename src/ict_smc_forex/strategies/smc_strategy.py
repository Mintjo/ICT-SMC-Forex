"""Composed ICT/SMC strategy combining market structure, order blocks, FVG, and liquidity."""
import pandas as pd

from ict_smc_forex.indicators.market_structure import detect_structure_breaks
from ict_smc_forex.indicators.order_blocks import detect_order_blocks
from ict_smc_forex.indicators.fair_value_gap import detect_fvg
from ict_smc_forex.indicators.liquidity import detect_equal_levels, detect_liquidity_sweep


def annotate(df: pd.DataFrame) -> pd.DataFrame:
    """Run the full ICT/SMC indicator pipeline over OHLCV data."""
    result = detect_structure_breaks(df)
    result = detect_order_blocks(result)
    result = detect_fvg(result)
    result = detect_equal_levels(result)
    result = detect_liquidity_sweep(result)
    return result
