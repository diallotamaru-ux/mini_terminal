"""Diversification : résultats connus ou calculés à la main."""

from datetime import date

import numpy as np
import pandas as pd
import pytest

from terminal import diversification as dv
from terminal import metrics as m


def _weekly(cols, t=3000, seed=0, factor=0.0, idio=0.02):
    rng = np.random.default_rng(seed)
    f = rng.normal(0, 0.02, (t, 1)) * factor
    return pd.DataFrame(f + rng.normal(0, idio, (t, len(cols))), columns=cols,
                        index=pd.date_range("2000-01-07", periods=t, freq="W-FRI"))


def _positions(values: dict, account="CTO"):
    return [dv.Position(account, k, v) for k, v in values.items()]


LABELS = {k: k for k in "ABCDEF"}


def test_independent_equal_risk_torsion_enb_is_n():
    w = _weekly(list("ABCD"), t=20_000)
    a = dv.analyze(w, _positions({k: 100.0 for k in "ABCD"}), {}, LABELS, 0.0, method="empirique")
    assert a.enb_mt == pytest.approx(4.0, rel=0.02)
    assert "réparti" in a.text


def test_pca_enb_is_unstable_when_eigenvalues_are_equal():
    # Valeurs propres égales : les vecteurs propres sont arbitraires, l'ENB par ACP aussi (METHODE.md).
    # Sur la covariance exacte (identité), la torsion donne N ; l'ACP dépend de la base choisie.
    cols = list("ABCD")
    cov = pd.DataFrame(np.eye(4) * 1e-4, index=cols, columns=cols)
    w = pd.Series(0.25, index=cols)
    frame = pd.DataFrame(np.zeros((3, 4)), columns=cols)
    assert m.minimum_torsion_diversification(frame, w, cov=cov)["enb"] == pytest.approx(4.0)
    assert 1.0 <= m.pca_diversification(frame, w, cov=cov)["enb"] <= 4.0


def test_common_factor_pca_enb_near_one_and_explained():
    w = _weekly(list("ABCD"), factor=3.0, idio=0.005)
    a = dv.analyze(w, _positions({k: 100.0 for k in "ABCD"}), {}, LABELS, 0.0, method="empirique")
    assert a.enb_pca == pytest.approx(1.0, abs=0.1)
    assert a.pc1_variance_share > 0.9
    assert a.enb_mt > 2 * a.enb_pca                                 # torsion aveugle au facteur, poids égaux
    assert a.text.startswith("Un facteur commun domine")
    assert (a.pc1_loadings > 0).all()


def test_euler_contributions_sum_to_one_by_line_account_and_class():
    w = _weekly(list("ABC"), factor=1.0)
    pos = [dv.Position("PEA", "A", 300.0), dv.Position("CTO", "A", 700.0),
           dv.Position("CTO", "B", 500.0), dv.Position("Crypto", "C", 500.0)]
    a = dv.analyze(w, pos, {"A": "etf", "B": "action", "C": "crypto"}, LABELS, 0.0)
    assert a.risk_contrib.sum() == pytest.approx(1.0)
    assert a.group_contrib["compte"].sum() == pytest.approx(1.0)
    assert a.group_contrib["classe"].sum() == pytest.approx(1.0)
    # Ligne A répartie 30 / 70 entre PEA et CTO : sa contribution se répartit exactement dans la même proportion.
    a_pea = a.group_contrib["compte"]["PEA"]
    a_cto_part = a.group_contrib["compte"]["CTO"] - (a.risk_contrib["B"])
    assert a_pea / (a_pea + a_cto_part) == pytest.approx(0.3)
    assert a.group_contrib["classe"]["etf"] == pytest.approx(a.risk_contrib["A"])
    assert a.weights.to_dict() == pytest.approx({"A": 0.5, "B": 0.25, "C": 0.25})


def test_real_weights_and_total_volatility_with_cash():
    # 9 000 € de titres, 1 000 € d'espèces : part d'espèces 10 %, sigma_total = 0,9 x sigma_risqué.
    w = _weekly(list("AB"))
    a = dv.analyze(w, _positions({"A": 6000.0, "B": 3000.0}), {}, LABELS, cash_eur=1000.0)
    assert a.cash_share == pytest.approx(0.1)
    assert a.sigma_total == pytest.approx(0.9 * a.sigma_risky)
    wt = a.weights.to_numpy()
    assert a.sigma_risky == pytest.approx(np.sqrt(wt @ a.estimate.cov.to_numpy() @ wt * 52))
    assert a.weights["A"] == pytest.approx(2 / 3)


