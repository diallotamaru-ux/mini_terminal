"""
API Valorisation (DCF inversé), sur des cours et des comptes fixés à la main.

AAA.PA (EUR, IFRS proposée) : trois exercices identiques, FCFF = 1 000 − 200 + 50 × 0,75 − 30 = 807,5 M ;
VE = 110 × 100 M + 600 M − 300 M + 20 M = 11 320 M ; k commun = 3 % (taux long de test) + 5 % = 8 %.
USX (USD, US GAAP proposée) : charge d'intérêts manquante sur le dernier exercice -> bloquée.
BBB.PA : ETF -> exclu.
"""

from __future__ import annotations

import pandas as pd
import pytest

from terminal import dcf
from terminal.errors import ProviderUnavailable

from .conftest import days_ago, post_tx

M = 1e6
YEARS = pd.to_datetime(["2023-12-31", "2024-12-31", "2025-12-31"])


def rows(**fields):
    return {f: pd.Series(v if isinstance(v, list) else [v] * 3, index=YEARS, dtype=float) for f, v in fields.items()}


BASE = dict(ocf=1000 * M, capex=-200 * M, interest_expense=50 * M, pretax_income=800 * M, tax_provision=200 * M,
            sbc=30 * M, total_debt=600 * M, lease_liabilities=100 * M, cash_sti=300 * M, minority_interest=20 * M,
            diluted_shares=100 * M, revenue=[4000 * M, 4400 * M, 4840 * M])


@pytest.fixture
def vclient(client, provider):
    provider.fundamental_data = {
        "AAA.PA": {"currency": "EUR", "sector": "Industrials", "industry": "Aerospace & Defense", "rows": rows(**BASE)},
        "USX": {"currency": "USD", "industry": "Software - Application",
                "rows": rows(**{**BASE, "minority_interest": 0.0,
                                "interest_expense": [50 * M, 50 * M, float("nan")]})},
        "BBB.PA": {"currency": "EUR", "quote_type": "ETF"},
    }
    acc = client.post("/api/accounts", json={"name": "CTO", "kind": "CTO", "cash_mode": "titres_seuls"}).json()
    for t, cls in (("AAA.PA", "action"), ("USX", "action"), ("BBB.PA", "etf")):
        assert client.post("/api/listings", json={"ticker": t, "asset_class": cls}).status_code == 201
    for t, fx in (("AAA.PA", None), ("USX", "0.9"), ("BBB.PA", None)):
        body = dict(account_id=acc["id"], date=days_ago(30), type="ACHAT", ticker=t, quantity="10", price="50")
        if fx:
            body["fx_rate"] = fx
        assert post_tx(client, **body).status_code == 201
    return client


EV = 110 * 100 * M + 600 * M - 300 * M + 20 * M


def settings(c, **kw):
    """Réglages actuels, références remplacées par une cotation connue du fournisseur de test."""
    s = c.get("/api/settings").json()["settings"]
    ref = {"ticker": "AAA.PA", "name": "Réf", "currency": "EUR", "withholding": "0"}
    return {**s, "reference_1": ref, "reference_2": ref, **kw}


def test_fiche_by_hand(vclient):
    v = vclient.get("/api/valuation/AAA.PA").json()
    assert v["status"] == "ok" and v["missing"] == []
    assert v["fcff0"] == pytest.approx(807.5 * M) and v["tax_rate"] == pytest.approx(0.25)
    assert v["ev"]["ev"] == pytest.approx(EV) and v["ev"]["market_cap"] == pytest.approx(11000 * M)
    assert "IFRS 16" in v["ev"]["debt_rule"]
    kc = v["k_common"]
    assert kc["k"] == pytest.approx(0.08) and "3,00 %" in kc["detail"] and "Taux longs de test" in kc["detail"]
    assert v["k_used"]["label"] == "commun EUR" and v["g"] == kc["g"]
    # g vérifie l'équation : la valeur actualisée du FCFF au taux g égale la VE.
    assert dcf.dcf_value(807.5 * M, v["g"], 0.08, 10, 0.02) == pytest.approx(EV, rel=1e-5)
    assert v["sentence"].startswith("Le prix actuel suppose une croissance du flux disponible de ")
    assert v["growth_revenue"] == {"value": pytest.approx(0.10), "status": "ok", "years": 2, "n_points": 3,
                                   "start": "2023-12-31", "end": "2025-12-31"}
    assert v["growth_fcff"]["value"] == pytest.approx(0.0, abs=1e-9)
    assert len(v["sensitivity"]) == 5 and v["sensitivity"][2][2]["g"] == pytest.approx(v["g"], abs=1e-6)
    assert v["k_capm"]["k"] is None and v["k_capm"]["error"]          # pas de référence chez le fournisseur de test
    assert v["profile"]["standard"] == "ifrs" and v["profile"]["standard_proposed"]
    assert any("Norme comptable proposée" in w for w in v["warnings"])
    cell = v["years"][-1]["values"]["ocf"]
    assert cell == {"value": "1000000000.0", "manual": False, "note": None, "entered_at": None}
    assert v["years"][-1]["fcff"] == pytest.approx(807.5 * M)
    assert any(s["name"] == "Comptes de test (comptes annuels)" for s in v["meta"]["sources"])
    assert any(s["name"] == "Taux longs de test" for s in v["meta"]["sources"])


