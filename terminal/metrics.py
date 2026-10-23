"""
Indicateurs de performance et de risque.

Toutes les fonctions sont pures : elles prennent des pandas Series/DataFrame
et ne font aucun appel réseau. C'est ce qui les rend testables.

Conventions
-----------
- Rendements simples quotidiens : r_t = P_t / P_{t-1} - 1.
- Annualisation sur A = 252 jours de bourse.
- Le taux sans risque est donné en taux annuel effectif, converti en taux
  quotidien par r_f,d = (1 + r_f)^(1/A) - 1.
"""

from __future__ import annotations

import numpy as np
import pandas as pd

TRADING_DAYS = 252


# ---------------------------------------------------------------------------
# Rendements
# ---------------------------------------------------------------------------

def simple_returns(prices: pd.DataFrame | pd.Series) -> pd.DataFrame | pd.Series:
    """r_t = P_t / P_{t-1} - 1. La première ligne (NaN) est supprimée."""
    return prices.pct_change().iloc[1:]


def daily_rf(rf_annual: float, periods: int = TRADING_DAYS) -> float:
    """Convertit un taux annuel effectif en taux par période."""
    return (1.0 + rf_annual) ** (1.0 / periods) - 1.0


def cumulative_index(returns: pd.Series | pd.DataFrame, base: float = 100.0):
    """Indice de richesse : W_t = base * prod_{s<=t} (1 + r_s)."""
    return base * (1.0 + returns).cumprod()


def total_return(returns: pd.Series) -> float:
    """R_total = prod(1 + r_t) - 1."""
    return float((1.0 + returns).prod() - 1.0)


def cagr(returns: pd.Series, periods: int = TRADING_DAYS) -> float:
    """
    Taux de croissance annuel composé.
    CAGR = (1 + R_total)^(A / N) - 1, avec N le nombre de rendements.
    """
    n = returns.count()
    if n == 0:
        return np.nan
    growth = 1.0 + total_return(returns.dropna())
    if growth <= 0:
        return -1.0
    return float(growth ** (periods / n) - 1.0)


# ---------------------------------------------------------------------------
# Risque
# ---------------------------------------------------------------------------

def annual_volatility(returns: pd.Series, periods: int = TRADING_DAYS) -> float:
    """sigma_a = sigma_d * sqrt(A), écart-type d'échantillon (ddof = 1)."""
    return float(returns.std(ddof=1) * np.sqrt(periods))


def downside_deviation(returns: pd.Series, target: float = 0.0,
                       periods: int = TRADING_DAYS) -> float:
    """
    Écart-type de baisse annualisé (semi-déviation sous la cible).
    DD = sqrt( mean( min(r_t - tau, 0)^2 ) ) * sqrt(A)
    """
    shortfall = np.minimum(returns - target, 0.0)
    return float(np.sqrt((shortfall ** 2).mean()) * np.sqrt(periods))


def drawdown_series(returns: pd.Series) -> pd.Series:
    """D_t = W_t / max_{s<=t} W_s - 1, avec W l'indice de richesse."""
    wealth = cumulative_index(returns, base=1.0)
    # On inclut le point de départ W_0 = 1 pour capter une baisse dès le jour 1.
    peak = np.maximum.accumulate(np.maximum(wealth.values, 1.0))
    return pd.Series(wealth.values / peak - 1.0, index=returns.index)


def max_drawdown(returns: pd.Series) -> float:
    """MDD = min_t D_t (valeur négative)."""
    return float(drawdown_series(returns).min())


def historical_var(returns: pd.Series, level: float = 0.95) -> float:
    """VaR historique quotidienne, exprimée comme une perte positive."""
    return float(-np.quantile(returns.dropna(), 1.0 - level))


def historical_cvar(returns: pd.Series, level: float = 0.95) -> float:
    """CVaR (Expected Shortfall) : perte moyenne au-delà de la VaR."""
    r = returns.dropna()
    threshold = np.quantile(r, 1.0 - level)
    return float(-r[r <= threshold].mean())


# ---------------------------------------------------------------------------
# Ratios rendement / risque
# ---------------------------------------------------------------------------

def sharpe_ratio(returns: pd.Series, rf_annual: float = 0.0,
                 periods: int = TRADING_DAYS) -> float:
    """
    S = mean(r_t - r_f,d) / std(r_t - r_f,d) * sqrt(A)
    """
    excess = returns - daily_rf(rf_annual, periods)
    sd = excess.std(ddof=1)
    if sd == 0 or np.isnan(sd):
        return np.nan
    return float(excess.mean() / sd * np.sqrt(periods))


def sortino_ratio(returns: pd.Series, rf_annual: float = 0.0,
                  periods: int = TRADING_DAYS) -> float:
    """
    So = mean(r_t - r_f,d) * A / DD, avec DD calculé sous la cible r_f,d.
    """
    rfd = daily_rf(rf_annual, periods)
    dd = downside_deviation(returns, target=rfd, periods=periods)
    if dd == 0:
        return np.nan
    return float((returns - rfd).mean() * periods / dd)


