"""Analyse Silver Bullet en live pour une journée de trading.

Réutilise strategies.silver_bullet pour produire, sur le dernier jour des données :
  - le biais HTF (H4) actuel
  - les niveaux de liquidité BSL / SSL alimentant les killzones
  - les sweeps détectés pendant la killzone London (08h-09h Cotonou / 07h-08h UTC)
  - les FVG actifs (non comblés)
  - un signal potentiel pour la killzone NY AM à venir (15h-16h Cotonou / 14h-15h UTC)

Les heures du rapport sont affichées en heure locale de Cotonou (UTC+1).
"""
import argparse
import json
import sys
from datetime import datetime
from pathlib import Path
from zoneinfo import ZoneInfo

import pandas as pd

if hasattr(sys.stdout, "reconfigure"):
    sys.stdout.reconfigure(encoding="utf-8")

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

import strategies.silver_bullet as sb
from strategies.silver_bullet import (
    PIP,
    compute_htf_bias,
    find_all_sweeps,
    killzone_window,
    resample_h4,
)

COTONOU = ZoneInfo("Africa/Porto-Novo")  # UTC+1, no DST
RESULTS_DIR = Path(__file__).parent.parent / "results"


def load_m5(path: Path) -> pd.DataFrame:
    df = pd.read_csv(path, parse_dates=["timestamp"]).set_index("timestamp").sort_index()
    if df.index.tz is None:
        df.index = df.index.tz_localize("UTC")
    return df


def fmt_cot(ts: pd.Timestamp) -> str:
    return ts.tz_convert(COTONOU).strftime("%Y-%m-%d %H:%M") + " (Cotonou)"


def htf_liquidity(df: pd.DataFrame, before, lookback: int = 2):
    """Dernier swing high (BSL) et swing low (SSL) d'un TF supérieur, avant `before`.

    Renvoie les niveaux de liquidité ICT que le prix est susceptible d'aller chercher.
    """
    from strategies.silver_bullet import find_swing_points

    win = df.loc[df.index < before]
    if len(win) < 2 * lookback + 1:
        return None, None
    marked = find_swing_points(win, lookback=lookback)
    sh = marked.loc[marked["swing_high"], "high"]
    sl = marked.loc[marked["swing_low"], "low"]
    bsl = float(sh.iloc[-1]) if len(sh) else None  # liquidité acheteuse (au-dessus)
    ssl = float(sl.iloc[-1]) if len(sl) else None   # liquidité vendeuse (en-dessous)
    return bsl, ssl


def active_fvgs(m5: pd.DataFrame, day_start, lookback_bars: int = 96):
    """Trouve les FVG formés dans la fenêtre de lookback que le prix n'a PAS encore comblés."""
    win = m5.loc[(m5.index >= day_start - pd.Timedelta(minutes=5 * lookback_bars)) & (m5.index <= m5.index.max())]
    fvgs = []
    highs, lows = win["high"].values, win["low"].values
    idx = win.index
    last_close = float(win["close"].iloc[-1])
    for k in range(2, len(win)):
        c1_high, c1_low = highs[k - 2], lows[k - 2]
        c3_high, c3_low = highs[k], lows[k]
        # bullish FVG: gap between candle1 high and candle3 low
        if c3_low > c1_high and (c3_low - c1_high) / PIP >= sb.MIN_FVG_PIPS:
            bottom, top = c1_high, c3_low
            filled = (win["low"].iloc[k + 1 :] <= bottom).any() if k + 1 < len(win) else False
            if not filled:
                fvgs.append({"type": "bullish", "time": idx[k], "bottom": bottom, "top": top,
                             "size_pips": round((top - bottom) / PIP, 1)})
        # bearish FVG: gap between candle1 low and candle3 high
        if c3_high < c1_low and (c1_low - c3_high) / PIP >= sb.MIN_FVG_PIPS:
            bottom, top = c3_high, c1_low
            filled = (win["high"].iloc[k + 1 :] >= top).any() if k + 1 < len(win) else False
            if not filled:
                fvgs.append({"type": "bearish", "time": idx[k], "bottom": bottom, "top": top,
                             "size_pips": round((top - bottom) / PIP, 1)})
    return fvgs, last_close


