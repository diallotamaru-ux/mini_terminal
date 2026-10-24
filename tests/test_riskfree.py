"""Taux sans risque : raccord EONIA / €STR, convention ACT/360, fournisseurs."""

import urllib.error
from datetime import date

import pandas as pd
import pytest

from terminal.errors import ProviderUnavailable
from terminal.marketdata import ecb
from terminal.marketdata.ecb import EcbRates
from terminal.marketdata.rates import SimulatedRates
from terminal.riskfree import ESTR_START, Segment, daily_rates, fixed_rates, segments, splice_eonia_estr


def test_act360_hand_example():
    # Taux de 3,60 % publié le vendredi 07/03/2025, 3,24 % le lundi 10/03.
    # Lundi : intérêt de vendredi à lundi, 3 jours : 0,036 x 3 / 360 = 0,0003.
    # Mardi : 1 jour au taux du lundi : 0,0324 / 360 = 0,00009.
    rate = pd.Series([3.60, 3.24], index=pd.DatetimeIndex(["2025-03-07", "2025-03-10"]))
    grid = pd.DatetimeIndex(["2025-03-10", "2025-03-11"])
    assert daily_rates(rate, grid).tolist() == pytest.approx([0.0003, 0.00009])


def test_first_date_accrues_from_previous_business_day_and_missing_is_nan():
    rate = pd.Series([3.60], index=pd.DatetimeIndex(["2025-03-07"]))
    # Première date de la grille un lundi : 3 jours depuis le vendredi.
    assert daily_rates(rate, pd.DatetimeIndex(["2025-03-10"])).iloc[0] == pytest.approx(0.0003)
    # Aucun taux connu avant la date : NaN, jamais 0.
    assert daily_rates(rate, pd.DatetimeIndex(["2025-03-03"])).isna().all()
    # Taux trop ancien (plus de 7 jours) : NaN.
    assert daily_rates(rate, pd.DatetimeIndex(["2025-03-20"])).isna().all()
    assert daily_rates(pd.Series(dtype=float), pd.DatetimeIndex(["2025-03-10"])).isna().all()
    assert daily_rates(rate, pd.DatetimeIndex([])).empty


def test_fixed_rate_same_convention():
    # 2 % fixe : un mardi 0,02 / 360, un lundi 3 x 0,02 / 360.
    grid = pd.DatetimeIndex(["2025-03-10", "2025-03-11"])
    assert fixed_rates(2.0, grid).tolist() == pytest.approx([0.06 / 360, 0.02 / 360])


def test_splice_eonia_before_estr_from_1_october_2019():
    # Valeurs réelles BCE : EONIA -0,451 le 30/09/2019, -0,464 le 01/10 ; €STR -0,549 le 01/10.
    eonia = pd.Series([-0.451, -0.464], index=pd.DatetimeIndex(["2019-09-30", "2019-10-01"]))
    estr = pd.Series([-0.549, -0.551], index=pd.DatetimeIndex(["2019-10-01", "2019-10-02"]))
    s = splice_eonia_estr(eonia, estr)
    assert s.tolist() == [-0.451, -0.549, -0.551]
    assert splice_eonia_estr(pd.Series(dtype=float), pd.Series(dtype=float)).empty


def test_segments_describe_series_used():
    assert segments(date(2018, 1, 2), date(2020, 6, 30)) == [
        Segment("EONIA", date(2018, 1, 2), date(2019, 9, 30)), Segment("€STR", ESTR_START, date(2020, 6, 30))]
    assert [s.name for s in segments(date(2021, 1, 1), date(2025, 1, 1))] == ["€STR"]
    assert [s.name for s in segments(date(2015, 1, 1), date(2018, 1, 1))] == ["EONIA"]
    assert segments(date(2021, 1, 1), date(2025, 1, 1), "fixe", 2.5)[0].name == "taux fixe 2,50 %"
    assert segments(date(2021, 1, 1), date(2025, 1, 1), "zero")[0].name == "zéro"


def test_simulated_rates():
    r = SimulatedRates()
    estr = r.overnight("estr", date(2019, 9, 1), date(2019, 10, 31)).closes
    assert estr.index[0] == pd.Timestamp("2019-10-01") and r.overnight("estr", date(2024, 1, 1), date(2024, 1, 31)).simulated
    eon = r.overnight("eonia", date(2019, 10, 1), date(2019, 10, 1)).closes
    assert eon.iloc[0] == pytest.approx(estr.iloc[0] + 0.085)                 # EONIA = €STR + 8,5 pb
    assert r.overnight("eonia", date(2022, 1, 1), date(2022, 3, 1)).closes.empty
    with pytest.raises(ProviderUnavailable):
        r.overnight("libor", date(2020, 1, 1), date(2020, 2, 1))


CSV = ("KEY,FREQ,TIME_PERIOD,OBS_VALUE\n"
       "EST.B.EU000A2X2A25.WT,B,2026-10-21,2.44\n"
       "EST.B.EU000A2X2A25.WT,B,2026-10-22,2.442\n")


