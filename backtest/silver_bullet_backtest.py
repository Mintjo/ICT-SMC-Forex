"""Backtest the ICT Silver Bullet strategy on EUR/USD M5 data (synthetic or real)."""
import argparse
import json
import sys
from itertools import groupby
from pathlib import Path

import numpy as np
import pandas as pd

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

import strategies.silver_bullet as sb
from strategies.silver_bullet import Trade, compute_htf_bias, resample_h4, run_killzone

DEFAULT_HISTORICAL_PATH = Path(__file__).parent.parent / "data" / "historical" / "EURUSD_M5.csv"
RESULTS_DIR = Path(__file__).parent.parent / "results"
STARTING_EQUITY = 10_000.0
RISK_PER_TRADE = 100.0  # fixed $ risk per trade (1% of starting equity)


def load_m5(path: Path) -> pd.DataFrame:
    df = pd.read_csv(path, parse_dates=["timestamp"])
    df = df.set_index("timestamp").sort_index()
    # Les exports MT5 live sont en UTC sans fuseau ; les killzones sont en UTC avec fuseau.
    if df.index.tz is None:
        df.index = df.index.tz_localize("UTC")
    return df


def run_backtest(m5: pd.DataFrame) -> list[Trade]:
    h4 = resample_h4(m5)
    trades: list[Trade] = []

    trading_days = pd.Series(m5.index.date).unique()
    for day in trading_days:
        day_ts = pd.Timestamp(day)
        h4_upto_day = h4.loc[h4.index < day_ts.tz_localize("UTC")]
        bias = compute_htf_bias(h4_upto_day)
        if bias is None:
            continue

        trades_today = 0
        for kz_name in sb.KILLZONES:
            if trades_today >= sb.MAX_TRADES_PER_DAY:
                break
            kz_trades = run_killzone(m5, day_ts, kz_name, bias)
            for trade in kz_trades:
                if trades_today >= sb.MAX_TRADES_PER_DAY:
                    break
                trades.append(trade)
                trades_today += 1

    return trades


def longest_streak(results: list[str], target: str) -> int:
    best = 0
    for key, group in groupby(results, key=lambda r: r == target):
        if key:
            best = max(best, len(list(group)))
    return best


def compute_metrics(trades: list[Trade]) -> dict:
    n = len(trades)
    if n == 0:
        return {"total_trades": 0}

    results = [t.result for t in trades]
    wins = [t for t in trades if t.result == "win"]
    losses = [t for t in trades if t.result in ("loss", "timeout") and t.pnl_r < 0]
    gains = [t.pnl_r for t in trades if t.pnl_r > 0]
    drawdowns = [t.pnl_r for t in trades if t.pnl_r < 0]

    win_rate = 100 * len(wins) / n
    gross_profit = sum(gains) if gains else 0.0
    gross_loss = abs(sum(drawdowns)) if drawdowns else 0.0
    profit_factor = (gross_profit / gross_loss) if gross_loss > 0 else float("inf")

    equity = [STARTING_EQUITY]
    for t in trades:
        equity.append(equity[-1] + t.pnl_r * RISK_PER_TRADE)
    equity_arr = np.array(equity)
    running_max = np.maximum.accumulate(equity_arr)
    drawdown_pct = (equity_arr - running_max) / running_max * 100
    max_drawdown_pct = drawdown_pct.min()

    r_values = np.array([t.pnl_r for t in trades])
    months = sorted(set((t.entry_time.year, t.entry_time.month) for t in trades))
    trades_per_month = n / max(len(months), 1)
    trades_per_year_est = trades_per_month * 12
    sharpe = (r_values.mean() / r_values.std() * np.sqrt(trades_per_year_est)) if r_values.std() > 0 else 0.0

    best_streak = longest_streak(results, "win")
    worst_streak = longest_streak(results, "loss") + longest_streak(results, "timeout")

    return {
        "total_trades": n,
        "win_rate_pct": round(win_rate, 2),
        "profit_factor": round(profit_factor, 2) if profit_factor != float("inf") else None,
        "max_drawdown_pct": round(max_drawdown_pct, 2),
        "sharpe_ratio": round(sharpe, 2),
        "trades_per_month": round(trades_per_month, 2),
        "best_win_streak": best_streak,
        "worst_loss_streak": worst_streak,
        "final_equity": round(equity_arr[-1], 2),
        "equity_curve": equity_arr.tolist(),
        "months": [f"{y}-{m:02d}" for y, m in months],
    }