def analyze(m5: pd.DataFrame, mode: str, h4_real: pd.DataFrame | None = None,
            h1: pd.DataFrame | None = None, m15: pd.DataFrame | None = None) -> dict:
    sb.set_mode(mode)
    # On privilégie le flux H4 dédié (plusieurs mois d'historique) plutôt qu'un resample
    # M5 court : sur quelques jours de live il donne trop peu de swings H4 pour un biais fiable.
    h4 = h4_real if h4_real is not None else resample_h4(m5)

    last_day = pd.Timestamp(m5.index.max().tz_convert("UTC").date())
    day_ts = last_day  # date calendaire sans fuseau pour killzone_window

    # --- Biais HTF (swings H4 strictement avant aujourd'hui) ---
    h4_upto = h4.loc[h4.index < last_day.tz_localize("UTC")]
    bias = compute_htf_bias(h4_upto)

    # --- BSL / SSL : plus haut / plus bas alimentant la killzone London ---
    lon_start, lon_end = killzone_window(day_ts, "london")
    lb_start = lon_start - pd.Timedelta(minutes=5 * sb.LOOKBACK_BARS)
    lookback = m5.loc[(m5.index >= lb_start) & (m5.index < lon_start)]
    bsl = float(lookback["high"].max()) if len(lookback) else None  # liquidité acheteuse (au-dessus)
    ssl = float(lookback["low"].min()) if len(lookback) else None   # liquidité vendeuse (en-dessous)

    # --- BSL / SSL sur H1 et M15 (swings des TF supérieurs avant la killzone London) ---
    h1_bsl, h1_ssl = htf_liquidity(h1, lon_start) if h1 is not None else (None, None)
    m15_bsl, m15_ssl = htf_liquidity(m15, lon_start) if m15 is not None else (None, None)

    # --- Sweeps pendant la killzone London ---
    lon_win = m5.loc[(m5.index >= lon_start) & (m5.index < lon_end)]
    sweeps = []
    if len(lon_win) and bsl is not None:
        for direction in ("bullish", "bearish"):
            rel_idxs, level = find_all_sweeps(lon_win, ssl, bsl, direction)
            for ri in rel_idxs:
                bar = lon_win.iloc[ri]
                sweeps.append({
                    "time": lon_win.index[ri],
                    "direction": direction,
                    "liquidity": "SSL" if direction == "bullish" else "BSL",
                    "level": ssl if direction == "bullish" else bsl,
                    "wick": float(bar["low"] if direction == "bullish" else bar["high"]),
                    "close": float(bar["close"]),
                })
    sweeps.sort(key=lambda s: s["time"])

    # --- Active unfilled FVGs ---
    fvgs, last_close = active_fvgs(m5, lon_start)

    # --- Potential NY AM signal ---
    ny_start, ny_end = killzone_window(day_ts, "ny_am")
    ny_have_data = m5.index.max() >= ny_start
    # lecture directionnelle : biais + quelle liquidité London a déjà balayée
    swept_ssl = any(s["liquidity"] == "SSL" for s in sweeps)
    swept_bsl = any(s["liquidity"] == "BSL" for s in sweeps)
    if bias == "bullish":
        ny_dir = "LONG (buy)"
    elif bias == "bearish":
        ny_dir = "SHORT (sell)"
    else:
        ny_dir = "LONG ou SHORT (biais neutre)"
    aligned_fvgs = [f for f in fvgs if (bias == "bullish" and f["type"] == "bullish")
                    or (bias == "bearish" and f["type"] == "bearish") or bias == "neutral"]

    return {
        "as_of_utc": m5.index.max().isoformat(),
        "as_of_cotonou": fmt_cot(m5.index.max()),
        "day": str(last_day.date()),
        "mode": mode,
        "htf_bias": bias,
        "bsl": bsl,
        "ssl": ssl,
        "h1_bsl": h1_bsl, "h1_ssl": h1_ssl,
        "m15_bsl": m15_bsl, "m15_ssl": m15_ssl,
        "london_window": (fmt_cot(lon_start), fmt_cot(lon_end)),
        "london_bars": len(lon_win),
        "sweeps": sweeps,
        "active_fvgs": fvgs,
        "last_close": last_close,
        "ny_am_window": (fmt_cot(ny_start), fmt_cot(ny_end)),
        "ny_am_have_data": bool(ny_have_data),
        "ny_am_direction": ny_dir,
        "ny_am_swept_ssl": swept_ssl,
        "ny_am_swept_bsl": swept_bsl,
        "ny_am_aligned_fvgs": aligned_fvgs,
    }


