"""API : CRUD, validation, valeurs du portefeuille sur des cours connus."""

from __future__ import annotations

from decimal import Decimal

import pytest

from .conftest import days_ago, post_tx

D = Decimal


# ---------------------------------------------------------------------------
# Comptes et cotations
# ---------------------------------------------------------------------------

def test_account_crud(client):
    r = client.post("/api/accounts", json={"name": "PEA", "kind": "PEA", "cash_mode": "avec_especes"})
    assert r.status_code == 201 and r.json()["n_transactions"] == 0
    assert client.post("/api/accounts", json={"name": "pea", "kind": "PEA",
                                              "cash_mode": "avec_especes"}).status_code == 409
    # La convention est obligatoire : pas de valeur par défaut implicite.
    assert client.post("/api/accounts", json={"name": "X", "kind": "PEA"}).status_code == 422
    aid = r.json()["id"]
    assert client.patch(f"/api/accounts/{aid}", json={"broker": "Fortuneo"}).json()["broker"] == "Fortuneo"
    assert client.delete(f"/api/accounts/{aid}").status_code == 204
    assert client.delete(f"/api/accounts/{aid}").status_code == 404


def test_account_with_transactions_cannot_be_deleted(client, setup):
    post_tx(client, account_id=setup["cash"], date=days_ago(5), type="DEPOT", amount="100")
    assert client.delete(f"/api/accounts/{setup['cash']}").status_code == 409


def test_cash_mode_change_refused_when_history_has_deposits(client, setup):
    post_tx(client, account_id=setup["cash"], date=days_ago(5), type="DEPOT", amount="100")
    r = client.patch(f"/api/accounts/{setup['cash']}", json={"cash_mode": "titres_seuls"})
    assert r.status_code == 422 and "titres seuls" in r.json()["errors"][0]
    # Sans dépôt, le changement est possible.
    r = client.patch(f"/api/accounts/{setup['secu']}", json={"cash_mode": "avec_especes"})
    assert r.status_code == 200 and r.json()["cash_mode"] == "avec_especes"


def test_listing_creation_checks_provider(client):
    r = client.post("/api/listings", json={"ticker": "aaa.pa", "isin": "FR0000000001"})
    assert r.status_code == 201
    body = r.json()
    assert body["ticker"] == "AAA.PA" and body["currency"] == "EUR"
    assert body["instrument"]["isin"] == "FR0000000001" and body["instrument"]["name"] == "Titre AAA.PA"
    assert client.post("/api/listings", json={"ticker": "AAA.PA"}).status_code == 409
    r = client.post("/api/listings", json={"ticker": "NOPE"})
    assert r.status_code == 422 and r.json()["kind"] == "ticker_inconnu"
    r = client.post("/api/listings", json={"ticker": "USX", "currency": "EUR"})
    assert r.status_code == 422 and "USD" in r.json()["detail"]


def test_same_isin_two_listings_share_instrument(client):
    a = client.post("/api/listings", json={"ticker": "AAA.PA", "isin": "FR0000000001"}).json()
    b = client.post("/api/listings", json={"ticker": "BBB.PA", "isin": "FR0000000001"}).json()
    assert a["instrument"]["id"] == b["instrument"]["id"]
    r = client.patch(f"/api/listings/{a['id']}/instrument", json={"asset_class": "etf"})
    assert r.json()["instrument"]["asset_class"] == "etf"
    assert len(client.get("/api/listings").json()) == 2


def test_listing_when_provider_down_requires_currency(client, provider):
    provider.currency.pop("DOWN.PA")
    from terminal.errors import ProviderUnavailable

    def down(t):
        raise ProviderUnavailable("fixe", "panne")
    provider.instrument_info = down
    r = client.post("/api/listings", json={"ticker": "DOWN.PA"})
    assert r.status_code == 503 and r.json()["kind"] == "fournisseur_indisponible"
    r = client.post("/api/listings", json={"ticker": "DOWN.PA", "currency": "EUR"})
    assert r.status_code == 201


# ---------------------------------------------------------------------------
# Transactions
# ---------------------------------------------------------------------------

