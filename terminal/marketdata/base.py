"""
Interface des fournisseurs de données de marché.

Le reste de l'application ne connaît que cette interface. Changer de
fournisseur revient à écrire une nouvelle implémentation dans un seul fichier.

Conventions
-----------
- `daily_closes` renvoie des clôtures ajustées des divisions d'actions mais
  PAS des dividendes : les dividendes sont saisis comme transactions, des cours
  ajustés les compteraient deux fois.
- `fx_rates(devise)` renvoie le nombre d'euros pour une unité de `devise`.
- Index : dates calendaires sans fuseau horaire, triées, sans doublon.
"""

from __future__ import annotations

from abc import ABC, abstractmethod
from dataclasses import dataclass, field
from datetime import date, datetime, timezone

import pandas as pd


@dataclass(frozen=True)
class InstrumentInfo:
    ticker: str
    currency: str
    name: str | None = None
    exchange: str | None = None


@dataclass(frozen=True)
class PriceSeries:
    ticker: str
    closes: pd.Series                 # flottants, index DatetimeIndex
    source: str
    simulated: bool = False
    fetched_at: datetime = field(default_factory=lambda: datetime.now(timezone.utc))

    @property
    def last_date(self) -> date | None:
        s = self.closes.dropna()
        return None if s.empty else pd.Timestamp(s.index[-1]).date()


def clean_series(s: pd.Series) -> pd.Series:
    """Normalise un index de cours : dates sans fuseau, triées, uniques, NaN retirés."""
    s = s.astype(float)
    idx = pd.DatetimeIndex(s.index)
    if idx.tz is not None:
        idx = idx.tz_localize(None)
    s.index = idx.normalize()
    s = s[~s.index.duplicated(keep="last")].sort_index()
    return s.dropna()


class MarketDataProvider(ABC):
    name: str = "abstrait"
    simulated: bool = False

    @abstractmethod
    def daily_closes(self, ticker: str, start: date, end: date) -> PriceSeries:
        """Clôtures quotidiennes de `ticker` sur [start, end]. Lève UnknownTicker ou ProviderUnavailable."""

    @abstractmethod
    def fx_rates(self, currency: str, start: date, end: date) -> PriceSeries:
        """Euros pour une unité de `currency`. Lève MissingCurrency ou ProviderUnavailable."""

    @abstractmethod
    def instrument_info(self, ticker: str) -> InstrumentInfo:
        """Devise et nom de la cotation. Lève UnknownTicker ou ProviderUnavailable."""
