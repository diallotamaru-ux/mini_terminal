"""
Diversification réelle du portefeuille.

Poids : valeurs de marché en EUR à la date de valorisation (poids réels, pas de
poids constants), espèces exclues puis renormalisés sur les lignes risquées.
La part d'espèces sert à la volatilité totale : sigma_total = (1 - e) x sigma_risqué,
les espèces ayant une variance nulle.

Données : rendements HEBDOMADAIRES en EUR de chaque ligne (titre regroupé sur tous
les comptes), sur la fenêtre de la période choisie. Une ligne avec moins de
MIN_WEEKS semaines de cours est exclue et signalée ; une ligne partielle (au moins
MIN_WEEKS semaines) est gardée sans réduire la fenêtre des autres (covariance par
paires, voir covariance.py). Aucune valeur n'est inventée.

Mesures : celles de metrics.py (risk_contributions, pca_diversification,
minimum_torsion_diversification), appliquées à la covariance estimée.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import date

import numpy as np
import pandas as pd

from . import covariance as cv
from . import metrics as m
from .benchmark import to_eur
from .errors import TerminalError
from .risk import index_returns, to_weekly

class DiversificationError(TerminalError):
    pass


MIN_WEEKS = 52          # un an : erreur-type d'une corrélation ~ (1 - rho^2) / sqrt(52) = 0,14 pour rho = 0
WEEKS_PER_YEAR = 52


# ---------------------------------------------------------------------------
# Données
# ---------------------------------------------------------------------------

def line_returns(closes: pd.Series, fx: pd.Series | None, grid: pd.DatetimeIndex,
                 base: date) -> tuple[pd.Series, pd.Series]:
    """
    Rendements d'une ligne en EUR : (quotidiens sur la grille de jours ouvrés,
    hebdomadaires). Clôtures du fournisseur x taux du jour ; NaN hors historique.
    """
    daily = index_returns(to_eur(closes, fx), grid, base)
    weekly, _ = to_weekly(daily)
    return daily, weekly


@dataclass
class Excluded:
    key: str
    label: str
    n_weeks: int
    reason: str


def select_lines(weekly: pd.DataFrame, labels: dict[str, str],
                 min_weeks: int = MIN_WEEKS) -> tuple[list[str], list[Excluded]]:
    """Lignes gardées (au moins `min_weeks` semaines de cours) et lignes exclues, avec la raison."""
    kept, excluded = [], []
    for k in weekly.columns:
        n = int(weekly[k].notna().sum())
        if n >= min_weeks:
            kept.append(k)
        else:
            excluded.append(Excluded(k, labels.get(k, k), n,
                                     f"{n} semaines de cours sur la période (minimum {min_weeks})"))
    return kept, excluded


# ---------------------------------------------------------------------------
# Analyse
# ---------------------------------------------------------------------------

@dataclass
class Position:
    account: str                 # nom du compte
    line: str                    # clé de la ligne (ISIN, sinon ticker)
    value_eur: float


@dataclass
class Analysis:
    lines: list[str]
    weights: pd.Series                       # poids sur les lignes risquées (somme 1)
    estimate: cv.CovEstimate
    corr: pd.DataFrame
    risk_contrib: pd.Series                  # Euler, par ligne, somme 1
    group_contrib: dict[str, pd.Series]      # « compte », « classe »
    group_weights: dict[str, pd.Series]
    enb_pca: float
    enb_mt: float
    pc1_variance_share: float                # part de la variance du portefeuille portée par le 1er facteur
    pc1_eigen_share: float                   # part de la 1re valeur propre dans la variance totale
    pc1_loadings: pd.Series                  # composantes du 1er facteur (signe : somme positive)
    mt_contrib: pd.Series                    # contributions de torsion par ligne
    sigma_risky: float                       # volatilité annualisée des lignes risquées
    sigma_total: float                       # espèces comprises
    cash_share: float
    text: str
    notes: list[str] = field(default_factory=list)


def _measures(weekly: pd.DataFrame, w: pd.Series, cov: pd.DataFrame) -> dict:
    """Mesures de metrics.py sur une covariance donnée. Les rendements ne servent qu'aux noms de colonnes."""
    cols = list(w.index)
    frame = weekly[cols]
    pca = m.pca_diversification(frame, w, cov=cov)
    mt = m.minimum_torsion_diversification(frame, w, cov=cov)
    rc = m.risk_contributions(frame, w, cov=cov)
    var_w = float(w.to_numpy() @ cov.loc[cols, cols].to_numpy() @ w.to_numpy())
    return {"pca": pca, "mt": mt, "rc": rc, "sigma": float(np.sqrt(var_w * WEEKS_PER_YEAR))}


