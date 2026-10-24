"""
TWR et TRI sur des cas calculés à la main.

Convention (voir terminal/performance.py) : apports en début de journée,
retraits en fin de journée, r_t = (V_t + O_t) / (V_{t-1} + I_t) - 1.
"""

from datetime import date, timedelta

import numpy as np
import pandas as pd
import pytest

from terminal import performance as pf

IDX3 = pd.date_range("2024-01-01", periods=3, freq="D")


def s(values, idx=IDX3):
    return pd.Series(values, index=idx[: len(values)], dtype=float)


def test_twr_hand_example():
    # Jour 0 : apport de 1 000, valeur 1 000           r0 = 1000 / (0 + 1000) - 1    = 0
    # Jour 1 : valeur 1 100                             r1 = 1100 / 1000 - 1          = 0,10
    # Jour 2 : apport de 500 le matin, valeur 1 520     r2 = 1520 / (1100 + 500) - 1  = -0,05
    # TWR = 1,00 x 1,10 x 0,95 - 1 = 0,045
    res = pf.twr(s([1000, 1100, 1520]), inflows=s([1000, 0, 500]))
    assert res.returns.tolist() == pytest.approx([0.0, 0.10, -0.05])
    assert res.total == pytest.approx(0.045, abs=1e-12)
    assert res.annualized is None                       # 3 jours : pas d'annualisation
    assert res.days == 3


def test_twr_full_sale_after_rise():
    # Valeur 100, puis tout est vendu 105 en fin de journée : r = (0 + 105) / 100 - 1 = 5 %.
    # Avec une convention « tout en début de journée », le dénominateur vaudrait 100 - 105 < 0.
    idx = pd.date_range("2024-01-01", periods=2, freq="D")
    res = pf.twr(s([100, 0], idx), inflows=s([100, 0], idx), outflows=s([0, 105], idx))
    assert res.total == pytest.approx(0.05)


def test_twr_ignores_timing_of_deposits_mwr_does_not():
    # Quatre valorisations suffisent (le calcul ne suppose pas une grille quotidienne).
    # j0 : apport 100, valeur 100                         r = 0
    # j1 (un an après) : valeur 200                       r = +100 %
    # j2 (lendemain) : apport 1 000 le matin, valeur 1200 r = 1200 / (200 + 1000) - 1 = 0
    # j3 (un an après) : valeur 600                       r = -50 %
    # TWR = 1 x 2 x 1 x 0,5 - 1 = 0 : la gestion n'a rien gagné ni perdu.
    # Mais l'investisseur a apporté 1 100 et récupère 600 : le TRI est très négatif.
    idx = pd.DatetimeIndex(["2022-01-01", "2023-01-01", "2023-01-02", "2024-01-02"])
    v = pd.Series([100.0, 200.0, 1200.0, 600.0], index=idx)
    inflow = pd.Series([100.0, 0.0, 1000.0, 0.0], index=idx)
    res_twr = pf.twr(v, inflows=inflow)
    res_mwr = pf.mwr(v, inflows=inflow)
    assert res_twr.total == pytest.approx(0.0, abs=1e-12)
    assert res_mwr.annualized and res_mwr.rate < -0.2


def test_twr_missing_value_is_not_zero():
    res = pf.twr(s([1000, np.nan, 1100]), inflows=s([1000, 0, 0]))
    assert res.total is None
    assert any("manquante" in w for w in res.warnings)


def test_twr_missing_first_value_blocks_instead_of_excluding_the_day():
    """Revue : valeur et apport du premier jour non valorisables (taux de change manquant). Le jour suivant a une
    base NaN : il doit donner un rendement NaN et bloquer le TWR, pas être exclu comme « sans capital »."""
    idx = pd.date_range("2024-01-01", periods=4, freq="D")
    res = pf.twr(s([np.nan, np.nan, 1100, 1210], idx), inflows=s([np.nan, 0, 0, 0], idx))
    assert res.total is None and any("manquante" in w for w in res.warnings)
    assert not any("sans capital" in w for w in res.warnings)


def test_twr_period_with_missing_base_value_is_none():
    """Sous-période dont la valeur à la date de base est manquante (apport initial NaN) : TWR None, pas 0."""
    res = pf.twr(s([1000, 1010, 1020]), inflows=s([np.nan, 0, 0]))
    assert res.total is None


def test_mwr_missing_first_inflow_blocks():
    """Revue : premier apport manquant. Avant correction, il était sauté et le TRI valait +1 121 %/an, sans message."""
    idx = pd.date_range("2024-01-01", periods=4, freq="D")
    res = pf.mwr(s([np.nan, np.nan, 1100, 1210], idx), inflows=s([np.nan, 0, 0, 0], idx))
    assert res.rate is None and "manquant" in res.warnings[0]
    assert res.start == date(2024, 1, 1)


def test_twr_flow_without_capital_is_flagged():
    # Dividende reçu après la vente de toute la position (convention titres seuls) :
    # aucun capital la veille, le jour est exclu et signalé.
    res = pf.twr(s([100, 0, 0]), inflows=s([100, 0, 0]), outflows=s([0, 100, 3]))
    assert res.total == pytest.approx(0.0)
    assert len(res.warnings) == 1 and "2024-01-03" in res.warnings[0]


def test_twr_no_capital():
    res = pf.twr(s([0, 0, 0]))
    assert res.total is None and res.days == 0


