"""Import CSV, cache des cours en base, type DecimalText, mode démo."""

from __future__ import annotations

import datetime as dt
from decimal import Decimal
from pathlib import Path

import pandas as pd
import pytest
from fastapi.testclient import TestClient
from sqlalchemy import text

from backend.app.config import Settings
from backend.app.db import Database
from backend.app.main import create_app
from backend.app.market import CachedProvider
from backend.app.services.csv_import import parse_date, parse_decimal
from terminal.errors import ProviderUnavailable
from terminal.marketdata.simulated import SimulatedProvider

from .conftest import FixedProvider, days_ago

EXAMPLE = Path(__file__).resolve().parents[2] / "examples" / "transactions_exemple.csv"
HEADER = "date;compte;type;ticker;isin;quantite;prix;montant;frais;devise;taux_change;retenue;note\n"


def upload(client, content: str | bytes, dry_run: bool = True):
    data = content.encode("utf-8") if isinstance(content, str) else content
    return client.post(f"/api/imports/csv?dry_run={str(dry_run).lower()}",
                       files={"file": ("t.csv", data, "text/csv")})


# ---------------------------------------------------------------------------
# Analyse des champs
# ---------------------------------------------------------------------------

@pytest.mark.parametrize("raw,expected", [
    ("1 234,56", "1234.56"), ("1.234,56", "1234.56"), ("1,234.56", "1234.56"), ("0,00235", "0.00235"),
    ("12", "12"), (" 1 000,5 €", "1000.5"), ("", None), (None, None),
])
def test_parse_decimal(raw, expected):
    assert parse_decimal(raw) == (None if expected is None else Decimal(expected))


@pytest.mark.parametrize("raw", ["abc", "1,2,3", "NaN"])
def test_parse_decimal_rejects(raw):
    with pytest.raises(ValueError):
        parse_decimal(raw)


def test_parse_date_formats():
    assert parse_date("2024-03-01") == parse_date("01/03/2024") == dt.date(2024, 3, 1)
    with pytest.raises(ValueError):
        parse_date("2024/03/01")


# ---------------------------------------------------------------------------
# Import du fichier d'exemple
# ---------------------------------------------------------------------------

@pytest.fixture
def sim_client():
    app = create_app(Settings(demo=False), provider=SimulatedProvider(), database_url="sqlite://")
    with TestClient(app) as c:
        for name, kind, mode in [("PEA Fortuneo", "PEA", "avec_especes"),
                                 ("CTO Trade Republic", "CTO", "avec_especes"),
                                 ("Crypto", "CRYPTO", "titres_seuls")]:
            c.post("/api/accounts", json={"name": name, "kind": kind, "cash_mode": mode})
        yield c


def test_example_file_preview_then_commit_then_reimport(sim_client):
    content = EXAMPLE.read_bytes()
    r = upload(sim_client, content).json()
    assert r["errors"] == [] and r["n_rows"] == 13 and r["n_valid"] == 13
    assert r["dry_run"] and not r["committed"]
    assert {n["ticker"] for n in r["new_listings"]} == {"PANX.PA", "CW8.PA", "AAPL", "BTC-EUR", "MC.PA"}
    assert sim_client.get("/api/transactions").json() == []          # l'aperçu n'écrit rien

    r = upload(sim_client, content, dry_run=False).json()
    assert r["committed"] and r["errors"] == []
    txs = sim_client.get("/api/transactions").json()
    assert len(txs) == 13
    btc = next(t for t in txs if t["ticker"] == "BTC-EUR")
    assert btc["quantity"] in ("0.00210000", "0.00235000")             # décimale française lue exactement
    listings = {l["ticker"]: l for l in sim_client.get("/api/listings").json()}
    assert listings["AAPL"]["currency"] == "USD" and listings["AAPL"]["instrument"]["asset_class"] == "action"
    assert listings["PANX.PA"]["instrument"]["isin"] == "FR0011871110"

    # Réimporter le même fichier : tout est reconnu comme doublon, rien n'est ajouté.
    r = upload(sim_client, content, dry_run=False).json()
    assert r["n_duplicates"] == 13 and r["n_valid"] == 0
    assert len(sim_client.get("/api/transactions").json()) == 13
    s = sim_client.get("/api/portfolio/summary").json()
    assert s["meta"]["simulated"] is True and s["total_value_eur"] is not None
    # L'exemple est cohérent : aucun compte avec espèces ne passe en solde négatif.
    assert not [w for w in s["meta"]["warnings"] if "négatif" in w]
    # CTO : 2000 - 372 x 0,915 + 0,41 x 0,92 - 813,40 - 0,99 + 191,10 x 0,923 - 200 = 821,99
    cto = next(a for a in s["accounts"] if a["name"] == "CTO Trade Republic")
    assert cto["cash_eur"] == "821.99"