def test_summary_sorted_and_reasons(vclient):
    b = vclient.get("/api/valuation").json()
    assert [r["ticker"] for r in b["rows"]] == ["AAA.PA"]
    assert b["rows"][0]["ev_multiple"] == pytest.approx(EV / (807.5 * M), abs=0.01)
    others = {r["ticker"]: r for r in b["others"]}
    assert others["USX"]["status"] == "bloquee" and others["BBB.PA"]["status"] == "exclue"
    assert "Fonds indiciel" in others["BBB.PA"]["reason"]
    assert [r["ticker"] for r in b["others"]] == ["USX", "BBB.PA"]            # bloquées avant exclues


def test_blocked_then_manual_entry_then_delete(vclient):
    v = vclient.get("/api/valuation/USX").json()
    assert v["status"] == "bloquee" and [(m["fiscal_end"], m["field"]) for m in v["missing"]] == [
        ("2025-12-31", "interest_expense")]
    assert v["years"][-1]["values"]["interest_expense"]["value"] is None          # manquant, jamais 0
    assert v["profile"]["standard"] == "us_gaap"
    r = vclient.put("/api/valuation/USX/fundamentals",
                    json={"fiscal_end": "2025-12-31", "field": "interest_expense", "value": "50000000",
                          "note": "rapport annuel 2025, p. 42"})
    assert r.status_code == 200
    v = r.json()
    assert v["status"] == "ok" and v["fcff0"] == pytest.approx(807.5 * M)
    cell = v["years"][-1]["values"]["interest_expense"]
    assert cell["manual"] and cell["note"] == "rapport annuel 2025, p. 42" and cell["value"] == "50000000"
    assert "hors dettes locatives" in v["ev"]["debt_rule"]                       # US GAAP
    assert any(r["manual"] for r in vclient.get("/api/valuation").json()["rows"] if r["ticker"] == "USX")
    r = vclient.delete("/api/valuation/USX/fundamentals/2025-12-31/interest_expense")
    assert r.status_code == 200 and r.json()["status"] == "bloquee"
    assert vclient.delete("/api/valuation/USX/fundamentals/2025-12-31/interest_expense").status_code == 404


def test_manual_entry_can_add_a_year(vclient):
    r = vclient.put("/api/valuation/AAA.PA/fundamentals",
                    json={"fiscal_end": "2022-12-31", "field": "revenue", "value": "3000000000"})
    v = r.json()
    assert v["years"][0]["fiscal_end"] == "2022-12-31" and v["years"][0]["values"]["revenue"]["manual"]
    assert v["years"][0]["values"]["ocf"]["value"] is None
    assert v["growth_revenue"]["years"] == 3 and v["growth_revenue"]["n_points"] == 4


def test_accept_interest_approximation_is_remembered(vclient):
    r = vclient.put("/api/valuation/USX/profile", json={"accept_interest_approx": True})
    assert r.status_code == 200
    v = vclient.get("/api/valuation/USX").json()
    assert v["status"] == "ok" and v["profile"]["accept_interest_approx"]
    assert v["fcff0"] == pytest.approx(770 * M)                                   # OCF − capex − SBC
    assert any("g implicite est surestimé" in w for w in v["warnings"])
    row = next(r for r in vclient.get("/api/valuation").json()["rows"] if r["ticker"] == "USX")
    assert row["approximations"]


def test_profile_hypotheses_and_custom_k(vclient):
    r = vclient.put("/api/valuation/AAA.PA/profile", json={"k": "0.01"})
    assert r.status_code == 422 and "strictement supérieur" in r.json()["detail"]
    v = vclient.put("/api/valuation/AAA.PA/profile",
                    json={"k": "0.10", "horizon": 5, "standard": "ifrs", "interest_class": "financement"}).json()
    assert v["k_used"]["label"] == "personnalisé" and v["k_used"]["k"] == pytest.approx(0.10)
    assert v["fcff0"] == pytest.approx(770 * M) and "financement" in v["fcff_rule"]
    assert not v["profile"]["standard_proposed"] and set(v["profile"]["custom"]) == {"horizon", "k"}
    assert dcf.dcf_value(770 * M, v["g"], 0.10, 5, 0.02) == pytest.approx(EV, rel=1e-5)
    row = vclient.get("/api/valuation").json()["rows"][0]
    assert row["k"] == pytest.approx(0.08) and row["k_label"] == "commun EUR"    # récapitulatif : k commun


