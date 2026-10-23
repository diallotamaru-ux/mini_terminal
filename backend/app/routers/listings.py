"""Cotations (ticker, place, devise) et titres (ISIN, nom, classe)."""

from __future__ import annotations

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel, Field
from sqlalchemy import select
from sqlalchemy.orm import Session

from terminal.errors import ProviderUnavailable

from .. import models, schemas
from ..deps import AppState, get_session, get_state

router = APIRouter(prefix="/api/listings", tags=["cotations"])


class InstrumentPatch(BaseModel):
    name: str | None = Field(default=None, max_length=200)
    asset_class: schemas.AssetClass | None = None


@router.get("", response_model=list[schemas.ListingOut])
def list_listings(s: Session = Depends(get_session)):
    return list(s.scalars(select(models.Listing).order_by(models.Listing.ticker)).unique())


@router.post("", response_model=schemas.ListingOut, status_code=201)
def create_listing(body: schemas.ListingIn, s: Session = Depends(get_session),
                   st: AppState = Depends(get_state)):
    if s.scalar(select(models.Listing).where(models.Listing.ticker == body.ticker)):
        raise HTTPException(409, f"La cotation {body.ticker} existe déjà.")
    try:
        info = st.provider.instrument_info(body.ticker)       # UnknownTicker -> 422
        currency, name, exchange = info.currency, info.name, info.exchange
    except ProviderUnavailable:
        if body.currency is None:
            raise
        currency, name, exchange = body.currency, None, None   # saisie manuelle, non vérifiée
    if body.currency and body.currency != currency:
        raise HTTPException(422, f"{body.ticker} cote en {currency} selon le fournisseur, "
                                 f"pas en {body.currency}.")
    inst = None
    if body.isin:
        inst = s.scalar(select(models.Instrument).where(models.Instrument.isin == body.isin))
    if inst is None:
        inst = models.Instrument(isin=body.isin, name=body.name or name, asset_class=body.asset_class)
        s.add(inst)
    listing = models.Listing(ticker=body.ticker, instrument=inst, currency=currency,
                             exchange=body.exchange or exchange)
    s.add(listing)
    s.commit()
    st.touch()
    return listing


@router.patch("/{listing_id}/instrument", response_model=schemas.ListingOut)
def update_instrument(listing_id: int, body: InstrumentPatch, s: Session = Depends(get_session),
                      st: AppState = Depends(get_state)):
    listing = s.get(models.Listing, listing_id)
    if listing is None:
        raise HTTPException(404, "Cotation introuvable.")
    if body.name is not None:
        listing.instrument.name = body.name
    if body.asset_class is not None:
        listing.instrument.asset_class = body.asset_class
    s.commit()
    st.touch()
    return listing
