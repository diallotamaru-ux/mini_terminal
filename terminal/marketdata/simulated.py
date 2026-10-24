"""
Fournisseur simulé : tests et mode démo, sans réseau.

Les cours viennent de `data.demo_prices` (modèle à deux facteurs, queues
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

# Profils de long terme (rendement espéré mu, volatilité sigma, bêta au marché mondial, bêta au
# facteur technologie ; les deux facteurs sont indépendants, de volatilité 20 %). Le facteur
# technologie sépare le Nasdaq du MSCI World : corrélation hebdomadaire en EUR d'environ 0,86,
# au lieu de 0,96 avec un seul facteur (0,85 à 0,90 en réalité). Deux ETF d'un même indice
# gardent une corrélation supérieure à 0,9.
SIM_PROFILE = {
    "QQQ":     (0.14, 0.21, 0.85, 0.60),
    "PANX.PA": (0.13, 0.22, 0.87, 0.62),
    "IWDA.AS": (0.09, 0.15, 0.72, 0.12),
    "CW8.PA":  (0.09, 0.15, 0.72, 0.12),
    "AAPL":    (0.15, 0.28, 0.90, 0.60),
    "MC.PA":   (0.09, 0.27, 0.85, 0.00),
    "ASML.AS": (0.14, 0.35, 1.00, 0.90),
    "NVDA":    (0.30, 0.50, 1.20, 1.20),
    "BTC-EUR": (0.30, 0.65, 0.75, 0.65),
}

# Une trajectoire simulée reste un tirage. La graine est la première (en partant de 0)
# dont les rendements et volatilités réalisés du 04/01/2021 au 23/10/2026 restent dans des
# ordres de grandeur historiques (test test_demo_universe_is_plausible) :
#   indices : 3 % à 18 % par an, volatilité 12 % à 28 % ;
#   actions : -10 % à 35 % par an, volatilité 18 % à 60 % ;
#   bitcoin : 5 % à 60 % par an, volatilité 45 % à 80 %, au plus +300 % sur les 3 dernières années.
SIM_SEED = 56
PLAUSIBLE = {"index": (0.03, 0.18, 0.12, 0.28), "stock": (-0.10, 0.35, 0.18, 0.60),
             "btc": (0.05, 0.60, 0.45, 0.80)}
KIND = {"QQQ": "index", "PANX.PA": "index", "IWDA.AS": "index", "CW8.PA": "index", "AAPL": "stock",
        "MC.PA": "stock", "ASML.AS": "stock", "NVDA": "stock", "BTC-EUR": "btc"}
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
        self._universe = list(SIM_PROFILE)
        self._prices = data.demo_prices(self._universe, SIM_START, SIM_END, seed=SIM_SEED, profile=SIM_PROFILE)
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
