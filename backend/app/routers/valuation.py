"""Page Valorisation : DCF inversé. Les écritures ne portent que sur des hypothèses et des saisies locales."""

from __future__ import annotations

import datetime as dt

from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy import delete
from sqlalchemy.orm import Session

from .. import models, schemas, settings_store
from ..deps import AppState, get_session, get_state
from ..services import valuation as sv

router = APIRouter(prefix="/api/valuation", tags=["valorisation"])


def _title(s: Session, st: AppState, ticker: str) -> sv.Title:
    t = sv.find_title(s, st.snapshot(s), ticker)
    if t is None:
        raise HTTPException(404, f"{ticker} n'est pas une position ouverte du portefeuille.")
    return t


@router.get("", response_model=schemas.ValuationSummaryOut)
def summary(s: Session = Depends(get_session), st: AppState = Depends(get_state)):
    return st.valuation(s, None)


@router.get("/{ticker}", response_model=schemas.ValuationOut)
def fiche(ticker: str, s: Session = Depends(get_session), st: AppState = Depends(get_state)):
    _title(s, st, ticker)
    return st.valuation(s, ticker.upper())


@router.put("/{ticker}/profile", response_model=schemas.ValuationOut)
def put_profile(ticker: str, body: schemas.ProfileIn, s: Session = Depends(get_session),
                st: AppState = Depends(get_state)):
    """Hypothèses et attributs comptables du titre ; null = valeur par défaut."""
    t = _title(s, st, ticker)
    g_term = body.g_term if body.g_term is not None else settings_store.load(s).g_term
    if body.k is not None and body.k <= g_term:
        raise HTTPException(422, "k doit être strictement supérieur à la croissance terminale.")
    p = s.get(models.ValuationProfile, t.instrument_id) or models.ValuationProfile(instrument_id=t.instrument_id)
    for name, value in body.model_dump().items():
        setattr(p, name, value)
    s.add(p)
    s.commit()
    st.touch()
    return st.valuation(s, t.ticker)


@router.put("/{ticker}/fundamentals", response_model=schemas.ValuationOut)
def put_fundamental(ticker: str, body: schemas.FundamentalIn, s: Session = Depends(get_session),
                    st: AppState = Depends(get_state)):
    """Saisie manuelle d'une valeur des comptes : elle prime sur le fournisseur et reste signalée."""
    t = _title(s, st, ticker)
    key = (t.instrument_id, body.fiscal_end, body.field)
    o = s.get(models.FundamentalOverride, key) or models.FundamentalOverride(
        instrument_id=t.instrument_id, fiscal_end=body.fiscal_end, field=body.field)
    o.value, o.note, o.entered_at = body.value, body.note, dt.datetime.now(dt.timezone.utc)
    s.add(o)
    s.commit()
    st.touch()
    return st.valuation(s, t.ticker)


@router.delete("/{ticker}/fundamentals/{fiscal_end}/{field}", response_model=schemas.ValuationOut)
def delete_fundamental(ticker: str, fiscal_end: dt.date, field: schemas.FundamentalField,
                       s: Session = Depends(get_session), st: AppState = Depends(get_state)):
    """Supprime une saisie manuelle : la valeur du fournisseur (ou « manquant ») revient."""
    t = _title(s, st, ticker)
    n = s.execute(delete(models.FundamentalOverride).where(
        models.FundamentalOverride.instrument_id == t.instrument_id,
        models.FundamentalOverride.fiscal_end == fiscal_end,
        models.FundamentalOverride.field == field)).rowcount
    if not n:
        raise HTTPException(404, "Aucune saisie manuelle pour cet exercice et ce champ.")
    s.commit()
    st.touch()
    return st.valuation(s, t.ticker)