def test_transaction_validation(client, setup):
    c, s = setup["cash"], setup["secu"]
    r = post_tx(client, account_id=c, date=days_ago(10), type="ACHAT", ticker="AAA.PA",
                quantity="1", price="100")
    assert r.status_code == 201 and r.json()["currency"] == "EUR"
    # Vente à découvert.
    r = post_tx(client, account_id=c, date=days_ago(5), type="VENTE", ticker="AAA.PA", quantity="2", price="100")
    assert r.status_code == 422 and "seulement 1 détenus" in r.json()["errors"][0]
    # Dépôt sur un compte titres seuls.
    r = post_tx(client, account_id=s, date=days_ago(5), type="DEPOT", amount="100")
    assert r.status_code == 422
    # Cotation inconnue, compte inconnu, devise incohérente avec la cotation.
    assert post_tx(client, account_id=c, date=days_ago(5), type="ACHAT", ticker="ZZZ",
                   quantity="1", price="1").status_code == 422
    assert post_tx(client, account_id=999, date=days_ago(5), type="DEPOT", amount="1").status_code == 422
    r = post_tx(client, account_id=c, date=days_ago(5), type="ACHAT", ticker="USX", quantity="1",
                price="1", currency="EUR")
    assert r.status_code == 422 and "USD" in r.json()["errors"][0]


def test_deleting_a_buy_that_a_sale_depends_on_is_refused(client, setup):
    c = setup["cash"]
    buy = post_tx(client, account_id=c, date=days_ago(10), type="ACHAT", ticker="AAA.PA",
                  quantity="2", price="100").json()
    post_tx(client, account_id=c, date=days_ago(5), type="VENTE", ticker="AAA.PA", quantity="2", price="100")
    assert client.delete(f"/api/transactions/{buy['id']}").status_code == 422


def test_update_and_list_transactions(client, setup):
    c = setup["cash"]
    t = post_tx(client, account_id=c, date=days_ago(10), type="DEPOT", amount="100.10").json()
    assert t["amount"] == "100.10"                          # Decimal exact, en chaîne
    body = {"account_id": c, "date": days_ago(9).isoformat(), "type": "DEPOT", "amount": "200"}
    r = client.put(f"/api/transactions/{t['id']}", json=body)
    assert r.status_code == 200 and r.json()["amount"] == "200"
    assert client.put("/api/transactions/9999", json=body).status_code == 404
    assert len(client.get(f"/api/transactions?account_id={c}").json()) == 1
    assert client.delete(f"/api/transactions/{t['id']}").status_code == 204
    assert client.delete(f"/api/transactions/{t['id']}").status_code == 404


# ---------------------------------------------------------------------------
# Portefeuille, sur des cours connus
# ---------------------------------------------------------------------------

def _known_portfolio(client, setup):
    # CTO (avec espèces) : dépôt 2 000 il y a 30 jours, achat 10 AAA à 100 (+1 de frais).
    # AAA cote 100 jusqu'à hier, 110 aujourd'hui.
    # Crypto (titres seuls) : achat 5 USX à 20 USD au taux courtier 0,90. USX cote 20 USD, USD = 0,90 EUR.
    c, s = setup["cash"], setup["secu"]
    post_tx(client, account_id=c, date=days_ago(30), type="DEPOT", amount="2000")
    post_tx(client, account_id=c, date=days_ago(30), type="ACHAT", ticker="AAA.PA", quantity="10",
            price="100", fees="1")
    post_tx(client, account_id=s, date=days_ago(30), type="ACHAT", ticker="USX", quantity="5",
            price="20", fx_rate="0.90")


def test_summary_known_values(client, setup):
    _known_portfolio(client, setup)
    r = client.get("/api/portfolio/summary").json()
    # Titres : 10 x 110 + 5 x 20 x 0,9 = 1 100 + 90 = 1 190. Espèces : 2 000 - 1 001 = 999.
    assert r["securities_eur"] == "1190.00" and r["cash_eur"] == "999.00"
    assert r["total_value_eur"] == "2189.00" and r["complete"] is True
    # PV latente : (1 100 - 1 001) + (90 - 90) = 99.
    assert r["unrealized_eur"] == "99.00"
    # Apports nets : dépôt 2 000 (CTO) + achat 90 (crypto, titres seuls) = 2 090.
    assert r["net_contributions_eur"] == "2090.00"
    by_cur = {i["key"]: i for i in r["by_currency"]}
    assert by_cur["USD"]["value_eur"] == "90.00" and by_cur["EUR"]["value_eur"] == "2099.00"
    assert {i["label"] for i in r["by_class"]} == {"Actions", "Espèces"}
    assert sum(D(i["weight"]) for i in r["by_account"]) == pytest.approx(D(1), abs=D("0.0002"))
    meta = r["meta"]
    assert meta["simulated"] is False and meta["as_of"]
    assert {s["name"] for s in meta["sources"]} == {"Cours de test", "Change de test"}


