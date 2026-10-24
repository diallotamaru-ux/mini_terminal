"""
Estimation de la covariance des rendements (hebdomadaires) des lignes.

Les lignes n'ont pas toutes le même historique de cours. Pour qu'une ligne
récente ne réduise pas la fenêtre des autres, chaque élément est estimé sur les
semaines communes aux deux lignes (covariance par paires). Une telle matrice
peut ne pas être semi-définie positive : sa matrice de corrélation est alors
remplacée par la matrice de corrélation la plus proche (Higham, 2002), et
l'ampleur de la correction est mesurée (garde-fou).

Trois estimateurs :
- « empirique » : covariance par paires (égale à la covariance empirique
  quand aucune donnée ne manque) ;
- « lw_cc » : Ledoit et Wolf (2004, « Honey, I Shrunk the Sample Covariance
  Matrix »), contraction vers une cible à corrélation constante ;
- « lw_id » : Ledoit et Wolf (2004, « A Well-Conditioned Estimator for
  Large-Dimensional Covariance Matrices »), contraction vers l'identité
  réduite. Cette cible tire les corrélations vers zéro : l'ENB est gonflé
  quand un facteur commun existe.

Avec des données manquantes, les moments de Ledoit-Wolf sont calculés par
paires et l'intensité utilise T_min, le plus petit nombre de semaines communes
(choix prudent : moins de données, plus de contraction). Sans donnée manquante,
on retrouve exactement les formules publiées.
"""

from __future__ import annotations

from dataclasses import dataclass

import numpy as np
import pandas as pd

ESTIMATORS = ("lw_cc", "lw_id", "empirique")
ESTIMATOR_LABELS = {"lw_cc": "Ledoit-Wolf, cible à corrélation constante",
                    "lw_id": "Ledoit-Wolf, cible identité réduite",
                    "empirique": "Covariance empirique"}


# ---------------------------------------------------------------------------
# Covariance par paires et matrice de corrélation la plus proche
# ---------------------------------------------------------------------------

def overlap_counts(x: pd.DataFrame) -> pd.DataFrame:
    """Nombre de semaines communes à chaque paire de lignes."""
    m = x.notna().astype(int)
    return m.T @ m


def pairwise_cov(x: pd.DataFrame) -> pd.DataFrame:
    """Covariance par paires (ddof = 1) : sans donnée manquante, c'est la covariance empirique."""
    return x.cov(min_periods=2, ddof=1)


def nearest_correlation(a: np.ndarray, tol: float = 1e-10, max_iter: int = 2000,
                        eig_floor: float = 1e-10) -> np.ndarray:
    """
    Matrice de corrélation la plus proche de `a` en norme de Frobenius
    (Higham, 2002) : projections alternées sur les matrices semi-définies
    positives et sur les matrices de diagonale unité, avec la correction de
    Dykstra. Les valeurs propres sont maintenues au-dessus de `eig_floor`
    pour que la matrice reste inversible (torsion minimale).
    """
    y = np.array(a, dtype=float)
    ds = np.zeros_like(y)
    for _ in range(max_iter):
        r = y - ds
        val, vec = np.linalg.eigh((r + r.T) / 2.0)
        x = (vec * np.maximum(val, eig_floor)) @ vec.T
        ds = x - r
        y_old = y
        y = x.copy()
        np.fill_diagonal(y, 1.0)
        if np.linalg.norm(y - y_old, "fro") <= tol * max(1.0, np.linalg.norm(y, "fro")):
            break
    return (y + y.T) / 2.0


@dataclass
class Repair:
    applied: bool
    frobenius_rel: float          # ||C~ - C||_F / ||C||_F sur les corrélations
    max_corr_change: float        # plus grande variation d'un coefficient de corrélation
    threshold: float              # 1 / sqrt(T_min) : erreur-type d'une corrélation
    warning: bool


def repair_psd(cov: pd.DataFrame, t_min: int) -> tuple[pd.DataFrame, Repair]:
    """Rend la covariance semi-définie positive si nécessaire, et mesure la correction."""
    sd = np.sqrt(np.diag(cov.values))
    corr = cov.values / np.outer(sd, sd)
    threshold = 1.0 / np.sqrt(max(t_min, 1))
    if np.linalg.eigvalsh(corr).min() >= -1e-12:
        return cov, Repair(False, 0.0, 0.0, float(threshold), False)
    fixed = nearest_correlation(corr)
    diff = fixed - corr
    info = Repair(True, float(np.linalg.norm(diff, "fro") / np.linalg.norm(corr, "fro")),
                  float(np.abs(diff).max()), float(threshold), bool(np.abs(diff).max() > threshold))
    return pd.DataFrame(fixed * np.outer(sd, sd), index=cov.index, columns=cov.columns), info


# ---------------------------------------------------------------------------
# Ledoit-Wolf, moments par paires
# ---------------------------------------------------------------------------

