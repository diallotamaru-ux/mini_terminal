"""
API Risque, Réglages et périodes de la page Performance, sur des cours connus.

Cas de référence : compte « titres seuls », 10 AAA.PA achetées à 100 il y a 400 jours.
Cours de AAA.PA (paliers) : 100 jusqu'à J-300, puis 105, 98 (J-200), 110 (J-100), 104 (J-50), 112 (J0).
Il y a un an (J-365), le cours valait 100 : TWR sur 1 an = 112 / 100 - 1 = 12 %.
"""

from __future__ import annotations

import pytest

from backend.app import schemas
from backend.app.services.portfolio import tri_twr_gap

from .conftest import days_ago, post_tx

STEPS = [(400, 100.0), (300, 105.0), (200, 98.0), (100, 110.0), (50, 104.0), (0, 112.0)]
SAME = {"reference_1": {"ticker": "AAA.PA", "name": "AAA", "currency": "EUR", "withholding": "0"},
        "reference_2": {"ticker": "USX", "name": "USX en EUR", "currency": "USD", "withholding": "0.15"},
        "rf_mode": "estr", "rf_fixed_rate": None, "rolling_window": 21}


@pytest.fixture
def held(client, provider):
    provider.levels["AAA.PA"] = STEPS
    provider.levels["USX"] = [(400, 20.0)]           # la référence doit couvrir toute la période
    acc = client.post("/api/accounts", json={"name": "PEA", "kind": "PEA", "cash_mode": "titres_seuls"}).json()
    client.post("/api/listings", json={"ticker": "AAA.PA", "asset_class": "etf"})
    client.post("/api/listings", json={"ticker": "USX", "asset_class": "action"})
    post_tx(client, account_id=acc["id"], date=days_ago(400), type="ACHAT", ticker="AAA.PA", quantity="10",
            price="100")
    r = client.put("/api/settings", json=SAME)
    assert r.status_code == 200, r.json()
    return acc


def test_settings_defaults_and_validation(client):
    d = client.get("/api/settings").json()["settings"]
    assert d["reference_1"]["ticker"] == "QQQ" and d["reference_1"]["withholding"] == "0.15"
    assert d["reference_2"]["ticker"] == "IWDA.AS" and d["rf_mode"] == "estr" and d["rolling_window"] == 63
    bad = {**SAME, "reference_1": {**SAME["reference_1"], "ticker": "NOPE"}}
    assert client.put("/api/settings", json=bad).json()["kind"] == "ticker_inconnu"
    bad = {**SAME, "reference_1": {**SAME["reference_1"], "currency": "USD"}}
    r = client.put("/api/settings", json=bad)
    assert r.status_code == 422 and "cote en EUR" in r.json()["detail"]
    assert client.put("/api/settings", json={**SAME, "rf_mode": "fixe"}).status_code == 422
    assert client.put("/api/settings", json={**SAME, "rolling_window": 5}).status_code == 422
    bad = {**SAME, "reference_2": {**SAME["reference_2"], "withholding": "0.9"}}
    assert client.put("/api/settings", json=bad).status_code == 422
    r = client.put("/api/settings", json=SAME).json()
    assert any("moins de 3 ans" in w for w in r["warnings"])     # cours de test : 60 jours d'historique


def test_risk_portfolio_identical_to_reference(client, held):
    b = client.get("/api/risk?period=1y").json()
    assert b["period_label"] == "1 an" and b["base_date"] == days_ago(365).isoformat()
    rows = {r["name"]: r for r in b["rows"]}
    p, ref = rows["Portefeuille"], rows["AAA"]
    assert p["total_return"] == pytest.approx(0.12) and ref["total_return"] == pytest.approx(0.12)
    # Série identique à la référence : bêta 1, corrélation 1, tracking error nulle, IR non défini.
    assert p["beta"] == pytest.approx(1.0) and p["correlation"] == pytest.approx(1.0)
    assert p["tracking_error"] == pytest.approx(0.0, abs=1e-12) and p["information_ratio"] is None
    assert p["alpha"] == pytest.approx(0.0, abs=1e-9)
    assert p["sharpe"] == pytest.approx(ref["sharpe"]) and p["sharpe_ci"] == ref["sharpe_ci"]
    assert ref["is_reference"] and ref["beta"] is None
    # Taux sans risque : €STR seul sur la période, source et date indiquées.
    assert b["risk_free"]["label"].startswith("€STR du ") and b["risk_free"]["last_value"] == 2.0
    assert b["short_history"] and "1,0 ans" in b["short_history"]
    assert b["available_periods"] == {"origine": True, "ytd": True, "1y": True, "3y": False, "5y": False}
    # Courbes : base 100 à la date de base, 112 aujourd'hui ; drawdown maximal 98/105 - 1.
    base100 = {c["name"]: c["values"] for c in b["base100"]}
    assert base100["Portefeuille"][0] == 100.0 and base100["Portefeuille"][-1] == pytest.approx(112.0)
    assert min(v for v in b["drawdown"][0]["values"] if v is not None) == pytest.approx(98 / 105 - 1, abs=1e-5)
    assert len(b["dates"]) == len(base100["AAA"]) and b["rolling_window"] == 21


