"""
Risque et comparaison : fréquences, biais des clôtures non synchrones,
intervalles de confiance, périodes. Cas calculés à la main.
"""

from datetime import date

import numpy as np
import pandas as pd
import pytest

from terminal import metrics as m
from terminal import performance as pf
from terminal import risk


# ---------------------------------------------------------------------------
# Jours ouvrés et semaines
# ---------------------------------------------------------------------------

def test_weekend_compounded_into_monday():
    # Ven. +1 %, sam. +2 %, dim. -1 %, lun. +3 %  ->  ven. +1 %, lun. 1,02 x 0,99 x 1,03 - 1 = +4,0094 %.
    idx = pd.date_range("2025-03-07", periods=4, freq="D")
    out = risk.to_business_days(pd.Series([0.01, 0.02, -0.01, 0.03], index=idx))
    assert out.index.tolist() == [pd.Timestamp("2025-03-07"), pd.Timestamp("2025-03-10")]
    assert out.tolist() == pytest.approx([0.01, 1.02 * 0.99 * 1.03 - 1])
    # Une valeur manquante n'est jamais ignorée.
    assert np.isnan(risk.to_business_days(pd.Series([0.01, np.nan], index=idx[1:3])).iloc[0])
    assert risk.to_business_days(pd.Series(dtype=float)).empty


def test_weekly_returns_hand_example():
    # Semaine 1 (03-07/03/2025) : +1 % chaque jour -> 1,01^5 - 1 = 5,101005 %.
    # Semaine 2 (10-14/03) : +2 %, -1 %, 0, 0, +1 % -> 1,02 x 0,99 x 1,01 - 1 = 1,9898 %.
    idx = pd.bdate_range("2025-03-03", "2025-03-14")
    r = pd.Series([0.01] * 5 + [0.02, -0.01, 0.0, 0.0, 0.01], index=idx)
    w, partial = risk.to_weekly(r)
    assert w.index.tolist() == [pd.Timestamp("2025-03-07"), pd.Timestamp("2025-03-14")]
    assert w.tolist() == pytest.approx([1.01 ** 5 - 1, 1.02 * 0.99 * 1.01 - 1])
    assert partial == 0
    # Début un mercredi : première semaine partielle, signalée.
    assert risk.to_weekly(r.iloc[2:])[1] == 1
    assert risk.to_weekly(r.iloc[:3])[1] == 1
    assert risk.to_weekly(pd.Series(dtype=float))[1] == 0


def test_asynchronous_closes_bias_daily_correlation():
    # B réagit avec un jour de retard à A (A i.i.d.) : B_t = A_{t-1}.
    # En quotidien, corrélation et bêta sont proches de 0.
    # En hebdomadaire, 4 jours sur 5 sont communs : corrélation et bêta proches de 4/5.
    # Le bêta de Dimson (semaines t-1, t, t+1) retrouve 4/5 + 1/5 = 1.
    rng = np.random.default_rng(42)
    idx = pd.bdate_range("2000-01-03", periods=20_000)
    a = pd.Series(rng.normal(0, 0.01, len(idx)), index=idx)
    b = a.shift(1).dropna()
    a = a.loc[b.index]
    daily_corr = a.corr(b)
    aw, _ = risk.to_weekly(a)
    bw, _ = risk.to_weekly(b)
    weekly_corr = aw.corr(bw)
    assert abs(daily_corr) < 0.03
    assert weekly_corr == pytest.approx(0.8, abs=0.03)
    assert weekly_corr - daily_corr > 0.7                         # biais nettement visible
    assert m.beta(bw, aw) == pytest.approx(0.8, abs=0.04)
    assert m.dimson_beta(bw, aw) == pytest.approx(1.0, abs=0.04)
    assert np.isnan(m.dimson_beta(bw.iloc[:3], aw.iloc[:3]))


def test_index_returns_holiday_and_base():
    # Base vendredi 99 ; lundi 100 ; mardi férié (pas de cours) ; mercredi 102.
    # Rendements : lundi 100/99 - 1, mardi 0 (cours reporté), mercredi 102/100 - 1.
    level = pd.Series([99.0, 100.0, 102.0], index=pd.DatetimeIndex(["2025-03-07", "2025-03-10", "2025-03-12"]))
    grid = pd.bdate_range("2025-03-10", "2025-03-12")
    r = risk.index_returns(level, grid, date(2025, 3, 7))
    assert r.tolist() == pytest.approx([100 / 99 - 1, 0.0, 0.02])
    # Plus de 7 jours sans cours : NaN.
    far = risk.index_returns(level, pd.bdate_range("2025-03-24", "2025-03-25"), date(2025, 3, 7))
    assert far.isna().all()
    assert risk.index_returns(pd.Series(dtype=float), grid, date(2025, 3, 7)).isna().all()