def test_financial_override_excludes(vclient):
    v = vclient.put("/api/valuation/AAA.PA/profile", json={"financial": True}).json()
    assert v["status"] == "exclue" and "Banque ou assurance" in v["reason"]


def test_unknown_or_not_held(vclient):
    assert vclient.get("/api/valuation/ZZZ").status_code == 404
    assert vclient.put("/api/valuation/ZZZ/profile", json={}).status_code == 404


def test_long_yield_unavailable_then_manual_k(vclient, rates):
    rates.down = True
    v = vclient.get("/api/valuation/AAA.PA").json()
    assert v["status"] == "impossible" and "Taux long EUR indisponible" in v["reason"]
    row = next(r for r in vclient.get("/api/valuation").json()["others"] if r["ticker"] == "AAA.PA")
    assert row["status"] == "impossible"
    assert vclient.put("/api/settings", json=settings(vclient, k_manual={"EUR": "0.09"})).status_code == 200
    v = vclient.get("/api/valuation/AAA.PA").json()
    assert v["status"] == "ok" and v["k_common"]["k"] == pytest.approx(0.09)
    assert vclient.put("/api/settings", json=settings(vclient, k_manual={"EURO": "0.09"})).status_code == 422


def test_settings_defaults(vclient):
    s = vclient.get("/api/settings").json()["settings"]
    assert (s["k_mode"], s["erp"], s["g_term"], s["horizon"], s["fcf_years"], s["sbc_deduct"]) == \
        ("devise", "0.05", "0.02", 10, 3, True)
    v = vclient.put("/api/settings", json=settings(vclient, horizon=5, fcf_years=1)).json()["settings"]
    assert v["horizon"] == 5
    assert vclient.get("/api/valuation/AAA.PA").json()["fcf_window"] == ["2025-12-31"]


def test_fundamentals_cache(vclient, provider):
    vclient.get("/api/valuation/AAA.PA")
    provider.calls.clear()
    vclient.put("/api/valuation/AAA.PA/profile", json={"horizon": 8})            # nouvelle révision, même cache
    assert "FUND:AAA.PA" not in provider.calls


def test_fundamentals_cache_served_when_provider_down(provider):
    import datetime as dt

    from backend.app.db import Database
    from backend.app.market import CachedProvider

    db = Database("sqlite://")
    db.create_all()
    provider.fundamental_data = {"AAA.PA": {"currency": "EUR", "rows": rows(**BASE)}}
    now = [dt.datetime(2026, 10, 1, tzinfo=dt.timezone.utc)]
    cp = CachedProvider(provider, db.sessionmaker, now=lambda: now[0])
    first = cp.fundamentals("AAA.PA")
    assert first.table.loc["2025-12-31", "ocf"] == 1000 * M and first.source == "Comptes de test"
    assert first.table["fcf_reported"].isna().all()                             # absent reste absent
    now[0] += dt.timedelta(days=8)                                               # cache périmé
    provider.down.add("AAA.PA")
    again = cp.fundamentals("AAA.PA")
    assert "cache du 2026-10-01" in again.source and again.table.equals(first.table)
    provider.down.add("USX")
    with pytest.raises(ProviderUnavailable):
        cp.fundamentals("USX")                                                   # ni fournisseur ni cache


def test_demo_capm_and_k_mode():
    """Démo (cours simulés) : β de Dimson calculable, k MEDAF affiché à côté du k commun, et retenu en mode MEDAF."""
    from fastapi.testclient import TestClient

    from backend.app.config import Settings
    from backend.app.main import create_app
    from terminal.marketdata.simulated import SimulatedProvider

    with TestClient(create_app(Settings(demo=True), provider=SimulatedProvider(), database_url="sqlite://")) as c:
        v = c.get("/api/valuation/ASML.AS").json()
        assert v["meta"]["simulated"] and v["status"] == "ok"
        assert v["profile"]["standard"] == "us_gaap" and not v["profile"]["standard_proposed"]
        capm = v["k_capm"]
        assert capm["k"] is not None and capm["g"] is not None and "Blume" in capm["detail"]
        assert v["k_used"]["label"] == "commun EUR"
        mc = c.get("/api/valuation/MC.PA").json()
        assert mc["status"] == "ok" and mc["years"][-1]["values"]["sbc"]["manual"]
        assert c.get("/api/valuation/AAPL").json()["status"] == "bloquee"
        s = c.get("/api/settings").json()["settings"]
        assert c.put("/api/settings", json={**s, "k_mode": "medaf"}).status_code == 200
        v = c.get("/api/valuation/ASML.AS").json()
        assert v["k_used"]["label"] == "MEDAF" and v["g"] == capm["g"]
        rows = c.get("/api/valuation").json()["rows"]
        assert all(r["k_label"].startswith("commun") for r in rows)          # le récapitulatif reste au k commun
        assert [r["g"] for r in rows] == sorted((r["g"] for r in rows), reverse=True)
