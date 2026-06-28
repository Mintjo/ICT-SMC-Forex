"""Premium/discount zone classification within a price range."""
import pandas as pd


def classify_zones(df: pd.DataFrame, range_high: float, range_low: float) -> pd.DataFrame:
    """Classify each close as premium, discount, or equilibrium within [range_low, range_high].

    Premium: upper 50% of the range. Discount: lower 50%. Equilibrium: the midpoint.
    """
    result = df.copy()
    midpoint = (range_high + range_low) / 2
    result["range_midpoint"] = midpoint
    result["zone"] = result["close"].apply(
        lambda c: "premium" if c > midpoint else ("discount" if c < midpoint else "equilibrium")
    )
    return result
