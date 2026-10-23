"""
Taux au jour le jour (taux sans risque) : interface et version simulée.

`overnight(series, start, end)` renvoie le taux annuel en POURCENT, convention
ACT/360, indexé par date de fixing. Séries : « estr » (depuis le 01/10/2019) et
« eonia » (jusqu'au 31/12/2021 ; égal au €STR + 8,5 pb depuis le 02/10/2019).
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


# Trajectoire simulée du €STR (dates, niveaux en %), interpolée linéairement.
_SIM_PATH = [("2015-01-01", -0.25), ("2019-09-30", -0.55), ("2022-07-26", -0.55), ("2023-09-20", 3.90),
             ("2024-06-12", 3.90), ("2025-06-11", 1.90), ("2030-12-31", 1.90)]


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
