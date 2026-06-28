"""OHLCV data loading utilities."""
import pandas as pd

REQUIRED_COLUMNS = ["open", "high", "low", "close"]


def load_ohlcv_csv(path: str) -> pd.DataFrame:
    """Load OHLCV data from a CSV file into a DataFrame indexed by timestamp."""
    df = pd.read_csv(path, parse_dates=["timestamp"])
    df = df.set_index("timestamp").sort_index()
    missing = [c for c in REQUIRED_COLUMNS if c not in df.columns]
    if missing:
        raise ValueError(f"Missing required columns: {missing}")
    return df