def test_short_lines_excluded_partial_lines_kept_without_shrinking_window():
    w = _weekly(list("ABC"), t=150)
    w.iloc[:120, 1] = np.nan          # B : 30 semaines -> exclue
    w.iloc[:80, 2] = np.nan           # C : 70 semaines -> gardée, partielle
    kept, excluded = dv.select_lines(w, LABELS)
    assert kept == ["A", "C"]
    assert excluded[0].key == "B" and excluded[0].n_weeks == 30 and "minimum 52" in excluded[0].reason
    a = dv.analyze(w[kept], _positions({"A": 1.0, "C": 1.0}), {}, LABELS, 0.0)
    assert a.estimate.t_max == 150 and a.estimate.t_min == 70       # la fenêtre de A n'est pas réduite
    assert not w[kept].isna().all().any()


def test_new_weights_hand_example():
    w = pd.Series({"A": 0.5, "B": 0.5})
    # Argent frais 25 % : A = (0,5 + 0,25) / 1,25 = 0,6 ; B = 0,5 / 1,25 = 0,4.
    assert dv.new_weights(w, "A", 0.25, "frais").to_dict() == pytest.approx({"A": 0.6, "B": 0.4})
    # Réallocation 25 % : A = 0,75 x 0,5 + 0,25 = 0,625 ; B = 0,375.
    assert dv.new_weights(w, "A", 0.25, "realloc").to_dict() == pytest.approx({"A": 0.625, "B": 0.375})
    # Nouveau ticker C, argent frais 25 % : C = 0,25 / 1,25 = 0,2 ; A = B = 0,4.
    assert dv.new_weights(w, "C", 0.25, "frais").to_dict() == pytest.approx({"A": 0.4, "B": 0.4, "C": 0.2})
    for bad in [("A", -0.1, "frais"), ("A", 1.5, "realloc"), ("A", 0.1, "vente")]:
        with pytest.raises(ValueError):
            dv.new_weights(w, *bad)


@pytest.mark.parametrize("mode", ["frais", "realloc"])
def test_adding_zero_changes_nothing(mode):
    weekly = _weekly(list("ABCD"), t=200, factor=1.0)
    daily = _weekly(list("ABCD"), t=1000, seed=1, factor=1.0)
    w = pd.Series({"A": 0.4, "B": 0.3, "C": 0.2, "D": 0.1})
    before, after, _ = dv.simulate(weekly, daily, w, "B", 0.0, mode, "lw_cc", cash_share=0.1)
    assert after.enb_pca == pytest.approx(before.enb_pca) and after.enb_mt == pytest.approx(before.enb_mt)
    assert after.sigma_risky == pytest.approx(before.sigma_risky) and after.sigma_total == pytest.approx(before.sigma_total)
    assert after.max_drawdown == pytest.approx(before.max_drawdown)
    pd.testing.assert_series_equal(after.risk_contrib, before.risk_contrib)


def test_simulation_changes_weights_and_dilutes_cash():
    weekly = _weekly(list("ABC"), t=200, factor=1.0)
    daily = _weekly(list("ABC"), t=500, seed=2, factor=1.0)
    w = pd.Series({"A": 0.5, "B": 0.5})                              # C : nouveau ticker
    before, after, est = dv.simulate(weekly, daily, w, "C", 0.25, "frais", "lw_cc", cash_share=0.1)
    assert before.weights["C"] == 0.0 and after.weights["C"] == pytest.approx(0.2)
    # Espèces : e' = 0,1 / (1 + 0,25 x 0,9) = 0,081633.
    assert after.sigma_total == pytest.approx((1 - 0.1 / 1.225) * after.sigma_risky)
    assert after.risk_contrib.sum() == pytest.approx(1.0) and after.risk_contrib["C"] > 0
    # Drawdown à poids constants : identique au calcul direct de metrics.
    expected = m.max_drawdown(m.portfolio_returns(daily[["A", "B", "C"]], after.weights))
    assert after.max_drawdown == pytest.approx(expected)


def test_concentrated_text_and_line_returns():
    w = _weekly(list("ABCDEF"), seed=3)
    a = dv.analyze(w, _positions({"A": 95.0, "B": 1, "C": 1, "D": 1, "E": 1, "F": 1}), {}, LABELS, 0.0)
    assert a.text.startswith("Le risque est concentré") and "A (" in a.text
    # line_returns : clôtures x change, puis semaines.
    idx = pd.bdate_range("2025-01-02", "2025-01-17")
    closes = pd.Series(np.linspace(100, 110, len(idx)), index=idx)
    fx = pd.Series(0.9, index=idx)
    daily, weekly = dv.line_returns(closes, fx, idx[1:], date(2025, 1, 2))
    assert daily.iloc[0] == pytest.approx(closes.iloc[1] / closes.iloc[0] - 1)
    assert weekly.iloc[-1] == pytest.approx(closes.iloc[-1] / closes.loc["2025-01-10"] - 1)


def test_no_value_raises():
    with pytest.raises(ValueError):
        dv.analyze(_weekly(list("AB")), [], {}, LABELS, 0.0)