def trades_to_dataframe(trades: list[Trade]) -> pd.DataFrame:
    rows = [
        {
            "entry_time": t.entry_time,
            "exit_time": t.exit_time,
            "killzone": t.killzone,
            "direction": t.direction,
            "entry_price": round(t.entry_price, 5),
            "sl": round(t.sl, 5),
            "tp": round(t.tp, 5),
            "exit_price": round(t.exit_price, 5),
            "result": t.result,
            "pnl_pips": round(t.pnl_pips, 1),
            "pnl_r": round(t.pnl_r, 2),
        }
        for t in trades
    ]
    return pd.DataFrame(rows)


def trades_per_month(df: pd.DataFrame) -> dict:
    if df.empty:
        return {}
    df = df.copy()
    df["month"] = df["entry_time"].dt.strftime("%Y-%m")
    return df.groupby("month").size().to_dict()


def killzone_breakdown(df: pd.DataFrame) -> dict:
    if df.empty:
        return {}
    out = {}
    for kz, group in df.groupby("killzone"):
        out[kz] = {
            "wins": int((group["result"] == "win").sum()),
            "losses": int((group["result"].isin(["loss", "timeout"])).sum()),
        }
    return out


def render_html_report(metrics: dict, df: pd.DataFrame, out_path: Path):
    months = list(trades_per_month(df).keys())
    month_counts = list(trades_per_month(df).values())
    kz_data = killzone_breakdown(df)
    kz_labels = list(kz_data.keys())
    kz_wins = [kz_data[k]["wins"] for k in kz_labels]
    kz_losses = [kz_data[k]["losses"] for k in kz_labels]
    equity_curve = metrics.get("equity_curve", [])
    last_20 = df.tail(20).to_dict(orient="records")

    rows_html = "".join(
        f"<tr><td>{r['entry_time']}</td><td>{r['killzone']}</td><td>{r['direction']}</td>"
        f"<td>{r['entry_price']}</td><td>{r['exit_price']}</td><td>{r['result']}</td>"
        f"<td>{r['pnl_pips']}</td><td>{r['pnl_r']}</td></tr>"
        for r in last_20
    )

    html = f"""<!DOCTYPE html>
<html lang="fr">
<head>
<meta charset="UTF-8">
<title>ICT Silver Bullet Backtest Report</title>
<script src="https://cdn.jsdelivr.net/npm/chart.js"></script>
<style>
  body {{ font-family: -apple-system, Arial, sans-serif; margin: 2rem; background: #0f1117; color: #e5e7eb; }}
  h1 {{ color: #fff; }}
  .metrics {{ display: flex; flex-wrap: wrap; gap: 1rem; margin-bottom: 2rem; }}
  .card {{ background: #1a1d29; border-radius: 8px; padding: 1rem 1.5rem; min-width: 160px; }}
  .card .value {{ font-size: 1.6rem; font-weight: bold; color: #4ade80; }}
  .card .label {{ font-size: 0.85rem; color: #9ca3af; }}
  .chart-container {{ background: #1a1d29; border-radius: 8px; padding: 1rem; margin-bottom: 2rem; }}
  table {{ width: 100%; border-collapse: collapse; background: #1a1d29; border-radius: 8px; }}
  th, td {{ padding: 0.5rem 0.75rem; text-align: left; border-bottom: 1px solid #2d3140; font-size: 0.85rem; }}
  th {{ color: #9ca3af; }}
</style>
</head>
<body>
<h1>ICT Silver Bullet — Rapport de Backtest</h1>

<div class="metrics">
  <div class="card"><div class="value">{metrics.get('total_trades', 0)}</div><div class="label">Total trades</div></div>
  <div class="card"><div class="value">{metrics.get('win_rate_pct', 0)}%</div><div class="label">Win rate</div></div>
  <div class="card"><div class="value">{metrics.get('profit_factor', 'N/A')}</div><div class="label">Profit factor</div></div>
  <div class="card"><div class="value">{metrics.get('max_drawdown_pct', 0)}%</div><div class="label">Max drawdown</div></div>
  <div class="card"><div class="value">{metrics.get('sharpe_ratio', 0)}</div><div class="label">Sharpe ratio</div></div>
  <div class="card"><div class="value">{metrics.get('trades_per_month', 0)}</div><div class="label">Trades / mois</div></div>
  <div class="card"><div class="value">{metrics.get('best_win_streak', 0)}</div><div class="label">Meilleure série (wins)</div></div>
  <div class="card"><div class="value">{metrics.get('worst_loss_streak', 0)}</div><div class="label">Pire série (losses)</div></div>
</div>

<div class="chart-container"><canvas id="equityChart" height="90"></canvas></div>
<div class="chart-container"><canvas id="monthChart" height="90"></canvas></div>
<div class="chart-container"><canvas id="killzoneChart" height="90"></canvas></div>

<h2>20 derniers trades</h2>
<table>
  <tr><th>Entrée</th><th>Killzone</th><th>Direction</th><th>Prix entrée</th><th>Prix sortie</th><th>Résultat</th><th>Pips</th><th>R</th></tr>
  {rows_html}
</table>

<script>
new Chart(document.getElementById('equityChart'), {{
  type: 'line',
  data: {{
    labels: {json.dumps(list(range(len(equity_curve))))},
    datasets: [{{ label: 'Equity ($)', data: {json.dumps(equity_curve)}, borderColor: '#4ade80', fill: false, tension: 0.1 }}]
  }},
  options: {{ plugins: {{ title: {{ display: true, text: 'Courbe d\\'équité', color: '#e5e7eb' }} }},
    scales: {{ x: {{ ticks: {{ color: '#9ca3af' }} }}, y: {{ ticks: {{ color: '#9ca3af' }} }} }} }}
}});

new Chart(document.getElementById('monthChart'), {{
  type: 'bar',
  data: {{
    labels: {json.dumps(months)},
    datasets: [{{ label: 'Trades par mois', data: {json.dumps(month_counts)}, backgroundColor: '#60a5fa' }}]
  }},
  options: {{ plugins: {{ title: {{ display: true, text: 'Distribution des trades par mois', color: '#e5e7eb' }} }},
    scales: {{ x: {{ ticks: {{ color: '#9ca3af' }} }}, y: {{ ticks: {{ color: '#9ca3af' }} }} }} }}
}});

new Chart(document.getElementById('killzoneChart'), {{
  type: 'bar',
  data: {{
    labels: {json.dumps(kz_labels)},
    datasets: [
      {{ label: 'Gagnants', data: {json.dumps(kz_wins)}, backgroundColor: '#4ade80' }},
      {{ label: 'Perdants', data: {json.dumps(kz_losses)}, backgroundColor: '#f87171' }}
    ]
  }},
  options: {{ plugins: {{ title: {{ display: true, text: 'Trades gagnants vs perdants par killzone', color: '#e5e7eb' }} }},
    scales: {{ x: {{ ticks: {{ color: '#9ca3af' }} }}, y: {{ ticks: {{ color: '#9ca3af' }} }} }} }}
}});
</script>
</body>
</html>
"""
    out_path.write_text(html, encoding="utf-8")


