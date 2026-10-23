from __future__ import annotations

from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy import func, select
from sqlalchemy.orm import Session

from terminal import ledger

from .. import models, schemas
from ..deps import AppState, get_session, get_state
from ..services.ledger_check import check

router = APIRouter(prefix="/api/accounts", tags=["comptes"])


def _out(s: Session, a: models.Account) -> schemas.AccountOut:
    n = s.scalar(select(func.count()).select_from(models.Transaction)
                 .where(models.Transaction.account_id == a.id))
    return schemas.AccountOut(id=a.id, name=a.name, broker=a.broker, kind=a.kind,
                              cash_mode=ledger.CashMode(a.cash_mode), currency=a.currency, n_transactions=n)


def _get(s: Session, account_id: int) -> models.Account:
    a = s.get(models.Account, account_id)
    if a is None:
        raise HTTPException(404, "Compte introuvable.")
    return a


def _name_taken(s: Session, name: str, exclude: int | None = None) -> bool:
    q = select(models.Account).where(func.lower(models.Account.name) == name.lower())
    return any(a.id != exclude for a in s.scalars(q))


@router.get("", response_model=list[schemas.AccountOut])
def list_accounts(s: Session = Depends(get_session)):
    return [_out(s, a) for a in s.scalars(select(models.Account).order_by(models.Account.id))]


@router.post("", response_model=schemas.AccountOut, status_code=201)
def create_account(body: schemas.AccountIn, s: Session = Depends(get_session),
                   st: AppState = Depends(get_state)):
    if _name_taken(s, body.name):
        raise HTTPException(409, f"Un compte « {body.name} » existe déjà.")
    a = models.Account(name=body.name.strip(), broker=body.broker, kind=body.kind,
                       cash_mode=body.cash_mode.value, currency=body.currency)
    s.add(a)
    s.commit()
    st.touch()
    return _out(s, a)


@router.patch("/{account_id}", response_model=schemas.AccountOut)
def update_account(account_id: int, body: schemas.AccountPatch, s: Session = Depends(get_session),
                   st: AppState = Depends(get_state)):
    a = _get(s, account_id)
    if body.name is not None and _name_taken(s, body.name, exclude=a.id):
        raise HTTPException(409, f"Un compte « {body.name} » existe déjà.")
    if body.cash_mode is not None and body.cash_mode.value != a.cash_mode:
        # Changer de convention n'est possible que si l'historique reste cohérent
        # (un compte « titres seuls » ne peut pas contenir de dépôt).
        check(s, accounts=[ledger.Account(a.id, a.name, body.cash_mode, a.currency)])
        a.cash_mode = body.cash_mode.value
    for f in ("name", "broker", "kind"):
        v = getattr(body, f)
        if v is not None:
            setattr(a, f, v)
    s.commit()
    st.touch()
    return _out(s, a)


@router.delete("/{account_id}", status_code=204)
def delete_account(account_id: int, s: Session = Depends(get_session), st: AppState = Depends(get_state)):
    a = _get(s, account_id)
    if _out(s, a).n_transactions:
        raise HTTPException(409, "Ce compte contient des transactions : supprimez-les d'abord.")
    s.delete(a)
    s.commit()
    st.touch()
