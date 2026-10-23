"""
Risque et comparaison à une référence, sur une période choisie.

Fréquences :
- quotidienne (jours ouvrés) pour le rendement, la volatilité, le drawdown, la
  VaR, le Sharpe et le Sortino : mesures propres à une série ;
- hebdomadaire (semaines terminées le vendredi) pour le bêta, l'alpha, la
  corrélation, la tracking error et le ratio d'information : mesures croisées,
  biaisées vers zéro en quotidien par les clôtures non synchrones d'Euronext
  (17 h 30) et de New York (22 h, heure de Paris). Scholes et Williams (1977),
  Dimson (1979).

Le taux sans risque varie dans le temps : les fonctions de `metrics` reçoivent
des rendements excédentaires r_t - rf_t avec rf_annual = 0, ce qui est la même
formule avec un taux variable.

Une période est définie par sa date de base b (clôture de référence) et la date
de valorisation : elle couvre les rendements des jours d de ]b, as_of].
"""

from __future__ import annotations

import math
from dataclasses import dataclass, field
from datetime import date, timedelta

import numpy as np
import pandas as pd

from . import metrics as m
from .errors import TerminalError
from .performance import DAYS_PER_YEAR, annualize

PERIODS = ("origine", "ytd", "1y", "3y", "5y")
PERIOD_LABELS = {"origine": "Depuis l'origine", "ytd": "Depuis le début de l'année", "1y": "1 an",
                 "3y": "3 ans", "5y": "5 ans"}
WEEKLY = 52
MIN_WEEKS = 26
SHORT_HISTORY_YEARS = 3


class PeriodError(TerminalError):
    pass


def _fr(x: float, digits: int) -> str:
    """Nombre à la française dans un message : 1,2 et non 1.2."""
    return f"{x:.{digits}f}".replace(".", ",")


# ---------------------------------------------------------------------------
# Périodes
# ---------------------------------------------------------------------------

def _years_back(d: date, years: int) -> date:
    try:
        return d.replace(year=d.year - years)
    except ValueError:                        # 29 février -> 28 février
        return d.replace(year=d.year - years, day=28)


def first_active_day(values: pd.Series, inflows: pd.Series) -> date | None:
    """Premier jour avec du capital investi (valeur non nulle ou apport). Une valeur inconnue compte comme active."""
    active = (values.fillna(1.0).abs() > 1e-9) | (inflows.fillna(0.0) > 0)
    return pd.Timestamp(values.index[active.to_numpy()][0]).date() if active.any() else None


def period_base(period: str, as_of: date, first_day: date) -> date:
    """
    Date de base b de la période. `first_day` : premier jour avec du capital
    investi ; la base la plus ancienne possible est sa veille. Lève PeriodError
    si la période dépasse l'historique.
    """
    origin = first_day - timedelta(days=1)
    if period == "origine":
        return origin
    if period == "ytd":
        b = date(as_of.year - 1, 12, 31)
    elif period in ("1y", "3y", "5y"):
        b = _years_back(as_of, int(period[0]))
    else:
        raise PeriodError(f"Période inconnue : {period}")
    if b < origin:
        years = (as_of - origin).days / DAYS_PER_YEAR
        raise PeriodError(f"Période « {PERIOD_LABELS[period]} » plus longue que l'historique "
                          f"({_fr(years, 1)} ans).")
    return b


def available_periods(as_of: date, first_day: date) -> dict[str, bool]:
    out = {}
    for p in PERIODS:
        try:
            period_base(p, as_of, first_day)
            out[p] = True
        except PeriodError:
            out[p] = False
    return out


def slice_for_period(values: pd.Series, inflows: pd.Series, outflows: pd.Series,
                     base: date) -> tuple[pd.Series, pd.Series, pd.Series]:
    """
    Séries d'un compte réduites à ]base, fin]. La valeur à la clôture de `base`
    devient un apport en début de premier jour : TWR et TRI de la sous-période
    se calculent alors avec les fonctions de `performance`, sans autre changement.
    """
    b = pd.Timestamp(base)
    v, i, o = values[values.index > b], inflows[inflows.index > b].copy(), outflows[outflows.index > b]
    start_value = values[values.index <= b]
    if len(start_value) and len(i):
        v0 = float(start_value.iloc[-1])
        i.iloc[0] = (i.iloc[0] if not np.isnan(i.iloc[0]) else 0.0) + (v0 if not np.isnan(v0) else np.nan)
    return v, i, o