def interpret(enb_pca: float, enb_mt: float, pc1_share: float, n: int,
              loadings: pd.Series, rc: pd.Series, labels: dict[str, str]) -> str:
    """Texte d'interprétation, selon des règles écrites (voir METHODE.md)."""
    pct = f"{pc1_share * 100:.0f}".replace(".", ",")
    fr = lambda x: f"{x:.1f}".replace(".", ",")
    top_f = ", ".join(labels.get(k, k) for k in loadings.abs().sort_values(ascending=False).index[:3])
    top_r = rc.sort_values(ascending=False)
    if pc1_share >= 0.6 and enb_mt >= 2 * enb_pca:
        return (f"Un facteur commun domine : il porte {pct} % de la variance du portefeuille. L'ACP ne voit "
                f"qu'environ {fr(enb_pca)} pari(s) indépendant(s) ; la torsion minimale, qui raisonne ligne par "
                f"ligne, en voit {fr(enb_mt)}. Vos {n} lignes sont distinctes, mais elles montent et baissent "
                f"ensemble. Lignes les plus exposées à ce facteur : {top_f}.")
    if enb_mt < 0.5 * n:
        lead = ", ".join(f"{labels.get(k, k)} ({v * 100:.0f} %)" for k, v in top_r.iloc[:3].items())
        return (f"Le risque est concentré : {fr(enb_mt)} pari(s) effectif(s) selon la torsion minimale pour "
                f"{n} lignes. Quelques lignes, par leur poids ou leur volatilité, portent l'essentiel du risque : "
                f"{lead}. Le premier facteur porte {pct} % de la variance.")
    return (f"Le risque est réparti entre plusieurs sources : {fr(enb_pca)} pari(s) selon l'ACP, {fr(enb_mt)} selon "
            f"la torsion minimale, pour {n} lignes. Le premier facteur porte {pct} % de la variance.")


def analyze(weekly: pd.DataFrame, positions: list[Position], classes: dict[str, str], labels: dict[str, str],
            cash_eur: float, method: str = "lw_cc") -> Analysis:
    """
    `weekly` : rendements hebdomadaires des lignes GARDÉES (NaN hors historique).
    `positions` : valeurs de marché EUR par (compte, ligne) à la date de valorisation.
    """
    cols = list(weekly.columns)
    rows = [p.__dict__ for p in positions if p.line in cols]
    if not rows:
        raise DiversificationError("Aucune position sur les lignes analysées.")
    pos = pd.DataFrame(rows)
    values = pos.groupby("line")["value_eur"].sum().reindex(cols).fillna(0.0)
    risky = float(values.sum())
    if risky <= 0:
        raise DiversificationError("Aucune valeur de marché sur les lignes analysées.")
    w = values / risky
    est = cv.estimate(weekly, method)
    cov = est.cov
    r = _measures(weekly, w, cov)
    pca, mt, rc = r["pca"], r["mt"], r["rc"]

    # Contributions par regroupement : linéarité d'Euler, RC_position = w_position (Sigma w)_ligne / sigma^2.
    marginal = pd.Series(cov.to_numpy() @ w.to_numpy(), index=cols)
    var_p = float(w.to_numpy() @ marginal.to_numpy())
    pos["w"] = pos["value_eur"] / risky
    pos["rc"] = pos["w"] * pos["line"].map(marginal) / var_p
    pos["classe"] = pos["line"].map(lambda k: classes.get(k, "autre"))
    group_contrib = {"compte": pos.groupby("account")["rc"].sum(), "classe": pos.groupby("classe")["rc"].sum()}
    group_weights = {"compte": pos.groupby("account")["w"].sum(), "classe": pos.groupby("classe")["w"].sum()}

    total = risky + max(cash_eur, 0.0)
    cash_share = max(cash_eur, 0.0) / total if total > 0 else 0.0
    loadings = pca["loadings_pc1"]
    text = interpret(pca["enb"], mt["enb"], float(pca["portfolio_variance_share"].iloc[0]), len(cols),
                     loadings, rc, labels)
    return Analysis(
        lines=cols, weights=w, estimate=est, corr=cv.correlation(cov), risk_contrib=rc,
        group_contrib=group_contrib, group_weights=group_weights, enb_pca=float(pca["enb"]), enb_mt=float(mt["enb"]),
        pc1_variance_share=float(pca["portfolio_variance_share"].iloc[0]),
        pc1_eigen_share=float(pca["eigenvalue_share"].iloc[0]), pc1_loadings=loadings,
        mt_contrib=mt["contributions"], sigma_risky=r["sigma"], sigma_total=(1.0 - cash_share) * r["sigma"],
        cash_share=cash_share, text=text)


