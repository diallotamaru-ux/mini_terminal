"""Fournisseurs de données de marché. Voir `base.MarketDataProvider`."""

from .base import InstrumentInfo, MarketDataProvider, PriceSeries


def get_provider(name: str) -> MarketDataProvider:
    """Seul point de sélection du fournisseur : 'yahoo' ou 'simule'."""
    if name == "yahoo":
        from .yahoo import YahooProvider
        return YahooProvider()
    if name == "simule":
        from .simulated import SimulatedProvider
        return SimulatedProvider()
    raise ValueError(f"Fournisseur inconnu : {name}")


__all__ = ["InstrumentInfo", "MarketDataProvider", "PriceSeries", "get_provider"]
