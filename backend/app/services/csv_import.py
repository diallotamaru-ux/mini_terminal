"""
Import CSV des transactions. Format documenté dans docs/FORMAT_CSV.md.

Deux temps : un aperçu (`dry_run=True`) qui n'écrit rien, puis la validation.
L'import est atomique : si une seule ligne est en erreur, rien n'est écrit.
Une ligne identique à une transaction déjà en base est signalée comme doublon
et ignorée, pour qu'un même fichier puisse être réimporté sans risque.
"""

from __future__ import annotations

import csv
import datetime as dt
import io
import re
import unicodedata
from decimal import Decimal, InvalidOperation

from sqlalchemy import select
from sqlalchemy.orm import Session

from terminal import ledger
from terminal.errors import LedgerError, ProviderUnavailable, UnknownTicker
from terminal.marketdata.base import MarketDataProvider

from .. import models, schemas
from .ledger_check import check
from .portfolio import load_ledger

REQUIRED = ("date", "compte", "type")
COLUMNS = ("date", "compte", "type", "ticker", "isin", "quantite", "prix", "montant", "frais",
           "devise", "taux_change", "retenue", "note", "classe")
_ID_OFFSET = 10 ** 9           # identifiants provisoires des lignes importées


class CsvFormatError(Exception):
    pass


def _norm(s: str) -> str:
    s = unicodedata.normalize("NFKD", s.strip().lower())
    return "".join(c for c in s if not unicodedata.combining(c)).replace(" ", "_")


def parse_decimal(raw: str | None) -> Decimal | None:
    """« 1 234,56 », « 1234.56 », « 1.234,56 » -> Decimal('1234.56'). Vide -> None."""
    if raw is None:
        return None
    s = raw.strip().replace(" ", "").replace(" ", "").replace(" ", "").replace("€", "")
    if not s:
        return None
    if "," in s and "." in s:
        # Le dernier séparateur est le séparateur décimal, l'autre groupe les milliers.
        if s.rfind(",") > s.rfind("."):
            s = s.replace(".", "").replace(",", ".")
        else:
            s = s.replace(",", "")
    else:
        s = s.replace(",", ".")
    try:
        d = Decimal(s)
    except InvalidOperation as e:
        raise ValueError(f"nombre illisible « {raw} »") from e
    if not d.is_finite():
        raise ValueError(f"nombre illisible « {raw} »")
    return d


def parse_date(raw: str) -> dt.date:
    s = raw.strip()
    for fmt in ("%Y-%m-%d", "%d/%m/%Y"):
        try:
            return dt.datetime.strptime(s, fmt).date()
        except ValueError:
            pass
    raise ValueError(f"date illisible « {raw} » (attendu AAAA-MM-JJ ou JJ/MM/AAAA)")


def parse_type(raw: str) -> ledger.TxType:
    s = _norm(raw).upper()
    try:
        return ledger.TxType(s)
    except ValueError:
        raise ValueError(f"type inconnu « {raw} » (ACHAT, VENTE, DIVIDENDE, DEPOT, RETRAIT, FRAIS)") from None


def read_rows(content: bytes) -> list[tuple[int, dict[str, str]]]:
    for enc in ("utf-8-sig", "cp1252"):
        try:
            text = content.decode(enc)
            break
        except UnicodeDecodeError:
            continue
    else:  # pragma: no cover - cp1252 décode presque tout
        raise CsvFormatError("Encodage illisible : enregistrez le fichier en UTF-8.")
    first = text.splitlines()[0] if text.strip() else ""
    if not first:
        raise CsvFormatError("Fichier vide.")
    delim = ";" if ";" in first else "\t" if "\t" in first else ","
    reader = csv.DictReader(io.StringIO(text), delimiter=delim)
    header = {_norm(h): h for h in (reader.fieldnames or []) if h}
    missing = [c for c in REQUIRED if c not in header]
    if missing:
        raise CsvFormatError(f"Colonnes obligatoires absentes : {', '.join(missing)}.")
    unknown = [h for k, h in header.items() if k not in COLUMNS]
    if unknown:
        raise CsvFormatError(f"Colonnes inconnues : {', '.join(unknown)}.")
    rows = []
    for i, raw in enumerate(reader, start=2):              # ligne 1 = en-tête
        row = {k: (raw.get(h) or "").strip() for k, h in header.items()}
        if any(row.values()):
            rows.append((i, row))
    return rows


def _key(t: ledger.Transaction) -> tuple:
    return (t.account_id, t.date, t.type, t.ticker, t.quantity, t.price, t.amount, t.fees)


