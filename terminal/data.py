"""
Couche données : téléchargement (yfinance), cache disque, conversion de devise,
et générateur de données simulées pour travailler hors ligne.
"""

from __future__ import annotations

import hashlib
from pathlib import Path

import numpy as np
import pandas as pd

CACHE_DIR = Path(__file__).resolve().parent.parent / ".cache"


# ---------------------------------------------------------------------------
# Téléchargement réel
# ---------------------------------------------------------------------------

def _cache_path(tickers: list[str], start: str, end: str | None) -> Path:
    key = "|".join(sorted(tickers)) + f"|{start}|{end}"
    digest = hashlib.sha1(key.encode()).hexdigest()[:16]
    return CACHE_DIR / f"prices_{digest}.csv"


def fetch_prices(tickers: list[str], start: str, end: str | None = None,
                 use_cache: bool = True) -> pd.DataFrame:
    """
    Cours de clôture ajustés (dividendes et splits) via yfinance.
    Retourne un DataFrame indexé par date, une colonne par ticker.
    """
    import yfinance as yf  # import local : le mode démo n'en a pas besoin

    path = _cache_path(tickers, start, end)
    # Le cache n'est utilisé que si la date de fin est figée : sinon les
    # données du jour seraient périmées.
    if use_cache and end is not None and path.exists():
        return pd.read_csv(path, index_col=0, parse_dates=True)

    raw = yf.download(tickers, start=start, end=end, auto_adjust=True,
                      progress=False, group_by="column", threads=True)
    if raw.empty:
        raise RuntimeError("Aucune donnée reçue. Vérifiez les tickers et la connexion.")

    close = raw["Close"] if isinstance(raw.columns, pd.MultiIndex) else raw[["Close"]]
    if isinstance(close, pd.Series):
        close = close.to_frame()
    if close.shape[1] == 1 and len(tickers) == 1:
        close.columns = tickers

    missing = [t for t in tickers if t not in close.columns or close[t].isna().all()]
    if missing:
        raise RuntimeError(f"Tickers sans données : {', '.join(missing)}")

    close = close[tickers]
    if use_cache and end is not None:
        CACHE_DIR.mkdir(exist_ok=True)
        close.to_csv(path)
    return close


def fetch_currencies(tickers: list[str]) -> dict[str, str]:
    """Devise de cotation de chaque ticker (ex. 'USD', 'EUR'). 'USD' par défaut."""
    import yfinance as yf

    out = {}
    for t in tickers:
        try:
            out[t] = (yf.Ticker(t).fast_info.get("currency") or "USD").upper()
        except Exception:
            out[t] = "USD"
    return out


def convert_to_base(prices: pd.DataFrame, currencies: dict[str, str],
                    base: str, start: str, end: str | None = None) -> pd.DataFrame:
    """
    Convertit chaque série dans la devise de base.
    Pour un actif coté en devise c, P_base = P_c * FX(c -> base).
    Le ticker Yahoo 'CBASE=X' donne le nombre d'unités de base pour 1 unité de c.
    """
    out = prices.copy()
    needed = {c for c in currencies.values() if c != base}
    if not needed:
        return out
    fx_tickers = [f"{c}{base}=X" for c in sorted(needed)]
    fx = fetch_prices(fx_tickers, start, end, use_cache=False)
    fx = fx.reindex(out.index).ffill()
    for t, c in currencies.items():
        if c != base:
            out[t] = out[t] * fx[f"{c}{base}=X"]
    return out


# ---------------------------------------------------------------------------
# Alignement des calendriers
# ---------------------------------------------------------------------------

def align_prices(prices: pd.DataFrame, max_ffill: int = 3) -> pd.DataFrame:
    """
    Aligne des actifs aux calendriers différents (actions 5 j/7, crypto 7 j/7,
    jours fériés propres à chaque bourse).

    1. Report du dernier cours connu sur au plus `max_ffill` jours.
    2. Conservation des seules dates où tous les actifs ont un cours.
    3. Retrait des week-ends : le rendement du lundi d'une crypto inclut alors
       le samedi et le dimanche, ce qui conserve le rendement total exact.
    """
    p = prices.sort_index().ffill(limit=max_ffill)
    p = p[p.index.day_of_week < 5]
    return p.dropna(how="any")


# ---------------------------------------------------------------------------
# Données simulées (mode démo)
# ---------------------------------------------------------------------------

DEMO_PROFILE = {
    # ticker : (drift annuel mu, vol annuelle sigma, bêta au facteur commun)
    "QQQ":     (0.14, 0.22, 1.00),
    "NVDA":    (0.35, 0.50, 1.80),
    "MSFT":    (0.18, 0.27, 1.05),
    "ASML":    (0.15, 0.35, 1.30),
    "BTC-USD": (0.40, 0.65, 0.90),
    "GLD":     (0.07, 0.15, 0.05),
    "TLT":     (0.02, 0.15, -0.15),
}


def demo_prices(tickers: list[str], start: str, end: str | None = None,
                seed: int = 7, profile: dict | None = None) -> pd.DataFrame:
    """
    Modèle à deux facteurs avec queues épaisses :
        r_i,t = mu_i,d + beta_i * f_t + gamma_i * g_t + e_i,t
    f_t : marché mondial ; g_t : facteur technologie, indépendant de f_t ; même volatilité de 20 %.
    `profile` : (mu, sigma, bêta) ou (mu, sigma, bêta, gamma) par ticker ; DEMO_PROFILE par défaut.
    Sans gamma (profil à trois paramètres), le modèle est celui à un facteur d'origine et les cours
    sont identiques au bit près : g_t vient d'un générateur séparé qui ne décale pas les tirages.
    f_t, g_t et e_i,t suivent des lois de Student à 4 degrés de liberté, normalisées à variance unité
    puis mises à l'échelle. Ces données sont FICTIVES : elles servent à tester le code, pas à prendre
    une décision.
    """
    rng = np.random.default_rng(seed)
    idx = pd.bdate_range(start=start, end=end or pd.Timestamp.today().normalize())
    n = len(idx)
    A, nu = 252, 4.0
    scale_t = np.sqrt((nu - 2) / nu)  # Student(4) -> variance 1

    sigma_f = 0.20 / np.sqrt(A)
    f = rng.standard_t(nu, n) * scale_t * sigma_f
    g = np.random.default_rng([seed, 1]).standard_t(nu, n) * scale_t * sigma_f

    cols = {}
    for t in tickers:
        mu, sig, b, *rest = (DEMO_PROFILE if profile is None else profile).get(t, (0.08, 0.25, 0.8))
        gam = rest[0] if rest else 0.0
        sig_d = sig / np.sqrt(A)
        idio_var = max(sig_d ** 2 - (b ** 2 + gam ** 2) * sigma_f ** 2, (0.2 * sig_d) ** 2)
        e = rng.standard_t(nu, n) * scale_t * np.sqrt(idio_var)
        r = mu / A - 0.5 * sig_d ** 2 + b * f + gam * g + e
        cols[t] = 100.0 * np.exp(np.cumsum(r))
    return pd.DataFrame(cols, index=idx)
