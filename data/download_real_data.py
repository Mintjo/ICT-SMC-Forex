"""Download real EUR/USD M5 OHLCV history from MT5 for backtesting.

Saves to data/historical/EURUSD_M5_real.csv (kept separate from the
synthetic data/historical/EURUSD_M5.csv used for code validation).
"""
import argparse
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

try:
    from dotenv import load_dotenv

    load_dotenv()
except ImportError:
    pass

from data.mt5_connector import MT5Connector, detect_symbol, mt5

OUT_PATH = Path(__file__).parent / "historical" / "EURUSD_M5_real.csv"


def download(symbol: str, days: int) -> Path:
    connector = MT5Connector()
    if not connector.connect(retries=3):
        raise ConnectionError("Could not connect to MT5 terminal")

    symbol = detect_symbol(symbol)
    bars_needed = days * 24 * 12  # M5 bars/day (24h market, FX trades ~5 days/week but oversample is fine)
    df = connector.fetch_ohlcv(symbol, "M5", count=bars_needed)
    connector.shutdown()

    OUT_PATH.parent.mkdir(parents=True, exist_ok=True)
    df.to_csv(OUT_PATH)
    return OUT_PATH


def parse_args():
    parser = argparse.ArgumentParser(description="Download real EUR/USD M5 history from MT5.")
    parser.add_argument("--symbol", default="EURUSD")
    parser.add_argument("--days", type=int, default=30)
    return parser.parse_args()


def main():
    args = parse_args()
    path = download(args.symbol, args.days)
    print(f"Donnees reelles sauvegardees : {path}")


if __name__ == "__main__":
    main()
