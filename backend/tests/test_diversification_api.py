"""
API Diversification et simulateur, sur des cours simulés.

Deux tickers ont un historique tronqué :
- ZNEW : cours depuis 200 jours seulement (moins de 52 semaines) -> exclu ;
- ZPART : cours depuis 500 jours (environ 71 semaines) -> gardé, ligne partielle sur 3 ans.
"""

from __future__ import annotations

import datetime as dt

import pandas as pd
import pytest
from fastapi.testclient import TestClient

from backend.app.config import Settings
from backend.app.main import create_app
from terminal.marketdata.base import PriceSeries
from terminal.marketdata.simulated import SimulatedProvider

from .conftest import FixedRates, days_ago, post_tx

START = {"ZNEW": days_ago(200), "ZPART": days_ago(500)}


class Truncated(SimulatedProvider):
    def daily_closes(self, ticker, start, end):
        s = super().daily_closes(ticker, start, end)
        if ticker in START:
            return PriceSeries(ticker, s.closes.loc[pd.Timestamp(START[ticker]):], s.source, simulated=True)
        return s


@pytest.fixture
def dclient():
    app = create_app(Settings(demo=False), provider=Truncated(), database_url="sqlite://", rates=FixedRates())
    with TestClient(app) as c:
        cto = c.post("/api/accounts", json={"name": "CTO", "kind": "CTO", "cash_mode": "avec_especes"}).json()
        pea = c.post("/api/accounts", json={"name": "PEA", "kind": "PEA", "cash_mode": "titres_seuls"}).json()
        for t, cls in [("AAPL", "action"), ("MC.PA", "action"), ("CW8.PA", "etf"), ("BTC-EUR", "crypto"),
                       ("ZNEW", "action"), ("ZPART", "action")]:
            assert c.post("/api/listings", json={"ticker": t, "asset_class": cls}).status_code == 201
        d0 = days_ago(4 * 365)
        post_tx(c, account_id=cto["id"], date=d0, type="DEPOT", amount="20000")
        post_tx(c, account_id=cto["id"], date=d0, type="ACHAT", ticker="AAPL", quantity="10", price="100", fx_rate="0.9")
        post_tx(c, account_id=cto["id"], date=d0, type="ACHAT", ticker="MC.PA", quantity="20", price="100")
        post_tx(c, account_id=cto["id"], date=d0, type="ACHAT", ticker="CW8.PA", quantity="5", price="100")
        post_tx(c, account_id=pea["id"], date=d0, type="ACHAT", ticker="CW8.PA", quantity="15", price="100")
        post_tx(c, account_id=pea["id"], date=d0, type="ACHAT", ticker="BTC-EUR", quantity="0.2", price="100")
        post_tx(c, account_id=cto["id"], date=days_ago(150), type="ACHAT", ticker="ZNEW", quantity="5", price="100")
        post_tx(c, account_id=cto["id"], date=days_ago(450), type="ACHAT", ticker="ZPART", quantity="5", price="100")
        yield c


def test_real_weights_contributions_and_volatility(dclient):
    b = dclient.get("/api/diversification?period=3y").json()
    pos = dclient.get("/api/portfolio/positions").json()["positions"]
    summ = dclient.get("/api/portfolio/summary").json()
    kept = {l["ticker"] for l in b["lines"]}
    assert kept == {"AAPL", "MC.PA", "CW8.PA", "BTC-EUR", "ZPART"}
    # Poids réels : valeur de marché EUR à la date de valorisation, CW8 regroupé sur les deux comptes.
    values = {}
    for p in pos:
        if p["ticker"] in kept:
            values[p["ticker"]] = values.get(p["ticker"], 0.0) + float(p["market_value_eur"])
    total = sum(values.values())
    for l in b["lines"]:
        assert l["weight"] == pytest.approx(values[l["ticker"]] / total, abs=1e-6)
    for g in ("ligne", "compte", "classe"):
        assert sum(i["contribution"] for i in b["contributions"][g]) == pytest.approx(1.0, abs=1e-5)
    # Espèces : sigma_total = (1 - e) x sigma_risqué.
    assert b["sigma_total"] == pytest.approx((1 - b["cash_share"]) * b["sigma_risky"], rel=1e-5)
    assert b["cash_share"] == pytest.approx(float(summ["cash_eur"]) / (float(summ["cash_eur"]) + total), abs=1e-4)
    assert b["estimator"] == "lw_cc" and 0 <= b["shrinkage"] <= 1
    assert 1 <= b["enb_pca"] <= b["n_lines"] and 1 <= b["enb_mt"] <= b["n_lines"]
    assert len(b["correlation"]["values"]) == b["n_lines"] and b["correlation"]["values"][0][0] == pytest.approx(1.0)
    assert b["meta"]["simulated"] is True and b["text"]