def calmar_ratio(returns: pd.Series, periods: int = TRADING_DAYS) -> float:
    """Calmar = CAGR / |MDD|."""
    mdd = max_drawdown(returns)
    if mdd == 0:
        return np.nan
    return float(cagr(returns, periods) / abs(mdd))


# ---------------------------------------------------------------------------
# Relatif à un indice de référence
# ---------------------------------------------------------------------------

def beta(returns: pd.Series, bench: pd.Series) -> float:
    """beta = Cov(r_i, r_b) / Var(r_b)."""
    df = pd.concat([returns, bench], axis=1).dropna()
    var_b = df.iloc[:, 1].var(ddof=1)
    if var_b == 0:
        return np.nan
    return float(df.cov(ddof=1).iloc[0, 1] / var_b)


def jensen_alpha(returns: pd.Series, bench: pd.Series, rf_annual: float = 0.0,
                 periods: int = TRADING_DAYS) -> float:
    """
    Alpha de Jensen annualisé (approximation arithmétique) :
    alpha = A * [ mean(r_i - r_f) - beta * mean(r_b - r_f) ]
    """
    rfd = daily_rf(rf_annual, periods)
    b = beta(returns, bench)
    df = pd.concat([returns, bench], axis=1).dropna()
    ex_i = df.iloc[:, 0] - rfd
    ex_b = df.iloc[:, 1] - rfd
    return float(periods * (ex_i.mean() - b * ex_b.mean()))


def tracking_error(returns: pd.Series, bench: pd.Series,
                   periods: int = TRADING_DAYS) -> float:
    """TE = std(r_i - r_b) * sqrt(A)."""
    active = (returns - bench).dropna()
    return float(active.std(ddof=1) * np.sqrt(periods))


def information_ratio(returns: pd.Series, bench: pd.Series,
                      periods: int = TRADING_DAYS) -> float:
    """IR = mean(r_i - r_b) * A / TE."""
    active = (returns - bench).dropna()
    te = active.std(ddof=1) * np.sqrt(periods)
    if te == 0:
        return np.nan
    return float(active.mean() * periods / te)


# ---------------------------------------------------------------------------
# Portefeuille et diversification
# ---------------------------------------------------------------------------

def portfolio_returns(returns: pd.DataFrame, weights: pd.Series) -> pd.Series:
    """
    Rendement d'un portefeuille rééquilibré chaque jour à poids constants :
    r_p,t = sum_i w_i r_i,t.
    Hypothèse forte : sans rééquilibrage, les poids dérivent avec les prix.
    """
    w = weights.reindex(returns.columns).fillna(0.0)
    w = w / w.sum()
    return (returns * w).sum(axis=1).rename("Portefeuille")


def pca_diversification(returns: pd.DataFrame, weights: pd.Series) -> dict:
    """
    Nombre effectif de paris (ENB), version ACP de Meucci (2009).

    Sigma = E Lambda E^T              (décomposition spectrale)
    v_k   = (E^T w)_k^2 * lambda_k     (variance portée par le facteur k)
    p_k   = v_k / sum_j v_j            (part de variance, sum p_k = 1)
    ENB   = exp( - sum_k p_k ln p_k )  (exponentielle de l'entropie)

    ENB vaut 1 si tout le risque vient d'un facteur, N si le risque est
    réparti à parts égales sur N facteurs non corrélés.
    """
    cols = returns.columns
    w = weights.reindex(cols).fillna(0.0).values
    w = w / w.sum()
    cov = returns.cov(ddof=1).values
    eigval, eigvec = np.linalg.eigh(cov)
    order = np.argsort(eigval)[::-1]
    eigval = np.clip(eigval[order], 0.0, None)
    eigvec = eigvec[:, order]

    exposures = eigvec.T @ w
    contrib = exposures ** 2 * eigval
    total = contrib.sum()
    p = contrib / total if total > 0 else np.zeros_like(contrib)
    p_pos = p[p > 1e-12]
    enb = float(np.exp(-(p_pos * np.log(p_pos)).sum()))

    return {
        "enb": enb,
        "n_assets": int(len(cols)),
        "portfolio_variance_share": pd.Series(p, index=[f"PC{i+1}" for i in range(len(p))]),
        "eigenvalue_share": pd.Series(eigval / eigval.sum(),
                                      index=[f"PC{i+1}" for i in range(len(p))]),
        "loadings_pc1": pd.Series(eigvec[:, 0] * np.sign(eigvec[:, 0].sum() or 1.0),
                                  index=cols),
    }


def _sqrtm_sym(a: np.ndarray) -> np.ndarray:
    """Racine carrée d'une matrice symétrique semi-définie positive."""
    val, vec = np.linalg.eigh(a)
    return (vec * np.sqrt(np.clip(val, 0.0, None))) @ vec.T


def _decorrelator(corr: np.ndarray, d: np.ndarray) -> np.ndarray:
    """q = (D C D)^{-1/2} D. Pour tout D diagonal > 0 : q C q^T = I."""
    u = _sqrtm_sym(np.diag(d) @ corr @ np.diag(d))
    return np.linalg.solve(u, np.diag(d))


