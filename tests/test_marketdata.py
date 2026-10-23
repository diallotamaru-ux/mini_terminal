"""Fournisseurs de données : simulé, et Yahoo avec un yfinance factice (aucun réseau)."""

import sys
import types
from datetime import date

import pandas as pd
import pytest

from terminal.errors import MissingCurrency, ProviderUnavailable, UnknownTicker
from terminal.marketdata import get_provider
from terminal.marketdata.base import PriceSeries, clean_series
from terminal.marketdata.simulated import SimulatedProvider
from terminal.marketdata.yahoo import YahooProvider

A, B = date(2024, 1, 1), date(2024, 3, 31)


@pytest.fixture(scope="module")
def sim():
    return SimulatedProvider()


def test_simulated_is_flagged_and_deterministic(sim):
    s = sim.daily_closes("PANX.PA", A, B)
    assert s.simulated and "fictives" in s.source
    # Le cours d'une date ne dépend pas de la fenêtre demandée ni d'une autre instance.
    other = SimulatedProvider().daily_closes("PANX.PA", date(2024, 2, 1), date(2024, 2, 29))
    common = other.closes.index
    pd.testing.assert_series_equal(s.closes.loc[common], other.closes)
    assert s.last_date <= B


def test_simulated_unknown_ticker_and_generic_profile(sim):
    with pytest.raises(UnknownTicker):
        sim.daily_closes("pas un ticker!", A, B)
    x = sim.daily_closes("ZZZ", A, B)
    assert not x.closes.empty
    pd.testing.assert_series_equal(x.closes, sim.daily_closes("ZZZ", A, B).closes)


def test_simulated_fx_and_currency_rules(sim):
    usd = sim.fx_rates("USD", A, B)
    assert usd.closes.between(0.6, 1.3).all() and len(usd.closes) == (B - A).days + 1
    assert (sim.fx_rates("EUR", A, B).closes == 1.0).all()
    with pytest.raises(MissingCurrency):
        sim.fx_rates("XYZ", A, B)
    assert sim.instrument_info("CW8.PA").currency == "EUR"
    assert sim.instrument_info("BTC-EUR").currency == "EUR"
    assert sim.instrument_info("AAPL").currency == "USD"


def test_get_provider():
    assert isinstance(get_provider("simule"), SimulatedProvider)
    assert isinstance(get_provider("yahoo"), YahooProvider)
    with pytest.raises(ValueError):
        get_provider("bloomberg")


def test_clean_series_normalises_index():
    idx = pd.DatetimeIndex(["2024-01-02 09:30", "2024-01-01 09:30", "2024-01-02 17:00"]).tz_localize("UTC")
    s = clean_series(pd.Series([2, 1, 3], index=idx))
    assert s.index.tz is None and s.tolist() == [1.0, 3.0]
    assert PriceSeries("X", pd.Series(dtype=float), "t").last_date is None


# ---------------------------------------------------------------------------
# Yahoo, avec un module yfinance factice
# ---------------------------------------------------------------------------

class FakeTicker:
    data: dict = {}

    def __init__(self, symbol):
        self.symbol = symbol
        spec = self.data.get(symbol, {})
        self._spec = spec
        if spec.get("info_error"):
            raise RuntimeError("panne réseau")
        self.fast_info = {"currency": spec.get("currency")}

    @property
    def splits(self):
        if self._spec.get("splits_error"):
            raise RuntimeError("panne réseau")
        raw = self._spec.get("splits", {})
        idx = pd.DatetimeIndex(list(raw)).tz_localize("America/New_York")
        return pd.Series(list(raw.values()), index=idx, dtype=float)

    def history(self, **kw):
        assert kw["auto_adjust"] is False            # jamais de cours ajustés des dividendes
        err = self._spec.get("error")
        if err:
            raise RuntimeError(err)
        closes = self._spec.get("closes")
        if closes is None:
            return pd.DataFrame()
        idx = pd.date_range("2024-01-01", periods=len(closes), freq="D", tz="America/New_York")
        return pd.DataFrame({"Close": closes}, index=idx)

    def get_info(self):
        if self._spec.get("no_name"):
            raise RuntimeError("quota")
        return {"longName": f"Nom {self.symbol}", "exchange": "NMS"}


