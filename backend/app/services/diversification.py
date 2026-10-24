"""
Page Diversification : charge les poids réels et les rendements des lignes, puis
appelle terminal/diversification.py. Le simulateur n'écrit rien en base.
"""

from __future__ import annotations

import datetime as dt
from dataclasses import dataclass

import numpy as np
import pandas as pd

from terminal import diversification as dv
from terminal import risk
from terminal.covariance import ESTIMATOR_LABELS
from terminal.errors import MissingCurrency, ProviderUnavailable, UnknownTicker
from terminal.marketdata.base import MarketDataProvider

from .. import schemas
from ..settings_store import AnalysisSettings
from .portfolio import Snapshot, positions_out

LOOKBACK = dt.timedelta(days=10)
CLASS_LABELS = {"action": "Actions", "etf": "ETF", "crypto": "Crypto", "autre": "Autres"}


@dataclass
class Prepared:
    base: dt.date
    grid: pd.DatetimeIndex
    window_weeks: int
    daily: pd.DataFrame
    weekly: pd.DataFrame                 # lignes gardées
    kept: list[str]
    excluded: list[dv.Excluded]
    partial: dict[str, int]
    positions: list[dv.Position]
    labels: dict[str, str]
    classes: dict[str, str]
    tickers: dict[str, str]
    cash_eur: float
    cash_known: bool
    warnings: list[str]
    values_known: bool = True            # valeur de marché connue pour toutes les lignes détenues

    @property
    def whole(self) -> bool:
        """Toutes les lignes détenues sont dans l'analyse : la volatilité espèces comprises a un sens."""
        return self.values_known and all(p.line in self.kept for p in self.positions)

    def cash_share_total(self) -> float | None:
        """Part d'espèces rapportée au portefeuille ENTIER (lignes exclues comprises) ; None si inconnue."""
        if not (self.cash_known and self.values_known):
            return None
        total = sum(p.value_eur for p in self.positions) + max(self.cash_eur, 0.0)
        return max(self.cash_eur, 0.0) / total if total > 0 else None


def _r(x, d=6):
    return None if x is None or not np.isfinite(x) else round(float(x), d)


def prepare(snap: Snapshot, period: str, partial: str = "inclure") -> Prepared:
    h = snap.history
    if h is None:
        raise dv.DiversificationError("Aucune transaction : rien à analyser.")
    first = risk.first_active_day(h.total["value"], h.total["inflow"])
    if first is None:
        raise dv.DiversificationError("Aucun capital investi : rien à analyser.")
    base = risk.period_base(period, snap.as_of, first)
    grid = risk.business_grid(base, snap.as_of)
    window_weeks = len(risk.to_weekly(pd.Series(0.0, index=grid))[0]) if len(grid) else 0
    warnings: list[str] = []

    # Positions ouvertes à la date de valorisation, regroupées par titre (ISIN, sinon ticker).
    rows = [p for p in positions_out(snap) if p.is_open]
    labels, classes, tickers = {}, {}, {}
    positions, missing_value = [], set()
    for p in rows:
        key = p.isin or p.ticker
        labels.setdefault(key, p.name or p.ticker)
        classes.setdefault(key, p.asset_class)
        tickers.setdefault(key, p.ticker)           # cotation dont on lit les cours
        if p.market_value_eur is None:
            missing_value.add(key)
            continue
        positions.append(dv.Position(p.account_name, key, float(p.market_value_eur)))

    daily_cols, weekly_cols, excluded = {}, {}, []
    for key, ticker in tickers.items():
        if key in missing_value:
            excluded.append(dv.Excluded(key, labels[key], 0, "valeur de marché manquante à la date de valorisation"))
            continue
        series = snap.series.get(ticker)
        listing = snap.listings.get(ticker)
        cur = listing.currency if listing else "EUR"
        fx = snap.fx_series.get(cur).closes if cur != "EUR" and cur in snap.fx_series else None
        if series is None or (cur != "EUR" and fx is None):
            excluded.append(dv.Excluded(key, labels[key], 0, "cours ou taux de change indisponibles"))
            continue
        d, w = dv.line_returns(series.closes, fx, grid, base)
        daily_cols[key], weekly_cols[key] = d, w
    daily = pd.DataFrame(daily_cols, index=grid)
    weekly_all = pd.DataFrame(weekly_cols)
    kept, short = dv.select_lines(weekly_all, labels) if len(weekly_all.columns) else ([], [])
    excluded += short
    part = {k: int(weekly_all[k].notna().sum()) for k in kept if weekly_all[k].notna().sum() < window_weeks - 1}
    if partial == "exclure":
        for k, n in part.items():
            excluded.append(dv.Excluded(k, labels[k], n, f"historique partiel ({n} semaines sur {window_weeks}), "
                                                         f"exclu pour comparaison"))
        kept = [k for k in kept if k not in part]
        part = {}
    if len(kept) < 2:
        raise dv.DiversificationError(
            f"Moins de deux lignes analysables sur la période ({window_weeks} semaines) : il faut au moins "
            f"{dv.MIN_WEEKS} semaines de cours par ligne.")
    cash_values = list(snap.cash.values())
    cash_known = all(v is not None for v in cash_values)
    if not cash_known:
        warnings.append("Solde d'espèces inconnu (taux de change manquant) : volatilité totale non calculée.")
    cash = float(sum(v for v in cash_values if v is not None))
    p = Prepared(base, grid, window_weeks, daily, weekly_all[kept], kept, excluded, part, positions, labels,
                 classes, tickers, cash, cash_known, warnings, values_known=not missing_value)
    if not p.whole:
        warnings.append("Des lignes détenues sont exclues de l'analyse : leur risque est inconnu, la volatilité du "
                        "portefeuille total (espèces comprises) n'est donc pas calculée. La part d'espèces est "
                        "rapportée au portefeuille entier.")
    return p


