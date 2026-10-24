"""
Taux au jour le jour (taux sans risque) : interface et version simulée.

`overnight(series, start, end)` renvoie le taux annuel en POURCENT, convention
ACT/360, indexé par date de fixing. Séries : « estr » (depuis le 01/10/2019) et
« eonia » (jusqu'au 31/12/2021 ; égal au €STR + 8,5 pb depuis le 02/10/2019).

`long_yield(devise, start, end)` renvoie le rendement d'État à 10 ans en POURCENT,
par jour ouvré : EUR = courbe AAA de la zone euro (BCE), USD = Treasury (FRED).
Il sert au coût du capital de la valorisation (phase 4).
"""

from __future__ import annotations

from abc import ABC, abstractmethod
from datetime import date

import numpy as np
import pandas as pd

from ..errors import ProviderUnavailable
from .base import PriceSeries, clean_series

SERIES = ("estr", "eonia")


class RateProvider(ABC):
    name: str = "abstrait"
    simulated: bool = False

    @abstractmethod
    def overnight(self, series: str, start: date, end: date) -> PriceSeries:
        """Taux annuel en %, ACT/360. Lève ProviderUnavailable."""

    @abstractmethod
    def long_yield(self, currency: str, start: date, end: date) -> PriceSeries:
        """Rendement d'État à 10 ans en %, par jour ouvré. Lève ProviderUnavailable (devise non couverte comprise)."""


# Trajectoire simulée du €STR (dates, niveaux en %), interpolée linéairement.
_SIM_PATH = [("2015-01-01", -0.25), ("2019-09-30", -0.55), ("2022-07-26", -0.55), ("2023-09-20", 3.90),
             ("2024-06-12", 3.90), ("2025-06-11", 1.90), ("2030-12-31", 1.90)]
# Taux longs simulés (rendement à 10 ans, en %).
_SIM_LONG = {"EUR": [("2015-01-01", 0.50), ("2020-03-01", -0.40), ("2022-01-01", 0.00), ("2023-10-01", 2.80),
                     ("2026-10-01", 2.70), ("2030-12-31", 2.70)],
             "USD": [("2015-01-01", 2.10), ("2020-08-01", 0.60), ("2023-10-01", 4.80), ("2026-10-01", 4.20),
                     ("2030-12-31", 4.20)]}


class SimulatedRates(RateProvider):
    name = "simule"
    simulated = True

    def overnight(self, series: str, start: date, end: date) -> PriceSeries:
        if series not in SERIES:
            raise ProviderUnavailable("simule", f"série inconnue {series}")
        days = pd.bdate_range(start, end)
        knots = pd.Series([v for _, v in _SIM_PATH], index=pd.DatetimeIndex([d for d, _ in _SIM_PATH]))
        x = np.interp(days.asi8, knots.index.asi8, knots.to_numpy())
        s = pd.Series(np.round(x, 3), index=days)
        if series == "estr":
            s = s[s.index >= pd.Timestamp("2019-10-01")]
        else:
            s = (s + 0.085)[s.index <= pd.Timestamp("2021-12-31")]
        return PriceSeries(series.upper(), clean_series(s), "Simulation (données fictives)", simulated=True)

    def long_yield(self, currency: str, start: date, end: date) -> PriceSeries:
        path = _SIM_LONG.get(currency)
        if path is None:
            raise ProviderUnavailable("simule", f"pas de taux long simulé en {currency}")
        days = pd.bdate_range(start, end)
        knots = pd.Series([v for _, v in path], index=pd.DatetimeIndex([d for d, _ in path]))
        s = pd.Series(np.round(np.interp(days.asi8, knots.index.asi8, knots.to_numpy()), 3), index=days)
        return PriceSeries(f"{currency}10Y", clean_series(s), "Simulation (données fictives)", simulated=True)


class CombinedRates(RateProvider):
    """Taux au jour le jour d'un fournisseur, taux longs d'un fournisseur par devise."""

    simulated = False

    def __init__(self, overnight: RateProvider, long: dict[str, RateProvider]):
        self._overnight = overnight
        self._long = long
        self.name = "+".join(dict.fromkeys([overnight.name, *(p.name for p in long.values())]))

    def overnight(self, series: str, start: date, end: date) -> PriceSeries:
        return self._overnight.overnight(series, start, end)

    def long_yield(self, currency: str, start: date, end: date) -> PriceSeries:
        p = self._long.get(currency)
        if p is None:
            raise ProviderUnavailable(self.name, f"pas de taux long pour la devise {currency}")
        return p.long_yield(currency, start, end)