def render_markdown(a: dict) -> str:
    L = []
    L.append(f"# Analyse ICT Silver Bullet — EUR/USD (EURUSDm)")
    L.append("")
    L.append(f"- **Date du rapport** : {a['day']} (29/06/2026)")
    L.append(f"- **Dernière donnée** : {a['as_of_cotonou']} / {a['as_of_utc']} UTC")
    L.append(f"- **Mode** : `{a['mode']}` (règles ICT réelles)")
    L.append(f"- **Source** : `data/live/EURUSDm_M5.csv` (flux MT5 live)")
    L.append("")
    L.append("## 1. Biais HTF (H4)")
    bias_fr = {"bullish": "🟢 BULLISH (haussier)", "bearish": "🔴 BEARISH (baissier)",
               "neutral": "⚪ NEUTRE (structure mixte)", None: "❓ Indéterminé (données H4 insuffisantes)"}
    L.append(f"**{bias_fr.get(a['htf_bias'])}**")
    L.append("")
    L.append("## 2. Niveaux de liquidité (BSL / SSL)")
    def _lvl(v):
        return f"{v:.5f}" if v else "n/a"
    L.append("")
    L.append("| Source | BSL (au-dessus) | SSL (en-dessous) |")
    L.append("|---|---|---|")
    L.append(f"| M5 (pre-London) | `{_lvl(a['bsl'])}` | `{_lvl(a['ssl'])}` |")
    L.append(f"| H1 (swing) | `{_lvl(a['h1_bsl'])}` | `{_lvl(a['h1_ssl'])}` |")
    L.append(f"| M15 (swing) | `{_lvl(a['m15_bsl'])}` | `{_lvl(a['m15_ssl'])}` |")
    L.append(f"")
    L.append(f"- Dernier close : `{a['last_close']:.5f}`")
    L.append("")
    L.append(f"## 3. Sweeps — Killzone London ({a['london_window'][0]} → {a['london_window'][1]})")
    if a["sweeps"]:
        L.append("")
        L.append("| Heure (Cotonou) | Type | Liquidité | Niveau | Wick | Close |")
        L.append("|---|---|---|---|---|---|")
        for s in a["sweeps"]:
            L.append(f"| {fmt_cot(pd.Timestamp(s['time']))} | {s['direction']} | {s['liquidity']} "
                     f"| {s['level']:.5f} | {s['wick']:.5f} | {s['close']:.5f} |")
    else:
        L.append(f"Aucun sweep détecté pendant la killzone London ({a['london_bars']} bougies M5 analysées, "
                 f"seuil strict = {sb.MIN_SWEEP_PIPS} pips).")
    L.append("")
    L.append("## 4. FVG actifs (non comblés)")
    if a["active_fvgs"]:
        L.append("")
        L.append("| Formé (Cotonou) | Type | Bas | Haut | Taille (pips) |")
        L.append("|---|---|---|---|---|")
        for f in a["active_fvgs"]:
            L.append(f"| {fmt_cot(pd.Timestamp(f['time']))} | {f['type']} | {f['bottom']:.5f} "
                     f"| {f['top']:.5f} | {f['size_pips']} |")
    else:
        L.append(f"Aucun FVG actif non comblé (seuil strict = {sb.MIN_FVG_PIPS} pips).")
    L.append("")
    L.append(f"## 5. Signal potentiel — Killzone NY AM ({a['ny_am_window'][0]} → {a['ny_am_window'][1]})")
    L.append("")
    if not a["ny_am_have_data"]:
        L.append("> ⏳ Killzone NY AM **à venir** — données live pas encore disponibles. Lecture prospective :")
        L.append("")
    L.append(f"- **Direction selon biais HTF** : **{a['ny_am_direction']}**")
    L.append(f"- London a balayé la SSL : {'oui' if a['ny_am_swept_ssl'] else 'non'}")
    L.append(f"- London a balayé la BSL : {'oui' if a['ny_am_swept_bsl'] else 'non'}")
    if a["ny_am_aligned_fvgs"]:
        L.append(f"- **{len(a['ny_am_aligned_fvgs'])} FVG aligné(s) avec le biais** comme zone(s) d'entrée potentielle(s) :")
        for f in a["ny_am_aligned_fvgs"]:
            L.append(f"  - {f['type']} FVG `{f['bottom']:.5f}`–`{f['top']:.5f}` "
                     f"(mid `{(f['bottom']+f['top'])/2:.5f}`, {f['size_pips']} pips)")
    else:
        L.append("- Aucun FVG aligné avec le biais pour l'instant — attendre un sweep + MSS pendant la NY AM.")
    L.append("")
    L.append("### Plan d'exécution NY AM")
    L.append("1. Attendre un **sweep** de liquidité (SSL si biais long, BSL si biais short) dans la fenêtre 15h-16h.")
    L.append("2. Confirmer un **MSS/CHoCH** dans le sens du biais.")
    L.append("3. Entrer sur le **retrace au 50% du premier FVG** post-MSS ; SL au-delà du niveau balayé (+2 pips), TP à 2R.")
    L.append("")
    L.append("---")
    L.append(f"*Généré le {datetime.now(COTONOU).strftime('%Y-%m-%d %H:%M')} (Cotonou) — ICT Silver Bullet, mode strict.*")
    return "\n".join(L)


