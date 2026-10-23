"""
Transactions. Toute écriture valide l'historique complet avant d'être
enregistrée : une suppression d'achat qui rendrait une vente ultérieure
impossible est refusée, comme une vente à découvert.
"""

from __future__ import annotations

from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy import select
from sqlalchemy.orm import Session

from terminal import ledger

from .. import models, schemas
from ..deps import AppState, get_session, get_state
from ..services.ledger_check import check

router = APIRouter(prefix="/api/transactions", tags=["transactions"])


def to_out(t: models.Transaction) -> schemas.TransactionOut:
    return schemas.TransactionOut(
        id=t.id, account_id=t.account_id, date=t.date, type=ledger.TxType(t.type),
        ticker=t.listing.ticker if t.listing else None, quantity=t.quantity, price=t.price,
        amount=t.amount, fees=t.fees, currency=t.currency, fx_rate=t.fx_rate,
        withholding=t.withholding, note=t.note)


def _resolve(s: Session, body: schemas.TransactionIn) -> tuple[models.Listing | None, str]:
    if s.get(models.Account, body.account_id) is None:
        raise HTTPException(422, "Compte inexistant.")
    listing = None
    if body.ticker:
        listing = s.scalar(select(models.Listing).where(models.Listing.ticker == body.ticker))
        if listing is None:
            raise HTTPException(422, f"Cotation {body.ticker} inconnue : ajoutez-la d'abord.")
    currency = body.currency or (listing.currency if listing else "EUR")
    return listing, currency


def _core(body: schemas.TransactionIn, currency: str, tx_id: int | None) -> ledger.Transaction:
    return ledger.Transaction(account_id=body.account_id, date=body.date, type=body.type, currency=currency,
                              ticker=body.ticker, quantity=body.quantity, price=body.price,
                              amount=body.amount, fees=body.fees, fx_rate=body.fx_rate,
                              withholding=body.withholding, id=tx_id)


def _apply(t: models.Transaction, body: schemas.TransactionIn, listing, currency: str) -> None:
    t.account_id, t.listing_id, t.date, t.type = body.account_id, listing.id if listing else None, \
        body.date, body.type.value
    t.quantity, t.price, t.amount, t.fees = body.quantity, body.price, body.amount, body.fees
    t.currency, t.fx_rate, t.withholding, t.note = currency, body.fx_rate, body.withholding, body.note


@router.get("", response_model=list[schemas.TransactionOut])
def list_transactions(account_id: int | None = None, s: Session = Depends(get_session)):
    q = select(models.Transaction).order_by(models.Transaction.date.desc(), models.Transaction.id.desc())
    if account_id is not None:
        q = q.where(models.Transaction.account_id == account_id)
    return [to_out(t) for t in s.scalars(q).unique()]


@router.post("", response_model=schemas.TransactionOut, status_code=201)
def create_transaction(body: schemas.TransactionIn, s: Session = Depends(get_session),
                       st: AppState = Depends(get_state)):
    listing, currency = _resolve(s, body)
    check(s, st.provider, add=[_core(body, currency, None)])
    t = models.Transaction()
    _apply(t, body, listing, currency)
    s.add(t)
    s.commit()
    st.touch()
    s.refresh(t)
    return to_out(t)


@router.put("/{tx_id}", response_model=schemas.TransactionOut)
def update_transaction(tx_id: int, body: schemas.TransactionIn, s: Session = Depends(get_session),
                       st: AppState = Depends(get_state)):
    t = s.get(models.Transaction, tx_id)
    if t is None:
        raise HTTPException(404, "Transaction introuvable.")
    listing, currency = _resolve(s, body)
    check(s, st.provider, add=[_core(body, currency, tx_id)], remove_ids={tx_id})
    _apply(t, body, listing, currency)
    s.commit()
    st.touch()
    s.refresh(t)
    return to_out(t)


@router.delete("/{tx_id}", status_code=204)
def delete_transaction(tx_id: int, s: Session = Depends(get_session), st: AppState = Depends(get_state)):
    t = s.get(models.Transaction, tx_id)
    if t is None:
        raise HTTPException(404, "Transaction introuvable.")
    check(s, st.provider, remove_ids={tx_id})
    s.delete(t)
    s.commit()
    st.touch()
