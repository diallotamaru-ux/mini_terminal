"""
Indices de référence dividendes réinvestis, convertis en euros.

    I_t = I_{t-1} x (P_t + D_t x (1 - tau)) / P_{t-1}          (en devise de cotation)
    I^EUR_t = I_t x FX_t                                         (FX : euros pour une unité)

P : clôture ajustée des seules divisions ; D : dividende brut par action à
l'ex-date ; tau : retenue à la source supposée sur les dividendes. Le
dividende net est réinvesti à la clôture de l'ex-date, comme dans un indice
« net total return ».
"""

from __future__ import annotations

import numpy as np
import pandas as pd


def total_return_index(closes: pd.Series, dividends: pd.Series | None = None,
                       withholding: float = 0.0, base: float = 1.0) -> pd.Series:
    """Indice dividendes réinvestis, base `base` à la première clôture."""
    if not 0.0 <= withholding < 1.0:
        raise ValueError("La retenue à la source doit être comprise entre 0 et 1.")
    p = closes.dropna().sort_index().astype(float)
    if p.empty:
        return p
    d = pd.Series(0.0, index=p.index)
    if dividends is not None and len(dividends):
        div = dividends.groupby(level=0).sum()
        # Un dividende dont l'ex-date tombe hors séance est rattaché à la séance suivante.
        pos = p.index.searchsorted(div.index)
        for i, amount in zip(pos, div.to_numpy()):
            if 0 < i < len(p):
                d.iloc[i] += amount
    growth = (p + d * (1.0 - withholding)) / p.shift(1)
    growth.iloc[0] = 1.0
    return base * growth.cumprod()


def to_eur(index: pd.Series, fx: pd.Series | None, max_stale_days: int = 7) -> pd.Series:
    """
    Convertit une série en euros au taux du jour (reporté au plus `max_stale_days`).
    `fx=None` : série déjà en euros. Un taux manquant donne NaN, jamais un taux inventé.
    """
    if fx is None:
        return index.copy()
    f = fx.dropna().sort_index()
    if f.empty or index.empty:
        return index * np.nan
    days = pd.date_range(min(f.index[0], index.index[0]), max(f.index[-1], index.index[-1]), freq="D")
    rate = f.reindex(days).ffill(limit=max_stale_days).reindex(index.index)
    return (index * rate).where(rate.notna(), np.nan)