# ---------------------------------------------------------------------------
# Rendements quotidiens (jours ouvrés) et hebdomadaires
# ---------------------------------------------------------------------------

def _compound(x: pd.Series) -> float:
    a = x.to_numpy(dtype=float)
    return float(np.prod(1.0 + a) - 1.0)          # NaN si un élément est NaN : jamais ignoré


def to_business_days(returns: pd.Series) -> pd.Series:
    """Rendements calendaires -> jours ouvrés : samedi et dimanche composés dans le lundi suivant."""
    if returns.empty:
        return returns
    idx = pd.DatetimeIndex(returns.index)
    shift = np.where(idx.day_of_week == 5, 2, np.where(idx.day_of_week == 6, 1, 0))
    key = idx + pd.to_timedelta(shift, unit="D")
    return returns.groupby(key).agg(_compound).rename(returns.name)


def to_weekly(returns: pd.Series) -> tuple[pd.Series, int]:
    """
    Rendements quotidiens -> hebdomadaires (semaines terminées le vendredi).
    Renvoie aussi le nombre de semaines partielles (début ou fin de période).
    """
    if returns.empty:
        return returns, 0
    idx = pd.DatetimeIndex(returns.index)
    week = idx.to_period("W-FRI")
    out = returns.groupby(week).agg(_compound)
    counts = returns.groupby(week).size()
    out.index = out.index.to_timestamp(how="end").normalize()
    partial = int((counts.iloc[[0, -1]] < 5).sum()) if len(counts) > 1 else int(counts.iloc[0] < 5)
    return out.rename(returns.name), partial


def index_returns(level: pd.Series, grid: pd.DatetimeIndex, base: date,
                  max_stale_days: int = 7) -> pd.Series:
    """
    Rendements d'un indice (niveau) sur une grille de jours ouvrés, depuis la
    clôture de `base`. Un jour sans cotation (férié) donne un rendement nul ;
    au-delà de `max_stale_days` jours sans cotation, NaN.
    """
    lv = level.dropna().sort_index()
    if lv.empty or len(grid) == 0:
        return pd.Series(np.nan, index=grid)
    b = pd.Timestamp(base)
    days = pd.date_range(min(lv.index[0], b), max(lv.index[-1], grid[-1]), freq="D")
    daily = lv.reindex(days).ffill(limit=max_stale_days)
    pts = daily.reindex(pd.DatetimeIndex([b]).append(grid))
    return pts.pct_change(fill_method=None).iloc[1:]


# ---------------------------------------------------------------------------
# Tableau comparatif
# ---------------------------------------------------------------------------

def _num(x) -> float | None:
    if x is None:
        return None
    x = float(x)
    return x if math.isfinite(x) else None


@dataclass
class RiskRow:
    name: str
    kind: str                                    # « portefeuille », « compte », « reference »
    complete: bool = True
    first_missing: date | None = None
    n_days: int = 0
    n_weeks: int = 0
    total_return: float | None = None
    annual_return: float | None = None
    volatility: float | None = None
    sharpe: float | None = None
    sharpe_ci: tuple[float, float] | None = None
    sortino: float | None = None
    max_drawdown: float | None = None
    calmar: float | None = None
    var95: float | None = None
    cvar95: float | None = None
    beta: float | None = None
    beta_dimson: float | None = None
    correlation: float | None = None
    alpha: float | None = None
    tracking_error: float | None = None
    information_ratio: float | None = None
    information_ratio_ci: tuple[float, float] | None = None
    is_reference: bool = False                   # référence de comparaison : mesures relatives sans objet
    notes: dict[str, str] = field(default_factory=dict)


