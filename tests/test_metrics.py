"""
Tests sur des cas dont la réponse est connue analytiquement.
Un indicateur faux mais plausible est le pire bug possible en finance :
il ne plante pas, il trompe. D'où ces tests.
"""

import numpy as np
import pandas as pd
import pytest

from terminal import metrics as m

IDX = pd.bdate_range("2020-01-01", periods=253)


def test_constant_return_cagr():
    # 252 rendements identiques de r => croissance annuelle exacte (1+r)^252 - 1
    r = pd.Series(0.001, index=IDX[1:])
    assert m.cagr(r) == pytest.approx(1.001 ** 252 - 1, rel=1e-12)


def test_total_return_round_trip():
    # +10 % puis -10 % ne ramène pas au point de départ : 1.1 * 0.9 = 0.99
    r = pd.Series([0.10, -0.10])
    assert m.total_return(r) == pytest.approx(-0.01)


def test_volatility_scaling():
    rng = np.random.default_rng(0)
    r = pd.Series(rng.normal(0, 0.01, 200_000))
    assert m.annual_volatility(r) == pytest.approx(0.01 * np.sqrt(252), rel=0.01)


def test_sharpe_known_value():
    # Série standardisée exactement : moyenne mu, écart-type sigma.
    # Sharpe = mu / sigma * sqrt(252), sans bruit d'estimation.
    rng = np.random.default_rng(1)
    mu, sigma = 0.0005, 0.01
    z = rng.normal(size=1000)
    z = (z - z.mean()) / z.std(ddof=1)
    r = pd.Series(mu + sigma * z)
    assert m.sharpe_ratio(r) == pytest.approx(mu / sigma * np.sqrt(252), rel=1e-12)


def test_daily_rf_compounds_back():
    assert (1 + m.daily_rf(0.03)) ** 252 == pytest.approx(1.03)


def test_max_drawdown_simple_path():
    # Prix : 100 -> 120 -> 60 -> 90. Plus haut 120, plus bas ensuite 60 => -50 %
    p = pd.Series([100, 120, 60, 90], dtype=float)
    r = p.pct_change().dropna()
    assert m.max_drawdown(r) == pytest.approx(-0.5)


def test_drawdown_on_first_day():
    # Une baisse dès le premier jour doit être captée (plus haut = point de départ)
    r = pd.Series([-0.2, 0.05])
    assert m.max_drawdown(r) == pytest.approx(-0.2)


def test_beta_of_leveraged_copy():
    rng = np.random.default_rng(2)
    b = pd.Series(rng.normal(0, 0.01, 5000))
    assert m.beta(2 * b, b) == pytest.approx(2.0)
    assert m.beta(b, b) == pytest.approx(1.0)


def test_information_ratio_zero_for_identical():
    rng = np.random.default_rng(3)
    b = pd.Series(rng.normal(0, 0.01, 1000))
    noise = pd.Series(rng.normal(0, 1e-4, 1000))
    assert abs(m.information_ratio(b + noise - noise.mean(), b)) < 1e-9


def test_enb_single_factor_is_one():
    # Deux actifs parfaitement corrélés : un seul pari
    rng = np.random.default_rng(4)
    f = rng.normal(0, 0.01, 2000)
    df = pd.DataFrame({"A": f, "B": 1.5 * f})
    res = m.pca_diversification(df, pd.Series({"A": 0.5, "B": 0.5}))
    assert res["enb"] == pytest.approx(1.0, abs=1e-6)


def test_mt_enb_independent_equal_risk_is_n():
    # N actifs indépendants, même volatilité, poids égaux => ENB = N
    rng = np.random.default_rng(5)
    df = pd.DataFrame(rng.normal(0, 0.01, (200_000, 4)), columns=list("ABCD"))
    res = m.minimum_torsion_diversification(df, pd.Series(1.0, index=df.columns))
    assert res["enb"] == pytest.approx(4.0, rel=0.01)


def test_pca_enb_detects_common_factor():
    # Quatre actifs pilotés par un même facteur : l'ACP voit un seul pari
    rng = np.random.default_rng(8)
    f = rng.normal(0, 0.01, (20_000, 1))
    df = pd.DataFrame(f * np.array([1, 1.2, 0.9, 1.1]) + rng.normal(0, 0.002, (20_000, 4)),
                      columns=list("ABCD"))
    res = m.pca_diversification(df, pd.Series(1.0, index=df.columns))
    assert res["enb"] == pytest.approx(1.0, abs=0.05)


def test_torsion_decorrelates_exactly():
    rng = np.random.default_rng(9)
    a = rng.normal(size=(5, 5))
    cov = a @ a.T / 5 + np.diag(rng.uniform(0.1, 0.5, 5))
    t = m.minimum_torsion_matrix(cov)
    f = t @ cov @ t.T
    assert np.abs(f - np.diag(np.diag(f))).max() < 1e-8


def test_torsion_is_identity_for_uncorrelated_assets():
    t = m.minimum_torsion_matrix(np.diag([1.0, 4.0, 9.0]))
    assert np.allclose(t, np.eye(3), atol=1e-6)


def test_torsion_beats_riccati_root():
    # L'optimum doit être au moins aussi proche des actifs que la solution
    # approchée x = C^{-1/2} (racine de Riccati).
    rng = np.random.default_rng(10)
    a = rng.normal(size=(6, 6))
    cov = a @ a.T / 6 + np.diag(rng.uniform(0.1, 0.5, 6))
    s = np.sqrt(np.diag(cov))
    c = cov / np.outer(s, s)
    def dist(x):
        e = x - np.eye(6)
        return np.trace(e @ c @ e.T)
    x_mt = np.diag(1 / s) @ m.minimum_torsion_matrix(cov) @ np.diag(s)
    x_ric = np.linalg.inv(m._sqrtm_sym(c))
    assert dist(x_mt) <= dist(x_ric) + 1e-10


def test_risk_contributions_sum_to_one():
    rng = np.random.default_rng(6)
    df = pd.DataFrame(rng.normal(0, 0.01, (3000, 3)), columns=list("XYZ"))
    rc = m.risk_contributions(df, pd.Series({"X": 0.5, "Y": 0.3, "Z": 0.2}))
    assert rc.sum() == pytest.approx(1.0)


def test_portfolio_weights_normalised():
    df = pd.DataFrame({"A": [0.01, 0.02], "B": [0.03, -0.01]})
    p = m.portfolio_returns(df, pd.Series({"A": 1.0, "B": 3.0}))
    assert p.iloc[0] == pytest.approx(0.25 * 0.01 + 0.75 * 0.03)


def test_var_cvar_ordering():
    rng = np.random.default_rng(7)
    r = pd.Series(rng.standard_t(4, 50_000) * 0.01)
    assert m.historical_cvar(r) >= m.historical_var(r) > 0
