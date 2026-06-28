"""ICT Silver Bullet strategy logic: killzone filter, HTF bias, BSL/SSL sweep,
MSS/CHoCH confirmation, FVG identification, and entry/exit rules.
"""
from dataclasses import dataclass
from zoneinfo import ZoneInfo

import pandas as pd

PIP = 0.0001
NY_TZ = ZoneInfo("America/New_York")

# Strict values are the real ICT Silver Bullet rules, used for live/real-data
# testing. Relaxed values exist only to validate the code on synthetic data,
# where the exact pattern conjunction is otherwise too rare to sample.
STRICT_PARAMS = {
    "killzones": {"london": (3, 4), "ny_am": (10, 11), "ny_pm": (14, 15)},
    "min_sweep_pips": 3,
    "min_fvg_pips": 5,
    "max_trades_per_killzone": 1,
}
RELAXED_PARAMS = {
    "killzones": {"london": (3, 5), "ny_am": (9, 11), "ny_pm": (13, 15)},
    "min_sweep_pips": 1.5,
    "min_fvg_pips": 2.5,
    "max_trades_per_killzone": 2,
}

KILLZONES = STRICT_PARAMS["killzones"]
MIN_SWEEP_PIPS = STRICT_PARAMS["min_sweep_pips"]
MIN_FVG_PIPS = STRICT_PARAMS["min_fvg_pips"]
MAX_TRADES_PER_KILLZONE = STRICT_PARAMS["max_trades_per_killzone"]

SL_BUFFER_PIPS = 2
RISK_REWARD = 2.0
LOOKBACK_BARS = 48          # 4h of M5 bars used to find the swept liquidity level
MSS_SEARCH_BARS = 12        # bars to search for MSS confirmation after a sweep
FVG_SEARCH_BARS = 12        # bars to search for the first FVG after MSS
ENTRY_WAIT_BARS = 12        # bars to wait for price to retrace into the FVG
MAX_HOLD_BARS = 48          # 4h max trade duration before timing out
MAX_TRADES_PER_DAY = 2


def set_mode(mode: str = "strict") -> None:
    """Switch between "strict" (real ICT rules) and "relaxed" (synthetic validation) parameters."""
    global KILLZONES, MIN_SWEEP_PIPS, MIN_FVG_PIPS, MAX_TRADES_PER_KILLZONE
    params = STRICT_PARAMS if mode == "strict" else RELAXED_PARAMS
    KILLZONES = params["killzones"]
    MIN_SWEEP_PIPS = params["min_sweep_pips"]
    MIN_FVG_PIPS = params["min_fvg_pips"]
    MAX_TRADES_PER_KILLZONE = params["max_trades_per_killzone"]


def to_ny(ts: pd.Timestamp) -> pd.Timestamp:
    return ts.tz_convert(NY_TZ) if ts.tzinfo else ts.tz_localize("UTC").tz_convert(NY_TZ)


def killzone_window(date: pd.Timestamp, name: str):
    """Return the (start, end) UTC timestamps for a killzone window on a given calendar date."""
    start_h, end_h = KILLZONES[name]
    start_ny = pd.Timestamp(date.year, date.month, date.day, start_h, tzinfo=NY_TZ)
    end_ny = pd.Timestamp(date.year, date.month, date.day, end_h, tzinfo=NY_TZ)
    return start_ny.tz_convert("UTC"), end_ny.tz_convert("UTC")


def find_swing_points(df: pd.DataFrame, lookback: int = 2) -> pd.DataFrame:
    """Fractal swing high/low detection, used for HTF bias."""
    highs, lows = df["high"], df["low"]
    swing_high = pd.Series(False, index=df.index)
    swing_low = pd.Series(False, index=df.index)
    for i in range(lookback, len(df) - lookback):
        wh = highs.iloc[i - lookback : i + lookback + 1]
        wl = lows.iloc[i - lookback : i + lookback + 1]
        if highs.iloc[i] == wh.max():
            swing_high.iat[i] = True
        if lows.iloc[i] == wl.min():
            swing_low.iat[i] = True
    out = df.copy()
    out["swing_high"] = swing_high
    out["swing_low"] = swing_low
    return out