def _moments(x: pd.DataFrame):
    """
    Rendements centrés (moyenne de chaque ligne sur ses propres semaines), puis,
    pour chaque paire, sur les semaines communes :
    S_ij  = moyenne(y_i y_j)                      (convention 1/T de Ledoit-Wolf)
    pi_ij = moyenne((y_i y_j - S_ij)^2)
    th_ij = moyenne((y_i^2 - S_ii)(y_i y_j - S_ij))
    """
    y = (x - x.mean()).to_numpy(dtype=float)
    mask = ~np.isnan(y)
    y0 = np.where(mask, y, 0.0)
    m = mask.astype(float)
    n = m.T @ m
    s = (y0.T @ y0) / n
    p2 = ((y0 ** 2).T @ (y0 ** 2)) / n                       # moyenne(y_i^2 y_j^2)
    pi = p2 - s ** 2
    t1 = ((y0 ** 3).T @ y0) / n                               # moyenne(y_i^3 y_j)
    yi2 = ((y0 ** 2).T @ m) / n                                # moyenne(y_i^2) sur l'intersection (i, j)
    # E[(y_i^2 - S_ii)(y_i y_j - S_ij)] = E[y_i^3 y_j] - S_ij E[y_i^2] sur l'intersection ;
    # sans donnée manquante, E[y_i^2] = S_ii : formule publiée.
    th = t1 - s * yi2
    return s, pi, th, n


@dataclass
class CovEstimate:
    cov: pd.DataFrame              # covariance hebdomadaire retenue
    method: str
    shrinkage: float | None        # intensité de contraction, dans [0, 1]
    repair: Repair
    t_min: int
    t_max: int


def ledoit_wolf(x: pd.DataFrame, target: str = "cc") -> tuple[pd.DataFrame, float, pd.DataFrame]:
    """
    Covariance contractée de Ledoit-Wolf. Renvoie (covariance, intensité,
    covariance d'échantillon S en convention 1/T avant contraction).
    """
    s, pi, th, n = _moments(x)
    t = int(n.min())
    f = _target(s, target)
    # Échelle de comparaison : en deçà, l'échantillon est déjà la cible (arrondis).
    tiny = 1e-14 * float((s ** 2).sum())
    if target == "cc":
        sd = np.sqrt(np.diag(s))
        rbar = _rbar(s)
        pi_hat = pi.sum()
        off = th.copy()
        np.fill_diagonal(off, 0.0)
        rho_hat = np.trace(pi) + rbar * ((sd[None, :] / sd[:, None]) * off).sum()
        gamma = ((f - s) ** 2).sum()
        delta = 0.0 if gamma <= tiny else max(0.0, min(1.0, (pi_hat - rho_hat) / gamma / t))
    elif target == "id":
        d2 = ((s - f) ** 2).sum()
        b2_bar = pi.sum() / t
        delta = 0.0 if d2 <= tiny else min(b2_bar, d2) / d2
    cols = x.columns
    s_df = pd.DataFrame(s, index=cols, columns=cols)
    return shrink(s_df, target, delta), float(delta), s_df


def estimate(x: pd.DataFrame, method: str = "lw_cc") -> CovEstimate:
    """
    Covariance des colonnes de `x` (rendements hebdomadaires, NaN hors historique).
    Ordre : moments par paires, projection de Higham si nécessaire, puis contraction.
    """
    if method not in ESTIMATORS:
        raise ValueError(f"Estimateur inconnu : {method}")
    n = overlap_counts(x).to_numpy()
    t_min, t_max = int(n.min()), int(np.diag(n).max())
    if method == "empirique":
        cov, rep = repair_psd(pairwise_cov(x), t_min)
        return CovEstimate(cov, method, None, rep, t_min, t_max)
    target = "cc" if method == "lw_cc" else "id"
    _, delta, s = ledoit_wolf(x, target)
    # L'intensité vient des moments par paires ; la contraction s'applique à
    # l'échantillon rendu semi-défini positif, vers la même cible.
    s_fixed, rep = repair_psd(s, t_min)
    return CovEstimate(shrink(s_fixed, target, delta), method, delta, rep, t_min, t_max)


def _rbar(s: np.ndarray) -> float:
    """Corrélation moyenne hors diagonale."""
    k = s.shape[0]
    if k < 2:
        return 0.0
    sd = np.sqrt(np.diag(s))
    return float(((s / np.outer(sd, sd)).sum() - k) / (k * (k - 1)))


def _target(s: np.ndarray, target: str) -> np.ndarray:
    """Cible : corrélation constante (variances conservées) ou identité réduite (trace conservée)."""
    if target == "cc":
        sd = np.sqrt(np.diag(s))
        f = _rbar(s) * np.outer(sd, sd)
        np.fill_diagonal(f, np.diag(s))
        return f
    if target == "id":
        return np.trace(s) / s.shape[0] * np.eye(s.shape[0])
    raise ValueError(f"Cible inconnue : {target}")


def shrink(s: pd.DataFrame, target: str, delta: float) -> pd.DataFrame:
    """delta x F + (1 - delta) x S."""
    v = s.to_numpy()
    return pd.DataFrame(delta * _target(v, target) + (1.0 - delta) * v, index=s.index, columns=s.columns)


def correlation(cov: pd.DataFrame) -> pd.DataFrame:
    sd = np.sqrt(np.diag(cov.values))
    return pd.DataFrame(cov.values / np.outer(sd, sd), index=cov.index, columns=cov.columns)