# ---------------------------------------------------------------------------
# Intervalles de confiance (Lo, 2002)
# ---------------------------------------------------------------------------

def test_sharpe_ci_hand_example():
    # SR = 1, 3 ans de données quotidiennes (n = 756), A = 252.
    # SR_p = 1 / sqrt(252) = 0,062994 ; SR_p^2 / 2 = 0,001984
    # SE_p = sqrt(1,001984 / 756) = 0,036406 ; annualisée : x sqrt(252) = 0,577927
    # demi-largeur = 1,959964 x 0,577927 = 1,132716  ->  IC = [-0,1327 ; 2,1327]
    lo, hi = m.sharpe_ci(1.0, 756)
    assert lo == pytest.approx(-0.132716, abs=1e-5) and hi == pytest.approx(2.132716, abs=1e-5)


def test_information_ratio_ci_weekly_hand_example():
    # IR = 0,5 sur 3 ans de semaines (n = 156), A = 52.
    # IR_p = 0,5 / sqrt(52) = 0,069338 ; IR_p^2 / 2 = 0,002404
    # SE_p = sqrt(1,002404 / 156) = 0,080161 ; x sqrt(52) = 0,578048
    # demi-largeur = 1,959964 x 0,578048 = 1,132953  ->  IC = [-0,6330 ; 1,6330]
    lo, hi = m.sharpe_ci(0.5, 156, periods=52)
    assert lo == pytest.approx(-0.632953, abs=1e-5) and hi == pytest.approx(1.632953, abs=1e-5)
    assert all(np.isnan(x) for x in m.sharpe_ci(0.5, 1))
    assert all(np.isnan(x) for x in m.sharpe_ci(np.nan, 100))


def test_short_history_warning():
    # 2 ans (504 séances) : demi-largeur pour un Sharpe nul = 1,96 x sqrt(1/504) x sqrt(252) = 1,386.
    w = risk.short_history_warning(730, 504)
    assert "2,0 ans" in w and "± 1,39" in w
    assert risk.short_history_warning(3 * 365, 756) is None
    assert risk.short_history_warning(100, 1) is None


# ---------------------------------------------------------------------------
# Périodes
# ---------------------------------------------------------------------------

def test_period_bases():
    as_of, first = date(2026, 10, 23), date(2020, 1, 15)
    assert risk.period_base("origine", as_of, first) == date(2020, 1, 14)
    assert risk.period_base("ytd", as_of, first) == date(2025, 12, 31)
    assert risk.period_base("1y", as_of, first) == date(2025, 10, 23)
    assert risk.period_base("3y", as_of, first) == date(2023, 10, 23)
    assert risk.period_base("5y", as_of, first) == date(2021, 10, 23)
    # 29 février : un an avant tombe le 28 février.
    assert risk.period_base("1y", date(2028, 2, 29), first) == date(2027, 2, 28)
    with pytest.raises(risk.PeriodError, match="inconnue"):
        risk.period_base("10y", as_of, first)


def test_period_longer_than_history_is_refused():
    as_of, first = date(2026, 10, 23), date(2024, 6, 1)
    with pytest.raises(risk.PeriodError, match="plus longue que l'historique \\(2,4 ans\\)"):
        risk.period_base("3y", as_of, first)
    assert risk.available_periods(as_of, first) == {"origine": True, "ytd": True, "1y": True,
                                                    "3y": False, "5y": False}
    # Historique commencé en cours d'année : début d'année indisponible.
    assert risk.available_periods(date(2026, 10, 23), date(2026, 3, 1))["ytd"] is False


