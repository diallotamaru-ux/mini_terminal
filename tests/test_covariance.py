"""Covariance par paires, matrice de corrélation la plus proche (Higham), Ledoit-Wolf."""

import numpy as np
import pandas as pd
import pytest

from terminal import covariance as cv


def _data(t=150, n=6, seed=0, missing=False):
    rng = np.random.default_rng(seed)
    f = rng.normal(0, 0.02, (t, 1))
    x = pd.DataFrame(f * rng.uniform(0.5, 1.5, n) + rng.normal(0, 0.015, (t, n)),
                     columns=[f"L{i}" for i in range(n)])
    if missing:
        x.iloc[:60, 0] = np.nan             # ligne récente : 90 semaines
        x.iloc[100:, 1] = np.nan            # ligne au cours interrompu : 100 semaines
    return x


# --- Ledoit-Wolf de référence, transcrit des articles (aucune donnée manquante) ---

def _lw_cc_reference(x):
    """Ledoit et Wolf (2004, « Honey »), notations de l'article."""
    y = x.to_numpy() - x.to_numpy().mean(0)
    t, n = y.shape
    s = y.T @ y / t
    var = np.diag(s)
    sd = np.sqrt(var)
    rbar = ((s / np.outer(sd, sd)).sum() - n) / (n * (n - 1))
    f = rbar * np.outer(sd, sd)
    np.fill_diagonal(f, var)
    pi_mat = (y ** 2).T @ (y ** 2) / t - s ** 2
    theta = (y ** 3).T @ y / t - var[:, None] * s
    np.fill_diagonal(theta, 0)
    rho = np.trace(pi_mat) + rbar * (np.outer(1 / sd, sd) * theta).sum()
    gamma = ((f - s) ** 2).sum()
    delta = max(0, min(1, (pi_mat.sum() - rho) / gamma / t))
    return delta * f + (1 - delta) * s, delta


def _lw_id_reference(x):
    """Ledoit et Wolf (2004, JMVA) : cible m I, b^2 = (1/T^2) sum_t ||y_t y_t' - S||^2."""
    y = x.to_numpy() - x.to_numpy().mean(0)
    t, n = y.shape
    s = y.T @ y / t
    m = np.trace(s) / n
    d2 = ((s - m * np.eye(n)) ** 2).sum()
    b2 = sum(((np.outer(r, r) - s) ** 2).sum() for r in y) / t ** 2
    delta = min(b2, d2) / d2
    return delta * m * np.eye(n) + (1 - delta) * s, delta


def test_pairwise_without_missing_is_sample_covariance():
    x = _data()
    pd.testing.assert_frame_equal(cv.pairwise_cov(x), x.cov())
    e = cv.estimate(x, "empirique")
    pd.testing.assert_frame_equal(e.cov, x.cov())
    assert e.t_min == e.t_max == 150 and not e.repair.applied and e.shrinkage is None


def test_pairwise_uses_common_weeks_only():
    x = _data(missing=True)
    c = cv.pairwise_cov(x)
    assert c.loc["L0", "L1"] == pytest.approx(x[["L0", "L1"]].dropna().cov().iloc[0, 1])
    n = cv.overlap_counts(x)
    assert n.loc["L0", "L0"] == 90 and n.loc["L1", "L1"] == 100 and n.loc["L0", "L1"] == 40


@pytest.mark.parametrize("method,ref", [("lw_cc", _lw_cc_reference), ("lw_id", _lw_id_reference)])
def test_ledoit_wolf_matches_published_formulas(method, ref):
    x = _data(seed=3)
    cov, delta, _ = cv.ledoit_wolf(x, "cc" if method == "lw_cc" else "id")
    r_cov, r_delta = ref(x)
    assert delta == pytest.approx(r_delta, rel=1e-10)
    np.testing.assert_allclose(cov.to_numpy(), r_cov, rtol=1e-10)
    e = cv.estimate(x, method)
    np.testing.assert_allclose(e.cov.to_numpy(), r_cov, rtol=1e-10)


