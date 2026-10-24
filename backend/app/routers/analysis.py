"""Page Risque et réglages d'analyse."""

from __future__ import annotations

import datetime as dt
from typing import Literal

from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy.orm import Session

from terminal.errors import ProviderUnavailable, UnknownTicker
from terminal.ledger import CURRENCIES

from .. import schemas, settings_store
from ..deps import AppState, get_session, get_state

router = APIRouter(prefix="/api", tags=["risque"])


@router.get("/risk", response_model=schemas.RiskOut)
def risk(period: schemas.Period = "origine", reference: int = Query(1, ge=1, le=2),
         as_of: dt.date | None = None, s: Session = Depends(get_session), st: AppState = Depends(get_state)):
    return st.risk(s, period, reference, as_of)


@router.get("/diversification", response_model=schemas.DiversificationOut)
def diversification(period: schemas.Period = "origine",
                    partial: Literal["inclure", "exclure"] = "inclure", as_of: dt.date | None = None,
                    s: Session = Depends(get_session), st: AppState = Depends(get_state)):
    return st.diversification(s, period, partial, as_of)


@router.post("/diversification/simulate", response_model=schemas.SimulationOut)
def simulate(body: schemas.SimulationIn, s: Session = Depends(get_session), st: AppState = Depends(get_state)):
    """Simulation sur données passées : rien n'est écrit en base."""
    from ..services.diversification import simulate_out

    return simulate_out(st.snapshot(s), st.provider, settings_store.load(s), body)


@router.get("/settings", response_model=schemas.SettingsOut)
def get_settings(s: Session = Depends(get_session)):
    return schemas.SettingsOut(settings=settings_store.load(s).model_dump(mode="json"))


@router.put("/settings", response_model=schemas.SettingsOut)
def put_settings(body: settings_store.AnalysisSettings, s: Session = Depends(get_session),
                 st: AppState = Depends(get_state)):
    """Chaque référence est vérifiée auprès du fournisseur : ticker existant, devise, historique."""
    warnings: list[str] = []
    if body.rf_mode == "fixe" and body.rf_fixed_rate is None:
        raise HTTPException(422, "Taux fixe choisi : indiquez sa valeur.")
    today = dt.date.today()
    for i in (1, 2):
        ref = body.reference(i)
        if ref.currency not in CURRENCIES:
            raise HTTPException(422, f"Devise {ref.currency} non prise en charge.")
        try:
            info = st.provider.instrument_info(ref.ticker)          # UnknownTicker -> 422
        except ProviderUnavailable:
            warnings.append(f"{ref.ticker} : fournisseur indisponible, ticker et devise non vérifiés.")
            continue
        if info.currency != ref.currency:
            raise HTTPException(422, f"{ref.ticker} cote en {info.currency} selon le fournisseur, "
                                     f"pas en {ref.currency}.")
        try:
            closes = st.provider.daily_closes(ref.ticker, today - dt.timedelta(days=3 * 365 + 10), today).closes
            if closes.empty or closes.index[0].date() > today - dt.timedelta(days=3 * 365):
                warnings.append(f"{ref.ticker} : moins de 3 ans d'historique chez le fournisseur.")
        except (UnknownTicker, ProviderUnavailable) as e:
            warnings.append(f"{ref.ticker} : historique non vérifié ({e}).")
    settings_store.save(s, body)
    st.touch()
    return schemas.SettingsOut(settings=body.model_dump(mode="json"), warnings=warnings)