def minimum_torsion_matrix(cov: np.ndarray) -> np.ndarray:
    """
    Matrice de torsion minimale (Meucci, Santangelo, Deguest, 2015).

    Sur les rendements réduits z = r / sigma, on cherche des facteurs
    g = x z décorrélés et le plus proches possible des z :

        min_x  sum_k Var(g_k - z_k)   sous   x C x^T diagonale.

    Toute solution s'écrit x = diag(s) q(D), q(D) = (D C D)^{-1/2} D.
    À D fixé, l'échelle optimale est s_k = (q C)_kk et l'objectif vaut
    sum_k [1 - (q C)_kk^2]. On maximise donc sum_k (q C)_kk^2 sur D.

    Si les actifs sont déjà décorrélés, x = I : chaque facteur est un actif.
    """
    from scipy.optimize import minimize

    sigma = np.sqrt(np.diag(cov))
    corr = cov / np.outer(sigma, sigma)
    n = len(sigma)

    def objective(log_d: np.ndarray) -> float:
        q = _decorrelator(corr, np.exp(log_d))
        return -float((np.diag(q @ corr) ** 2).sum())

    res = minimize(objective, np.zeros(n), method="L-BFGS-B",
                   options={"maxiter": 2000, "ftol": 1e-14, "gtol": 1e-10})
    q = _decorrelator(corr, np.exp(res.x))
    x = np.diag(np.diag(q @ corr)) @ q
    return np.diag(sigma) @ x @ np.diag(1.0 / sigma)


def minimum_torsion_diversification(returns: pd.DataFrame, weights: pd.Series) -> dict:
    """
    ENB par torsion minimale.

    t      : matrice de torsion, facteurs f = t r décorrélés
    b      = (t^{-1})^T w            expositions du portefeuille aux facteurs
    p_k    = b_k (t Sigma w)_k / (w^T Sigma w)   part de variance du facteur k
    ENB    = exp( - sum_k p_k ln p_k )

    Chaque facteur reste « collé » à un actif : p_k se lit comme la part de
    risque propre de l'actif k, une fois retirées ses corrélations.
    """
    cols = returns.columns
    w = weights.reindex(cols).fillna(0.0).values
    w = w / w.sum()
    cov = returns.cov(ddof=1).values
    t = minimum_torsion_matrix(cov)
    b = np.linalg.solve(t.T, w)
    p = b * (t @ cov @ w) / float(w @ cov @ w)
    p = np.clip(p, 0.0, None)          # erreurs numériques résiduelles
    p = p / p.sum()
    p_pos = p[p > 1e-12]
    enb = float(np.exp(-(p_pos * np.log(p_pos)).sum()))
    return {"enb": enb, "contributions": pd.Series(p, index=cols), "torsion": t}


def risk_contributions(returns: pd.DataFrame, weights: pd.Series) -> pd.Series:
    """
    Contribution de chaque actif à la variance du portefeuille (Euler) :
    RC_i = w_i (Sigma w)_i / (w^T Sigma w),  sum_i RC_i = 1.
    """
    w = weights.reindex(returns.columns).fillna(0.0)
    w = w / w.sum()
    cov = returns.cov(ddof=1)
    marginal = cov.values @ w.values
    var_p = float(w.values @ marginal)
    return pd.Series(w.values * marginal / var_p, index=returns.columns)


# ---------------------------------------------------------------------------
# Séries glissantes
# ---------------------------------------------------------------------------

def rolling_volatility(returns: pd.DataFrame | pd.Series, window: int = 63,
                       periods: int = TRADING_DAYS):
    return returns.rolling(window).std(ddof=1) * np.sqrt(periods)


def rolling_sharpe(returns: pd.DataFrame | pd.Series, window: int = 126,
                   rf_annual: float = 0.0, periods: int = TRADING_DAYS):
    excess = returns - daily_rf(rf_annual, periods)
    return excess.rolling(window).mean() / excess.rolling(window).std(ddof=1) * np.sqrt(periods)


# ---------------------------------------------------------------------------
# Table de synthèse
# ---------------------------------------------------------------------------

def summary_table(returns: pd.DataFrame, bench: pd.Series | None = None,
                  rf_annual: float = 0.0) -> pd.DataFrame:
    """Une ligne par série, une colonne par indicateur."""
    rows = {}
    for name, r in returns.items():
        r = r.dropna()
        row = {
            "Rendement total": total_return(r),
            "CAGR": cagr(r),
            "Volatilité": annual_volatility(r),
            "Sharpe": sharpe_ratio(r, rf_annual),
            "Sortino": sortino_ratio(r, rf_annual),
            "Max drawdown": max_drawdown(r),
            "Calmar": calmar_ratio(r),
            "VaR 95 % (1 j)": historical_var(r),
            "CVaR 95 % (1 j)": historical_cvar(r),
        }
        if bench is not None:
            b = bench.reindex(r.index)
            row.update({
                "Bêta": beta(r, b),
                "Alpha (Jensen)": jensen_alpha(r, b, rf_annual),
                "Tracking error": tracking_error(r, b),
                "Ratio d'information": information_ratio(r, b),
            })
        rows[name] = row
    return pd.DataFrame(rows).T
