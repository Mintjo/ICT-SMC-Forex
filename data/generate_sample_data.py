"""Generate realistic synthetic EUR/USD M5 OHLCV data for backtesting.

Used because yfinance is blocked by the network proxy. Simulates:
- alternating bullish/bearish trend segments
- realistic M5 volatility (ATR ~10-15 pips)
- session-dependent spread (wider outside killzones)
- weekend gaps
"""
from pathlib import Path
from zoneinfo import ZoneInfo

import numpy as np
import pandas as pd

PIP = 0.0001
NY_TZ = ZoneInfo("America/New_York")
OUT_PATH = Path(__file__).parent / "historical" / "EURUSD_M5.csv"

SEGMENT_LENGTH_BARS = 2880  # ~10 trading days of M5 bars, alternates trend direction


def session_spread_pips(ts_ny) -> float:
    """Wider spread outside the main London/NY killzones, narrowest during NY AM/PM overlap."""
    hour = ts_ny.hour
    if 8 <= hour < 17:
        return 1.0
    if 3 <= hour < 11:
        return 1.2
    if hour >= 17 or hour < 3:
        return 3.0
    return 2.0


def _trading_timestamps(start: str, months: int) -> pd.DatetimeIndex:
    start_dt = pd.Timestamp(start, tz="UTC")
    end_dt = start_dt + pd.DateOffset(months=months)
    all_ts = pd.date_range(start_dt, end_dt, freq="5min", tz="UTC", inclusive="left")
    dow = all_ts.dayofweek
    hour = all_ts.hour
    closed = (dow == 5) | ((dow == 6) & (hour < 22))
    return all_ts[~closed]


def generate(months: int = 6, start: str = "2024-01-01", base_price: float = 1.1000, seed: int = 42) -> pd.DataFrame:
    rng = np.random.default_rng(seed)
    timestamps = _trading_timestamps(start, months)
    n = len(timestamps)

    opens = np.empty(n)
    highs = np.empty(n)
    lows = np.empty(n)
    closes = np.empty(n)
    volumes = np.empty(n, dtype=int)
    spreads = np.empty(n)

    prev_close = base_price
    trend_sign = 1
    bars_in_segment = 0

    for i in range(n):
        if bars_in_segment >= SEGMENT_LENGTH_BARS:
            trend_sign *= -1
            bars_in_segment = 0
        bars_in_segment += 1

        if i > 0 and (timestamps[i] - timestamps[i - 1]) > pd.Timedelta(hours=4):
            gap = rng.normal(0, 5) * PIP  # weekend gap
            open_price = prev_close + gap
        else:
            open_price = prev_close

        drift = trend_sign * rng.uniform(0.02, 0.06) * PIP
        sigma = rng.uniform(5.5, 8.0) * PIP
        close_price = open_price + drift + rng.normal(0, 1) * sigma

        wiggle = abs(rng.normal(0, 1)) * sigma * 1.8
        high = max(open_price, close_price) + wiggle * 0.5
        low = min(open_price, close_price) - wiggle * 0.5

        ny_hour_ts = timestamps[i].tz_convert(NY_TZ)

        opens[i] = open_price
        highs[i] = high
        lows[i] = low
        closes[i] = close_price
        volumes[i] = rng.integers(50, 500)
        spreads[i] = session_spread_pips(ny_hour_ts)

        prev_close = close_price

    df = pd.DataFrame(
        {"open": opens, "high": highs, "low": lows, "close": closes, "volume": volumes, "spread": spreads},
        index=timestamps,
    )
    df.index.name = "timestamp"
    return df


def main():
    df = generate()
    OUT_PATH.parent.mkdir(parents=True, exist_ok=True)
    df.to_csv(OUT_PATH)
    avg_range_pips = ((df["high"] - df["low"]) / PIP).mean()
    print(f"Generated {len(df)} M5 bars from {df.index[0]} to {df.index[-1]}")
    print(f"Average bar range: {avg_range_pips:.1f} pips")
    print(f"Saved to {OUT_PATH}")


if __name__ == "__main__":
    main()