def print_summary(metrics: dict):
    print("\n=== ICT Silver Bullet — Résumé du Backtest ===")
    if metrics.get("total_trades", 0) == 0:
        print("Aucun trade généré sur la période.")
        return
    print(f"Total trades       : {metrics['total_trades']}")
    print(f"Win rate           : {metrics['win_rate_pct']}%")
    print(f"Profit factor      : {metrics['profit_factor']}")
    print(f"Max drawdown       : {metrics['max_drawdown_pct']}%")
    print(f"Sharpe ratio       : {metrics['sharpe_ratio']}")
    print(f"Trades / mois      : {metrics['trades_per_month']}")
    print(f"Meilleure série    : {metrics['best_win_streak']} wins")
    print(f"Pire série         : {metrics['worst_loss_streak']} losses")
    print(f"Equity finale      : ${metrics['final_equity']}")


def parse_args():
    parser = argparse.ArgumentParser(description="Backtest the ICT Silver Bullet strategy.")
    parser.add_argument("--data", type=Path, default=DEFAULT_HISTORICAL_PATH, help="Path to M5 OHLCV CSV.")
    parser.add_argument(
        "--mode",
        choices=["strict", "relaxed"],
        default="strict",
        help="strict = real ICT rules (3 pip sweep, 5 pip FVG, 1h killzones, 1 trade/killzone). "
        "relaxed = synthetic-data validation parameters.",
    )
    return parser.parse_args()


def main():
    args = parse_args()
    sb.set_mode(args.mode)

    m5 = load_m5(args.data)
    trades = run_backtest(m5)
    df = trades_to_dataframe(trades)
    metrics = compute_metrics(trades)

    RESULTS_DIR.mkdir(parents=True, exist_ok=True)
    df.to_csv(RESULTS_DIR / "trades_log.csv", index=False)
    render_html_report(metrics, df, RESULTS_DIR / "backtest_report.html")

    print(f"Mode: {args.mode} | Data: {args.data}")
    print_summary(metrics)
    print(f"\nRapport HTML : {RESULTS_DIR / 'backtest_report.html'}")
    print(f"Journal CSV  : {RESULTS_DIR / 'trades_log.csv'}")


if __name__ == "__main__":
    main()