@pytest.mark.parametrize("method", ["lw_cc", "lw_id", "empirique"])
@pytest.mark.parametrize("missing", [False, True])
def test_shrinkage_intensity_in_unit_interval_and_positive_definite(method, missing):
    for seed in range(5):
        e = cv.estimate(_data(seed=seed, missing=missing), method)
        if method != "empirique":
            assert 0.0 <= e.shrinkage <= 1.0
        assert np.linalg.eigvalsh(e.cov.to_numpy()).min() > 0


def test_no_shrinkage_when_sample_is_already_the_target():
    # Colonnes orthogonales de même norme : S = m I exactement -> la cible identité ne change rien.
    h = np.array([[1, 1, 1, 1], [1, -1, 1, -1], [1, 1, -1, -1], [1, -1, -1, 1]], dtype=float)
    x = pd.DataFrame(np.vstack([h, -h]), columns=list("ABCD"))
    _, delta, s = cv.ledoit_wolf(x, "id")
    assert delta == 0.0 and np.allclose(s.to_numpy(), np.eye(4))
    _, delta_cc, _ = cv.ledoit_wolf(x, "cc")          # corrélations toutes nulles : déjà constantes
    assert delta_cc == 0.0


def test_identity_target_pulls_correlations_to_zero():
    # Un facteur commun fort : la cible identité réduit la corrélation moyenne, la cible
    # à corrélation constante la conserve.
    x = _data(t=60, n=10, seed=4)
    corr = lambda c: cv.correlation(c).to_numpy()[np.triu_indices(10, 1)].mean()
    base = corr(x.cov())
    assert corr(cv.estimate(x, "lw_id").cov) < base
    assert corr(cv.estimate(x, "lw_cc").cov) == pytest.approx(base, abs=0.02)


def test_higham_published_example():
    # Higham (2002), exemple de la section 4 : matrice [[1,1,0],[1,1,1],[0,1,1]].
    a = np.array([[1.0, 1.0, 0.0], [1.0, 1.0, 1.0], [0.0, 1.0, 1.0]])
    x = cv.nearest_correlation(a, eig_floor=0.0)
    expected = np.array([[1.0, 0.7607, 0.1573], [0.7607, 1.0, 0.7607], [0.1573, 0.7607, 1.0]])
    np.testing.assert_allclose(x, expected, atol=1e-4)


def test_repair_leaves_valid_matrix_and_flags_large_corrections():
    good = pd.DataFrame(np.eye(3) * 4.0, index=list("ABC"), columns=list("ABC"))
    fixed, info = cv.repair_psd(good, t_min=52)
    assert not info.applied and fixed is good and info.threshold == pytest.approx(1 / np.sqrt(52))
    # Corrélations incohérentes (A~B et B~C très liées, A et C opposées) : correction forte, avertissement.
    bad = pd.DataFrame([[1.0, 0.9, -0.9], [0.9, 1.0, 0.9], [-0.9, 0.9, 1.0]], index=list("ABC"), columns=list("ABC"))
    fixed, info = cv.repair_psd(bad * 4.0, t_min=52)
    assert info.applied and info.warning and info.max_corr_change > info.threshold
    assert np.linalg.eigvalsh(fixed.to_numpy()).min() > 0
    np.testing.assert_allclose(np.diag(fixed.to_numpy()), 4.0)                # variances conservées
    # Incohérence légère : correction inférieure à l'erreur-type, pas d'avertissement.
    mild = pd.DataFrame([[1.0, 0.7, 0.0], [0.7, 1.0, 0.72], [0.0, 0.72, 1.0]], index=list("ABC"), columns=list("ABC"))
    if np.linalg.eigvalsh(mild.to_numpy()).min() < 0:
        _, info = cv.repair_psd(mild, t_min=52)
        assert info.applied and not info.warning


def test_unknown_estimator():
    with pytest.raises(ValueError):
        cv.estimate(_data(), "oas")
    with pytest.raises(ValueError):
        cv.shrink(_data().cov(), "xyz", 0.5)
