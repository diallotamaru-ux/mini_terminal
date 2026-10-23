"""
Taux sans risque quotidien.

Série par défaut : EONIA strictement avant le 01/10/2019, €STR à partir de
cette date. Depuis le 02/10/2019 la BCE définit l'EONIA comme €STR + 8,5 points
de base : le raccord crée une marche de 8,5 pb sur le taux annuel, soit environ
0,0002 % par jour, sans effet mesurable sur les ratios.

Conversion d'un taux du marché monétaire (ACT/360, en %) en rendement sur la
période qui sépare deux dates de la grille :

    rf(t) = R(t0) / 100 x (t - t0) / 360

avec t0 la date précédente de la grille et R(t0) le dernier taux publié à t0.
Un lundi porte donc trois jours d'intérêt. Un taux fixe saisi suit la même
convention.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import date, timedelta

import pandas as pd

ESTR_START = date(2019, 10, 1)
MAX_STALE_DAYS = 7


@dataclass(frozen=True)
class Segment:
    name: str                # « €STR », « EONIA », « taux fixe 2,00 % », « zéro »
    start: date
    end: date


def splice_eonia_estr(eonia: pd.Series, estr: pd.Series) -> pd.Series:
    """Taux en % : EONIA avant le 01/10/2019, €STR ensuite."""
    cut = pd.Timestamp(ESTR_START)
    parts = [p for p in (eonia[eonia.index < cut] if len(eonia) else eonia,
                         estr[estr.index >= cut] if len(estr) else estr) if len(p)]
    return pd.concat(parts).sort_index() if parts else pd.Series(dtype=float)


def segments(start: date, end: date, mode: str = "estr", fixed_rate: float | None = None) -> list[Segment]:
    """Séries utilisées sur [start, end], pour l'affichage."""
    if mode == "zero":
        return [Segment("zéro", start, end)]
    if mode == "fixe":
        return [Segment(f"taux fixe {fixed_rate:.2f} %".replace(".", ","), start, end)]
    out = []
    if start < ESTR_START:
        out.append(Segment("EONIA", start, min(end, ESTR_START - timedelta(days=1))))
    if end >= ESTR_START:
        out.append(Segment("€STR", max(start, ESTR_START), end))
    return out


def daily_rates(rate_pct: pd.Series, grid: pd.DatetimeIndex) -> pd.Series:
    """
    Rendement sans risque de chaque date de `grid`, depuis la date précédente.
    La première date porte l'intérêt depuis la veille ouvrée. NaN si aucun taux
    n'est connu à t0 (au plus MAX_STALE_DAYS jours de report).
    """
    if len(grid) == 0:
        return pd.Series(dtype=float)
    prev = grid.to_series().shift(1)
    first = grid[0]
    prev.iloc[0] = first - pd.offsets.BDay(1)
    days = (grid.to_series() - prev).dt.days
    r = rate_pct.dropna().sort_index()
    if r.empty:
        return pd.Series(float("nan"), index=grid)
    cal = pd.date_range(min(r.index[0], prev.iloc[0]), max(r.index[-1], grid[-1]), freq="D")
    known = r.reindex(cal).ffill(limit=MAX_STALE_DAYS)
    rate_at_t0 = known.reindex(pd.DatetimeIndex(prev.to_numpy())).to_numpy()
    return pd.Series(rate_at_t0 / 100.0 * days.to_numpy() / 360.0, index=grid)


def fixed_rates(rate_pct: float, grid: pd.DatetimeIndex) -> pd.Series:
    """Taux fixe annuel en %, même convention ACT/360."""
    flat = pd.Series(rate_pct, index=pd.date_range(grid[0] - pd.Timedelta(days=10), grid[-1], freq="D")) \
        if len(grid) else pd.Series(dtype=float)
    return daily_rates(flat, grid)