def test_slice_for_period_twr_and_mwr_hand_example():
    # 1 000 apportés le 01/01/2024, valeur 1 000 jusqu'au 31/12/2024, puis 1 100 au 31/12/2025.
    # Période 1 an au 31/12/2025, base 31/12/2024 : la valeur de base (1 000) devient l'apport du 01/01/2025.
    # TWR = 1 100 / 1 000 - 1 = 10 %. TRI : -1 000 au 01/01/2025, +1 100 le 01/01/2026 (365 jours) = 10 %.
    idx = pd.date_range("2024-01-01", "2025-12-31", freq="D")
    v = pd.Series(1000.0, index=idx)
    v.iloc[-1] = 1100.0
    inflow = pd.Series(0.0, index=idx)
    inflow.iloc[0] = 1000.0
    outflow = pd.Series(0.0, index=idx)
    base = risk.period_base("1y", date(2025, 12, 31), date(2024, 1, 1))
    sv, si, so = risk.slice_for_period(v, inflow, outflow, base)
    assert sv.index[0] == pd.Timestamp("2025-01-01") and si.iloc[0] == 1000.0
    t = pf.twr(sv, si, so)
    assert t.total == pytest.approx(0.10) and t.days == 365 and t.annualized == pytest.approx(0.10)
    r = pf.mwr(sv, si, so)
    assert r.annualized and r.rate == pytest.approx(0.10)
    # L'original n'est pas modifié.
    assert inflow.loc["2025-01-01"] == 0.0


# ---------------------------------------------------------------------------
# Tableau : règles
# ---------------------------------------------------------------------------

def _series(n, seed=1, beta=1.2):
    rng = np.random.default_rng(seed)
    idx = pd.bdate_range("2021-01-04", periods=n)
    ref = pd.Series(rng.normal(0.0004, 0.01, n), index=idx)
    r = beta * ref + pd.Series(rng.normal(0.0001, 0.003, n), index=idx)
    rf = pd.Series(0.02 / 360, index=idx)
    return r, rf, ref


def test_full_row_reuses_metrics():
    r, rf, ref = _series(900)                                      # environ 3,5 ans
    row = risk.risk_row("Portefeuille", "portefeuille", r, rf, ref, span_days=1260)
    assert row.complete and row.n_days == 900 and row.n_weeks == 180
    assert row.sharpe == pytest.approx(m.sharpe_ratio(r - rf, 0.0))
    assert row.sharpe_ci == pytest.approx(m.sharpe_ci_hac(r - rf))           # robuste à l'autocorrélation
    assert row.volatility == pytest.approx(m.annual_volatility(r))
    assert row.max_drawdown == pytest.approx(m.max_drawdown(r))
    rw, bw, fw = risk.to_weekly(r)[0], risk.to_weekly(ref)[0], risk.to_weekly(rf)[0]
    assert row.beta == pytest.approx(m.beta(rw - fw, bw - fw)) and row.beta == pytest.approx(1.2, abs=0.05)
    assert row.tracking_error == pytest.approx(m.tracking_error(rw, bw, periods=52))
    assert row.information_ratio_ci is not None and row.beta_dimson == pytest.approx(1.2, abs=0.1)
    assert row.annual_return == pytest.approx((1 + row.total_return) ** (365 / 1260) - 1)
    assert row.notes == {}


def test_under_one_year_hides_annualized_ratios():
    r, rf, ref = _series(180)                                      # 36 semaines, 250 jours calendaires
    row = risk.risk_row("P", "portefeuille", r, rf, ref, span_days=250)
    for f in risk.ANNUALIZED:
        assert getattr(row, f) is None, f
    assert row.sharpe_ci is None and row.information_ratio_ci is None
    assert row.total_return is not None and row.max_drawdown is not None and row.var95 is not None
    assert row.beta is not None and row.correlation is not None    # non annualisés : affichés
    assert "moins d'un an" in row.notes["annualise"]


def test_insufficient_weeks_and_reference_rows():
    r, rf, ref = _series(100)                                      # 20 semaines
    row = risk.risk_row("P", "portefeuille", r, rf, ref, span_days=400)
    assert row.beta is None and "20 semaines" in row.notes["relatif"]
    ref_row = risk.risk_row("QQQ", "reference", ref, rf, ref, span_days=400, is_reference=True)
    assert ref_row.beta is None and ref_row.sharpe is not None and "relatif" not in ref_row.notes
    bad_ref = ref.copy()
    bad_ref.iloc[50] = np.nan
    r2, rf2, _ = _series(300)
    row = risk.risk_row("P", "portefeuille", r2, rf2, bad_ref.reindex(r2.index), span_days=430)
    assert row.beta is None and "référence incomplète" in row.notes["relatif"]


