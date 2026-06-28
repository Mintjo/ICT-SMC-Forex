"""Generate realistic synthetic EUR/USD M5 OHLCV data for backtesting.

Used because yfinance is blocked by the network proxy. Simulates:
- alternating bullish/bearish trend segments
- realistic M5 volatility (ATR ~10-15 pips)
- session-dependent spread (wider outside killzones)
- weekend gaps
- deliberate ICT microstructure in each killzone window: a liquidity sweep
  of the prior session's high/low (e.g. Asian range swept at London open),
  a brief fake breakout against the real direction, then an MSS/CHoCH and
  an impulsive fair value gap in the direction of the prevailing trend
"""
import sys
from pathlib import Path
from zoneinfo import ZoneInfo

import numpy as np
import pandas as pd

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
from strategies.silver_bullet import KILLZONES  # noqa: E402

PIP = 0.0001
NY_TZ = ZoneInfo("America/New_York")
OUT_PATH = Path(__file__).parent / "historical" / "EURUSD_M5.csv"

SEGMENT_LENGTH_BARS = 2880  # ~10 trading days of M5 bars, alternates trend direction
LOOKBACK_BARS_FOR_INJECTION = 48  # matches strategy's 4h liquidity lookback
INJECTION_PROBABILITY = 0.6


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


def _base_random_walk(months: int, start: str, base_price: float, rng):
    timestamps = _trading_timestamps(start, months)
    n = len(timestamps)

    opens = np.empty(n)
    highs = np.empty(n)
    lows = np.empty(n)
    closes = np.empty(n)
    volumes = np.empty(n, dtype=int)
    spreads = np.empty(n)
    trend_signs = np.empty(n, dtype=int)

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
        trend_signs[i] = trend_sign

        prev_close = close_price

    return timestamps, opens, highs, lows, closes, volumes, spreads, trend_signs


def _killzone_start_utc(date, kz_name: str) -> pd.Timestamp:
    start_h, _ = KILLZONES[kz_name]
    start_ny = pd.Timestamp(date.year, date.month, date.day, start_h, tzinfo=NY_TZ)
    return start_ny.tz_convert("UTC")


