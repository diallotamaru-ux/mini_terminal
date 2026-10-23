"""
Génère un rapport HTML autonome, publiable tel quel (WordPress, GitHub Pages...).

    python legacy/report.py                 # paramètres de config.py, données réelles
    python legacy/report.py --demo          # données simulées, hors ligne
    python legacy/report.py --theme light   # fond clair, pour un article de blog
"""

from __future__ import annotations

import argparse
import html
import sys
from datetime import date
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))  # racine du projet

from config import DEFAULT
from terminal import charts, engine, views


def render(res: engine.Results, theme: str) -> str:
    t = charts.THEMES[theme]
    figs = views.build_figures(res, theme=theme)
    order = ["performance", "drawdown", "rolling_sharpe", "rolling_vol",
             "corr", "risk_contrib", "pca", "mt"]
    blocks = []
    for i, key in enumerate(order):
        blocks.append(figs[key].to_html(full_html=False,
                                        include_plotlyjs="cdn" if i == 0 else False,
                                        config={"displaylogo": False, "responsive": True}))

    table = views.format_table(res.table)
    table_html = table.to_html(classes="metrics", border=0, escape=True)

    p = res.table.loc["Portefeuille"]
    p0, p1 = res.prices.index[0].date(), res.prices.index[-1].date()
    notes = "".join(f"<p class='warn'>{html.escape(w)}</p>" for w in res.warnings)
    tiles = [
        ("CAGR", f"{p['CAGR']:.1%}"), ("Volatilité", f"{p['Volatilité']:.1%}"),
        ("Sharpe", f"{p['Sharpe']:.2f}"), ("Max drawdown", f"{p['Max drawdown']:.1%}"),
        ("ENB ACP / torsion", f"{res.pca['enb']:.2f} / {res.mt['enb']:.2f}"),
    ]
    tiles_html = "".join(f"<div class='tile'><span>{k}</span><b>{v}</b></div>" for k, v in tiles)
    weights = ", ".join(f"{a} {w:.0%}" for a, w in res.weights.items())

    return f"""<!doctype html>
<html lang="fr"><head><meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<title>Mini-terminal</title>
<style>
  body {{margin:0; background:{t['page']}; color:{t['ink']};
        font-family:system-ui,-apple-system,"Segoe UI",sans-serif;}}
  main {{max-width:1100px; margin:0 auto; padding:24px 16px 48px;}}
  h1 {{font-size:26px; margin:0 0 4px;}}
  .meta, .foot {{color:{t['muted']}; font-size:13px;}}
  .warn {{color:{t['ink2']}; border-left:3px solid #fab219; padding:4px 10px;}}
  .tiles {{display:grid; grid-template-columns:repeat(auto-fit,minmax(160px,1fr));
          gap:10px; margin:18px 0;}}
  .tile {{background:{t['surface']}; border:1px solid {t['grid']}; border-radius:8px;
         padding:12px 14px; display:flex; flex-direction:column; gap:4px;}}
  .tile span {{color:{t['ink2']}; font-size:12px;}}
  .tile b {{font-size:22px; font-weight:600;}}
  .card {{background:{t['surface']}; border:1px solid {t['grid']}; border-radius:8px;
         padding:8px; margin:12px 0; overflow-x:auto;}}
  table.metrics {{border-collapse:collapse; width:100%; font-size:13px;
                  font-variant-numeric:tabular-nums;}}
  table.metrics th, table.metrics td {{padding:6px 8px; text-align:right;
                  border-bottom:1px solid {t['grid']}; white-space:nowrap;}}
  table.metrics th:first-child, table.metrics tbody th {{text-align:left;}}
  table.metrics thead th {{color:{t['ink2']}; font-weight:600;}}
</style></head>
<body><main>
<h1>Mini-terminal</h1>
<p class="meta">{len(res.prices)} séances, du {p0} au {p1}. Référence : {html.escape(res.config.benchmark)}.
Poids : {html.escape(weights)}. Taux sans risque : {res.config.rf_annual:.2%}. Généré le {date.today()}.</p>
{notes}
<div class="tiles">{tiles_html}</div>
{''.join(f"<div class='card'>{b}</div>" for b in blocks)}
<div class="card">{table_html}</div>
<p class="foot">Mesures calculées sur données passées : ce ne sont pas des prévisions.
Rendements quotidiens, annualisation sur 252 séances, portefeuille rééquilibré chaque jour.</p>
</main></body></html>"""


def main() -> None:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--demo", action="store_true", help="données simulées hors ligne")
    ap.add_argument("--theme", choices=["dark", "light"], default="dark")
    ap.add_argument("--out", default="rapport.html")
    args = ap.parse_args()

    cfg = engine.Config(
        assets=DEFAULT["assets"], benchmark=DEFAULT["benchmark"],
        weights=DEFAULT.get("weights"), start=DEFAULT["start"],
        rf_annual=DEFAULT["rf_annual"], base_currency=DEFAULT["base_currency"],
        demo=args.demo or DEFAULT["demo"], rolling_window=DEFAULT["rolling_window"],
    )
    res = engine.run(cfg)
    out = Path(args.out)
    out.write_text(render(res, args.theme), encoding="utf-8")
    print(f"Rapport écrit : {out.resolve()}")
    print(views.format_table(res.table)[["CAGR", "Volatilité", "Sharpe", "Max drawdown"]].to_string())


if __name__ == "__main__":
    main()
