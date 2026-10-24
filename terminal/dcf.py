"""
Valorisation par DCF inversé : quelle croissance le prix actuel suppose-t-il ?

Cohérence du modèle (voir METHODE.md) : le flux disponible pour l'ENTREPRISE (FCFF), avant
paiement des créanciers, est actualisé au coût du capital k et comparé à la valeur
d'ENTREPRISE (capitalisation + dette − trésorerie + minoritaires). Le module n'offre aucune
voie « FCF des actionnaires contre capitalisation » : `implied_growth` ne prend qu'un FCFF et
une VE, et `enterprise_value` est la seule façon de construire la VE.

On résout g dans
    VE = Σ_{t=1..N} FCF0 (1+g)^t / (1+k)^t + VT / (1+k)^N,   VT = FCF0 (1+g)^N (1+g_term) / (k − g_term).

Une donnée manquante n'est jamais remplacée par zéro : le calcul est bloqué (`Missing`), sauf
approximation explicitement acceptée, qui pose un avertissement. Calcul en flottants : c'est un
modèle, pas une comptabilité.
"""

from __future__ import annotations

import math
from dataclasses import dataclass, field

import numpy as np
import pandas as pd
from scipy.optimize import brentq

from .errors import TerminalError

STANDARDS = {"us_gaap": "US GAAP", "ifrs": "IFRS"}
INTEREST_CLASSES = {"exploitation": "en exploitation", "financement": "en financement"}
G_BOUNDS = (-0.99, 2.0)                       # plage de recherche de g : −99 % à +200 % par an
SENSI_K_STEPS = (-0.02, -0.01, 0.0, 0.01, 0.02)
SENSI_G_TERM = (0.01, 0.015, 0.02, 0.025, 0.03)
BLUME = (0.67, 0.33)                          # β ajusté = 0,67 β + 0,33 (Blume, 1971)

FIELD_LABELS = {
    "revenue": "chiffre d'affaires", "ocf": "flux de trésorerie d'exploitation", "capex": "investissements",
    "fcf_reported": "flux disponible publié", "sbc": "rémunération en actions", "interest_expense": "charge d'intérêts",
    "pretax_income": "résultat avant impôt", "tax_provision": "impôt sur les résultats", "financial_debt": "dette financière", "lt_investments": "placements non courants",
    "lease_liabilities": "dettes locatives", "cash_sti": "trésorerie et placements", "minority_interest":
    "intérêts minoritaires", "diluted_shares": "nombre d'actions dilué",
}


class DCFError(TerminalError):
    """Calcul impossible. `code` identifie le cas pour l'interface."""

    def __init__(self, code: str, message: str):
        self.code = code
        super().__init__(message)


@dataclass(frozen=True)
class MissingItem:
    fiscal_end: pd.Timestamp | None           # None : donnée non annuelle (taux d'impôt, cours…)
    field: str
    remedy: str                               # ce que l'utilisateur peut faire

    @property
    def label(self) -> str:
        year = f" ({self.fiscal_end.date().isoformat()})" if self.fiscal_end is not None else ""
        return f"{FIELD_LABELS.get(self.field, self.field)}{year}"


class Missing(DCFError):
    def __init__(self, items: list[MissingItem]):
        self.items = items
        super().__init__("manquant", "Données manquantes : " + ", ".join(i.label for i in items)
                         + ". Saisissez-les à la main (ou acceptez l'approximation proposée).")


# ---------------------------------------------------------------------------
# Périmètre
# ---------------------------------------------------------------------------

FUND_TYPES = {"ETF", "MUTUALFUND", "INDEX"}
CRYPTO_TYPES = {"CRYPTOCURRENCY"}
FINANCIAL_PREFIXES = ("Banks", "Insurance -", "Reinsurance")


def is_financial(industry: str | None) -> bool:
    return bool(industry) and industry.startswith(FINANCIAL_PREFIXES)


