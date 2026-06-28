# ICT-SMC-Forex

Forex analysis toolkit implementing ICT (Inner Circle Trader) and SMC (Smart Money Concepts) methodology: market structure, order blocks, fair value gaps (FVG), liquidity pools, and premium/discount zones.

## Features

- **Market Structure**: swing high/low detection, break of structure (BOS), change of character (CHoCH)
- **Order Blocks**: bullish/bearish order block identification
- **Fair Value Gaps (FVG)**: imbalance detection between candles
- **Liquidity**: equal highs/lows, liquidity sweeps
- **Premium/Discount**: range-based zone classification (Fibonacci-based)

## Project structure

```
src/ict_smc_forex/
  data/          # data loading and OHLCV handling
  indicators/    # market structure, order blocks, FVG, liquidity
  strategies/    # composed ICT/SMC strategies
  utils/         # shared helpers
data/
  mt5_connector.py  # live MT5 connection (Windows only, see below)
  live/             # live OHLCV snapshots (gitignored)
  historical/       # historical OHLCV for backtesting (gitignored)
strategies/      # standalone strategy logic (e.g. Silver Bullet)
backtest/        # backtesting scripts and reports
results/         # backtest reports and daily analyses
tests/           # unit tests
config/          # configuration files
notebooks/       # exploratory analysis
docs/            # documentation
```

## Setup

```bash
python -m venv venv
source venv/bin/activate
pip install -r requirements.txt
```

## Live MT5 data feed

`data/mt5_connector.py` connects directly to a MetaTrader 5 terminal to pull
live OHLCV data (EUR/USD on M5/M15/H1/H4), with auto-reconnect and ICT
killzone detection (London, NY AM, NY PM, converted to WAT/Cotonou time).

**This requires Windows** with the MT5 terminal installed and running — the
official `MetaTrader5` Python package has no Linux/macOS build. Set these
environment variables before running it (e.g. for an Exness demo account):

```bash
set MT5_LOGIN=12345678
set MT5_PASSWORD=your_password
set MT5_SERVER=Exness-MT5Trial7
```

Run it with:

```bash
python data/mt5_connector.py
```

It polls continuously, writing CSVs to `data/live/` and logging the active
killzone and reconnect attempts.

## Silver Bullet backtester

Since `yfinance` is blocked by the network proxy in this environment,
`data/generate_sample_data.py` generates 6 months of synthetic but realistic
EUR/USD M5 data (alternating trend segments, ~10-15 pip ATR, session-dependent
spread, weekend gaps):

```bash
python data/generate_sample_data.py
```

`backtest/silver_bullet_backtest.py` then runs the full ICT Silver Bullet
pipeline (killzone filter → H4 bias → BSL/SSL sweep → MSS/CHoCH → first FVG →
50%-retracement entry, 1:2 R:R, max 2 trades/day) over that data:

```bash
python backtest/silver_bullet_backtest.py
```

Outputs:
- `results/backtest_report.html` — visual report (equity curve, monthly
  distribution, win/loss by killzone, last 20 trades)
- `results/trades_log.csv` — full trade log
- console summary (win rate, profit factor, max drawdown, Sharpe ratio, etc.)

Strategy logic lives in `strategies/silver_bullet.py` and is parameterized
(min sweep distance, min FVG size, risk:reward, etc.) at the top of the file.

## Testing

```bash
pytest
```