def test_import_is_atomic_and_reports_lines(sim_client):
    csv_ = HEADER + "\n".join([
        "2024-01-05;PEA Fortuneo;DEPOT;;;;;500;;EUR;;;",          # 2 valide
        "2024-13-05;PEA Fortuneo;DEPOT;;;;;500;;EUR;;;",          # 3 date
        "2024-01-05;Inconnu;DEPOT;;;;;500;;EUR;;;",               # 4 compte
        "2024-01-05;PEA Fortuneo;VIREMENT;;;;;500;;EUR;;;",       # 5 type
        "2024-01-05;PEA Fortuneo;ACHAT;bad!;;1;1;;;;;;",          # 6 ticker
        "2024-01-05;PEA Fortuneo;DEPOT;;;;;cinq;;EUR;;;",         # 7 nombre
    ])
    r = upload(sim_client, csv_, dry_run=False).json()
    assert [e["line"] for e in r["errors"]] == [3, 4, 5, 6, 7]
    assert not r["committed"] and sim_client.get("/api/transactions").json() == []


def test_import_ledger_errors_are_mapped_to_lines(sim_client):
    csv_ = HEADER + "\n".join([
        "2024-01-05;Crypto;ACHAT;BTC-EUR;;0,1;40000;;;;;;",
        "2024-01-06;Crypto;VENTE;BTC-EUR;;0,2;40000;;;;;;",       # 3 : vente à découvert
        "2024-01-07;Crypto;DEPOT;;;;;100;;EUR;;;",                # 4 : dépôt en titres seuls
    ])
    r = upload(sim_client, csv_).json()
    lines = {e["line"]: e["message"] for e in r["errors"]}
    assert set(lines) == {3, 4}
    assert "ligne 3" in lines[3] and "détenus" in lines[3] and "titres seuls" in lines[4]


def test_import_isin_conflict_and_format_errors(sim_client):
    upload(sim_client, HEADER + "2024-01-05;Crypto;ACHAT;AAPL;US0378331005;1;100;;;;;;", dry_run=False)
    r = upload(sim_client, HEADER + "2024-01-06;Crypto;ACHAT;AAPL;FR0000000001;1;100;;;;;;").json()
    assert "ISIN" in r["errors"][0]["message"]
    assert upload(sim_client, "date;type\n2024-01-01;DEPOT\n").status_code == 422      # compte absent
    assert upload(sim_client, "date;compte;type;bizarre\n").status_code == 422          # colonne inconnue
    assert upload(sim_client, "").status_code == 422
    r = upload(sim_client, HEADER + "2024-01-05;Crypto;ACHAT;ZZZ;;1;1;;;;;;\n").json()
    assert r["new_listings"][0]["currency"] == "USD"


def test_import_cp1252_and_comma_delimiter(sim_client):
    content = "date,compte,type,montant,note\n2024-01-05,PEA Fortuneo,DÉPÔT,500,épargne\n".encode("cp1252")
    r = upload(sim_client, content).json()
    assert r["errors"] == [] and r["transactions"][0]["type"] == "DEPOT"


def test_import_unknown_asset_class(sim_client):
    csv_ = "date;compte;type;ticker;quantite;prix;classe\n2024-01-05;Crypto;ACHAT;ZZZ;1;1;obligation\n"
    assert "classe" in upload(sim_client, csv_).json()["errors"][0]["message"]


# ---------------------------------------------------------------------------
# Cache des cours
# ---------------------------------------------------------------------------