def eligibility(asset_class: str, quote_type: str | None, industry: str | None,
                financial_override: bool | None = None) -> str | None:
    """None si l'action est analysable, sinon la raison de l'exclusion (phrase complète)."""
    if asset_class == "etf" or (quote_type or "").upper() in FUND_TYPES:
        return ("Fonds indiciel : le DCF valorise une entreprise à partir de ses flux. Un ETF se lit par les "
                "valorisations des sociétés qu'il contient, pas par un flux disponible propre.")
    if asset_class == "crypto" or (quote_type or "").upper() in CRYPTO_TYPES:
        return "Cryptoactif : aucun flux de trésorerie à actualiser, le DCF ne s'applique pas."
    if asset_class != "action":
        return "Le DCF inversé ne s'applique qu'aux actions."
    financial = is_financial(industry) if financial_override is None else financial_override
    if financial:
        return ("Banque ou assurance : la dette y est une matière première (dépôts, réserves techniques) et non un "
                "financement, si bien que flux disponible et valeur d'entreprise n'ont pas de sens. Ces sociétés se "
                "valorisent par les fonds propres (dividendes, rentabilité des capitaux propres).")
    return None


# ---------------------------------------------------------------------------
# Hypothèses et flux disponible
# ---------------------------------------------------------------------------

@dataclass(frozen=True)
class Assumptions:
    k: float                                  # coût du capital, annuel
    horizon: int = 10                         # N
    g_term: float = 0.02                      # croissance à perpétuité
    fcf_years: int = 3                        # lissage du FCF de départ
    sbc_deduct: bool = True                   # retrancher la rémunération en actions
    standard: str = "ifrs"                    # norme comptable du titre
    interest_class: str = "exploitation"      # classement des intérêts versés (IFRS)
    statutory_tax: float | None = None        # taux légal saisi ; sinon taux effectif moyen
    accept_interest_approx: bool = False      # FCFF ≈ OCF − capex si les intérêts manquent
    accept_minority_approx: bool = False      # VE sans minoritaires s'ils manquent


@dataclass
class FcffResult:
    table: pd.DataFrame                       # par exercice : ocf, capex, interest_after_tax, sbc, fcff
    window: list[pd.Timestamp]                # exercices du FCF de départ
    fcff0: float
    tax_rate: float | None
    tax_source: str                           # « effectif moyen 2023-2025 » ou « légal (saisi) »
    rule: str                                 # règle affichée
    warnings: list[str] = field(default_factory=list)


def _year(ts: pd.Timestamp) -> str:
    return str(pd.Timestamp(ts).year)


def tax_rate(table: pd.DataFrame, window: list[pd.Timestamp], statutory: float | None) -> tuple[float, str]:
    """Taux légal saisi, sinon Σ impôt / Σ résultat avant impôt sur la fenêtre. Jamais inventé."""
    if statutory is not None:
        return statutory, "taux légal (saisi)"
    sub = table.loc[window, ["tax_provision", "pretax_income"]]
    missing = [MissingItem(d, f, "saisir la valeur, ou saisir le taux légal du pays")
               for d in window for f in ("tax_provision", "pretax_income") if pd.isna(sub.loc[d, f])]
    if missing:
        raise Missing(missing)
    pretax = float(sub["pretax_income"].sum())
    if pretax <= 0:
        raise DCFError("impot", "Taux effectif non calculable (résultat avant impôt cumulé négatif ou nul) : "
                                "saisissez le taux légal du pays.")
    return float(sub["tax_provision"].sum()) / pretax, f"effectif moyen {_year(window[0])}-{_year(window[-1])}"