def available_periods(snap: Snapshot) -> dict[str, bool]:
    """Périodes couvertes par l'historique ET d'au moins MIN_WEEKS semaines (sinon aucune ligne n'est analysable)."""
    first = risk.first_active_day(snap.history.total["value"], snap.history.total["inflow"])
    out = {}
    for k, ok in risk.available_periods(snap.as_of, first).items():
        out[k] = ok and (snap.as_of - risk.period_base(k, snap.as_of, first)).days >= dv.MIN_WEEKS * 7
    return out


def _items(series: pd.Series, labels: dict[str, str], weights: pd.Series | None = None) -> list[schemas.ContribItem]:
    out = [schemas.ContribItem(key=str(k), label=labels.get(k, str(k)), contribution=_r(v),
                               weight=_r(weights.get(k)) if weights is not None else None)
           for k, v in series.items()]
    return sorted(out, key=lambda i: -(i.contribution or 0))


def diversification_out(snap: Snapshot, settings: AnalysisSettings, period: str,
                        partial: str = "inclure") -> schemas.DiversificationOut:
    p = prepare(snap, period, partial)
    a = dv.analyze(p.weekly, p.positions, p.classes, p.labels, p.cash_eur, settings.covariance)
    est = a.estimate
    rep = est.repair
    warnings = list(p.warnings)
    if rep.warning:
        fr = lambda x: f"{x:.2f}".replace(".", ",")
        warnings.append(
            f"Correction de Higham importante : un coefficient de corrélation a bougé de "
            f"{fr(rep.max_corr_change)} (seuil {fr(rep.threshold)}, erreur-type d'une corrélation sur "
            f"{est.t_min} semaines). Comparez avec les lignes partielles exclues.")
    meta = snap.meta()
    meta.warnings = meta.warnings + warnings
    lines = [schemas.LineOut(key=k, label=p.labels[k], ticker=p.tickers[k], asset_class=p.classes.get(k, "autre"),
                             weight=_r(a.weights[k]), n_weeks=int(p.weekly[k].notna().sum()), partial=k in p.partial)
             for k in a.lines]
    cls = {k: CLASS_LABELS.get(k, k) for k in a.group_contrib["classe"].index}
    return schemas.DiversificationOut(
        meta=meta, period=period, period_label=risk.PERIOD_LABELS[period], base_date=p.base,
        available_periods=available_periods(snap),
        window_start=p.grid[0].date(), window_end=p.grid[-1].date(), window_weeks=p.window_weeks,
        min_weeks=dv.MIN_WEEKS, partial_mode=partial,
        estimator=est.method, estimator_label=ESTIMATOR_LABELS[est.method], shrinkage=_r(est.shrinkage, 4),
        t_min=est.t_min, t_max=est.t_max,
        higham=schemas.HighamOut(applied=rep.applied, frobenius_rel=_r(rep.frobenius_rel, 5),
                                 max_corr_change=_r(rep.max_corr_change, 4), threshold=_r(rep.threshold, 4),
                                 warning=rep.warning),
        lines=lines,
        excluded=[schemas.ExcludedOut(key=e.key, label=e.label, n_weeks=e.n_weeks, reason=e.reason)
                  for e in p.excluded],
        cash_share=_r(p.cash_share_total()),
        sigma_risky=_r(a.sigma_risky), sigma_total=_r(a.sigma_total) if p.cash_known and p.whole else None,
        correlation=schemas.MatrixOut(labels=[p.labels[k] for k in a.lines],
                                      values=[[_r(v, 4) for v in row] for row in a.corr.to_numpy()]),
        contributions={
            "ligne": _items(a.risk_contrib, p.labels, a.weights),
            "compte": _items(a.group_contrib["compte"], {}, a.group_weights["compte"]),
            "classe": _items(a.group_contrib["classe"], cls, a.group_weights["classe"]),
        },
        enb_pca=_r(a.enb_pca, 4), enb_mt=_r(a.enb_mt, 4), n_lines=len(a.lines),
        pc1_variance_share=_r(a.pc1_variance_share, 4), pc1_eigen_share=_r(a.pc1_eigen_share, 4),
        pc1_loadings=_items(a.pc1_loadings, p.labels),
        mt_contributions=_items(a.mt_contrib, p.labels, a.weights),
        text=a.text, warnings=warnings,
    )