def test_reference_converted_with_fx_and_net_dividend(client, held, provider):
    # USX : 20 $ constant, change 0,9 constant, dividende de 1 $ il y a 100 jours, retenue 15 %.
    # Rendement de la référence = 1 x 0,85 / 20 = 4,25 % (le change constant n'ajoute rien).
    import pandas as pd
    provider.dividend_data["USX"] = pd.Series([1.0], index=[pd.Timestamp(days_ago(100))])
    rows = {r["name"]: r for r in client.get("/api/risk?period=1y&reference=1").json()["rows"]}
    assert rows["USX en EUR"]["total_return"] == pytest.approx(0.0425)


def test_risk_period_errors_and_fixed_rate(client, held, rates):
    r = client.get("/api/risk?period=5y")
    assert r.status_code == 422 and "plus longue que l'historique" in r.json()["detail"]
    assert client.get("/api/risk?period=10y").status_code == 422
    client.put("/api/settings", json={**SAME, "rf_mode": "fixe", "rf_fixed_rate": "3.5"})
    b = client.get("/api/risk?period=1y").json()
    assert b["risk_free"]["label"] == "taux fixe 3,50 %" and b["risk_free"]["source"] == "réglage"
    client.put("/api/settings", json={**SAME, "rf_mode": "zero"})
    assert client.get("/api/risk?period=1y").json()["risk_free"]["label"] == "Taux nul"


def test_risk_free_outage_is_visible(client, held, rates):
    rates.down = True
    b = client.get("/api/risk?period=origine").json()
    assert any("Taux sans risque indisponible" in w for w in b["warnings"])
    assert any("taux nul" in w for w in b["meta"]["warnings"])


def test_eonia_used_before_estr(client, provider, rates):
    # Achat en 2018 : la période depuis l'origine couvre EONIA puis €STR.
    import datetime as dt
    provider.levels["AAA.PA"] = [(3000, 100.0), (0, 120.0)]
    acc = client.post("/api/accounts", json={"name": "PEA", "kind": "PEA", "cash_mode": "titres_seuls"}).json()
    client.post("/api/listings", json={"ticker": "AAA.PA"})
    client.put("/api/settings", json=SAME)
    post_tx(client, account_id=acc["id"], date=dt.date(2018, 3, 1), type="ACHAT", ticker="AAA.PA",
            quantity="1", price="100")
    rf = client.get("/api/risk?period=origine").json()["risk_free"]
    assert [s["name"] for s in rf["segments"]] == ["EONIA", "€STR"]
    assert rf["segments"][0]["end"] == "2019-09-30" and rf["segments"][1]["start"] == "2019-10-01"
    assert rf["label"].startswith("EONIA du 28/02/2018 au 30/09/2019, puis €STR du 01/10/2019")


def test_performance_by_period_and_gap(client, held):
    # Sur 1 an : valeur de base 1 000 (10 x 100), finale 1 120. TWR = TRI = 12 % : écart nul.
    p = client.get("/api/portfolio/performance?period=1y").json()
    assert p["period"] == "1y" and p["base_date"] == days_ago(365).isoformat()
    t = p["total"]
    assert t["twr"]["total"] == pytest.approx(0.12) and t["mwr"]["rate"] == pytest.approx(0.12, abs=1e-6)
    assert abs(t["gap_points"]) < 1e-3 and t["gap_comment"].startswith("Écart faible")
    assert client.get("/api/portfolio/performance?period=3y").status_code == 422
    assert client.get("/api/portfolio/performance").json()["period"] == "origine"


def test_gap_sentences():
    def twr(total, ann):
        return schemas.TwrOut(total=total, annualized=ann, start=None, end=None, days=0, warnings=[])

    def mwr(rate, ann):
        return schemas.MwrOut(rate=rate, annualized=ann, start=None, end=None, days=0, warnings=[])

    # Annualisés : TWR 10 %/an, TRI 8,2 %/an -> -1,8 point par an.
    gap, ann, text = tri_twr_gap(twr(0.5, 0.10), mwr(0.082, True))
    assert gap == pytest.approx(-1.8) and ann and "inférieur de 1,8 point par an" in text
    gap, _, text = tri_twr_gap(twr(0.5, 0.10), mwr(0.13, True))
    assert gap == pytest.approx(3.0) and "dépasse votre TWR de 3,0 points par an" in text
    # Sous un an : comparaison des rendements sur la période.
    gap, ann, text = tri_twr_gap(twr(0.05, None), mwr(0.047, False))
    assert gap == pytest.approx(-0.3) and not ann and "faible" in text and "sur la période" in text
    assert tri_twr_gap(twr(None, None), mwr(0.1, True)) == (None, False, None)
    assert tri_twr_gap(twr(0.05, None), mwr(0.1, True)) == (None, True, None)


def test_empty_portfolio_risk(client):
    assert client.get("/api/risk").status_code == 422
    assert client.get("/api/portfolio/performance?period=1y").status_code == 422
