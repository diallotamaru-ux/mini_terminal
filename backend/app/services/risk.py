"""
Page Risque : TWR réel du portefeuille et de chaque compte, comparé aux
références, sur la période choisie. Les calculs sont dans terminal/risk.py ;
ce module charge les données et met en forme.
"""

from __future__ import annotations

import datetime as dt
import math

import numpy as np
import pandas as pd

from terminal import metrics as m
from terminal import performance, risk, riskfree
from terminal.benchmark import to_eur, total_return_index
from terminal.errors import MissingCurrency, ProviderUnavailable, UnknownTicker
from terminal.marketdata.base import MarketDataProvider
from terminal.marketdata.rates import RateProvider

from .. import schemas
from ..settings_store import AnalysisSettings, Reference
from .portfolio import Snapshot

LOOKBACK = dt.timedelta(days=10)
EONIA_END = riskfree.ESTR_START - dt.timedelta(days=1)


def _fr_date(d: dt.date) -> str:
    return d.strftime("%d/%m/%Y")


def _round(x, digits: int = 6):
    return None if x is None or (isinstance(x, float) and not math.isfinite(x)) else round(float(x), digits)


def _floats(s: pd.Series, digits: int = 4) -> list[float | None]:
    return [None if pd.isna(v) else round(float(v), digits) for v in s]


# ---------------------------------------------------------------------------
# Séries
# ---------------------------------------------------------------------------

def account_returns(values: pd.Series, inflows: pd.Series, outflows: pd.Series, base: dt.date,
                    grid: pd.DatetimeIndex) -> tuple[pd.Series, dt.date | None]:
    """TWR quotidien en jours ouvrés sur la grille. Avant le premier jour actif : hors série."""
    v, i, o = risk.slice_for_period(values, inflows, outflows, base)
    r, _ = performance.daily_returns(v, i, o)
    bd = risk.to_business_days(r, end=grid[-1].date() if len(grid) else None)
    start = pd.Timestamp(bd.index[0]) if len(bd) else None
    if start is None:
        return pd.Series(dtype=float), None
    g = grid[grid >= start]
    out = pd.Series(0.0, index=g)              # jour sans capital investi : rendement nul
    common = bd.index.intersection(g)
    out.loc[common] = bd.loc[common]
    return out, start.date()


def reference_returns(provider: MarketDataProvider, ref: Reference, base: dt.date, as_of: dt.date,
                      grid: pd.DatetimeIndex, warnings: list[str], sources: list) -> pd.Series:
    start = base - LOOKBACK
    try:
        closes = provider.daily_closes(ref.ticker, start, as_of)
        divs = provider.dividends(ref.ticker, start, as_of)
        fx = provider.fx_rates(ref.currency, start, as_of) if ref.currency != "EUR" else None
    except (UnknownTicker, ProviderUnavailable, MissingCurrency) as e:
        warnings.append(f"Référence {ref.name} indisponible : {e}")
        return pd.Series(np.nan, index=grid)
    sources.extend([closes] + ([fx] if fx is not None else []))
    level = to_eur(total_return_index(closes.closes, divs.closes, float(ref.withholding)),
                   fx.closes if fx is not None else None)
    first = level.first_valid_index()
    if first is None or first.date() > base:
        warnings.append(f"Référence {ref.name} : historique commençant après le début de la période.")
    return risk.index_returns(level, grid, base)


