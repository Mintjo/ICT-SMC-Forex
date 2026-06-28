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

## Testing

```bash
pytest
```