def test_missing_value_makes_row_incomplete():
    r, rf, ref = _series(300)
    r.iloc[120] = np.nan
    row = risk.risk_row("P", "portefeuille", r, rf, ref, span_days=430)
    assert not row.complete and row.sharpe is None and row.first_missing == r.index[120].date()
    r, rf, ref = _series(300)
    rf.iloc[10] = np.nan
    assert not risk.risk_row("P", "portefeuille", r, rf, ref, span_days=430).complete
    empty = risk.risk_row("P", "portefeuille", pd.Series(dtype=float), pd.Series(dtype=float), None, 0)
    assert not empty.complete and empty.notes["serie"] == "aucune donnée"


# ---------------------------------------------------------------------------
# Intervalle robuste à l'autocorrélation (Lo, 2002, GMM + Newey-West)
# ---------------------------------------------------------------------------

def test_sharpe_ci_hac_hand_example_without_lags():
    # r = [2 %, -1 %, 3 %, 0 %], sans retard (L = 0), sans annualisation (A = 1).
    # mu = 0,01 ; d = [0,01 ; -0,02 ; 0,02 ; -0,01] ; sigma^2 = mean(d^2) = 2,5e-4 ; sigma = 0,0158114
    # moments h2 = d^2 - sigma^2 = [-1,5 ; 1,5 ; 1,5 ; -1,5] x 1e-4
    # S11 = 2,5e-4 ; S12 = mean(d x h2) = 0 ; S22 = mean(h2^2) = 2,25e-8
    # V = S11 / sigma^2 + (mu / (2 sigma^3))^2 x S22 = 1 + 1264,91^2 x 2,25e-8 = 1,036
    # SE = sqrt(1,036 / 4) = 0,508920 ; Sharpe affiché (écart-type ddof = 1) = 0,01 / 0,0182574 = 0,547723
    # demi-largeur = 1,959964 x 0,508920 = 0,997465 -> IC = [-0,449742 ; 1,545188]
    r = pd.Series([0.02, -0.01, 0.03, 0.00])
    lo, hi = m.sharpe_ci_hac(r, periods=1, lags=0)
    assert lo == pytest.approx(-0.449742, abs=1e-5) and hi == pytest.approx(1.545188, abs=1e-5)


def test_sharpe_ci_hac_matches_iid_without_autocorrelation():
    # Rendements gaussiens i.i.d. : la version robuste retrouve la version i.i.d. (V = 1 + SR_p^2 / 2).
    rng = np.random.default_rng(21)
    r = pd.Series(rng.normal(0.0005, 0.01, 200_000))
    sr = m.sharpe_ratio(r, 0.0)
    lo_h, hi_h = m.sharpe_ci_hac(r)
    lo_i, hi_i = m.sharpe_ci(sr, len(r))
    assert (hi_h - lo_h) == pytest.approx(hi_i - lo_i, rel=0.03)
    assert (lo_h + hi_h) / 2 == pytest.approx(sr)


def test_sharpe_ci_hac_widens_with_positive_autocorrelation():
    # AR(1) de coefficient 0,5 : la variance de long terme de la moyenne est multipliée par
    # (1 + rho) / (1 - rho) = 3. Pour un Sharpe petit, l'intervalle s'élargit d'environ sqrt(3) = 1,73.
    rng = np.random.default_rng(22)
    e = rng.normal(0, 0.01, 200_000)
    x = np.empty_like(e)
    x[0] = e[0]
    for t in range(1, len(e)):
        x[t] = 0.5 * x[t - 1] + e[t]
    r = pd.Series(x + 0.0002)
    lo_h, hi_h = m.sharpe_ci_hac(r, lags=50)
    lo_i, hi_i = m.sharpe_ci(m.sharpe_ratio(r, 0.0), len(r))
    assert (hi_h - lo_h) / (hi_i - lo_i) == pytest.approx(np.sqrt(3), rel=0.08)


def test_sharpe_ci_hac_edge_cases_and_lags():
    assert m.newey_west_lags(756) == 6 and m.newey_west_lags(156) == 4
    assert all(np.isnan(v) for v in m.sharpe_ci_hac(pd.Series([0.01, 0.02])))
    assert all(np.isnan(v) for v in m.sharpe_ci_hac(pd.Series([0.01] * 10)))
