"""
Orchestration : des paramètres utilisateur aux résultats calculés.
Un seul point d'entrée, réutilisé par le tableau de bord, le rapport HTML et la CLI.
"""

from __future__ import annotations

from dataclasses import dataclass, field

import pandas as pd

from . import data, metrics


@dataclass
class Config:
    assets: list[str]
    benchmark: str = "QQQ"
    weights: dict[str, float] | None = None   # None -> poids égaux
    start: str = "2019-01-01"
    end: str | None = None
    rf_annual: float = 0.0
    base_currency: str | None = None          # ex. "EUR" ; None -> aucune conversion
    demo: bool = False
    rolling_window: int = 126


@dataclass
class Results:
    config: Config
    prices: pd.DataFrame
    returns: pd.DataFrame          # actifs seuls
    port: pd.Series
    bench: pd.Series
    weights: pd.Series
    table: pd.DataFrame
    corr: pd.DataFrame
    pca: dict
    mt: dict
    risk_contrib: pd.Series
    warnings: list[str] = field(default_factory=list)


def run(cfg: Config) -> Results:
    warnings: list[str] = []
    tickers = list(dict.fromkeys(cfg.assets + [cfg.benchmark]))

    if cfg.demo:
        raw = data.demo_prices(tickers, cfg.start, cfg.end)
        warnings.append("Mode démo : données simulées, aucune valeur réelle.")
    else:
        raw = data.fetch_prices(tickers, cfg.start, cfg.end)
        if cfg.base_currency:
            cur = data.fetch_currencies(tickers)
            raw = data.convert_to_base(raw, cur, cfg.base_currency, cfg.start, cfg.end)
            converted = [t for t, c in cur.items() if c != cfg.base_currency]
            if converted:
                warnings.append(f"Convertis en {cfg.base_currency} : {', '.join(converted)}.")

    prices = data.align_prices(raw)
    if len(prices) < cfg.rolling_window + 20:
        warnings.append(f"Historique court ({len(prices)} jours) : estimations très bruitées.")

    rets_all = metrics.simple_returns(prices)
    assets_r = rets_all[cfg.assets]
    bench_r = rets_all[cfg.benchmark].rename(f"{cfg.benchmark} (réf.)")

    if cfg.weights:
        w = pd.Series(cfg.weights, dtype=float).reindex(cfg.assets).fillna(0.0)
    else:
        w = pd.Series(1.0, index=cfg.assets)
    if w.sum() <= 0:
        raise ValueError("La somme des poids doit être positive.")
    w = w / w.sum()

    port = metrics.portfolio_returns(assets_r, w)

    all_series = pd.concat([port, assets_r, bench_r], axis=1)
    table = metrics.summary_table(all_series, bench=rets_all[cfg.benchmark],
                                  rf_annual=cfg.rf_annual)

    return Results(
        config=cfg, prices=prices, returns=assets_r, port=port, bench=bench_r,
        weights=w, table=table, corr=assets_r.corr(),
        pca=metrics.pca_diversification(assets_r, w),
        mt=metrics.minimum_torsion_diversification(assets_r, w),
        risk_contrib=metrics.risk_contributions(assets_r, w),
        warnings=warnings,
    )
