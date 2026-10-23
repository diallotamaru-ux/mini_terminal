"""
Compléments à test_metrics.py : indicateurs jusqu'ici non testés,
sur des cas dont la réponse se calcule à la main.
"""

import numpy as np
import pandas as pd
import pytest

from terminal import data
from terminal import metrics as m

A = 252


def test_sortino_hand_example():
    # r = [1 %, -2 %, 3 %, -1 %], cible 0.
    # moyenne = 0,25 % ; DD = sqrt((0 + 0,0004 + 0 + 0,0001) / 4) x sqrt(252)
    r = pd.Series([0.01, -0.02, 0.03, -0.01])
    dd = np.sqrt(0.0005 / 4) * np.sqrt(A)
    assert m.downside_deviation(r) == pytest.approx(dd)
    assert m.sortino_ratio(r) == pytest.approx(0.0025 * A / dd)


def test_calmar_hand_example():
    # Prix 100 -> 120 -> 60 -> 90 : R = -10 % sur 3 séances, MDD = -50 %.
    r = pd.Series([100, 120, 60, 90], dtype=float).pct_change().dropna()
    cagr = 0.9 ** (A / 3) - 1
    assert m.cagr(r) == pytest.approx(cagr)
    assert m.calmar_ratio(r) == pytest.approx(cagr / 0.5)


def test_jensen_alpha_of_levered_copy_plus_constant():
    # r = 2 b + c : bêta = 2 exactement et alpha = 252 c (rf = 0).
    rng = np.random.default_rng(11)
    b = pd.Series(rng.normal(0, 0.01, 2000))
    c = 0.0002
    assert m.jensen_alpha(2 * b + c, b) == pytest.approx(A * c)
    # Avec rf > 0 : alpha = A [ (2 mb + c - rf) - 2 (mb - rf) ] = A (c + rf).
    rfd = m.daily_rf(0.03)
    assert m.jensen_alpha(2 * b + c, b, rf_annual=0.03) == pytest.approx(A * (c + rfd))


def test_tracking_error_equals_active_volatility():
    rng = np.random.default_rng(12)
    b = pd.Series(rng.normal(0, 0.01, 1000))
    noise = pd.Series(rng.normal(0, 0.002, 1000))
    assert m.tracking_error(b + noise, b) == pytest.approx(noise.std(ddof=1) * np.sqrt(A))
    ir = noise.mean() * A / (noise.std(ddof=1) * np.sqrt(A))
    assert m.information_ratio(b + noise, b) == pytest.approx(ir)


def test_degenerate_inputs_give_nan_not_zero():
    flat = pd.Series([0.01] * 10)
    assert np.isnan(m.sharpe_ratio(flat))                # écart-type nul
    assert np.isnan(m.sortino_ratio(flat))               # aucune baisse
    assert np.isnan(m.calmar_ratio(flat))                # aucun drawdown
    assert np.isnan(m.beta(flat, flat))                  # variance de la référence nulle
    assert np.isnan(m.information_ratio(flat, flat))     # tracking error nulle
    assert np.isnan(m.cagr(pd.Series(dtype=float)))
    assert m.cagr(pd.Series([-1.0, 0.1])) == -1.0        # ruine


def test_rolling_series_match_direct_computation():
    rng = np.random.default_rng(13)
    r = pd.Series(rng.normal(0.0005, 0.01, 300))
    w = 63
    assert m.rolling_volatility(r, w).iloc[-1] == pytest.approx(m.annual_volatility(r.iloc[-w:]))
    assert m.rolling_sharpe(r, w, rf_annual=0.02).iloc[-1] == pytest.approx(
        m.sharpe_ratio(r.iloc[-w:], rf_annual=0.02))
    assert m.rolling_volatility(r, w).iloc[: w - 1].isna().all()


def test_cumulative_index_and_simple_returns():
    p = pd.Series([100.0, 110.0, 99.0])
    r = m.simple_returns(p)
    assert r.tolist() == pytest.approx([0.10, -0.10])
    assert m.cumulative_index(r).tolist() == pytest.approx([110.0, 99.0])


def test_summary_table_matches_individual_functions():
    rng = np.random.default_rng(14)
    idx = pd.bdate_range("2020-01-01", periods=500)
    b = pd.Series(rng.normal(0.0004, 0.01, 500), index=idx)
    df = pd.DataFrame({"P": 1.2 * b + rng.normal(0, 0.003, 500)}, index=idx)
    t = m.summary_table(df, bench=b, rf_annual=0.02)
    assert t.loc["P", "Sharpe"] == pytest.approx(m.sharpe_ratio(df["P"], 0.02))
    assert t.loc["P", "Bêta"] == pytest.approx(m.beta(df["P"], b))
    assert t.loc["P", "Max drawdown"] == pytest.approx(m.max_drawdown(df["P"]))
    assert "Tracking error" in t.columns
    assert "Bêta" not in m.summary_table(df).columns


# ---------------------------------------------------------------------------
# data.py : alignement des calendriers et conversion de devise
# ---------------------------------------------------------------------------

def test_align_prices_drops_weekends_and_keeps_common_dates():
    idx = pd.date_range("2024-01-05", "2024-01-09", freq="D")    # ven. -> mar.
    p = pd.DataFrame({"BTC": [1, 2, 3, 4, 5], "AAA": [10, np.nan, np.nan, 13, 14]},
                     index=idx, dtype=float)
    out = data.align_prices(p)
    assert list(out.index.day_of_week) == [4, 0, 1]
    # Le lundi d'AAA est observé ; celui de BTC aussi : le rendement du lundi inclut le week-end.
    assert out.loc["2024-01-08", "BTC"] == 4


def test_convert_to_base_multiplies_by_fx(monkeypatch):
    idx = pd.bdate_range("2024-01-01", periods=3)
    prices = pd.DataFrame({"US": [100.0, 101.0, 102.0], "EU": [10.0, 10.0, 10.0]}, index=idx)
    fx = pd.DataFrame({"USDEUR=X": [0.9, np.nan, 0.8]}, index=idx)
    monkeypatch.setattr(data, "fetch_prices", lambda *a, **k: fx)
    out = data.convert_to_base(prices, {"US": "USD", "EU": "EUR"}, "EUR", "2024-01-01")
    assert out["US"].tolist() == pytest.approx([90.0, 90.9, 81.6])     # taux reporté le jour 2
    assert out["EU"].tolist() == [10.0, 10.0, 10.0]
    same = data.convert_to_base(prices, {"US": "EUR", "EU": "EUR"}, "EUR", "2024-01-01")
    pd.testing.assert_frame_equal(same, prices)