def compute_htf_bias(h4_upto_now: pd.DataFrame) -> str | None:
    """bullish if last two swing highs/lows are both rising (HH+HL), bearish if both falling (LH+LL)."""
    if len(h4_upto_now) < 20:
        return None
    marked = find_swing_points(h4_upto_now, lookback=2)
    swing_highs = marked.loc[marked["swing_high"], "high"]
    swing_lows = marked.loc[marked["swing_low"], "low"]
    if len(swing_highs) < 2 or len(swing_lows) < 2:
        return None
    hh = swing_highs.iloc[-1] > swing_highs.iloc[-2]
    hl = swing_lows.iloc[-1] > swing_lows.iloc[-2]
    lh = swing_highs.iloc[-1] < swing_highs.iloc[-2]
    ll = swing_lows.iloc[-1] < swing_lows.iloc[-2]
    if hh and hl:
        return "bullish"
    if lh and ll:
        return "bearish"
    return "neutral"  # mixed structure: allow both directions instead of skipping the day


def resample_h4(m5: pd.DataFrame) -> pd.DataFrame:
    return m5.resample("4h").agg({"open": "first", "high": "max", "low": "min", "close": "last"}).dropna()


def find_sweep(window: pd.DataFrame, swing_low: float, swing_high: float, direction: str):
    """Find the first bar in `window` that sweeps liquidity in the direction needed for `direction` bias.

    bullish bias -> look for an SSL sweep (wick below swing_low, close back above).
    bearish bias -> look for a BSL sweep (wick above swing_high, close back below).
    """
    idxs, level = find_all_sweeps(window, swing_low, swing_high, direction)
    if not idxs:
        return None, None
    return idxs[0], level


def find_all_sweeps(window: pd.DataFrame, swing_low: float, swing_high: float, direction: str):
    """Find every bar in `window` that sweeps the relevant liquidity level for `direction`."""
    matches = []
    for i in range(len(window)):
        bar = window.iloc[i]
        if direction == "bullish":
            if bar["low"] <= swing_low - MIN_SWEEP_PIPS * PIP and bar["close"] > swing_low:
                matches.append(i)
        else:
            if bar["high"] >= swing_high + MIN_SWEEP_PIPS * PIP and bar["close"] < swing_high:
                matches.append(i)
    level = swing_low if direction == "bullish" else swing_high
    return matches, level


def find_mss(m5: pd.DataFrame, sweep_idx: int, direction: str, search_bars: int = MSS_SEARCH_BARS):
    """After a sweep, find the bar that breaks structure in the trade direction (MSS/CHoCH)."""
    pre_window = m5.iloc[max(0, sweep_idx - 3) : sweep_idx + 1]
    ref_high = pre_window["high"].max()
    ref_low = pre_window["low"].min()
    end = min(len(m5), sweep_idx + 1 + search_bars)
    for j in range(sweep_idx + 1, end):
        bar = m5.iloc[j]
        if direction == "bullish" and bar["close"] > ref_high:
            return j
        if direction == "bearish" and bar["close"] < ref_low:
            return j
    return None


def find_first_fvg(m5: pd.DataFrame, mss_idx: int, direction: str, search_bars: int = FVG_SEARCH_BARS):
    """Find the first fair value gap after the MSS bar, in the trade direction."""
    end = min(len(m5), mss_idx + 1 + search_bars)
    for k in range(mss_idx + 1, end):
        if k < 2:
            continue
        c1_high, c1_low = m5["high"].iloc[k - 2], m5["low"].iloc[k - 2]
        c3_high, c3_low = m5["high"].iloc[k], m5["low"].iloc[k]
        if direction == "bullish" and c3_low > c1_high and (c3_low - c1_high) / PIP >= MIN_FVG_PIPS:
            return k, c1_high, c3_low
        if direction == "bearish" and c3_high < c1_low and (c1_low - c3_high) / PIP >= MIN_FVG_PIPS:
            return k, c3_high, c1_low
    return None, None, None


@dataclass
class Trade:
    killzone: str
    direction: str
    entry_time: pd.Timestamp
    entry_price: float
    sl: float
    tp: float
    exit_time: pd.Timestamp
    exit_price: float
    result: str  # "win", "loss", "timeout"
    pnl_pips: float
    pnl_r: float


