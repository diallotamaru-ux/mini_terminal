"""Assemble les graphiques à partir des résultats du moteur."""

from __future__ import annotations

import pandas as pd

from . import charts, metrics
from .engine import Results

PERCENT_COLS = ["Rendement total", "CAGR", "Volatilité", "Max drawdown",
                "VaR 95 % (1 j)", "CVaR 95 % (1 j)", "Alpha (Jensen)", "Tracking error"]
RATIO_COLS = ["Sharpe", "Sortino", "Calmar", "Bêta", "Ratio d'information"]


def build_figures(res: Results, theme: str = "dark", log_scale: bool = True) -> dict:
    assets = list(res.returns.columns)
    colors = charts.color_map(assets, theme)
    bname = res.bench.name
    specials = ("Portefeuille", bname)

    series = pd.concat([res.port, res.returns, res.bench], axis=1)
    wealth = metrics.cumulative_index(series)

    dd = pd.concat([metrics.drawdown_series(res.port).rename("Portefeuille"),
                    metrics.drawdown_series(res.bench).rename(bname)], axis=1)

    win = res.config.rolling_window
    rvol = metrics.rolling_volatility(series, window=63).dropna(how="all")
    rshp = metrics.rolling_sharpe(pd.concat([res.port, res.bench], axis=1),
                                  window=win, rf_annual=res.config.rf_annual).dropna(how="all")

    pca_share = res.pca["portfolio_variance_share"]
    pca_share = pca_share[pca_share.cumsum().shift(fill_value=0) < 0.999].head(8)

    return {
        "performance": charts.performance_chart(wealth, colors, theme, specials, log_scale),
        "drawdown": charts.drawdown_chart(dd, theme, specials),
        "rolling_vol": charts.rolling_chart(rvol, colors, theme, specials,
                                            "Volatilité glissante (63 jours, annualisée)", ".0%"),
        "rolling_sharpe": charts.rolling_chart(rshp, colors, theme, specials,
                                               f"Sharpe glissant ({win} jours)", ".2f"),
        "corr": charts.correlation_heatmap(res.corr, theme),
        "risk_contrib": charts.bar_chart(res.risk_contrib.sort_values(ascending=False), theme,
                                         "Contribution de chaque ligne à la variance (Euler)"),
        "pca": charts.bar_chart(pca_share, theme,
                                "ACP : part de variance du portefeuille par facteur"),
        "mt": charts.bar_chart(res.mt["contributions"].sort_values(ascending=False), theme,
                               "Torsion minimale : part de variance par facteur-actif"),
    }


def format_table(table: pd.DataFrame) -> pd.DataFrame:
    """Version texte de la table, pour l'affichage et l'export."""
    out = table.copy().astype(object)
    for c in out.columns:
        if c in PERCENT_COLS:
            out[c] = table[c].map(lambda v: "" if pd.isna(v) else f"{v:.1%}")
        elif c in RATIO_COLS:
            out[c] = table[c].map(lambda v: "" if pd.isna(v) else f"{v:.2f}")
    return out