# ---------------------------------------------------------------------------
# Simulateur
# ---------------------------------------------------------------------------

MODES = ("frais", "realloc")
FORMULAS = {"frais": "w' = (w + x·e_Y) / (1 + x) : un montant égal à x fois la valeur des lignes risquées est "
                     "investi dans Y, sans rien vendre.",
            "realloc": "w' = (1 − x)·w + x·e_Y : Y gagne x points de poids, les autres lignes sont réduites "
                       "au prorata."}


def new_weights(w: pd.Series, target: str, x: float, mode: str) -> pd.Series:
    """Poids après l'opération simulée (cible ajoutée à 0 si absente)."""
    if mode not in MODES:
        raise ValueError(f"Mode inconnu : {mode}")
    if x < 0 or (mode == "realloc" and x > 1):
        raise ValueError("Pourcentage hors bornes.")
    w = w.reindex(w.index.union([target]) if target not in w.index else w.index).fillna(0.0)
    e = pd.Series(0.0, index=w.index)
    e[target] = 1.0
    return (w + x * e) / (1.0 + x) if mode == "frais" else (1.0 - x) * w + x * e


@dataclass
class Scenario:
    enb_pca: float
    enb_mt: float
    sigma_risky: float
    sigma_total: float
    max_drawdown: float | None
    risk_contrib: pd.Series
    weights: pd.Series


def scenario(weekly: pd.DataFrame, daily: pd.DataFrame, w: pd.Series, cov: pd.DataFrame,
             cash_share: float) -> Scenario:
    """Mesures d'un jeu de poids. Drawdown historique à poids constants (rééquilibrage quotidien)."""
    r = _measures(weekly, w, cov)
    common = daily[list(w.index)].dropna()
    mdd = float(m.max_drawdown(m.portfolio_returns(common, w))) if len(common) > 1 else None
    return Scenario(float(r["pca"]["enb"]), float(r["mt"]["enb"]), r["sigma"], (1.0 - cash_share) * r["sigma"],
                    mdd, r["rc"], w)


def simulate(weekly: pd.DataFrame, daily: pd.DataFrame, w: pd.Series, target: str, x: float, mode: str,
             method: str, cash_share: float) -> tuple[Scenario, Scenario, cv.CovEstimate]:
    """
    Avant / après, sur la MÊME covariance (estimée sur toutes les colonnes de
    `weekly`, cible comprise). `cash_share` : part d'espèces actuelle. En argent
    frais, le montant d'espèces est inchangé mais dilué : e' = e / (1 + x (1 - e)).
    """
    est = cv.estimate(weekly, method)
    before_w = w.reindex(weekly.columns).fillna(0.0)
    after_w = new_weights(before_w, target, x, mode).reindex(weekly.columns)
    cash_after = cash_share / (1.0 + x * (1.0 - cash_share)) if mode == "frais" else cash_share
    return (scenario(weekly, daily, before_w, est.cov, cash_share),
            scenario(weekly, daily, after_w, est.cov, cash_after), est)