@pytest.fixture
def yahoo(monkeypatch):
    fake = types.ModuleType("yfinance")
    fake.Ticker = FakeTicker
    monkeypatch.setitem(sys.modules, "yfinance", fake)
    FakeTicker.data = {
        "AAPL": {"currency": "USD", "closes": [190.0, 191.0]},
        "NVDA": {"currency": "USD", "splits": {"2021-07-20": 4.0, "2024-06-10": 10.0}},
        "REV": {"currency": "USD", "splits": {"2024-01-02": 0.125}},
        "SPLITDOWN": {"currency": "USD", "splits_error": True},
        "VOD.L": {"currency": "GBp", "closes": [7000.0]},
        "USDEUR=X": {"closes": [0.91, 0.92]},
        "OLD": {"error": "OLD: possibly delisted; no data found"},
        "DOWN": {"currency": "USD", "error": "Connection reset by peer"},
        "XYZEUR=X": {"error": "No data found, symbol may be delisted"},
        "CHFEUR=X": {},
        "QUIET": {"currency": "EUR", "closes": [1.0], "no_name": True},
        "BROKEN": {"info_error": True},
    }
    return YahooProvider()


def test_yahoo_closes_are_naive_and_tagged(yahoo):
    s = yahoo.daily_closes("AAPL", A, B)
    assert s.source == "Yahoo Finance" and not s.simulated
    assert s.closes.index.tz is None and s.closes.tolist() == [190.0, 191.0]


def test_yahoo_pence_converted_to_pounds(yahoo):
    assert yahoo.daily_closes("VOD.L", A, B).closes.iloc[0] == pytest.approx(70.0)
    assert yahoo.instrument_info("VOD.L").currency == "GBP"


def test_yahoo_errors_are_typed(yahoo):
    with pytest.raises(UnknownTicker):
        yahoo.daily_closes("OLD", A, B)
    with pytest.raises(UnknownTicker):
        yahoo.daily_closes("NOPE", A, B)               # historique vide
    with pytest.raises(ProviderUnavailable):
        yahoo.daily_closes("DOWN", A, B)
    with pytest.raises(UnknownTicker):
        yahoo.instrument_info("NOPE")                  # pas de devise
    with pytest.raises(ProviderUnavailable):
        yahoo.instrument_info("BROKEN")


def test_yahoo_fx(yahoo):
    assert yahoo.fx_rates("USD", A, B).closes.tolist() == [0.91, 0.92]
    assert (yahoo.fx_rates("EUR", A, B).closes == 1.0).all()
    with pytest.raises(MissingCurrency):
        yahoo.fx_rates("XYZ", A, B)
    with pytest.raises(MissingCurrency):
        yahoo.fx_rates("CHF", A, B)


def test_yahoo_info(yahoo):
    info = yahoo.instrument_info("AAPL")
    assert info.currency == "USD" and info.name == "Nom AAPL" and info.exchange == "NMS"
    assert yahoo.instrument_info("QUIET").name is None


def test_yahoo_splits(yahoo):
    nv = yahoo.splits("NVDA")
    assert [(x.date, x.numerator, x.denominator) for x in nv] == [
        (date(2021, 7, 20), 4, 1), (date(2024, 6, 10), 10, 1)]
    assert [(x.numerator, x.denominator) for x in yahoo.splits("REV")] == [(1, 8)]
    assert yahoo.splits("AAPL") == []
    with pytest.raises(ProviderUnavailable):
        yahoo.splits("SPLITDOWN")


def test_simulated_splits(sim):
    s = sim.splits("NVDA")
    assert len(s) == 1 and s[0].label == "10 pour 1" and s[0].date == date(2024, 6, 10)
    assert sim.splits("PANX.PA") == []
    with pytest.raises(UnknownTicker):
        sim.splits("pas un ticker!")