def test_ecb_parsing_and_errors(monkeypatch):
    p = EcbRates()
    urls = []
    monkeypatch.setattr(p, "_get", lambda url: urls.append(url) or CSV)
    s = p.overnight("estr", date(2026, 10, 20), date(2026, 10, 22))
    assert s.closes.tolist() == [2.44, 2.442] and s.source == ecb.SOURCE
    assert "EST/B.EU000A2X2A25.WT" in urls[0] and "startPeriod=2026-10-20" in urls[0]
    monkeypatch.setattr(p, "_get", lambda url: "")
    assert p.overnight("eonia", date(2022, 1, 1), date(2022, 2, 1)).closes.empty
    monkeypatch.setattr(p, "_get", lambda url: "TIME_PERIOD,OBS_VALUE\n2026-10-21,abc\n")
    with pytest.raises(ProviderUnavailable):
        p.overnight("estr", date(2026, 10, 20), date(2026, 10, 22))
    with pytest.raises(ProviderUnavailable):
        p.overnight("libor", date(2026, 10, 20), date(2026, 10, 22))


def test_ecb_http_errors(monkeypatch):
    def raise_(exc):
        def f(*a, **k):
            raise exc
        return f
    p = EcbRates()
    monkeypatch.setattr(ecb.urllib.request, "urlopen",
                        raise_(urllib.error.HTTPError("u", 404, "Not Found", {}, None)))
    assert p._get("https://ecb.test/x") == ""
    monkeypatch.setattr(ecb.urllib.request, "urlopen",
                        raise_(urllib.error.HTTPError("u", 503, "Unavailable", {}, None)))
    with pytest.raises(ProviderUnavailable):
        p._get("https://ecb.test/x")
    monkeypatch.setattr(ecb.urllib.request, "urlopen", raise_(urllib.error.URLError("dns")))
    with pytest.raises(ProviderUnavailable):
        p._get("https://ecb.test/x")

    class Resp:
        def __enter__(self): return self
        def __exit__(self, *a): return False
        def read(self): return CSV.encode()
    monkeypatch.setattr(ecb.urllib.request, "urlopen", lambda req, timeout: Resp())
    assert p._get("https://ecb.test/x") == CSV


def test_ecb_long_yield(monkeypatch):
    p = EcbRates()
    urls = []
    monkeypatch.setattr(p, "_get", lambda url: urls.append(url) or CSV)
    s = p.long_yield("EUR", date(2026, 10, 20), date(2026, 10, 22))
    assert s.ticker == "EUR10Y" and s.closes.tolist() == [2.44, 2.442]
    assert "YC/B.U2.EUR.4F.G_N_A.SV_C_YM.SR_10Y" in urls[0]
    with pytest.raises(ProviderUnavailable):
        p.long_yield("USD", date(2026, 10, 20), date(2026, 10, 22))


def test_fred_long_yield(monkeypatch):
    from terminal.marketdata import fred
    from terminal.marketdata.fred import FredRates

    class Resp:
        def __init__(self, body):
            self.body = body.encode()

        def __enter__(self):
            return self

        def __exit__(self, *a):
            return False

        def read(self):
            return self.body

    seen = []

    def ok(req, timeout):
        seen.append(req)
        return Resp("observation_date,DGS10\n2026-10-19,4.10\n2026-10-20,.\n2026-10-21,4.15\n")
    monkeypatch.setattr(fred.urllib.request, "urlopen", ok)
    p = FredRates()
    s = p.long_yield("USD", date(2026, 10, 19), date(2026, 10, 21))
    assert s.closes.tolist() == [4.10, 4.15] and s.source == fred.SOURCE      # « . » = pas de cotation
    assert "id=DGS10" in seen[0].full_url and "cosd=2026-10-19" in seen[0].full_url
    assert "Mozilla" in seen[0].get_header("User-agent")
    with pytest.raises(ProviderUnavailable):
        p.long_yield("EUR", date(2026, 10, 19), date(2026, 10, 21))
    with pytest.raises(ProviderUnavailable):
        p.overnight("estr", date(2026, 10, 19), date(2026, 10, 21))
    monkeypatch.setattr(fred.urllib.request, "urlopen", lambda r, timeout: Resp("autre,format\n1,2\n"))
    with pytest.raises(ProviderUnavailable):
        p.long_yield("USD", date(2026, 10, 19), date(2026, 10, 21))

    def boom(exc):
        def f(*a, **k):
            raise exc
        return f
    monkeypatch.setattr(fred.urllib.request, "urlopen", boom(urllib.error.HTTPError("u", 500, "x", {}, None)))
    with pytest.raises(ProviderUnavailable):
        p.long_yield("USD", date(2026, 10, 19), date(2026, 10, 21))
    monkeypatch.setattr(fred.urllib.request, "urlopen", boom(TimeoutError("lent")))
    with pytest.raises(ProviderUnavailable):
        p.long_yield("USD", date(2026, 10, 19), date(2026, 10, 21))


def test_simulated_and_combined_long_yield():
    from terminal.marketdata.rates import CombinedRates, SimulatedRates
    sim = SimulatedRates()
    s = sim.long_yield("EUR", date(2026, 10, 1), date(2026, 10, 9))
    assert s.simulated and s.closes.iloc[0] == pytest.approx(2.70)
    with pytest.raises(ProviderUnavailable):
        sim.long_yield("JPY", date(2026, 10, 1), date(2026, 10, 9))
    c = CombinedRates(sim, {"USD": sim})
    assert c.name == "simule"
    assert c.long_yield("USD", date(2026, 10, 1), date(2026, 10, 2)).closes.iloc[0] == pytest.approx(4.20)
    assert not c.overnight("estr", date(2026, 10, 1), date(2026, 10, 2)).closes.empty
    with pytest.raises(ProviderUnavailable):
        c.long_yield("EUR", date(2026, 10, 1), date(2026, 10, 2))