def risk_free(rates: RateProvider, settings: AnalysisSettings, base: dt.date, as_of: dt.date,
              grid: pd.DatetimeIndex, warnings: list[str]) -> tuple[pd.Series, schemas.RiskFreeOut]:
    segs = riskfree.segments(base, as_of, settings.rf_mode,
                             float(settings.rf_fixed_rate) if settings.rf_fixed_rate is not None else None)
    seg_out = [{"name": x.name, "start": x.start.isoformat(), "end": x.end.isoformat()} for x in segs]
    if settings.rf_mode == "zero":
        return pd.Series(0.0, index=grid), schemas.RiskFreeOut(
            mode="zero", label="Taux nul", segments=seg_out, source="réglage", last_date=None,
            last_value=0.0, simulated=False)
    if settings.rf_mode == "fixe":
        rate = float(settings.rf_fixed_rate or 0)
        return riskfree.fixed_rates(rate, grid), schemas.RiskFreeOut(
            mode="fixe", label=segs[0].name, segments=seg_out, source="réglage", last_date=None,
            last_value=rate, simulated=False)
    parts, source, simulated, last = [], rates.name, rates.simulated, None
    try:
        eonia = rates.overnight("eonia", base - LOOKBACK, min(as_of, EONIA_END)).closes \
            if base < riskfree.ESTR_START else pd.Series(dtype=float)
        estr_s = rates.overnight("estr", max(base - LOOKBACK, riskfree.ESTR_START), as_of) \
            if as_of >= riskfree.ESTR_START else None
        estr = estr_s.closes if estr_s is not None else pd.Series(dtype=float)
        if estr_s is not None:
            source, simulated = estr_s.source, estr_s.simulated
        spliced = riskfree.splice_eonia_estr(eonia, estr)
        rf = riskfree.daily_rates(spliced, grid)
        if len(spliced):
            last = (pd.Timestamp(spliced.index[-1]).date(), float(spliced.iloc[-1]))
    except ProviderUnavailable as e:
        rf = pd.Series(np.nan, index=grid)
        warnings.append(f"Taux sans risque indisponible ({e}).")
    if rf.isna().any():
        warnings.append("Taux sans risque manquant sur une partie de la période : calculs avec un taux nul "
                        "pour ces jours. Sharpe, Sortino et alpha sont donc légèrement surestimés.")
        rf = rf.fillna(0.0)
    label = ", puis ".join(f"{x.name} du {_fr_date(x.start)} au {_fr_date(x.end)}" for x in segs)
    return rf, schemas.RiskFreeOut(mode="estr", label=label, segments=seg_out, source=source,
                                   last_date=last[0] if last else None, last_value=last[1] if last else None,
                                   simulated=simulated)


# ---------------------------------------------------------------------------
# Assemblage
# ---------------------------------------------------------------------------

def _row_out(row: risk.RiskRow, start: dt.date | None) -> schemas.RiskRowOut:
    d = {k: _round(getattr(row, k)) for k in (
        "total_return", "annual_return", "volatility", "sharpe", "sortino", "max_drawdown", "calmar", "var95",
        "cvar95", "beta", "beta_dimson", "correlation", "alpha", "tracking_error", "information_ratio")}
    ci = lambda c: [round(c[0], 4), round(c[1], 4)] if c and all(math.isfinite(x) for x in c) else None
    return schemas.RiskRowOut(name=row.name, kind=row.kind, complete=row.complete, first_missing=row.first_missing,
                              start=start, n_days=row.n_days, n_weeks=row.n_weeks, sharpe_ci=ci(row.sharpe_ci),
                              information_ratio_ci=ci(row.information_ratio_ci), is_reference=row.is_reference,
                              notes=row.notes, **d)


def _ref_out(i: int, r: Reference) -> schemas.ReferenceOut:
    return schemas.ReferenceOut(index=i, ticker=r.ticker, name=r.name, currency=r.currency,
                                withholding=float(r.withholding))