def import_csv(s: Session, provider: MarketDataProvider, content: bytes,
               dry_run: bool = True) -> schemas.ImportReport:
    rows = read_rows(content)
    errors: list[schemas.ImportRowError] = []
    warnings: list[str] = []
    accounts = {a.name.lower(): a for a in s.scalars(select(models.Account))}
    listings = {l.ticker: l for l in s.scalars(select(models.Listing)).unique()}
    new_listings: dict[str, schemas.NewListing] = {}
    classes: dict[str, str] = {}
    _, _, existing, _ = load_ledger(s)
    existing_keys = {_key(t) for t in existing}

    parsed: list[tuple[int, ledger.Transaction, schemas.TransactionIn]] = []
    n_dup = 0
    for line, r in rows:
        try:
            acc = accounts.get(r["compte"].lower())
            if acc is None:
                raise ValueError(f"compte « {r['compte']} » inconnu : créez-le d'abord")
            kind = parse_type(r["type"])
            ticker = (r.get("ticker") or "").upper() or None
            isin = (r.get("isin") or "").upper() or None
            currency = (r.get("devise") or "").upper() or None
            if ticker:
                listing_cur = None
                if ticker in listings:
                    l = listings[ticker]
                    listing_cur = l.currency
                    if isin and l.instrument.isin and l.instrument.isin != isin:
                        raise ValueError(f"ISIN {isin} différent de celui déjà associé à {ticker} "
                                         f"({l.instrument.isin})")
                elif ticker in new_listings:
                    listing_cur = new_listings[ticker].currency
                else:
                    try:
                        info = provider.instrument_info(ticker)
                    except UnknownTicker:
                        raise ValueError(f"ticker {ticker} inconnu du fournisseur de données") from None
                    except ProviderUnavailable as e:
                        raise ValueError(f"impossible de vérifier {ticker} : {e}") from None
                    new_listings[ticker] = schemas.NewListing(ticker=ticker, isin=isin,
                                                              currency=info.currency, name=info.name)
                    listing_cur = info.currency
                if r.get("classe"):
                    classes[ticker] = _norm(r["classe"])
                currency = currency or listing_cur
            currency = currency or "EUR"
            tin = schemas.TransactionIn(
                account_id=acc.id, date=parse_date(r["date"]), type=kind, ticker=ticker,
                quantity=parse_decimal(r.get("quantite")), price=parse_decimal(r.get("prix")),
                amount=parse_decimal(r.get("montant")), fees=parse_decimal(r.get("frais")) or Decimal(0),
                currency=currency, fx_rate=parse_decimal(r.get("taux_change")),
                withholding=parse_decimal(r.get("retenue")), note=r.get("note") or None)
        except ValueError as e:
            errors.append(schemas.ImportRowError(line=line, message=str(e)))
            continue
        core = ledger.Transaction(account_id=tin.account_id, date=tin.date, type=tin.type,
                                  currency=tin.currency, ticker=tin.ticker, quantity=tin.quantity,
                                  price=tin.price, amount=tin.amount, fees=tin.fees, fx_rate=tin.fx_rate,
                                  withholding=tin.withholding, id=_ID_OFFSET + line)
        if _key(core) in existing_keys:
            n_dup += 1
            warnings.append(f"Ligne {line} : identique à une transaction existante, ignorée.")
            continue
        parsed.append((line, core, tin))

    for k, c in classes.items():
        if c not in ("action", "etf", "crypto", "autre"):
            errors.append(schemas.ImportRowError(line=0, message=f"classe « {c} » inconnue pour {k}"))

    if not errors:
        try:
            warnings += _relabel(check(s, provider, add=[c for _, c, _ in parsed],
                                       listing_currency={t: n.currency for t, n in new_listings.items()}))
        except LedgerError as e:
            for msg in e.errors:
                line = _line_of(msg)
                errors.append(schemas.ImportRowError(line=line, message=_relabel([msg])[0]))

    committed = False
    if not dry_run and not errors:
        _commit(s, parsed, new_listings, classes, listings)
        committed = True

    return schemas.ImportReport(
        dry_run=dry_run, committed=committed, n_rows=len(rows), n_valid=len(parsed) if not errors else 0,
        n_duplicates=n_dup, errors=sorted(errors, key=lambda e: e.line), warnings=warnings,
        new_listings=list(new_listings.values()), transactions=[t for _, _, t in parsed])


def _line_of(msg: str) -> int:
    m = re.search(r"#(\d+)", msg)
    if m and int(m.group(1)) >= _ID_OFFSET:
        return int(m.group(1)) - _ID_OFFSET
    return 0


def _relabel(msgs: list[str]) -> list[str]:
    def sub(m):
        n = int(m.group(1))
        return f"ligne {n - _ID_OFFSET}" if n >= _ID_OFFSET else f"transaction #{n}"
    return [re.sub(r"#(\d+)", sub, m) for m in msgs]


def _commit(s: Session, parsed, new_listings: dict[str, schemas.NewListing], classes: dict[str, str],
            listings: dict[str, models.Listing]) -> None:
    for ticker, nl in new_listings.items():
        inst = s.scalar(select(models.Instrument).where(models.Instrument.isin == nl.isin)) if nl.isin else None
        if inst is None:
            inst = models.Instrument(isin=nl.isin, name=nl.name, asset_class=classes.get(ticker, "autre"))
            s.add(inst)
        listing = models.Listing(ticker=ticker, instrument=inst, currency=nl.currency)
        s.add(listing)
        listings[ticker] = listing
    s.flush()
    for _, _, t in parsed:
        s.add(models.Transaction(
            account_id=t.account_id, listing_id=listings[t.ticker].id if t.ticker else None,
            date=t.date, type=t.type.value, quantity=t.quantity, price=t.price, amount=t.amount,
            fees=t.fees, currency=t.currency, fx_rate=t.fx_rate, withholding=t.withholding, note=t.note))
    s.commit()
