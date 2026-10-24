"""
Application FastAPI.

    python -m uvicorn backend.app.main:create_app --factory --reload   (depuis la racine)

L'application lit et analyse. Elle n'exécute aucun ordre, ne se connecte à
aucun courtier et ne stocke aucun identifiant.
"""

from __future__ import annotations

import logging
from datetime import timedelta

from fastapi import FastAPI, Request
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse

from terminal.errors import LedgerError, MissingCurrency, ProviderUnavailable, TerminalError, UnknownTicker
from terminal.marketdata import get_provider
from terminal.marketdata.base import MarketDataProvider
from terminal.marketdata.rates import RateProvider, SimulatedRates

from . import demo
from .config import Settings, get_settings
from .db import Database
from .deps import AppState
from .market import CachedProvider, CachedRates
from .routers import accounts, analysis, listings, portfolio, transactions
from .services.csv_import import CsvFormatError

log = logging.getLogger("mini_terminal")


def create_app(settings: Settings | None = None, provider: MarketDataProvider | None = None,
               database_url: str | None = None, rates: RateProvider | None = None) -> FastAPI:
    settings = settings or get_settings()
    db = Database(database_url or settings.database_url)
    db.create_all()
    inner = provider or get_provider(settings.effective_provider)
    cached = CachedProvider(inner, db.sessionmaker, ttl=timedelta(minutes=settings.cache_ttl_minutes))
    # Taux simulés si le fournisseur de cours l'est : une démo ne mélange jamais réel et fictif.
    if rates is None:
        if inner.simulated:
            rates = SimulatedRates()
        else:
            from terminal.marketdata.ecb import EcbRates
            from terminal.marketdata.fred import FredRates
            from terminal.marketdata.rates import CombinedRates
            ecb = EcbRates()
            rates = CombinedRates(ecb, {"EUR": ecb, "USD": FredRates()})
    cached_rates = CachedRates(rates, db.sessionmaker, ttl=timedelta(minutes=settings.cache_ttl_minutes))
    state = AppState(settings=settings, db=db, provider=cached, rates=cached_rates)
    if settings.demo:
        with db.sessionmaker() as s:
            if demo.seed(s, cached):
                log.info("Base de démonstration créée.")

    app = FastAPI(title="Mini-terminal", version=_version(),
                  description="Analyse de portefeuille personnel. Lecture seule : aucun ordre, aucun courtier.")
    app.state.mt = state
    app.add_middleware(CORSMiddleware, allow_origins=settings.cors_origins, allow_methods=["*"],
                       allow_headers=["*"])
    for r in (accounts.router, listings.router, transactions.router, portfolio.router, analysis.router):
        app.include_router(r)

    @app.exception_handler(LedgerError)
    async def _ledger(_: Request, e: LedgerError):
        return JSONResponse(status_code=422, content={"detail": "Transactions incohérentes.",
                                                      "errors": e.errors})

    @app.exception_handler(TerminalError)
    async def _terminal(_: Request, e: TerminalError):
        code = 503 if isinstance(e, ProviderUnavailable) else 422
        kind = {UnknownTicker: "ticker_inconnu", MissingCurrency: "devise_manquante",
                ProviderUnavailable: "fournisseur_indisponible"}.get(type(e), "erreur")
        return JSONResponse(status_code=code, content={"detail": str(e), "kind": kind})

    @app.exception_handler(CsvFormatError)
    async def _csv(_: Request, e: CsvFormatError):
        return JSONResponse(status_code=422, content={"detail": str(e), "kind": "format_csv"})

    return app


def _version() -> str:
    from . import __version__
    return __version__