def test_positions_known_values(client, setup):
    _known_portfolio(client, setup)
    rows = {p["ticker"]: p for p in client.get("/api/portfolio/positions").json()["positions"]}
    a = rows["AAA.PA"]
    assert a["quantity"] == "10" and a["pru"] == "100.1000" and a["price"] == "110.0"
    assert a["market_value_eur"] == "1100.00" and a["unrealized_eur"] == "99.00"
    assert a["unrealized_pct"] == "0.0989" and a["price_stale"] is False
    u = rows["USX"]
    assert u["currency"] == "USD" and u["market_value"] == "100.00" and u["market_value_eur"] == "90.00"
    assert u["cost_eur"] == "90.00" and u["fx_rate"] == "0.9"


def test_performance_known_values(client, setup):
    _known_portfolio(client, setup)
    r = client.get("/api/portfolio/performance").json()
    cto = next(b for b in r["accounts"] if b["name"] == "CTO")
    # Compte : 2 000 apportés, 2 099 aujourd'hui. Le jour de l'achat, la valeur est
    # 999 + 1 000 = 1 999 : r0 = 1999/2000 - 1. Puis +100 le dernier jour.
    assert cto["twr"]["total"] == pytest.approx(2099 / 2000 - 1)
    # Poche titres : apport 1 001, valeur 1 000, puis 1 100 : 1100/1001 - 1.
    assert cto["twr_securities"]["total"] == pytest.approx(1100 / 1001 - 1)
    assert cto["twr"]["annualized"] is None                  # moins d'un an
    assert cto["mwr"]["annualized"] is False
    crypto = next(b for b in r["accounts"] if b["name"] == "Crypto")
    assert crypto["twr_securities"] is None and crypto["twr"]["total"] == pytest.approx(0.0, abs=1e-12)
    assert r["total"]["twr"]["total"] is not None


def test_history_shapes(client, setup):
    _known_portfolio(client, setup)
    h = client.get("/api/portfolio/history").json()
    assert len(h["dates"]) == 31 and len(h["value"]) == 31
    assert h["value"][-1] == pytest.approx(2189.0)
    assert h["net_contributions"][-1] == pytest.approx(2090.0)
    assert {a["name"] for a in h["accounts"]} == {"CTO", "Crypto"}


def test_missing_price_is_reported_not_zero(client, setup, provider):
    # Cotation créée quand le fournisseur répondait, puis panne sur ses cours.
    provider.down.discard("DOWN.PA")
    assert client.post("/api/listings", json={"ticker": "DOWN.PA"}).status_code == 201
    provider.down.add("DOWN.PA")
    post_tx(client, account_id=setup["secu"], date=days_ago(40), type="ACHAT", ticker="DOWN.PA",
            quantity="3", price="10")
    r = client.get("/api/portfolio/summary").json()
    assert r["complete"] is False and r["total_value_eur"] is None
    assert r["missing"] == ["DOWN.PA (Crypto)"]
    assert any("indisponible" in w for w in r["meta"]["warnings"])
    p = client.get("/api/portfolio/positions").json()["positions"][0]
    assert p["market_value_eur"] is None and p["price"] is None
    perf = client.get("/api/portfolio/performance").json()
    assert perf["total"]["twr"]["total"] is None


def test_recent_transaction_price_used_as_fallback(client, setup, provider):
    provider.down.discard("DOWN.PA")
    client.post("/api/listings", json={"ticker": "DOWN.PA"})
    provider.down.add("DOWN.PA")
    post_tx(client, account_id=setup["secu"], date=days_ago(2), type="ACHAT", ticker="DOWN.PA",
            quantity="3", price="10")
    p = client.get("/api/portfolio/positions").json()
    pos = p["positions"][0]
    assert pos["price"] == "10" and pos["price_stale"] is True
    assert pos["price_source"] == "Prix de la dernière transaction"
    assert any(s["name"] == "Prix de la dernière transaction" for s in p["meta"]["sources"])


def test_empty_portfolio(client):
    r = client.get("/api/portfolio/summary").json()
    assert r["total_value_eur"] == "0.00" and r["complete"] is True
    assert client.get("/api/portfolio/history").json()["dates"] == []
    assert client.get("/api/portfolio/performance").json()["total"]["twr"]["total"] is None


def test_snapshot_is_recomputed_after_write(client, setup):
    post_tx(client, account_id=setup["cash"], date=days_ago(3), type="DEPOT", amount="100")
    assert client.get("/api/portfolio/summary").json()["cash_eur"] == "100.00"
    post_tx(client, account_id=setup["cash"], date=days_ago(2), type="DEPOT", amount="50")
    assert client.get("/api/portfolio/summary").json()["cash_eur"] == "150.00"


def test_meta(client):
    m = client.get("/api/meta").json()
    assert m == {"demo": False, "provider": "fixe", "simulated": False, "version": "0.1.0"}
