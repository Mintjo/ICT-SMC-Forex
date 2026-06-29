"""Live OHLCV connector for MetaTrader 5 (e.g. Exness demo).

Requires Windows with a running MT5 terminal and the official
`MetaTrader5` Python package (Windows-only, not installable on Linux/macOS).

Environment variables:
    MT5_LOGIN     - MT5 account number
    MT5_PASSWORD  - MT5 account password
    MT5_SERVER    - broker server name, e.g. "Exness-MT5Trial7"
    MT5_PATH      - optional path to terminal64.exe
"""
import os
import time
import logging
from datetime import datetime, timedelta
from pathlib import Path
from zoneinfo import ZoneInfo

import pandas as pd

try:
    import MetaTrader5 as mt5
except ImportError:
    mt5 = None

logger = logging.getLogger("mt5_connector")
logging.basicConfig(level=logging.INFO, format="%(asctime)s [%(levelname)s] %(message)s")

LIVE_DATA_DIR = Path(__file__).parent / "live"

TIMEFRAMES = {
    "M5": "TIMEFRAME_M5",
    "M15": "TIMEFRAME_M15",
    "H1": "TIMEFRAME_H1",
    "H4": "TIMEFRAME_H4",
}

# Killzones expressed in New York local time (DST-aware); converted to WAT (Cotonou, UTC+1, no DST).
KILLZONES_NY = {
    "london": (2, 5),
    "ny_am": (7, 10),
    "ny_pm": (13, 16),
}
NY_TZ = ZoneInfo("America/New_York")
WAT_TZ = ZoneInfo("Africa/Lagos")  # UTC+1 year-round, same offset as Cotonou


def get_active_killzone(now: datetime | None = None) -> str | None:
    """Return the name of the currently active ICT killzone, or None."""
    now_ny = (now or datetime.now(tz=WAT_TZ)).astimezone(NY_TZ)
    hour = now_ny.hour
    for name, (start, end) in KILLZONES_NY.items():
        if start <= hour < end:
            return name
    return None


def detect_symbol(base: str = "EURUSD") -> str:
    """Detect the broker-specific symbol name for `base` (e.g. Exness appends
    a suffix like "m": "EURUSDm"). Tries the bare name first, then common
    broker suffixes, and falls back to scanning all broker symbols for one
    that starts with `base`."""
    candidates = [base, f"{base}m", f"{base}.m", f"{base}_m", f"{base}.a", f"{base}#"]
    for candidate in candidates:
        if mt5.symbol_info(candidate) is not None:
            return candidate

    all_symbols = mt5.symbols_get() or []
    for sym in all_symbols:
        if sym.name.upper().startswith(base.upper()):
            return sym.name

    raise RuntimeError(f"No broker symbol found matching base '{base}'")


def killzone_status_wat() -> dict:
    """Return killzone status with both NY and WAT (Cotonou) local times, for logging/display."""
    now_wat = datetime.now(tz=WAT_TZ)
    now_ny = now_wat.astimezone(NY_TZ)
    return {
        "active_killzone": get_active_killzone(now_wat),
        "time_wat": now_wat.strftime("%Y-%m-%d %H:%M:%S"),
        "time_ny": now_ny.strftime("%Y-%m-%d %H:%M:%S"),
    }