def simulate_out(snap: Snapshot, provider: MarketDataProvider, settings: AnalysisSettings,
                 body: schemas.SimulationIn) -> schemas.SimulationOut:
    p = prepare(snap, body.period, "inclure")
    a = dv.analyze(p.weekly, p.positions, p.classes, p.labels, p.cash_eur, settings.covariance)
    ticker = body.ticker.strip().upper()
    key = next((k for k, t in p.tickers.items() if t == ticker or k == ticker), None)
    weekly, daily, labels = p.weekly.copy(), p.daily[p.kept].copy(), dict(p.labels)
    notes = []
    if key is None or key not in p.kept:
        if key is not None:
            raise dv.DiversificationError(f"{ticker} est détenu mais exclu de l'analyse (historique insuffisant).")
        info = provider.instrument_info(ticker)                       # UnknownTicker -> 422
        try:
            closes = provider.daily_closes(ticker, p.base - LOOKBACK, snap.as_of).closes
            fx = provider.fx_rates(info.currency, p.base - LOOKBACK, snap.as_of).closes \
                if info.currency != "EUR" else None
        except (ProviderUnavailable, MissingCurrency, UnknownTicker) as e:
            raise dv.DiversificationError(f"Cours de {ticker} indisponibles : {e}") from e
        d, w = dv.line_returns(closes, fx, p.grid, p.base)
        n = int(w.notna().sum())
        if n < dv.MIN_WEEKS:
            raise dv.DiversificationError(f"{ticker} : {n} semaines de cours sur la période, "
                                          f"minimum {dv.MIN_WEEKS}.")
        key = ticker
        weekly[key], daily[key] = w, d
        labels[key] = info.name or ticker
        notes.append("Nouveau ticker : la covariance « avant » est estimée avec lui (poids nul), pour que avant "
                     "et après soient comparables ; les ENB « avant » peuvent donc différer légèrement de ceux "
                     "de la page.")
    x = body.pct / 100.0
    before, after, est = dv.simulate(weekly, daily, a.weights, key, x, body.mode, settings.covariance, a.cash_share)
    common = daily.dropna()
    contrib = [schemas.SimContrib(key=k, label=labels.get(k, k), weight_before=_r(before.weights[k]),
                                  weight_after=_r(after.weights[k]), before=_r(before.risk_contrib[k]),
                                  after=_r(after.risk_contrib[k]))
               for k in weekly.columns]
    contrib.sort(key=lambda c: -(c.after or 0))
    scen = lambda s_: schemas.ScenarioOut(enb_pca=_r(s_.enb_pca, 4), enb_mt=_r(s_.enb_mt, 4),
                                          sigma_risky=_r(s_.sigma_risky), sigma_total=_r(s_.sigma_total)
                                          if p.cash_known and p.whole else None, max_drawdown=_r(s_.max_drawdown))
    return schemas.SimulationOut(
        target=key, target_label=labels.get(key, key), pct=body.pct, mode=body.mode, formula=dv.FORMULAS[body.mode],
        before=scen(before), after=scen(after), contributions=contrib,
        drawdown_start=common.index[0].date() if len(common) else None,
        drawdown_end=common.index[-1].date() if len(common) else None,
        estimator_label=ESTIMATOR_LABELS[est.method], notes=notes,
        disclaimer="Simulation sur données passées, à poids constants pour le drawdown. Ce n'est pas un conseil "
                   "d'investissement ; rien n'est enregistré.")
