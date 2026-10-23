from __future__ import annotations

import datetime as dt

import pandas as pd
import pytest
from fastapi.testclient import TestClient

from backend.app.config import Settings
from backend.app.main import create_app
from terminal.errors import MissingCurrency, ProviderUnavailable, UnknownTicker
from terminal.marketdata.base import InstrumentInfo, MarketDataProvider, PriceSeries
from terminal.marketdata.rates import RateProvider
from terminal.splits import Split

TODAY = dt.date.today()


def days_ago(n: int) -> dt.date:
    return TODAY - dt.timedelta(days=n)


class FixedProvider(MarketDataProvider):
    """
    Cours fixés à la main : `levels[ticker] = [(depuis_n_jours, cours), ...]`.
    Le cours vaut le dernier palier atteint, chaque jour calendaire.
    """

    name = "fixe"
    simulated = False

    def __init__(self):
        self.currency = {"AAA.PA": "EUR", "BBB.PA": "EUR", "USX": "USD", "DOWN.PA": "EUR"}
        self.levels = {"AAA.PA": [(60, 100.0), (0, 110.0)], "BBB.PA": [(60, 50.0)],
                       "USX": [(60, 20.0)], "DOWN.PA": [(60, 10.0)]}
        self.fx = {"USD": 0.9}
        self.down: set[str] = {"DOWN.PA"}
        self.split_data: dict[str, list[Split]] = {}
        self.dividend_data: dict[str, pd.Series] = {}
        self.calls: list[str] = []

    def _series(self, steps, start, end):
        idx = pd.date_range(start, end, freq="D")
        s = pd.Series(float("nan"), index=idx)
        for n, v in sorted(steps, reverse=True):
            s[s.index >= pd.Timestamp(days_ago(n))] = v
        return s.dropna()

    def daily_closes(self, ticker, start, end):
        self.calls.append(ticker)
        if ticker in self.down:
            raise ProviderUnavailable("fixe", "panne simulée")
        if ticker not in self.levels:
            raise UnknownTicker(ticker)
        return PriceSeries(ticker, self._series(self.levels[ticker], start, end), "Cours de test")

    def fx_rates(self, currency, start, end):
        self.calls.append(f"FX:{currency}")
        if currency not in self.fx:
            raise MissingCurrency(currency)
        return PriceSeries(currency, self._series([(9999, self.fx[currency])], start, end), "Change de test")

    def dividends(self, ticker, start, end):
        self.calls.append(f"DIV:{ticker}")
        if ticker in self.down:
            raise ProviderUnavailable("fixe", "panne simulée")
        d = self.dividend_data.get(ticker, pd.Series(dtype=float))
        return PriceSeries(ticker, d.loc[pd.Timestamp(start):pd.Timestamp(end)] if len(d) else d, "Dividendes de test")

    def splits(self, ticker):
        self.calls.append(f"SPLITS:{ticker}")
        if ticker in self.down:
            raise ProviderUnavailable("fixe", "panne simulée")
        return list(self.split_data.get(ticker, []))

    def instrument_info(self, ticker):
        if ticker not in self.currency:
            raise UnknownTicker(ticker)
        return InstrumentInfo(ticker, self.currency[ticker], name=f"Titre {ticker}")


class FixedRates(RateProvider):
    """Taux au jour le jour constant (en %), ou panne si `down`."""

    name = "taux-fixes"
    simulated = False

    def __init__(self, estr=2.0, eonia=-0.3):
        self.levels = {"estr": estr, "eonia": eonia}
        self.down = False

    def overnight(self, series, start, end):
        if self.down:
            raise ProviderUnavailable("taux-fixes", "panne simulée")
        idx = pd.bdate_range(start, end)
        if series == "estr":
            idx = idx[idx >= pd.Timestamp("2019-10-01")]
        return PriceSeries(series.upper(), pd.Series(self.levels[series], index=idx, dtype=float), "Taux de test")


@pytest.fixture
def rates():
    return FixedRates()


@pytest.fixture
def provider():
    return FixedProvider()


@pytest.fixture
def client(provider, rates):
    app = create_app(Settings(demo=False), provider=provider, database_url="sqlite://", rates=rates)
    with TestClient(app) as c:
        yield c


@pytest.fixture
def setup(client):
    """Deux comptes et deux cotations, prêts à recevoir des transactions."""
    cash = client.post("/api/accounts", json={"name": "CTO", "kind": "CTO",
                                              "cash_mode": "avec_especes"}).json()
    secu = client.post("/api/accounts", json={"name": "Crypto", "kind": "CRYPTO",
                                              "cash_mode": "titres_seuls"}).json()
    for t in ("AAA.PA", "USX"):
        assert client.post("/api/listings", json={"ticker": t, "asset_class": "action"}).status_code == 201
    return {"cash": cash["id"], "secu": secu["id"]}


def post_tx(client, **kw):
    body = {k: (v.isoformat() if isinstance(v, dt.date) else v) for k, v in kw.items()}
    return client.post("/api/transactions", json=body)
