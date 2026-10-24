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
from .base import Fundamentals, InstrumentInfo, MarketDataProvider, PriceSeries, clean_series, fundamentals_frame

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

# Comptes annuels fictifs (5 exercices), d'ordres de grandeur plausibles pour les cours simulés
# (VE / flux disponible d'environ 20 à 40 au 23/10/2026). None = donnée absente, comme chez
# Yahoo : charge d'intérêts et dettes locatives d'AAPL sur les deux derniers exercices,
# minoritaires d'AAPL, rémunération en actions de MC.PA. Les montants sont en unités.
_B = 1e9
SIM_FUNDAMENTALS = {
    "AAPL": dict(
        currency="USD", sector="Technology", industry="Consumer Electronics", fy_end="09-30",
        revenue=[366, 394, 383, 391, 416], ocf=[104, 122, 111, 118, 111], capex=[-11, -11, -11, -9, -13],
        sbc=[8, 9, 11, 12, 13], interest_expense=[2.6, 2.9, 3.9, None, None],
        pretax_income=[109, 119, 114, 123, 133], tax_provision=[14, 19, 17, 30, 21],
        financial_debt=[125, 132, 111, 107, 99], lease_liabilities=[11, 11.5, 12.8, None, None],
        cash_sti=[63, 48, 62, 65, 55], lt_investments=[128, 121, 101, 91, 78], minority_interest=None, diluted_shares=[5.07, 4.94, 4.81, 4.71, 4.64]),
    "MC.PA": dict(
        currency="EUR", sector="Consumer Cyclical", industry="Luxury Goods", fy_end="12-31",
        revenue=[64.2, 79.2, 86.2, 84.7, 80.8], ocf=[19.6, 17.8, 18.4, 18.9, 18.9],
        capex=[-2.6, -5.1, -7.8, -5.6, -4.7], sbc=None, interest_expense=[0.2, 0.4, 1.0, 1.2, 1.15],
        pretax_income=[17.4, 20.1, 21.6, 18.1, 16.7], tax_provision=[4.5, 5.4, 5.7, 5.2, 5.5],
        financial_debt=[20.0, 19.7, 21.9, 22.9, 20.3], lease_liabilities=[14.0, 15.4, 17.0, 18.3, 16.4],
        cash_sti=[8.0, 7.3, 11.3, 13.6, 13.5], lt_investments=[1.0, 1.1, 1.4, 1.6, 1.9],
        minority_interest=[1.4, 1.5, 1.7, 1.8, 1.5],
        diluted_shares=[0.601, 0.600, 0.598, 0.596, 0.594]),
    "ASML.AS": dict(
        currency="EUR", sector="Technology", industry="Semiconductor Equipment & Materials", fy_end="12-31",
        revenue=[18.6, 21.2, 27.6, 28.3, 32.7], ocf=[10.8, 8.5, 5.4, 11.2, 11.0],
        capex=[-0.9, -1.3, -2.2, -2.1, -1.8], sbc=[0.15, 0.17, 0.21, 0.40, 0.60],
        interest_expense=[0.06, 0.08, 0.10, 0.10, 0.10], pretax_income=[6.9, 6.8, 9.1, 9.0, 11.6],
        tax_provision=[1.0, 1.2, 1.3, 1.4, 2.0], financial_debt=[4.7, 4.5, 4.3, 4.4, 4.3],
        lease_liabilities=[0.2, 0.2, 0.3, 0.3, 0.3], cash_sti=[7.6, 7.4, 7.0, 12.7, 12.7],
        minority_interest=[0.0, 0.0, 0.0, 0.0, 0.0], diluted_shares=[0.945, 0.940, 0.935, 0.932, 0.929]),
    "NVDA": dict(
        currency="USD", sector="Technology", industry="Semiconductors", fy_end="01-31",
        revenue=[26.9, 27.0, 60.9, 130.5, 190.0], ocf=[9.1, 5.6, 28.1, 64.1, 100.0],
        capex=[-1.0, -1.8, -1.1, -3.2, -5.0], sbc=[2.0, 2.7, 3.5, 4.7, 6.0],
        interest_expense=[0.24, 0.26, 0.26, 0.25, 0.25], pretax_income=[9.9, 4.2, 33.8, 84.0, 125.0],
        tax_provision=[0.2, -0.2, 4.1, 11.1, 19.0], financial_debt=[10.8, 10.9, 9.8, 8.5, 8.0],
        lease_liabilities=[1.0, 1.1, 1.3, 1.8, 2.0], cash_sti=[21.2, 13.3, 26.0, 43.2, 60.0], lt_investments=[0.3, 0.3, 1.3, 3.4, 22.0],
        minority_interest=[0.0, 0.0, 0.0, 0.0, 0.0], diluted_shares=[5.62, 5.55, 5.50, 5.47, 5.44]),
}
SIM_QUOTE_TYPE = {"QQQ": "ETF", "PANX.PA": "ETF", "IWDA.AS": "ETF", "CW8.PA": "ETF", "BTC-EUR": "CRYPTOCURRENCY"}

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

    def fundamentals(self, ticker: str) -> Fundamentals:
        self._series(ticker)
        spec = SIM_FUNDAMENTALS.get(ticker)
        if spec is None:
            return Fundamentals(ticker, None, SIM_QUOTE_TYPE.get(ticker), None, None, fundamentals_frame({}), SOURCE,
                                simulated=True)
        last = 2026 if spec["fy_end"] == "01-31" else 2025          # exercice NVDA clos en janvier
        ends = pd.DatetimeIndex([f"{last - 4 + i}-{spec['fy_end']}" for i in range(5)])
        rows = {}
        for f, values in spec.items():
            if isinstance(values, list):
                rows[f] = pd.Series([np.nan if v is None else v * _B for v in values], index=ends, dtype=float)
        rows["fcf_reported"] = rows["ocf"] + rows["capex"]
        return Fundamentals(ticker, spec["currency"], "EQUITY", spec["sector"], spec["industry"],
                            fundamentals_frame(rows), SOURCE, simulated=True)