def test_short_line_excluded_partial_line_kept(dclient):
    b = dclient.get("/api/diversification?period=3y").json()
    ex = {e["label"]: e for e in b["excluded"]}
    znew = next(e for e in b["excluded"] if "ZNEW" in e["label"])
    assert znew["n_weeks"] < 52 and "minimum 52" in znew["reason"]
    part = next(l for l in b["lines"] if l["ticker"] == "ZPART")
    assert part["partial"] and 52 <= part["n_weeks"] < b["window_weeks"]
    full = next(l for l in b["lines"] if l["ticker"] == "AAPL")
    assert not full["partial"] and full["n_weeks"] >= b["window_weeks"] - 1      # fenêtre non réduite
    assert b["t_min"] == part["n_weeks"] and b["t_max"] >= b["window_weeks"] - 1
    # Comparaison demandée par le garde-fou : lignes partielles exclues.
    c = dclient.get("/api/diversification?period=3y&partial=exclure").json()
    assert "ZPART" not in {l["ticker"] for l in c["lines"]}
    assert any("comparaison" in e["reason"] for e in c["excluded"]) and c["partial_mode"] == "exclure"
    assert len(ex) == 1


def test_periods_shorter_than_52_weeks_unavailable(dclient):
    b = dclient.get("/api/diversification?period=3y").json()
    ytd_ok = (dt.date.today() - dt.date(dt.date.today().year - 1, 12, 31)).days >= 364
    assert b["available_periods"]["ytd"] is ytd_ok
    if not ytd_ok:
        r = dclient.get("/api/diversification?period=ytd")
        assert r.status_code == 422 and "52 semaines" in r.json()["detail"]


def test_simulator(dclient):
    sim = lambda **kw: dclient.post("/api/diversification/simulate", json={"period": "3y", **kw})
    # Ajouter 0 % ne change rien, dans les deux modes.
    for mode in ("frais", "realloc"):
        b = sim(ticker="MC.PA", pct=0, mode=mode).json()
        assert b["before"] == b["after"]
        assert all(c["before"] == c["after"] for c in b["contributions"])
    # Argent frais 20 % sur MC.PA : w' = (w + 0,2) / 1,2.
    b = sim(ticker="MC.PA", pct=20, mode="frais").json()
    mc = next(c for c in b["contributions"] if "MC.PA" in c["key"] or c["label"].startswith("MC.PA"))
    assert mc["weight_after"] == pytest.approx((mc["weight_before"] + 0.2) / 1.2, abs=1e-6)
    assert "(1 + x)" in b["formula"] and "pas un conseil" in b["disclaimer"]
    assert sum(c["after"] for c in b["contributions"]) == pytest.approx(1.0, abs=1e-5)
    # Nouveau ticker avec historique suffisant : poids nul avant, 1/6 après 20 % d'argent frais.
    b = sim(ticker="ASML.AS", pct=20, mode="frais").json()
    new = next(c for c in b["contributions"] if c["key"] == "ASML.AS")
    assert new["weight_before"] == 0 and new["weight_after"] == pytest.approx(0.2 / 1.2, abs=1e-6)   # arrondi API
    assert b["notes"] and b["drawdown_start"] is not None
    # Erreurs explicites : ticker inconnu, historique trop court (ligne exclue), pourcentage hors bornes.
    assert sim(ticker="pas un ticker!", pct=10).status_code == 422
    r = sim(ticker="ZNEW", pct=10)
    assert r.status_code == 422 and "exclu" in r.json()["detail"]
    assert sim(ticker="MC.PA", pct=150).status_code == 422
    # Rien n'est écrit : les transactions sont inchangées.
    assert len(dclient.get("/api/transactions").json()) == 8              # les 8 de la fixture


def test_covariance_setting(dclient):
    s = dclient.get("/api/settings").json()["settings"]
    assert s["covariance"] == "lw_cc"
    s["covariance"] = "lw_id"
    assert dclient.put("/api/settings", json=s).status_code == 200
    assert dclient.get("/api/diversification?period=3y").json()["estimator"] == "lw_id"
    s["covariance"] = "empirique"
    dclient.put("/api/settings", json=s)
    b = dclient.get("/api/diversification?period=3y").json()
    assert b["estimator"] == "empirique" and b["shrinkage"] is None


def test_empty_portfolio(client):
    assert client.get("/api/diversification").status_code == 422