class Clock:
    def __init__(self):
        self.t = dt.datetime.now(dt.timezone.utc)

    def __call__(self):
        return self.t


@pytest.fixture
def cache():
    db = Database("sqlite://")
    db.create_all()
    inner, clock = FixedProvider(), Clock()
    return CachedProvider(inner, db.sessionmaker, ttl=dt.timedelta(hours=6), now=clock), inner, clock, db


def test_cache_avoids_refetch_and_extends_range(cache):
    c, inner, clock, _ = cache
    a = c.daily_closes("AAA.PA", days_ago(20), days_ago(10))
    b = c.daily_closes("AAA.PA", days_ago(18), days_ago(12))
    assert inner.calls == ["AAA.PA"]
    assert b.closes.tolist() == a.closes.loc[b.closes.index].tolist()
    c.daily_closes("AAA.PA", days_ago(30), days_ago(10))             # plage plus large : refetch
    assert inner.calls == ["AAA.PA", "AAA.PA"]
    c.fx_rates("USD", days_ago(5), days_ago(1))
    c.fx_rates("USD", days_ago(5), days_ago(1))
    assert inner.calls.count("FX:USD") == 1
    assert (c.fx_rates("EUR", days_ago(5), days_ago(1)).closes == 1.0).all()


def test_cache_refreshes_today_after_ttl(cache):
    c, inner, clock, _ = cache
    c.daily_closes("AAA.PA", days_ago(5), days_ago(0))
    c.daily_closes("AAA.PA", days_ago(5), days_ago(0))
    assert inner.calls == ["AAA.PA"]
    clock.t += dt.timedelta(hours=7)
    c.daily_closes("AAA.PA", days_ago(5), days_ago(0))
    assert inner.calls == ["AAA.PA", "AAA.PA"]


def test_cache_served_when_provider_down(cache):
    c, inner, clock, _ = cache
    c.daily_closes("AAA.PA", days_ago(5), days_ago(0))
    clock.t += dt.timedelta(days=1)
    inner.down.add("AAA.PA")
    s = c.daily_closes("AAA.PA", days_ago(5), days_ago(0))
    assert "fournisseur indisponible" in s.source and not s.closes.empty
    with pytest.raises(ProviderUnavailable):
        c.daily_closes("DOWN.PA", days_ago(5), days_ago(0))            # aucun cache


def test_cache_invalidated_when_provider_changes(cache):
    c, inner, clock, db = cache
    c.daily_closes("AAA.PA", days_ago(5), days_ago(1))
    other = CachedProvider(SimulatedProvider(), db.sessionmaker)
    s = other.daily_closes("AAA.PA", days_ago(5), days_ago(1))
    assert s.simulated and s.closes.iloc[-1] != 100.0


def test_decimal_text_is_exact():
    db = Database("sqlite://")
    db.create_all()
    from backend.app import models
    with db.sessionmaker() as s:
        s.add(models.MarketBar(symbol="X", date=dt.date(2024, 1, 1), value=Decimal("0.1")))
        s.commit()
        assert s.execute(text("SELECT value FROM market_bars")).scalar() == "0.1"
        assert s.get(models.MarketBar, ("X", dt.date(2024, 1, 1))).value == Decimal("0.1")
        s.add(models.MarketBar(symbol="Y", date=dt.date(2024, 1, 1), value=0.1))
        with pytest.raises(Exception, match="Decimal"):
            s.commit()
        s.rollback()
        s.add(models.MarketBar(symbol="Z", date=dt.date(2024, 1, 1), value=Decimal("NaN")))
        with pytest.raises(Exception, match="NaN"):
            s.commit()


# ---------------------------------------------------------------------------
# Mode démo
# ---------------------------------------------------------------------------

