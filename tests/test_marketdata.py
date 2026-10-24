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
    def dividends(self):
        if self._spec.get("splits_error"):
            raise RuntimeError("panne réseau")
        raw = self._spec.get("dividends", {})
        idx = pd.DatetimeIndex(list(raw)).tz_localize("America/New_York")
        return pd.Series(list(raw.values()), index=idx, dtype=float)

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
        return {"longName": f"Nom {self.symbol}", "exchange": "NMS", **self._spec.get("info", {})}

    def _statement(self, name):
        if self._spec.get("statements_error"):
            raise RuntimeError("panne réseau")
        rows = self._spec.get("statements", {}).get(name)
        if rows is None:
            return pd.DataFrame()
        cols = pd.DatetimeIndex(["2025-12-31", "2024-12-31"])
        return pd.DataFrame(rows, index=cols).T                # lignes = postes, colonnes = exercices

    cashflow = property(lambda self: self._statement("cashflow"))
    income_stmt = property(lambda self: self._statement("income_stmt"))
    balance_sheet = property(lambda self: self._statement("balance_sheet"))


@pytest.fixture
def yahoo(monkeypatch):
    fake = types.ModuleType("yfinance")
    fake.Ticker = FakeTicker
    monkeypatch.setitem(sys.modules, "yfinance", fake)
    FakeTicker.data = {
        "AAPL": {"currency": "USD", "closes": [190.0, 191.0]},
        "NVDA": {"currency": "USD", "splits": {"2021-07-20": 4.0, "2024-06-10": 10.0}},
        "REV": {"currency": "USD", "splits": {"2024-01-02": 0.125}},
        "QQQ": {"currency": "USD", "dividends": {"2023-12-18": 0.6, "2024-03-18": 0.57, "2024-06-24": 0.58}},
        "VOD.DIV": {"currency": "GBp", "dividends": {"2024-02-01": 400.0}},
        "SPLITDOWN": {"currency": "USD", "splits_error": True},
        "VOD.L": {"currency": "GBp", "closes": [7000.0]},
        "USDEUR=X": {"closes": [0.91, 0.92]},
        "OLD": {"error": "OLD: possibly delisted; no data found"},
        "DOWN": {"currency": "USD", "error": "Connection reset by peer"},
        "XYZEUR=X": {"error": "No data found, symbol may be delisted"},
        "CHFEUR=X": {},
        "QUIET": {"currency": "EUR", "closes": [1.0], "no_name": True},
        "BROKEN": {"info_error": True},
        "FUND.PA": {"currency": "EUR",
                    "info": {"financialCurrency": "EUR", "quoteType": "EQUITY", "sector": "Industrials",
                             "industry": "Aerospace & Defense"},
                    "statements": {
                        "cashflow": {"Operating Cash Flow": [120.0, 100.0], "Capital Expenditure": [-20.0, -15.0],
                                     "Free Cash Flow": [100.0, 85.0], "Unrelated Row": [1.0, 2.0]},
                        "income_stmt": {"Total Revenue": [1000.0, 900.0], "Interest Expense": [None, 4.0]},
                        "balance_sheet": {"Total Debt": [999.0, 999.0], "Long Term Debt": [250.0, 270.0],
                                          "Current Debt": [50.0, None],
                                          "Current Debt And Capital Lease Obligation": [None, 60.0],
                                          "Current Capital Lease Obligation": [None, 10.0],
                                          "Long Term Capital Lease Obligation": [None, 40.0],
                                          "Capital Lease Obligations": [45.0, None]}}},
        "FUNDDOWN": {"currency": "EUR", "statements_error": True},
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


def test_yahoo_dividends(yahoo):
    d = yahoo.dividends("QQQ", date(2024, 1, 1), date(2024, 12, 31))
    assert d.closes.tolist() == [0.57, 0.58] and d.closes.index.tz is None
    assert yahoo.dividends("AAPL", A, B).closes.empty
    assert yahoo.dividends("VOD.DIV", A, B).closes.tolist() == [4.0]          # pence -> livres
    with pytest.raises(ProviderUnavailable):
        yahoo.dividends("SPLITDOWN", A, B)


def test_simulated_dividends(sim):
    d = sim.dividends("QQQ", date(2024, 1, 1), date(2024, 12, 31)).closes
    assert len(d) == 4 and all(x.month in (3, 6, 9, 12) for x in d.index)
    px = sim.daily_closes("QQQ", date(2024, 1, 1), date(2024, 12, 31)).closes
    assert d.iloc[0] == pytest.approx(px.loc[d.index[0]] * 0.0015)
    assert sim.dividends("IWDA.AS", A, B).closes.empty


def test_demo_universe_is_plausible(sim):
    # Les rendements et volatilités réalisés de la démo restent dans des ordres de grandeur historiques.
    import numpy as np
    from terminal.marketdata.simulated import KIND, PLAUSIBLE
    px = sim._prices.loc["2021-01-04":"2026-10-23"]
    years = (px.index[-1] - px.index[0]).days / 365.25
    for t in px:
        s = px[t]
        ann = (s.iloc[-1] / s.iloc[0]) ** (1 / years) - 1
        vol = s.pct_change().std() * np.sqrt(252)
        lo, hi, vlo, vhi = PLAUSIBLE[KIND[t]]
        assert lo <= ann <= hi and vlo <= vol <= vhi, (t, ann, vol)
    b3 = px["BTC-EUR"].loc["2023-10-23":]
    assert b3.iloc[-1] / b3.iloc[0] - 1 <= 3.0
    w = px.resample("W-FRI").last().pct_change().dropna().corr()
    assert w.loc["QQQ", "PANX.PA"] > 0.9 and w.loc["IWDA.AS", "CW8.PA"] > 0.9


def test_demo_two_factor_correlations(sim):
    # Le facteur technologie sépare le Nasdaq du MSCI World (corrélations hebdomadaires en EUR).
    px = sim._prices.loc["2021-01-04":"2026-10-23"].copy()
    fx = sim.fx_rates("USD", date(2021, 1, 1), date(2026, 10, 23)).closes
    for t in ("QQQ", "AAPL", "NVDA"):
        px[t] = px[t] * fx.reindex(px.index).ffill()
    w = px.resample("W-FRI").last().pct_change().dropna().corr()
    assert 0.80 <= w.loc["QQQ", "IWDA.AS"] <= 0.92
    assert w.loc["QQQ", "IWDA.AS"] < w.loc["IWDA.AS", "CW8.PA"]
    assert w.loc["NVDA", "QQQ"] > w.loc["NVDA", "IWDA.AS"]          # exposition technologie
    assert w.loc["MC.PA", "IWDA.AS"] > w.loc["MC.PA", "QQQ"]        # aucune exposition technologie


def test_demo_prices_two_factor_model():
    import numpy as np
    from terminal import data
    # Sans bêta technologie, le modèle est exactement celui à un facteur d'origine.
    three = {"A": (0.08, 0.20, 0.9), "B": (0.10, 0.30, 1.2)}
    four = {k: (*v, 0.0) for k, v in three.items()}
    assert data.demo_prices(list(three), "2020-01-01", "2022-12-31", profile=three).equals(
        data.demo_prices(list(four), "2020-01-01", "2022-12-31", profile=four))
    # Sur un long échantillon, la corrélation retrouve la valeur théorique
    # rho = 0,2^2 (b_i b_j + g_i g_j) / (sigma_i sigma_j).
    prof = {"W": (0.0, 0.15, 0.72, 0.12), "N": (0.0, 0.21, 0.85, 0.60), "T": (0.0, 0.50, 1.20, 1.20)}
    r = np.log(data.demo_prices(list(prof), "1900-01-01", "1999-12-31", seed=3, profile=prof)).diff().dropna()
    c = r.corr()
    for i, j in (("W", "N"), ("W", "T"), ("N", "T")):
        th = 0.04 * (prof[i][2] * prof[j][2] + prof[i][3] * prof[j][3]) / (prof[i][1] * prof[j][1])
        assert c.loc[i, j] == pytest.approx(th, abs=0.02), (i, j)


def test_yahoo_fundamentals_mapping(yahoo):
    from terminal.marketdata.base import FUNDAMENTAL_FIELDS
    f = yahoo.fundamentals("FUND.PA")
    assert (f.currency, f.quote_type, f.industry, f.source) == ("EUR", "EQUITY", "Aerospace & Defense", "Yahoo Finance")
    t = f.table
    assert list(t.columns) == list(FUNDAMENTAL_FIELDS)
    assert list(t.index) == [pd.Timestamp("2024-12-31"), pd.Timestamp("2025-12-31")]        # triés
    assert t.loc["2025-12-31", "ocf"] == 120.0 and t.loc["2025-12-31", "capex"] == -20.0
    assert t.loc["2024-12-31", "interest_expense"] == 4.0
    # Absent chez le fournisseur : manquant (NaN), jamais zéro, et jamais déduit d'un autre poste.
    assert pd.isna(t.loc["2025-12-31", "interest_expense"])
    assert t["sbc"].isna().all() and t["minority_interest"].isna().all()
    # Dette financière construite hors locations ; « Total Debt » ignorée (périmètre variable selon la société).
    assert t.loc["2025-12-31", "financial_debt"] == 300.0                     # 250 + 50
    assert t.loc["2024-12-31", "financial_debt"] == 320.0                     # 270 + (60 − 10)
    assert t.loc["2025-12-31", "lease_liabilities"] == 45.0                   # total publié
    assert t.loc["2024-12-31", "lease_liabilities"] == 50.0                   # 40 + 10


def test_yahoo_fundamentals_errors(yahoo):
    with pytest.raises(ProviderUnavailable):
        yahoo.fundamentals("FUNDDOWN")
    with pytest.raises(ProviderUnavailable):
        yahoo.fundamentals("BROKEN")
    empty = yahoo.fundamentals("AAPL")                 # pas de comptes : tableau vide, pas d'erreur
    assert empty.table.empty and empty.quote_type is None


def test_simulated_fundamentals(sim):
    f = sim.fundamentals("AAPL")
    assert f.simulated and f.currency == "USD" and f.quote_type == "EQUITY" and len(f.table) == 5
    t = f.table
    assert t.index[-1] == pd.Timestamp("2025-09-30")
    assert (t["fcf_reported"] == t["ocf"] + t["capex"]).all()
    assert t["interest_expense"].iloc[-2:].isna().all() and t["minority_interest"].isna().all()
    assert sim.fundamentals("MC.PA").table["sbc"].isna().all()
    assert sim.fundamentals("NVDA").table.index[-1] == pd.Timestamp("2026-01-31")
    etf = sim.fundamentals("CW8.PA")
    assert etf.quote_type == "ETF" and etf.table.empty
    assert sim.fundamentals("BTC-EUR").quote_type == "CRYPTOCURRENCY"
    with pytest.raises(UnknownTicker):
        sim.fundamentals("pas un ticker!")