def test_twr_annualized_over_one_year():
    # 10 % par an sur exactement 730 jours : TWR cumulé 21 %, annualisé 10 %.
    idx = pd.date_range("2023-01-01", periods=730, freq="D")
    daily = 1.21 ** (1 / 730)
    v = pd.Series(1000.0 * daily ** np.arange(1, 731), index=idx)
    inflow = pd.Series(0.0, index=idx)
    inflow.iloc[0] = 1000.0
    res = pf.twr(v, inflows=inflow)
    assert res.total == pytest.approx(0.21)
    assert res.annualized == pytest.approx(0.10)


def test_annualize_total_loss():
    assert pf.annualize(-1.0, 400) == -1.0


def test_xirr_two_deposits_hand_example():
    # -1 000 à t = 0, -1 000 à t = 365 j, +2 310 à t = 730 j.
    # À r = 10 % : 1000 x 1,1^2 + 1000 x 1,1 = 1210 + 1100 = 2310. Donc TRI = 10 %.
    t0 = date(2023, 1, 1)
    dates = [t0, t0 + timedelta(days=365), t0 + timedelta(days=730)]
    assert pf.xirr(dates, [-1000, -1000, 2310]) == pytest.approx(0.10, abs=1e-10)


def test_xirr_one_year():
    # -1 000 puis +1 100 365 jours plus tard : 10 %.
    t0 = date(2023, 1, 1)
    assert pf.xirr([t0, t0 + timedelta(days=365)], [-1000, 1100]) == pytest.approx(0.10)


def test_xirr_large_gain_expands_bracket():
    # x 10 en un an : TRI = 900 %, hors de l'intervalle initial [-1, 1].
    t0 = date(2023, 1, 1)
    assert pf.xirr([t0, t0 + timedelta(days=365)], [-100, 1000]) == pytest.approx(9.0)


@pytest.mark.parametrize("dates,amounts", [
    ([date(2023, 1, 1), date(2024, 1, 1)], [-100, -50]),     # tous négatifs
    ([date(2023, 1, 1), date(2024, 1, 1)], [100, 50]),       # tous positifs
    ([date(2023, 1, 1)], [-100]),                            # un seul flux
    ([date(2023, 1, 1), date(2023, 1, 1)], [-100, 110]),     # une seule date
])
def test_xirr_rejects_degenerate_flows(dates, amounts):
    with pytest.raises(pf.PerformanceError):
        pf.xirr(dates, amounts)


def test_mwr_from_series_matches_hand_example():
    # Même cas que test_xirr_two_deposits_hand_example, à partir des séries.
    # Apports en début des jours 0 et 365 ; valeur de clôture 2 310 au jour 729,
    # datée fin de journée, soit t = 730 j.
    idx = pd.date_range("2023-01-01", periods=730, freq="D")
    v = pd.Series(1.0, index=idx)
    v.iloc[-1] = 2310.0
    inflow = pd.Series(0.0, index=idx)
    inflow.iloc[0], inflow.iloc[365] = 1000.0, 1000.0
    res = pf.mwr(v, inflows=inflow)
    assert res.annualized and res.days == 730
    assert res.rate == pytest.approx(0.10, abs=1e-10)


def test_mwr_under_one_year_is_not_annualized():
    # Apport de 1 000, valeur 1 020 après 100 jours : +2 % sur la période,
    # et non (1,02)^(365/100) - 1 = 7,5 % « par an ».
    idx = pd.date_range("2024-01-01", periods=100, freq="D")
    v = pd.Series(1000.0, index=idx)
    v.iloc[-1] = 1020.0
    inflow = pd.Series(0.0, index=idx)
    inflow.iloc[0] = 1000.0
    res = pf.mwr(v, inflows=inflow)
    assert not res.annualized
    assert res.rate == pytest.approx(0.02, abs=1e-10)


def test_mwr_with_withdrawal():
    # Apport 1 000 (jour 0, t = 0), retrait 1 100 en fin de jour 364 (t = 365), valeur finale 0.
    idx = pd.date_range("2023-01-01", periods=365, freq="D")
    v = pd.Series(1000.0, index=idx)
    v.iloc[-1] = 0.0
    inflow, outflow = pd.Series(0.0, index=idx), pd.Series(0.0, index=idx)
    inflow.iloc[0], outflow.iloc[-1] = 1000.0, 1100.0
    res = pf.mwr(v, inflows=inflow, outflows=outflow)
    assert res.annualized and res.rate == pytest.approx(0.10)


def test_mwr_missing_and_empty():
    assert pf.mwr(s([0, 0, 0])).rate is None
    res = pf.mwr(s([1000, 1010, np.nan]), inflows=s([1000, 0, 0]))
    assert res.rate is None and "manquant" in res.warnings[0]


def test_mwr_reports_solver_failure():
    # Valeur finale nulle sans retrait : aucun flux positif, pas de TRI.
    res = pf.mwr(s([1000, 500, 0]), inflows=s([1000, 0, 0]))
    assert res.rate is None and res.warnings


def test_xirr_without_real_root():
    # 100 - 200 x + 150 x^2, x = 1/(1+r) : discriminant 200^2 - 4 x 150 x 100 < 0, aucune racine.
    t0 = date(2023, 1, 1)
    dates = [t0, t0 + timedelta(days=365), t0 + timedelta(days=730)]
    with pytest.raises(pf.PerformanceError, match="Aucun TRI"):
        pf.xirr(dates, [100, -200, 150])