def _inject_setup(opens, highs, lows, closes, idx0: int, direction: str, rng) -> None:
    """Overwrite 8 bars starting at idx0 with a sweep -> fakeout -> MSS -> FVG -> retrace pattern,
    then shift all subsequent bars to preserve continuity with the rest of the random walk."""
    n = len(closes)
    if idx0 < LOOKBACK_BARS_FOR_INJECTION or idx0 + 8 >= n:
        return

    sign = 1 if direction == "bullish" else -1

    prev_close = closes[idx0 - 1]
    lookback_lo = idx0 - LOOKBACK_BARS_FOR_INJECTION
    level = lows[lookback_lo:idx0].min() if direction == "bullish" else highs[lookback_lo:idx0].max()

    sweep_dist = rng.uniform(2.0, 3.5) * PIP
    fakeout_dist = rng.uniform(1.0, 2.0) * PIP
    impulse_dist = rng.uniform(2.5, 4.0) * PIP
    fvg_gap = rng.uniform(3.0, 5.0) * PIP

    bars = []  # list of (open, high, low, close)

    # bar0: liquidity sweep of the prior session's high/low
    open0 = prev_close
    if direction == "bullish":
        close0 = level + 0.8 * PIP
        low0 = level - sweep_dist
        high0 = max(open0, close0) + 0.3 * PIP
    else:
        close0 = level - 0.8 * PIP
        high0 = level + sweep_dist
        low0 = min(open0, close0) - 0.3 * PIP
    bars.append((open0, high0, low0, close0))

    # bar1: fake breakout against the real direction
    open1 = close0
    close1 = open1 - sign * fakeout_dist
    high1 = max(open1, close1) + 0.2 * PIP
    low1 = min(open1, close1) - 0.2 * PIP
    bars.append((open1, high1, low1, close1))

    # bar2: turn back toward the real direction
    open2 = close1
    close2 = open2 + sign * 1.2 * PIP
    high2 = max(open2, close2) + 0.2 * PIP
    low2 = min(open2, close2) - 0.2 * PIP
    bars.append((open2, high2, low2, close2))

    # bar3: MSS / CHoCH - breaks the local structure formed by bars 0-2
    ref_high = max(high0, high1, high2)
    ref_low = min(low0, low1, low2)
    open3 = close2
    if direction == "bullish":
        close3 = ref_high + impulse_dist
        high3 = close3 + 0.3 * PIP
        low3 = min(open3, close3) - 0.2 * PIP
    else:
        close3 = ref_low - impulse_dist
        low3 = close3 - 0.3 * PIP
        high3 = max(open3, close3) + 0.2 * PIP
    bars.append((open3, high3, low3, close3))

    # bar4: impulsive continuation (FVG candle 1 of 3, by index)
    open4 = close3
    close4 = open4 + sign * 1.5 * PIP
    high4 = max(open4, close4) + 0.2 * PIP
    low4 = min(open4, close4) - 0.2 * PIP
    bars.append((open4, high4, low4, close4))

    # bar5: completes the 3-candle fair value gap against bar3
    if direction == "bullish":
        low5 = high3 + fvg_gap
        close5 = low5 + 1.0 * PIP
        high5 = close5 + 0.3 * PIP
        open5 = low5
    else:
        high5 = low3 - fvg_gap
        close5 = high5 - 1.0 * PIP
        low5 = close5 - 0.3 * PIP
        open5 = high5
    bars.append((open5, high5, low5, close5))

    # bar6: retraces into the 50% midpoint of the FVG (the entry trigger)
    if direction == "bullish":
        fvg_mid = (high3 + low5) / 2
    else:
        fvg_mid = (low3 + high5) / 2
    open6 = close5
    close6 = fvg_mid
    high6 = max(open6, close6) + 0.2 * PIP
    low6 = min(open6, close6) - 0.2 * PIP
    bars.append((open6, high6, low6, close6))

    # bar7: continuation in the real direction after the retracement
    open7 = close6
    close7 = open7 + sign * 2.0 * PIP
    high7 = max(open7, close7) + 0.2 * PIP
    low7 = min(open7, close7) - 0.2 * PIP
    bars.append((open7, high7, low7, close7))

    orig_close7 = closes[idx0 + 7]

    for offset, (bo, bh, bl, bc) in enumerate(bars):
        i = idx0 + offset
        opens[i] = bo
        highs[i] = bh
        lows[i] = bl
        closes[i] = bc

    delta = close7 - orig_close7
    if idx0 + 8 < n:
        opens[idx0 + 8 :] += delta
        highs[idx0 + 8 :] += delta
        lows[idx0 + 8 :] += delta
        closes[idx0 + 8 :] += delta


def inject_microstructure(timestamps, opens, highs, lows, closes, trend_signs, rng) -> None:
    """Mutates opens/highs/lows/closes in place, injecting a sweep/MSS/FVG pattern per killzone."""
    dates = pd.Series(timestamps.date).unique()
    day_index = pd.Index(timestamps.date)

    for d in dates:
        day_idxs = np.where(day_index == d)[0]
        if len(day_idxs) == 0:
            continue
        direction = "bullish" if trend_signs[day_idxs[0]] > 0 else "bearish"

        for kz_name in KILLZONES:
            if rng.random() > INJECTION_PROBABILITY:
                continue
            kz_start_utc = _killzone_start_utc(d, kz_name)
            pos = timestamps.searchsorted(kz_start_utc)
            if pos >= len(timestamps):
                continue
            _inject_setup(opens, highs, lows, closes, int(pos), direction, rng)


def generate(months: int = 12, start: str = "2024-01-01", base_price: float = 1.1000, seed: int = 42) -> pd.DataFrame:
    rng = np.random.default_rng(seed)
    timestamps, opens, highs, lows, closes, volumes, spreads, trend_signs = _base_random_walk(
        months, start, base_price, rng
    )
    inject_microstructure(timestamps, opens, highs, lows, closes, trend_signs, rng)

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