ANNUALIZED = ("annual_return", "volatility", "sharpe", "sortino", "calmar", "alpha", "tracking_error",
              "information_ratio")
RELATIVE = ("beta", "beta_dimson", "correlation", "alpha", "tracking_error", "information_ratio")


def risk_row(name: str, kind: str, r: pd.Series, rf: pd.Series, ref: pd.Series | None,
             span_days: int, is_reference: bool = False) -> RiskRow:
    """
    `r`, `rf`, `ref` : rendements quotidiens sur la même grille de jours ouvrés.
    `span_days` : durée calendaire de la période (règle « pas d'annualisation sous un an »).
    """
    row = RiskRow(name, kind, n_days=len(r), is_reference=is_reference)
    bad = r.isna() | rf.reindex(r.index).isna()
    if r.empty or bad.any():
        row.complete = False
        row.first_missing = pd.Timestamp(r.index[bad.to_numpy()][0]).date() if bad.any() else None
        row.notes["serie"] = "série incomplète" if bad.any() else "aucune donnée"
        return row

    ex = r - rf
    row.total_return = _num(m.total_return(r))
    row.max_drawdown = _num(m.max_drawdown(r))
    row.var95 = _num(m.historical_var(r))
    row.cvar95 = _num(m.historical_cvar(r))
    row.annual_return = annualize(row.total_return, span_days) if row.total_return is not None else None
    row.volatility = _num(m.annual_volatility(r))
    row.sharpe = _num(m.sharpe_ratio(ex, 0.0))
    if row.sharpe is not None:
        row.sharpe_ci = m.sharpe_ci(row.sharpe, len(ex))
    row.sortino = _num(m.sortino_ratio(ex, 0.0))
    row.calmar = _num(m.calmar_ratio(r))

    if ref is not None and not is_reference:
        rw, _ = to_weekly(r)
        bw, _ = to_weekly(ref.reindex(r.index))
        fw, _ = to_weekly(rf.reindex(r.index))
        row.n_weeks = int(pd.concat([rw, bw], axis=1).dropna().shape[0])
        if bw.isna().any():
            row.notes["relatif"] = "référence incomplète sur la période"
        elif row.n_weeks < MIN_WEEKS:
            row.notes["relatif"] = f"historique insuffisant ({row.n_weeks} semaines, minimum {MIN_WEEKS})"
        else:
            exw, bexw = rw - fw, bw - fw
            row.beta = _num(m.beta(exw, bexw))
            row.beta_dimson = _num(m.dimson_beta(exw, bexw))
            row.correlation = _num(pd.concat([rw, bw], axis=1).corr().iloc[0, 1])
            row.alpha = _num(m.jensen_alpha(exw, bexw, 0.0, periods=WEEKLY))
            row.tracking_error = _num(m.tracking_error(rw, bw, periods=WEEKLY))
            row.information_ratio = _num(m.information_ratio(rw, bw, periods=WEEKLY))
            if row.information_ratio is not None:
                row.information_ratio_ci = m.sharpe_ci(row.information_ratio, row.n_weeks, periods=WEEKLY)

    if span_days < DAYS_PER_YEAR:
        for f in ANNUALIZED:
            setattr(row, f, None)
        row.sharpe_ci = row.information_ratio_ci = None
        row.notes["annualise"] = "moins d'un an : aucun indicateur annualisé"
    return row


def short_history_warning(span_days: int, n_days: int) -> str | None:
    """Avertissement visible sous 3 ans, avec la demi-largeur de l'IC d'un Sharpe nul."""
    if span_days >= SHORT_HISTORY_YEARS * DAYS_PER_YEAR or n_days < 2:
        return None
    lo, hi = m.sharpe_ci(0.0, n_days)
    years = span_days / DAYS_PER_YEAR
    return (f"Historique court ({_fr(years, 1)} ans) : l'intervalle de confiance à 95 % d'un Sharpe "
            f"est d'environ ± {_fr(hi, 2)}. Une différence de cet ordre entre deux séries n'est pas "
            f"significative.")