def fcff(table: pd.DataFrame, a: Assumptions) -> FcffResult:
    """
    FCFF par exercice et FCF de départ (moyenne des `fcf_years` derniers exercices).
        FCFF = OCF − |capex| + intérêts × (1 − t)   si les intérêts sont classés en exploitation
        FCFF = OCF − |capex|                        s'ils le sont en financement (IFRS seulement)
        moins la rémunération en actions si `sbc_deduct`.
    """
    if a.standard not in STANDARDS or a.interest_class not in INTEREST_CLASSES:
        raise DCFError("hypothese", "Norme comptable ou classement des intérêts inconnu.")
    if a.fcf_years < 1:
        raise DCFError("hypothese", "Le lissage porte sur au moins un exercice.")
    years = list(table.index)
    if len(years) < a.fcf_years:
        raise DCFError("historique", f"{len(years)} exercice(s) disponible(s), {a.fcf_years} demandé(s) pour le "
                                     "FCF de départ : réduisez le lissage ou saisissez des exercices plus anciens.")
    window = years[-a.fcf_years:]
    # US GAAP : intérêts versés toujours en exploitation. IFRS : selon le choix publié par la société.
    add_interest = a.standard == "us_gaap" or a.interest_class == "exploitation"
    warnings: list[str] = []
    missing = [MissingItem(d, f, "saisir la valeur")
               for d in window for f in ("ocf", "capex") if pd.isna(table.loc[d, f])]
    if a.sbc_deduct:
        missing += [MissingItem(d, "sbc", "saisir la valeur, ou ne plus retrancher la rémunération en actions")
                    for d in window if pd.isna(table.loc[d, "sbc"])]
    interest_missing = add_interest and table.loc[window, "interest_expense"].isna().any()
    if interest_missing and not a.accept_interest_approx:
        missing += [MissingItem(d, "interest_expense", "saisir la valeur, ou accepter l'approximation OCF − capex")
                    for d in window if pd.isna(table.loc[d, "interest_expense"])]
    t, t_src = None, "sans objet (intérêts classés en financement)"
    if add_interest and not (interest_missing and a.accept_interest_approx):
        try:
            t, t_src = tax_rate(table, window, a.statutory_tax)
        except Missing as e:
            missing += e.items
    if missing:
        raise Missing(missing)

    out = pd.DataFrame(index=table.index)
    out["ocf"] = table["ocf"]
    out["capex"] = -table["capex"].abs()
    if add_interest and t is not None:
        out["interest_after_tax"] = table["interest_expense"] * (1 - t)
    elif add_interest:
        out["interest_after_tax"] = np.nan
    else:
        out["interest_after_tax"] = 0.0          # intérêts déjà hors de l'OCF : rien à rajouter
    out["sbc"] = table["sbc"] if a.sbc_deduct else 0.0
    parts = out["ocf"] + out["capex"] - out["sbc"]
    if add_interest and t is None:
        # Approximation acceptée : FCFF ≈ OCF − capex (− rémunération en actions).
        out["fcff"] = parts
        warnings.append("Approximation acceptée : charge d'intérêts manquante, FCFF ≈ OCF − capex. Le FCFF est "
                        "sous-estimé des intérêts après impôt, donc le g implicite est surestimé.")
    else:
        out["fcff"] = parts + out["interest_after_tax"]
    rule = "FCFF = OCF − investissements"
    if add_interest and t is not None:
        rule += " + intérêts × (1 − t)"
    if a.sbc_deduct:
        rule += " − rémunération en actions"
    if not add_interest:
        rule += " (intérêts versés classés en financement : déjà hors de l'OCF)"
    fcff0 = float(out.loc[window, "fcff"].mean())
    return FcffResult(out, window, fcff0, t, t_src, rule, warnings)


# ---------------------------------------------------------------------------
# Valeur d'entreprise
# ---------------------------------------------------------------------------

@dataclass
class EnterpriseValue:
    price: float                              # cours dans la devise de cotation
    fx: float                                 # unités de la devise des comptes pour une unité de cotation
    shares: float
    market_cap: float                         # devise des comptes
    debt: float
    debt_rule: str
    cash: float
    lt_investments: float | None             # None : manquant, non retranché (avertissement)
    minority: float | None
    ev: float
    balance_date: pd.Timestamp
    warnings: list[str] = field(default_factory=list)