def render_html(a: dict) -> str:
    """Rendu HTML autonome (thème sombre) du rapport d'analyse Silver Bullet."""
    def lvl(v):
        return f"{v:.5f}" if v else "n/a"

    bias_fr = {"bullish": ("🟢 BULLISH (haussier)", "#4ade80"),
               "bearish": ("🔴 BEARISH (baissier)", "#f87171"),
               "neutral": ("⚪ NEUTRE (structure mixte)", "#9ca3af"),
               None: ("❓ Indéterminé", "#9ca3af")}
    bias_txt, bias_col = bias_fr.get(a["htf_bias"])

    sweeps_rows = "".join(
        f"<tr><td>{fmt_cot(pd.Timestamp(s['time']))}</td><td>{s['direction']}</td>"
        f"<td>{s['liquidity']}</td><td>{s['level']:.5f}</td><td>{s['wick']:.5f}</td>"
        f"<td>{s['close']:.5f}</td></tr>"
        for s in a["sweeps"]
    ) or f"<tr><td colspan='6'>Aucun sweep détecté ({a['london_bars']} bougies M5, seuil {sb.MIN_SWEEP_PIPS} pips).</td></tr>"

    fvg_rows = "".join(
        f"<tr><td>{fmt_cot(pd.Timestamp(f['time']))}</td><td>{f['type']}</td>"
        f"<td>{f['bottom']:.5f}</td><td>{f['top']:.5f}</td><td>{f['size_pips']}</td></tr>"
        for f in a["active_fvgs"]
    ) or f"<tr><td colspan='5'>Aucun FVG actif non comblé (seuil {sb.MIN_FVG_PIPS} pips).</td></tr>"

    ny_note = ("<p class='warn'>⏳ Killzone NY AM <b>à venir</b> — lecture prospective.</p>"
               if not a["ny_am_have_data"] else "")
    aligned = "".join(
        f"<li>{f['type']} FVG <code>{f['bottom']:.5f}</code>–<code>{f['top']:.5f}</code> "
        f"(mid <code>{(f['bottom']+f['top'])/2:.5f}</code>, {f['size_pips']} pips)</li>"
        for f in a["ny_am_aligned_fvgs"]
    ) or "<li>Aucun FVG aligné avec le biais — attendre un sweep + MSS pendant la NY AM.</li>"

    return f"""<!DOCTYPE html>
<html lang="fr"><head><meta charset="UTF-8">
<title>ICT Silver Bullet — Rapport {a['day']}</title>
<style>
 body {{ font-family:-apple-system,Arial,sans-serif; margin:2rem; background:#0f1117; color:#e5e7eb; }}
 h1 {{ color:#fff; }} h2 {{ color:#fff; border-bottom:1px solid #2d3140; padding-bottom:.3rem; margin-top:2rem; }}
 .bias {{ font-size:1.5rem; font-weight:bold; color:{bias_col}; }}
 table {{ width:100%; border-collapse:collapse; background:#1a1d29; border-radius:8px; margin-top:.5rem; }}
 th,td {{ padding:.5rem .75rem; text-align:left; border-bottom:1px solid #2d3140; font-size:.9rem; }}
 th {{ color:#9ca3af; }} code {{ color:#60a5fa; }} .warn {{ color:#fbbf24; }}
 .meta {{ color:#9ca3af; font-size:.9rem; }}
 ol li, ul li {{ margin:.3rem 0; }}
</style></head><body>
<h1>ICT Silver Bullet — Rapport EUR/USD (EURUSDm)</h1>
<p class="meta">Date : <b>{a['day']}</b> (29/06/2026) · Dernière donnée : {a['as_of_cotonou']} ({a['as_of_utc']} UTC)
 · Mode : <code>{a['mode']}</code> · Source : flux MT5 live</p>

<h2>1. Biais HTF (H4)</h2>
<p class="bias">{bias_txt}</p>

<h2>2. Niveaux de liquidité (BSL / SSL)</h2>
<table>
 <tr><th>Source</th><th>BSL (au-dessus)</th><th>SSL (en-dessous)</th></tr>
 <tr><td>M5 (pre-London)</td><td><code>{lvl(a['bsl'])}</code></td><td><code>{lvl(a['ssl'])}</code></td></tr>
 <tr><td>H1 (swing)</td><td><code>{lvl(a['h1_bsl'])}</code></td><td><code>{lvl(a['h1_ssl'])}</code></td></tr>
 <tr><td>M15 (swing)</td><td><code>{lvl(a['m15_bsl'])}</code></td><td><code>{lvl(a['m15_ssl'])}</code></td></tr>
</table>
<p class="meta">Dernier close : <code>{a['last_close']:.5f}</code></p>

<h2>3. Sweeps — Killzone London ({a['london_window'][0]} → {a['london_window'][1]})</h2>
<table>
 <tr><th>Heure (Cotonou)</th><th>Type</th><th>Liquidité</th><th>Niveau</th><th>Wick</th><th>Close</th></tr>
 {sweeps_rows}
</table>

<h2>4. FVG actifs (non comblés) — M5</h2>
<table>
 <tr><th>Formé (Cotonou)</th><th>Type</th><th>Bas</th><th>Haut</th><th>Taille (pips)</th></tr>
 {fvg_rows}
</table>

<h2>5. Signal potentiel — Killzone NY AM ({a['ny_am_window'][0]} → {a['ny_am_window'][1]})</h2>
{ny_note}
<ul>
 <li><b>Direction selon biais HTF :</b> {a['ny_am_direction']}</li>
 <li>London a balayé la SSL : {'oui' if a['ny_am_swept_ssl'] else 'non'}</li>
 <li>London a balayé la BSL : {'oui' if a['ny_am_swept_bsl'] else 'non'}</li>
</ul>
<p><b>FVG alignés avec le biais (zones d'entrée) :</b></p>
<ul>{aligned}</ul>
<h3>Plan d'exécution NY AM</h3>
<ol>
 <li>Attendre un <b>sweep</b> de liquidité (SSL si biais long, BSL si biais short) entre 15h et 16h.</li>
 <li>Confirmer un <b>MSS/CHoCH</b> dans le sens du biais.</li>
 <li>Entrer sur le <b>retrace au 50% du premier FVG</b> post-MSS ; SL au-delà du niveau balayé (+2 pips), TP à 2R.</li>
</ol>
<p class="meta">Généré le {datetime.now(COTONOU).strftime('%Y-%m-%d %H:%M')} (Cotonou) — ICT Silver Bullet, mode strict.</p>
</body></html>"""