def test_demo_mode_seeds_once_and_is_flagged():
    from backend.app import demo
    app = create_app(Settings(demo=True), database_url="sqlite://")
    with TestClient(app) as c:
        accounts = c.get("/api/accounts").json()
        assert len(accounts) == 3 and {a["cash_mode"] for a in accounts} == {"avec_especes", "titres_seuls"}
        s = c.get("/api/portfolio/summary").json()
        assert s["meta"]["simulated"] is True and s["complete"] is True
        assert s["meta"]["warnings"] == []          # jeu de démo cohérent : aucun solde négatif
        adj = c.get("/api/portfolio/positions").json()["split_adjustments"]
        assert [(a["ticker"], a["quantity_before"], a["quantity_after"]) for a in adj] == [("NVDA", "2", "20")]
        assert c.get("/api/meta").json()["simulated"] is True
        st = app.state.mt
        with st.db.sessionmaker() as sess:
            assert demo.seed(sess, st.provider) is False


def test_demo_on_file_database(tmp_path):
    # Base fichier (et non en mémoire) : plusieurs connexions, comme en production.
    # Régression : le pré-remplissage et le calcul bloquaient la base (« database is locked »).
    app = create_app(Settings(demo=True), database_url=f"sqlite:///{(tmp_path / 'd.db').as_posix()}")
    with TestClient(app) as c:
        assert c.get("/api/portfolio/summary").status_code == 200
        assert c.get("/api/portfolio/performance").status_code == 200
        assert c.get("/api/portfolio/history").status_code == 200      # instantané réutilisé, sans session


def test_split_cache(cache):
    from terminal.splits import Split
    c, inner, clock, _ = cache
    inner.split_data["AAA.PA"] = [Split("AAA.PA", dt.date(2024, 6, 10), 10, 1)]
    assert c.splits("AAA.PA")[0].numerator == 10
    assert c.splits("AAA.PA")[0].numerator == 10
    assert inner.calls.count("SPLITS:AAA.PA") == 1                  # relu en base
    clock.t += dt.timedelta(hours=7)                                # après le TTL : retéléchargé
    inner.split_data["AAA.PA"].append(Split("AAA.PA", dt.date(2025, 1, 2), 2, 1))
    assert len(c.splits("AAA.PA")) == 2 and inner.calls.count("SPLITS:AAA.PA") == 2
    clock.t += dt.timedelta(hours=7)
    inner.down.add("AAA.PA")                                        # panne : cache servi
    assert len(c.splits("AAA.PA")) == 2
    with pytest.raises(ProviderUnavailable):
        c.splits("DOWN.PA")                                         # panne sans cache
    assert c.splits("BBB.PA") == []


def test_dividend_cache(cache):
    c, inner, clock, _ = cache
    inner.dividend_data["AAA.PA"] = pd.Series([1.5], index=[pd.Timestamp(days_ago(20))])
    a = c.dividends("AAA.PA", days_ago(30), days_ago(5))
    b = c.dividends("AAA.PA", days_ago(25), days_ago(10))
    assert a.closes.tolist() == b.closes.tolist() == [1.5]
    assert inner.calls.count("DIV:AAA.PA") == 1
    assert c.dividends("BBB.PA", days_ago(30), days_ago(5)).closes.empty


def test_rate_cache_and_outage():
    from backend.app.market import CachedRates
    from terminal.marketdata.rates import SimulatedRates

    class Counting(SimulatedRates):
        calls = 0
        down = False

        def overnight(self, series, start, end):
            Counting.calls += 1
            if Counting.down:
                raise ProviderUnavailable("bce", "panne")
            return super().overnight(series, start, end)

    db = Database("sqlite://")
    db.create_all()
    clock = Clock()
    c = CachedRates(Counting(), db.sessionmaker, ttl=dt.timedelta(hours=6), now=clock)
    a = c.overnight("estr", dt.date(2024, 1, 1), dt.date(2024, 3, 31))
    b = c.overnight("estr", dt.date(2024, 2, 1), dt.date(2024, 2, 29))
    assert Counting.calls == 1 and b.closes.tolist() == a.closes.loc["2024-02"].tolist() and b.simulated
    clock.t += dt.timedelta(days=2)
    Counting.down = True
    s = c.overnight("estr", dt.date(2024, 1, 1), dt.date(2025, 1, 31))          # plage plus large, panne
    assert "fournisseur indisponible" in s.source
    with pytest.raises(ProviderUnavailable):
        c.overnight("eonia", dt.date(2018, 1, 1), dt.date(2018, 2, 1))          # aucun cache