def enterprise_value(table: pd.DataFrame, price: float, fx: float, a: Assumptions) -> EnterpriseValue:
    """
    VE = cours × actions diluées + dette − trésorerie − placements non courants + minoritaires, au dernier bilan.
    Placements non courants manquants : ils ne sont pas retranchés, la cellule reste « manquant » et un avertissement
    le dit (la VE peut être surestimée). On ne bloque pas : la plupart des sociétés n'en ont pas de significatifs.
    """
    if not table.index.size:
        raise DCFError("historique", "Aucun exercice disponible.")
    d = table.index[-1]
    row = table.loc[d]
    missing = [MissingItem(d, f, "saisir la valeur (0 si la société n'en a pas)")
               for f in ("diluted_shares", "financial_debt", "cash_sti") if pd.isna(row[f])]
    if a.standard == "ifrs" and pd.isna(row["lease_liabilities"]):
        missing.append(MissingItem(d, "lease_liabilities", "saisir la valeur (0 si la société n'en a pas) : en "
                                                           "IFRS, les dettes locatives font partie de la dette"))
    if pd.isna(row["minority_interest"]) and not a.accept_minority_approx:
        missing.append(MissingItem(d, "minority_interest",
                                   "saisir la valeur (0 si la société n'en a pas), ou accepter l'approximation"))
    if missing:
        raise Missing(missing)
    if not (price > 0 and fx > 0):
        raise DCFError("cours", "Cours ou taux de change manquant à la date de valorisation.")
    warnings: list[str] = []
    debt = float(row["financial_debt"])
    if a.standard == "ifrs":
        debt += float(row["lease_liabilities"])
        rule = "dette financière + dettes locatives (IFRS 16 : loyers classés en financement)"
    else:
        rule = "dette financière, dettes locatives exclues (US GAAP : loyers déjà déduits de l'OCF)"
    minority = None if pd.isna(row["minority_interest"]) else float(row["minority_interest"])
    if minority is None:
        warnings.append("Approximation acceptée : intérêts minoritaires manquants, non ajoutés à la VE. Si la société "
                        "en a, la VE est sous-estimée et le g implicite aussi.")
    lt = None if pd.isna(row["lt_investments"]) else float(row["lt_investments"])
    if lt is None:
        warnings.append("Placements financiers non courants manquants chez le fournisseur : non retranchés de la VE. "
                        "Si la société en détient, la VE et le g implicite sont surestimés. Saisissez-les (0 si "
                        "aucun) dans le tableau des comptes.")
    cap = price * fx * float(row["diluted_shares"])
    ev = cap + debt - float(row["cash_sti"]) - (lt or 0.0) + (minority or 0.0)
    return EnterpriseValue(price, fx, float(row["diluted_shares"]), cap, debt, rule, float(row["cash_sti"]), lt,
                           minority, ev, d, warnings)


# ---------------------------------------------------------------------------
# DCF inversé
# ---------------------------------------------------------------------------

def _check(k: float, n: int, g_term: float) -> None:
    if n < 1 or int(n) != n:
        raise DCFError("hypothese", "L'horizon N est un nombre entier d'années, au moins 1.")
    if not k > -1:
        raise DCFError("hypothese", "Le coût du capital k doit être supérieur à −100 %.")
    if k <= g_term:
        raise DCFError("k_le_gterm", f"k ({k:.2%}) doit être strictement supérieur à la croissance terminale "
                                     f"({g_term:.2%}) : sinon la valeur terminale est infinie ou négative.")


def dcf_value(fcff0: float, g: float, k: float, n: int, g_term: float) -> float:
    """Valeur d'entreprise d'un FCFF0 croissant de g pendant N ans, puis de g_term à perpétuité."""
    _check(k, n, g_term)
    t = np.arange(1, n + 1)
    ratio = (1 + g) / (1 + k)
    explicit = fcff0 * float(np.sum(ratio ** t))
    terminal = fcff0 * (1 + g) ** n * (1 + g_term) / ((k - g_term) * (1 + k) ** n)
    return explicit + terminal


def implied_growth(fcff0: float, ev: float, k: float, n: int, g_term: float) -> float:
    """g tel que dcf_value(fcff0, g, …) = ev. V est strictement croissante en g quand FCFF0 > 0."""
    _check(k, n, g_term)
    if not fcff0 > 0:
        raise DCFError("fcf_negatif", "Flux disponible de départ négatif ou nul : pas de DCF inversé. Aucune "
                                      "croissance ne transforme un flux négatif en valeur positive.")
    if not ev > 0:
        raise DCFError("ve_negative", "Valeur d'entreprise négative ou nulle (trésorerie supérieure à la "
                                      "capitalisation et à la dette) : pas de DCF inversé.")
    lo, hi = G_BOUNDS
    f = lambda g: dcf_value(fcff0, g, k, n, g_term) - ev     # noqa: E731
    if f(lo) > 0:
        raise DCFError("sans_solution", "Aucune solution : même une baisse de 99 % par an du flux disponible "
                                        "donnerait une valeur supérieure à la valeur d'entreprise.")
    if f(hi) < 0:
        raise DCFError("sans_solution", "Aucune solution : il faudrait plus de 200 % de croissance par an.")
    return float(brentq(f, lo, hi, xtol=1e-14, rtol=1e-14, maxiter=200))