def simulate_exit(m5: pd.DataFrame, start_idx: int, direction: str, entry_price: float, sl: float, tp: float):
    """Walk forward bar by bar until SL or TP is hit, or MAX_HOLD_BARS elapses (timeout)."""
    end = min(len(m5), start_idx + 1 + MAX_HOLD_BARS)
    for i in range(start_idx + 1, end):
        bar = m5.iloc[i]
        if direction == "bullish":
            if bar["low"] <= sl:
                return i, sl, "loss"
            if bar["high"] >= tp:
                return i, tp, "win"
        else:
            if bar["high"] >= sl:
                return i, sl, "loss"
            if bar["low"] <= tp:
                return i, tp, "win"
    last_idx = end - 1
    return last_idx, m5["close"].iloc[last_idx], "timeout"


def find_entry(m5: pd.DataFrame, fvg_idx: int, direction: str, fvg_bottom: float, fvg_top: float):
    """Wait for price to retrace into the 50% midpoint of the FVG."""
    mid = (fvg_top + fvg_bottom) / 2
    end = min(len(m5), fvg_idx + 1 + ENTRY_WAIT_BARS)
    for i in range(fvg_idx + 1, end):
        bar = m5.iloc[i]
        if bar["low"] <= mid <= bar["high"]:
            return i, mid
    return None, None


def _build_trade(m5: pd.DataFrame, kz_name: str, direction: str, sweep_idx: int, swept_level: float):
    """Run MSS -> FVG -> entry -> exit for a single sweep candidate. Returns a Trade or None."""
    mss_idx = find_mss(m5, sweep_idx, direction)
    if mss_idx is None:
        return None

    fvg_idx, fvg_bottom, fvg_top = find_first_fvg(m5, mss_idx, direction)
    if fvg_idx is None:
        return None

    entry_idx, entry_price = find_entry(m5, fvg_idx, direction, fvg_bottom, fvg_top)
    if entry_idx is None:
        return None

    if direction == "bullish":
        sl = swept_level - SL_BUFFER_PIPS * PIP
        risk = entry_price - sl
        tp = entry_price + RISK_REWARD * risk
    else:
        sl = swept_level + SL_BUFFER_PIPS * PIP
        risk = sl - entry_price
        tp = entry_price - RISK_REWARD * risk

    if risk <= 0:
        return None

    exit_idx, exit_price, result = simulate_exit(m5, entry_idx, direction, entry_price, sl, tp)

    pnl_price = (exit_price - entry_price) if direction == "bullish" else (entry_price - exit_price)
    pnl_pips = pnl_price / PIP
    pnl_r = pnl_price / risk

    return Trade(
        killzone=kz_name,
        direction=direction,
        entry_time=m5.index[entry_idx],
        entry_price=entry_price,
        sl=sl,
        tp=tp,
        exit_time=m5.index[exit_idx],
        exit_price=exit_price,
        result=result,
        pnl_pips=pnl_pips,
        pnl_r=pnl_r,
    )


def run_killzone(m5: pd.DataFrame, day: pd.Timestamp, kz_name: str, bias: str):
    """Find up to MAX_TRADES_PER_KILLZONE Silver Bullet trades in the given killzone/day.

    `bias` of "neutral" allows setups in both directions.
    """
    start, end = killzone_window(day, kz_name)
    window = m5.loc[(m5.index >= start) & (m5.index < end)]
    if len(window) < 3 or bias is None:
        return []

    lookback_start = start - pd.Timedelta(minutes=5 * LOOKBACK_BARS)
    lookback = m5.loc[(m5.index >= lookback_start) & (m5.index < start)]
    if len(lookback) < 5:
        return []
    swing_low = lookback["low"].min()
    swing_high = lookback["high"].max()

    directions = ["bullish", "bearish"] if bias == "neutral" else [bias]

    candidates = []  # (window_rel_idx, direction, swept_level)
    for direction in directions:
        rel_idxs, level = find_all_sweeps(window, swing_low, swing_high, direction)
        for rel_idx in rel_idxs:
            candidates.append((rel_idx, direction, level))
    candidates.sort(key=lambda c: c[0])

    trades = []
    used_abs_idxs = set()
    for rel_idx, direction, level in candidates:
        if len(trades) >= MAX_TRADES_PER_KILLZONE:
            break
        sweep_idx = m5.index.get_loc(window.index[rel_idx])
        if sweep_idx in used_abs_idxs:
            continue
        trade = _build_trade(m5, kz_name, direction, sweep_idx, level)
        if trade is not None:
            trades.append(trade)
            used_abs_idxs.add(sweep_idx)

    return trades