def parse_args():
    p = argparse.ArgumentParser(description="Analyse Silver Bullet en live sur une journée.")
    p.add_argument("--data", type=Path, required=True, help="CSV M5 (flux live).")
    p.add_argument("--htf", type=Path, default=None, help="CSV H4 dédié pour le biais HTF.")
    p.add_argument("--h1", type=Path, default=None, help="CSV H1 pour la liquidité BSL/SSL.")
    p.add_argument("--m15", type=Path, default=None, help="CSV M15 pour la liquidité BSL/SSL.")
    p.add_argument("--mode", choices=["strict", "relaxed"], default="strict")
    p.add_argument("--out", type=Path, default=None, help="Chemin du rapport Markdown.")
    p.add_argument("--html", type=Path, default=None, help="Chemin du rapport HTML.")
    return p.parse_args()


def main():
    args = parse_args()
    m5 = load_m5(args.data)
    h4_real = load_m5(args.htf) if args.htf else None
    h1 = load_m5(args.h1) if args.h1 else None
    m15 = load_m5(args.m15) if args.m15 else None
    a = analyze(m5, args.mode, h4_real, h1, m15)
    md = render_markdown(a)

    RESULTS_DIR.mkdir(parents=True, exist_ok=True)
    out = args.out or (RESULTS_DIR / "silver_bullet_live_2026-06-29.md")
    out.write_text(md, encoding="utf-8")
    (out.with_suffix(".json")).write_text(json.dumps(a, default=str, indent=2), encoding="utf-8")
    html_out = args.html or (RESULTS_DIR / "report_29062026.html")
    html_out.write_text(render_html(a), encoding="utf-8")

    print(md)
    print(f"\n[rapport HTML] {html_out}")
    print(f"\n[rapport] {out}")
    print(f"[json]    {out.with_suffix('.json')}")


if __name__ == "__main__":
    main()
