"""
Fournisseur simulé : tests et mode démo, sans réseau.

Les cours viennent de `data.demo_prices` (modèle à un facteur, queues
épaisses). Ils sont générés une fois sur une fenêtre fixe, puis découpés :
le cours d'un ticker à une date donnée ne dépend donc ni de la date de la
requête ni des autres tickers demandés. Toutes les séries portent
`simulated=True` : l'interface doit afficher le bandeau « données simulées ».
"""

from __future__ import annotations

import re
import zlib
from datetime import date

import numpy as np
import pandas as pd

from .. import data
from ..errors import MissingCurrency, UnknownTicker
from ..splits import Split
from .base import InstrumentInfo, MarketDataProvider, PriceSeries, clean_series

SIM_START = "2015-01-01"
SIM_END = "2030-12-31"
SOURCE = "Simulation (données fictives)"

_TICKER_RE = re.compile(r"^[A-Z0-9][A-Z0-9.\-^=]{0,19}$")
_EUR_SUFFIXES = (".PA", ".AS", ".DE", ".MI", ".MC", ".BR", "-EUR")

# Divisions simulées. Les cours simulés sont, comme ceux de Yahoo, déjà ajustés :
# une transaction saisie avant la date doit l'être en prix d'origine (x 10 ici).
SIM_SPLITS = {"NVDA": [(date(2024, 6, 10), 10, 1)]}

# Dividendes simulés : taux trimestriel versé à la mi-mars, juin, septembre, décembre.
SIM_DIVIDEND_YIELD_Q = {"QQQ": 0.0015}

# Niveau moyen des taux simulés (euros pour une unité de devise).
_FX_LEVEL = {"USD": 0.90, "GBP": 1.17, "CHF": 1.03, "JPY": 0.0063, "CAD": 0.67}


class SimulatedProvider(MarketDataProvider):
    name = "simule"
    simulated = True

    def __init__(self) -> None:
        self._universe = list(data.DEMO_PROFILE)
        self._prices = data.demo_prices(self._universe, SIM_START, SIM_END)
        self._extra: dict[str, pd.Series] = {}

    def _series(self, ticker: str) -> pd.Series:
        if not _TICKER_RE.match(ticker):
            raise UnknownTicker(ticker)
        if ticker in self._prices.columns:
            return self._prices[ticker]
        if ticker not in self._extra:
            # Ticker hors univers : profil générique, graine propre au ticker.
            seed = zlib.crc32(ticker.encode())
            self._extra[ticker] = data.demo_prices([ticker], SIM_START, SIM_END, seed=seed)[ticker]
        return self._extra[ticker]

    def daily_closes(self, ticker: str, start: date, end: date) -> PriceSeries:
        s = self._series(ticker)
        s = s.loc[pd.Timestamp(start):pd.Timestamp(end)]
        return PriceSeries(ticker, clean_series(s), SOURCE, simulated=True)

    def fx_rates(self, currency: str, start: date, end: date) -> PriceSeries:
        if currency == "EUR":
            idx = pd.date_range(start, end, freq="D")
            return PriceSeries("EUR", pd.Series(1.0, index=idx), SOURCE, simulated=True)
        level = _FX_LEVEL.get(currency)
        if level is None:
            raise MissingCurrency(currency, "absente du fournisseur simulé")
        rng = np.random.default_rng(zlib.crc32(currency.encode()))
        idx = pd.date_range(SIM_START, SIM_END, freq="D")
        # Marche aléatoire en log, 7 % de volatilité annuelle, rappel vers le niveau moyen.
        x = np.zeros(len(idx))
        shocks = rng.normal(0.0, 0.07 / np.sqrt(365), len(idx))
        for k in range(1, len(idx)):
            x[k] = 0.998 * x[k - 1] + shocks[k]
        s = pd.Series(level * np.exp(x), index=idx).loc[pd.Timestamp(start):pd.Timestamp(end)]
        return PriceSeries(f"{currency}EUR", clean_series(s), SOURCE, simulated=True)

    def instrument_info(self, ticker: str) -> InstrumentInfo:
        self._series(ticker)
        currency = "EUR" if ticker.endswith(_EUR_SUFFIXES) else "USD"
        return InstrumentInfo(ticker, currency, name=f"{ticker} (simulé)")

    def splits(self, ticker: str) -> list[Split]:
        self._series(ticker)
        return [Split(ticker, d, n, m) for d, n, m in SIM_SPLITS.get(ticker, [])]

    def dividends(self, ticker: str, start: date, end: date) -> PriceSeries:
        s = self._series(ticker)
        q = SIM_DIVIDEND_YIELD_Q.get(ticker)
        if not q:
            return PriceSeries(ticker, pd.Series(dtype=float), SOURCE, simulated=True)
        ex = [d for d in s.index if d.month in (3, 6, 9, 12) and 15 <= d.day <= 21 and d.day_of_week == 0]
        out = pd.Series({d: float(s.loc[d]) * q for d in ex}, dtype=float)
        return PriceSeries(ticker, clean_series(out.loc[pd.Timestamp(start):pd.Timestamp(end)]), SOURCE,
                           simulated=True)