class MT5Connector:
    """Manages a resilient connection to MetaTrader 5 and OHLCV retrieval."""

    def __init__(self, login=None, password=None, server=None, path=None):
        if mt5 is None:
            raise ImportError(
                "MetaTrader5 package not available. Install it on Windows with: "
                "pip install MetaTrader5"
            )
        self.login = login or os.environ.get("MT5_LOGIN")
        self.password = password or os.environ.get("MT5_PASSWORD")
        self.server = server or os.environ.get("MT5_SERVER")
        self.path = path or os.environ.get("MT5_PATH")
        self._connected = False

    def connect(self, retries: int = 5, backoff_seconds: float = 2.0) -> bool:
        """Initialize and log in to the MT5 terminal, retrying with exponential backoff."""
        for attempt in range(1, retries + 1):
            kwargs = {}
            if self.path:
                kwargs["path"] = self.path
            if not mt5.initialize(**kwargs):
                logger.warning("mt5.initialize failed (attempt %d/%d): %s", attempt, retries, mt5.last_error())
            elif self.login and self.password and self.server:
                if mt5.login(int(self.login), password=self.password, server=self.server):
                    logger.info("Connected to MT5 account %s on %s", self.login, self.server)
                    self._connected = True
                    return True
                logger.warning("mt5.login failed (attempt %d/%d): %s", attempt, retries, mt5.last_error())
            else:
                logger.info("Connected to MT5 terminal (no explicit login, using terminal session)")
                self._connected = True
                return True

            time.sleep(backoff_seconds * attempt)

        logger.error("Failed to connect to MT5 after %d attempts", retries)
        self._connected = False
        return False

    def is_connected(self) -> bool:
        if not self._connected:
            return False
        info = mt5.terminal_info()
        return info is not None and info.connected

    def ensure_connection(self) -> bool:
        """Re-establish the MT5 connection if it has dropped."""
        if self.is_connected():
            return True
        logger.warning("MT5 connection lost, reconnecting...")
        return self.connect()

    def fetch_ohlcv(self, symbol: str, timeframe: str, count: int = 500) -> pd.DataFrame:
        """Fetch the latest `count` OHLCV bars for `symbol` on `timeframe` (M5/M15/H1/H4)."""
        if not self.ensure_connection():
            raise ConnectionError("Could not connect to MT5")

        tf_const = getattr(mt5, TIMEFRAMES[timeframe])
        rates = mt5.copy_rates_from_pos(symbol, tf_const, 0, count)
        if rates is None or len(rates) == 0:
            raise RuntimeError(f"No data returned for {symbol} {timeframe}: {mt5.last_error()}")

        df = pd.DataFrame(rates)
        df["time"] = pd.to_datetime(df["time"], unit="s")
        df = df.rename(columns={"time": "timestamp", "tick_volume": "volume"})
        df = df.set_index("timestamp")[["open", "high", "low", "close", "volume"]]
        return df

    def save_ohlcv(self, df: pd.DataFrame, symbol: str, timeframe: str) -> Path:
        """Save OHLCV data to data/live/<SYMBOL>_<TIMEFRAME>.csv."""
        LIVE_DATA_DIR.mkdir(parents=True, exist_ok=True)
        out_path = LIVE_DATA_DIR / f"{symbol}_{timeframe}.csv"
        df.to_csv(out_path)
        return out_path

    def update_all(self, symbol: str = "EURUSD", timeframes=("M5", "M15", "H1", "H4"), count: int = 500):
        """Fetch and persist OHLCV data for each requested timeframe."""
        symbol = detect_symbol(symbol)
        for tf in timeframes:
            df = self.fetch_ohlcv(symbol, tf, count=count)
            path = self.save_ohlcv(df, symbol, tf)
            logger.info("Saved %d bars for %s %s -> %s", len(df), symbol, tf, path)

    def shutdown(self):
        mt5.shutdown()
        self._connected = False

    def run_forever(self, symbol: str = "EURUSD", timeframes=("M5", "M15", "H1", "H4"),
                     poll_seconds: int = 30):
        """Continuously poll MT5 for fresh OHLCV data, logging killzone status, with auto-reconnect."""
        symbol = detect_symbol(symbol)
        logger.info("Starting live feed loop for %s", symbol)
        while True:
            try:
                if not self.ensure_connection():
                    time.sleep(poll_seconds)
                    continue

                status = killzone_status_wat()
                logger.info(
                    "Killzone: %s | WAT: %s | NY: %s",
                    status["active_killzone"] or "none",
                    status["time_wat"],
                    status["time_ny"],
                )

                self.update_all(symbol, timeframes)
            except Exception:
                logger.exception("Error in live feed loop, will retry")
                self._connected = False

            time.sleep(poll_seconds)


if __name__ == "__main__":
    connector = MT5Connector()
    connector.connect()
    connector.run_forever()
