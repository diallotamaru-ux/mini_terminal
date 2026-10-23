"""
Paramètres par défaut. Modifiez ce fichier pour refléter votre propre portefeuille.

Tickers Yahoo Finance utiles :
- Actions US : NVDA, MSFT, ASML (ADR) ; Europe : ASML.AS, MC.PA, AIR.PA
- ETF : QQQ (Nasdaq 100), SPY (S&P 500), CW8.PA (MSCI World, PEA), PANX.PA (Nasdaq 100, PEA)
- Crypto : BTC-USD, BTC-EUR ; Or : GLD ; Obligations longues US : TLT
"""

DEFAULT = {
    "assets": ["NVDA", "MSFT", "ASML", "BTC-USD", "GLD", "TLT"],
    "benchmark": "QQQ",
    # Poids en pourcentage. None ou {} -> poids égaux.
    "weights": {"NVDA": 25, "MSFT": 20, "ASML": 15, "BTC-USD": 15, "GLD": 15, "TLT": 10},
    "start": "2019-01-01",
    "rf_annual": 0.025,          # taux sans risque annuel (ordre de grandeur du livret / €STR)
    "base_currency": None,       # "EUR" pour tout convertir en euros
    "rolling_window": 126,       # environ 6 mois de bourse
    "demo": False,
}
