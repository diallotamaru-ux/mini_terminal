"""
Erreurs métier du cœur de calcul.

Chaque erreur porte un message en français destiné à l'utilisateur final :
l'API les renvoie telles quelles.
"""

from __future__ import annotations


class TerminalError(Exception):
    """Classe de base des erreurs métier."""


class LedgerError(TerminalError):
    """Transactions incohérentes. `errors` liste tous les problèmes trouvés."""

    def __init__(self, errors: list[str]):
        self.errors = list(errors)
        super().__init__("; ".join(self.errors))


class UnknownTicker(TerminalError):
    def __init__(self, ticker: str):
        self.ticker = ticker
        super().__init__(f"Ticker inconnu du fournisseur de données : {ticker}")


class ProviderUnavailable(TerminalError):
    def __init__(self, provider: str, detail: str = ""):
        self.provider = provider
        msg = f"Fournisseur de données indisponible ({provider})"
        super().__init__(f"{msg} : {detail}" if detail else msg)


class MissingCurrency(TerminalError):
    def __init__(self, currency: str, detail: str = ""):
        self.currency = currency
        msg = f"Taux de change manquant pour {currency}"
        super().__init__(f"{msg} : {detail}" if detail else msg)