@dataclass
class Cell:
    k: float
    g_term: float
    g: float | None
    reason: str | None                        # raison quand g est None


def sensitivity(fcff0: float, ev: float, k: float, n: int,
                k_steps=SENSI_K_STEPS, g_terms=SENSI_G_TERM) -> list[list[Cell]]:
    """Grille de g implicite : une ligne par k, une colonne par g_term. Jamais de nombre sans solution."""
    grid = []
    for dk in k_steps:
        row = []
        for gt in g_terms:
            kk = round(k + dk, 10)
            try:
                row.append(Cell(kk, gt, implied_growth(fcff0, ev, kk, n, gt), None))
            except DCFError as e:
                row.append(Cell(kk, gt, None, "k ≤ g terminal" if e.code == "k_le_gterm" else str(e)))
        grid.append(row)
    return grid


# ---------------------------------------------------------------------------
# Croissance historique, coût du capital, phrase
# ---------------------------------------------------------------------------

@dataclass
class Growth:
    value: float | None
    years: int                                # nombre d'années entre les deux exercices extrêmes
    n_points: int                             # exercices disponibles
    status: str                               # "ok", "non_significatif", "manquant"
    start: pd.Timestamp | None = None
    end: pd.Timestamp | None = None


def historical_growth(series: pd.Series) -> Growth:
    """Taux annuel composé entre le premier et le dernier exercice disponibles."""
    s = series.dropna().sort_index()
    if len(s) < 2:
        return Growth(None, 0, len(s), "manquant")
    first, last = s.index[0], s.index[-1]
    years = round((last - first).days / 365.25)
    if years < 1:
        return Growth(None, 0, len(s), "manquant", first, last)
    if s.iloc[0] <= 0 or s.iloc[-1] <= 0:
        return Growth(None, years, len(s), "non_significatif", first, last)
    return Growth(float((s.iloc[-1] / s.iloc[0]) ** (1 / years) - 1), years, len(s), "ok", first, last)


def common_k(rf: float, erp: float) -> float:
    """k commun de la devise : taux long + prime de risque, β = 1."""
    return rf + erp


@dataclass
class CapmK:
    k: float | None
    ke: float | None
    beta_raw: float | None
    beta_adj: float | None
    kd_after_tax: float | None
    weight_equity: float | None
    reason: str | None = None


def capm_k(rf: float, erp: float, beta_raw: float | None, market_cap: float, debt: float,
           interest: float | None, avg_debt: float | None, tax: float | None) -> CapmK:
    """
    WACC du MEDAF : ke = rf + β_Blume × prime, kd = intérêts / dette moyenne, après impôt,
    pondérations de marché E / (D + E). Manquant si un élément manque (rien n'est inventé).
    """
    if beta_raw is None or not math.isfinite(beta_raw):
        return CapmK(None, None, None, None, None, None, "β non calculable (historique de cours insuffisant)")
    b = BLUME[0] * beta_raw + BLUME[1]
    ke = rf + b * erp
    if debt <= 0:
        return CapmK(ke, ke, beta_raw, b, None, 1.0)
    if interest is None or avg_debt is None or not avg_debt > 0 or tax is None:
        return CapmK(None, ke, beta_raw, b, None, None,
                     "coût de la dette non calculable (charge d'intérêts, dette ou taux d'impôt manquant)")
    kd = interest / avg_debt * (1 - tax)
    we = market_cap / (market_cap + debt)
    return CapmK(we * ke + (1 - we) * kd, ke, beta_raw, b, kd, we)


def sentence(g: float, n: int, g_term: float, k: float) -> str:
    return (f"Le prix actuel suppose une croissance du flux disponible de {_pct(g)} par an pendant {n} ans, puis de "
            f"{_pct(g_term)} par an à perpétuité, avec un coût du capital de {_pct(k)}.")


def _pct(x: float) -> str:
    return f"{x * 100:.1f}".replace(".", ",").replace("-", "−") + " %"
