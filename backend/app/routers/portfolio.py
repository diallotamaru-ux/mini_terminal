"""Lecture du portefeuille. Chaque réponse porte sa date, ses sources et ses avertissements."""

from __future__ import annotations

import datetime as dt

from fastapi import APIRouter, Depends, File, Query, UploadFile
from sqlalchemy.orm import Session

from .. import schemas
from ..deps import AppState, get_session, get_state
from ..services import portfolio as svc
from ..services.csv_import import import_csv

router = APIRouter(prefix="/api", tags=["portefeuille"])


@router.get("/portfolio/positions", response_model=schemas.PositionsOut)
def positions(as_of: dt.date | None = None, s: Session = Depends(get_session),
              st: AppState = Depends(get_state)):
    snap = st.snapshot(s, as_of)
    return schemas.PositionsOut(meta=snap.meta(), positions=svc.positions_out(snap),
                                split_adjustments=svc.adjustments_out(snap))


@router.get("/portfolio/summary", response_model=schemas.SummaryOut)
def summary(as_of: dt.date | None = None, s: Session = Depends(get_session),
            st: AppState = Depends(get_state)):
    return svc.summary_out(st.snapshot(s, as_of))


@router.get("/portfolio/history", response_model=schemas.HistoryOut)
def history(as_of: dt.date | None = None, s: Session = Depends(get_session),
            st: AppState = Depends(get_state)):
    return svc.history_out(st.snapshot(s, as_of))


@router.get("/portfolio/performance", response_model=schemas.PerformanceOut)
def performance(period: schemas.Period = "origine", as_of: dt.date | None = None,
                s: Session = Depends(get_session), st: AppState = Depends(get_state)):
    return svc.performance_out(st.snapshot(s, as_of), period)


@router.post("/imports/csv", response_model=schemas.ImportReport)
async def import_transactions(file: UploadFile = File(...), dry_run: bool = Query(True),
                              s: Session = Depends(get_session), st: AppState = Depends(get_state)):
    content = await file.read()
    report = import_csv(s, st.provider, content, dry_run=dry_run)
    if report.committed:
        st.touch()
    return report


@router.get("/meta", response_model=schemas.AppMeta)
def meta(st: AppState = Depends(get_state)):
    from .. import __version__
    return schemas.AppMeta(demo=st.settings.demo, provider=st.provider.name,
                           simulated=st.provider.simulated, version=__version__)
