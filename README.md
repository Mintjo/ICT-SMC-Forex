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
`data/generate_sample_data.py` generates 12 months of synthetic but realistic
EUR/USD M5 data: alternating trend segments, ~15 pip ATR, session-dependent
spread, weekend gaps, and a deliberate ICT microstructure injected into each
killzone window (liquidity sweep of the prior session's high/low, a brief
fake breakout, MSS/CHoCH, and an impulsive FVG) so the strategy has enough
valid setups to produce a statistically meaningful sample:

```bash
python data/generate_sample_data.py
```

`backtest/silver_bullet_backtest.py` then runs the full ICT Silver Bullet
pipeline (killzone filter → H4 bias → BSL/SSL sweep → MSS/CHoCH → first FVG →
50%-retracement entry, 1:2 R:R, max 2 trades/day) over that data. The current
thresholds in `strategies/silver_bullet.py` are intentionally relaxed for
synthetic-data validation (sweep ≥1.5 pips, FVG ≥2.5 pips, 2h killzone
windows, up to 2 trades/killzone, neutral H4 bias trades both directions) —
tighten them back to the strict ICT values (3 pips, 5 pips, 1h windows, 1
trade/killzone, skip on neutral bias) before trading live MT5 data:

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

## Windows setup with real MT5 data

`scripts/setup_windows.bat` automates the full pipeline on a Windows machine
with a running MT5 terminal:

1. checks Python is installed
2. installs dependencies from `requirements.txt`
3. checks the `MetaTrader5` package is installed
4. runs `data/test_mt5_connection.py` to verify the MT5 connection
5. runs `data/download_real_data.py` to download 30 days of real EUR/USD M5
   data into `data/historical/EURUSD_M5_real.csv`
6. runs `backtest/silver_bullet_backtest.py --mode strict` on that real data
   (strict ICT thresholds: 3 pip sweep, 5 pip FVG, 1h killzones, 1
   trade/killzone)
7. confirms the report was generated in `results/`

Copy `.env.example` to `.env` and fill in your MT5 demo credentials (e.g.
Exness) before running it:

```bash
copy .env.example .env
```

```
MT5_LOGIN=ton_numero_compte
MT5_PASSWORD=ton_mot_de_passe
MT5_SERVER=Exness-MT5Trial9
```

Then run:

```bat
scripts\setup_windows.bat
```

## Testing

```bash
pytest
```
