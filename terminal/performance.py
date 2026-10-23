"""
Performance d'un portefeuille réel, avec apports et retraits.

Deux mesures, qui répondent à deux questions différentes :

- TWR (rendement pondéré par le temps) : la performance des choix
  d'investissement, neutre vis-à-vis du calendrier des apports.
      TWR = prod_t (1 + r_t) - 1
  Calculé sur une grille quotidienne, il coïncide exactement avec le TWR par
  sous-périodes entre deux flux : entre deux flux, le produit se télescope.

- MWR (rendement pondéré par les capitaux, TRI) : la performance vécue par
  l'investisseur, qui dépend du moment où il a apporté son argent.
      sum_t CF_t / (1 + r)^((t - t0) / 365) = 0

Convention de date des flux (jour t, valeur de clôture V_t) :
- les entrées I_t (apports) arrivent en début de journée : elles travaillent
  le jour même, au prix d'exécution réel ;
- les sorties O_t (retraits) partent en fin de journée.
      r_t = (V_t + O_t) / (V_{t-1} + I_t) - 1
Cette convention évite les deux pièges classiques : un dénominateur nul le
premier jour (tout en fin de journée), et un dénominateur négatif quand on
vend tout après une hausse (tout en début de journée).

Toutes les séries sont en flottants : ce sont des calculs statistiques.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import date, timedelta

import numpy as np
import pandas as pd

from .errors import TerminalError
from .metrics import total_return

DAYS_PER_YEAR = 365
_EPS = 1e-9


class PerformanceError(TerminalError):
    pass


def daily_returns(values: pd.Series, inflows: pd.Series | None = None,
                  outflows: pd.Series | None = None) -> tuple[pd.Series, list[str]]:
    """
    Rendements quotidiens r_t = (V_t + O_t) / (V_{t-1} + I_t) - 1.

    `inflows` et `outflows` sont positifs, indexés comme `values`. Les jours
    sans capital investi (V_{t-1} + I_t = 0) sont exclus. Un NaN dans les
    valeurs (cours manquant) donne un rendement NaN : jamais un zéro.
    """
    idx = values.index
    i = (inflows if inflows is not None else pd.Series(0.0, index=idx)).reindex(idx, fill_value=0.0)
    o = (outflows if outflows is not None else pd.Series(0.0, index=idx)).reindex(idx, fill_value=0.0)
    prev = values.shift(1, fill_value=0.0)
    base = prev + i
    num = values + o

    warnings: list[str] = []
    active = base.abs() > _EPS
    orphan = (~active) & (num.abs() > _EPS)
    for d in idx[orphan.fillna(False).to_numpy(dtype=bool)]:
        warnings.append(f"{pd.Timestamp(d).date().isoformat()} : flux ou valeur sans capital investi "
                        f"la veille, jour exclu du TWR.")
    active = active.fillna(True)        # base NaN -> rendement NaN, conservé
    r = (num[active] / base[active]) - 1.0
    return r.rename("r"), warnings


@dataclass
class TwrResult:
    total: float | None              # rendement cumulé sur la période
    annualized: float | None         # None si moins d'un an
    start: date | None
    end: date | None
    days: int
    returns: pd.Series = field(repr=False, default_factory=lambda: pd.Series(dtype=float))
    warnings: list[str] = field(default_factory=list)


def twr(values: pd.Series, inflows: pd.Series | None = None,
        outflows: pd.Series | None = None) -> TwrResult:
    """TWR cumulé, et annualisé sur base 365 jours si la période dépasse un an."""
    r, warnings = daily_returns(values, inflows, outflows)
    if r.empty:
        return TwrResult(None, None, None, None, 0, r, warnings + ["Aucun capital investi."])
    start, end = pd.Timestamp(r.index[0]).date(), pd.Timestamp(r.index[-1]).date()
    days = (end - start).days + 1
    if r.isna().any():
        missing = pd.Timestamp(r.index[r.isna()][0]).date().isoformat()
        return TwrResult(None, None, start, end, days, r,
                         warnings + [f"Valorisation manquante (premier jour : {missing}) : "
                                     f"TWR non calculable."])
    total = total_return(r)
    ann = annualize(total, days)
    return TwrResult(total, ann, start, end, days, r, warnings)


def annualize(total: float, days: int) -> float | None:
    """(1 + R)^(365 / jours) - 1 ; None sous un an (convention GIPS)."""
    if days < DAYS_PER_YEAR:
        return None
    if total <= -1.0:
        return -1.0
    return float((1.0 + total) ** (DAYS_PER_YEAR / days) - 1.0)


# ---------------------------------------------------------------------------
# TRI
# ---------------------------------------------------------------------------

def _npv(rate: float, t: np.ndarray, cf: np.ndarray) -> float:
    return float((cf / (1.0 + rate) ** t).sum())


def xirr(dates: list[date], amounts: list[float]) -> float:
    """
    Taux annuel r tel que sum_k CF_k / (1 + r)^((t_k - t_0) / 365) = 0.

    Convention de signe : point de vue de l'investisseur (apport < 0,
    retrait ou valeur finale > 0). Résolution par Brent sur un intervalle
    élargi jusqu'à encadrer une racine.
    """
    from scipy.optimize import brentq

    if len(dates) != len(amounts) or len(dates) < 2:
        raise PerformanceError("Le TRI exige au moins deux flux datés.")
    cf = np.asarray(amounts, dtype=float)
    if not ((cf > 0).any() and (cf < 0).any()):
        raise PerformanceError("Le TRI exige au moins un flux positif et un flux négatif.")
    t0 = min(dates)
    t = np.array([(d - t0).days for d in dates], dtype=float) / DAYS_PER_YEAR
    if t.max() == 0:
        raise PerformanceError("Le TRI exige des flux répartis sur au moins deux dates.")

    lo, hi = -1.0 + 1e-9, 1.0
    f_lo = _npv(lo, t, cf)
    while np.sign(_npv(hi, t, cf)) == np.sign(f_lo):
        hi *= 4.0
        if hi > 1e9:
            raise PerformanceError("Aucun TRI trouvé : les flux n'ont pas de racine réelle.")
    return float(brentq(_npv, lo, hi, args=(t, cf), xtol=1e-14, rtol=1e-12, maxiter=500))


@dataclass
class MwrResult:
    rate: float | None            # annualisé si days >= 365, sinon cumulé sur la période
    annualized: bool
    start: date | None
    end: date | None
    days: int
    warnings: list[str] = field(default_factory=list)


def mwr(values: pd.Series, inflows: pd.Series | None = None,
        outflows: pd.Series | None = None) -> MwrResult:
    """
    TRI d'un historique. Flux investisseur : -apports, +retraits, puis la
    valeur finale comme dernier flux positif. Sous un an, renvoie le taux
    cumulé sur la période, (1 + r)^(jours / 365) - 1, et non un taux annuel.

    Datation cohérente avec le TWR : un apport du jour d est daté d (début de
    journée), un retrait du jour d et la valeur de clôture finale sont datés
    d + 1 (fin de journée).
    """
    idx = values.index
    i = (inflows if inflows is not None else pd.Series(0.0, index=idx)).reindex(idx, fill_value=0.0)
    o = (outflows if outflows is not None else pd.Series(0.0, index=idx)).reindex(idx, fill_value=0.0)
    active = (i.abs() > _EPS) | (o.abs() > _EPS) | (values.abs() > _EPS)
    if not active.any():
        return MwrResult(None, False, None, None, 0, ["Aucun flux."])
    first = idx[active.to_numpy()][0]
    start, end = pd.Timestamp(first).date(), pd.Timestamp(idx[-1]).date()
    days = (end - start).days + 1
    end_value = values.iloc[-1]
    if np.isnan(end_value) or i.loc[first:].isna().any() or o.loc[first:].isna().any():
        return MwrResult(None, False, start, end, days,
                         ["Valorisation ou flux manquant : TRI non calculable."])

    dates: list[date] = []
    amounts: list[float] = []
    one_day = timedelta(days=1)
    for d in idx[idx >= first]:
        day = pd.Timestamp(d).date()
        if abs(i[d]) > _EPS:
            dates.append(day)
            amounts.append(-float(i[d]))
        if abs(o[d]) > _EPS:
            dates.append(day + one_day)
            amounts.append(float(o[d]))
    dates.append(end + one_day)
    amounts.append(float(end_value))
    try:
        r = xirr(dates, amounts)
    except PerformanceError as e:
        return MwrResult(None, False, start, end, days, [str(e)])
    if days >= DAYS_PER_YEAR:
        return MwrResult(r, True, start, end, days)
    return MwrResult(float((1.0 + r) ** (days / DAYS_PER_YEAR) - 1.0), False, start, end, days)