def risk_out(snap: Snapshot, provider: MarketDataProvider, rates: RateProvider, settings: AnalysisSettings,
             period: str, reference: int = 1) -> schemas.RiskOut:
    h = snap.history
    if h is None:
        raise risk.PeriodError("Aucune transaction : rien à analyser.")
    as_of = snap.as_of
    first = risk.first_active_day(h.total["value"], h.total["inflow"])
    if first is None:
        raise risk.PeriodError("Aucun capital investi : rien à analyser.")
    base = risk.period_base(period, as_of, first)
    grid = risk.business_grid(base, as_of)
    span = (as_of - base).days
    warnings: list[str] = []
    ref_sources: list = []

    rf, rf_out = risk_free(rates, settings, base, as_of, grid, warnings)
    refs = {i: reference_returns(provider, settings.reference(i), base, as_of, grid, warnings, ref_sources)
            for i in (1, 2)}
    cmp_ref = refs[reference]

    rows: list[schemas.RiskRowOut] = []
    port, port_start = account_returns(h.total["value"], h.total["inflow"], h.total["outflow"], base, grid)
    rows.append(_row_out(risk.risk_row("Portefeuille", "portefeuille", port, rf.reindex(port.index),
                                       cmp_ref.reindex(port.index), span), port_start))
    for a in snap.accounts:
        f = h.accounts[a.id]
        r, start = account_returns(f["value"], f["inflow"], f["outflow"], base, grid)
        a_span = (as_of - start).days + 1 if start else 0
        rows.append(_row_out(risk.risk_row(a.name, "compte", r, rf.reindex(r.index), cmp_ref.reindex(r.index),
                                           min(span, a_span)), start))
    for i in (1, 2):
        ref = settings.reference(i)
        rows.append(_row_out(risk.risk_row(ref.name, "reference", refs[i], rf, cmp_ref, span,
                                           is_reference=(i == reference)), grid[0].date() if len(grid) else None))

    # Courbes : base 100 (TWR), drawdown, volatilité glissante — sur la grille, base au jour `base`.
    def base100(r: pd.Series) -> pd.Series:
        s = m.cumulative_index(r.reindex(grid))
        return pd.concat([pd.Series([100.0], index=[pd.Timestamp(base)]), s])

    def dd(r: pd.Series) -> pd.Series:
        rr = r.reindex(grid)
        return pd.concat([pd.Series([0.0], index=[pd.Timestamp(base)]),
                          m.drawdown_series(rr.fillna(0.0)).where(rr.notna())])

    w = settings.rolling_window
    vol = lambda r: pd.concat([pd.Series([np.nan], index=[pd.Timestamp(base)]),
                               m.rolling_volatility(r.reindex(grid), window=w)])
    p_full = port.reindex(grid)                # avant le premier jour actif : NaN (pas de courbe)
    names = {i: settings.reference(i).name for i in (1, 2)}
    dates = [pd.Timestamp(base).date()] + [d.date() for d in grid]

    meta = snap.meta()
    for s_ in ref_sources:
        meta.sources.append(schemas.SourceInfo(name=s_.source, symbols=[s_.ticker], last_date=s_.last_date,
                                               fetched_at=s_.fetched_at, simulated=s_.simulated))
    meta.sources.append(schemas.SourceInfo(name=f"{rf_out.source} (taux sans risque)", symbols=[rf_out.label],
                                           last_date=rf_out.last_date, fetched_at=None,
                                           simulated=rf_out.simulated))
    meta.simulated = meta.simulated or rf_out.simulated or any(s_.simulated for s_ in ref_sources)
    meta.warnings = meta.warnings + warnings

    return schemas.RiskOut(
        meta=meta, period=period, period_label=risk.PERIOD_LABELS[period], base_date=base, span_days=span,
        available_periods=risk.available_periods(as_of, first),
        reference=_ref_out(reference, settings.reference(reference)),
        references=[_ref_out(i, settings.reference(i)) for i in (1, 2)],
        risk_free=rf_out, rows=rows, dates=dates,
        base100=[schemas.CurveOut(name="Portefeuille", values=_floats(base100(p_full), 3))]
                + [schemas.CurveOut(name=names[i], values=_floats(base100(refs[i]), 3)) for i in (1, 2)],
        drawdown=[schemas.CurveOut(name="Portefeuille", values=_floats(dd(p_full), 5)),
                  schemas.CurveOut(name=names[reference], values=_floats(dd(cmp_ref), 5))],
        rolling_volatility=[schemas.CurveOut(name="Portefeuille", values=_floats(vol(p_full), 5)),
                            schemas.CurveOut(name=names[reference], values=_floats(vol(cmp_ref), 5))],
        rolling_window=w,
        short_history=risk.short_history_warning(span, len(port)),
        warnings=warnings,
    )
