import { type FormEvent, useMemo, useState } from "react";

import { api, useAccounts, useLedgerMutation, useListings, useTransactions } from "../api/client";
import type { ImportReport, TransactionIn, TxType } from "../api/types";
import { Button, Card, ErrorBox, Field, Loading } from "../components/ui";
import { date, money, num, qty, TX_LABEL } from "../lib/format";

const TYPES: TxType[] = ["ACHAT", "VENTE", "DIVIDENDE", "DEPOT", "RETRAIT", "FRAIS"];
const today = () => new Date().toISOString().slice(0, 10);

/** Une virgule décimale est acceptée à la saisie ; envoyé tel quel en chaîne (Decimal côté API). */
const dec = (s: string) => (s.trim() === "" ? null : s.trim().replace(/\s/g, "").replace(",", "."));

function TransactionForm() {
  const accounts = useAccounts();
  const listings = useListings();
  const create = useLedgerMutation(api.createTransaction);
  const [f, setF] = useState({ account_id: "", type: "ACHAT" as TxType, date: today(), ticker: "", quantity: "",
    price: "", amount: "", fees: "", fx_rate: "", withholding: "", note: "" });
  const set = (k: keyof typeof f) => (e: { target: { value: string } }) => setF({ ...f, [k]: e.target.value });

  const acc = accounts.data?.find((a) => String(a.id) === f.account_id);
  const listing = listings.data?.find((l) => l.ticker === f.ticker);
  const trade = f.type === "ACHAT" || f.type === "VENTE";
  const needsTicker = trade || f.type === "DIVIDENDE";
  const currency = needsTicker ? listing?.currency ?? "" : "EUR";
  const cashMove = f.type === "DEPOT" || f.type === "RETRAIT";
  const blocked = cashMove && acc?.cash_mode === "titres_seuls";

  const submit = (e: FormEvent) => {
    e.preventDefault();
    const body: TransactionIn = {
      account_id: Number(f.account_id), date: f.date, type: f.type, ticker: needsTicker ? f.ticker : null,
      quantity: trade ? dec(f.quantity) : null, price: trade ? dec(f.price) : null, amount: dec(f.amount),
      fees: dec(f.fees) ?? "0", fx_rate: currency !== "EUR" ? dec(f.fx_rate) : null,
      withholding: f.type === "DIVIDENDE" ? dec(f.withholding) : null, note: f.note || null,
    };
    create.mutate(body, { onSuccess: () => setF({ ...f, quantity: "", price: "", amount: "", fees: "", note: "" }) });
  };

  if (accounts.isLoading || listings.isLoading) return <Loading />;
  if (!accounts.data?.length) return <p className="text-sm text-muted">Créez d'abord un compte (page Comptes et titres).</p>;

  return (
    <form onSubmit={submit} className="space-y-3">
      <div className="grid grid-cols-2 gap-3 md:grid-cols-4">
        <Field label="Compte">
          <select required value={f.account_id} onChange={set("account_id")}>
            <option value="">Choisir…</option>
            {accounts.data.map((a) => <option key={a.id} value={a.id}>{a.name}</option>)}
          </select>
        </Field>
        <Field label="Type">
          <select value={f.type} onChange={set("type")}>
            {TYPES.map((t) => <option key={t} value={t}>{TX_LABEL[t]}</option>)}
          </select>
        </Field>
        <Field label="Date"><input type="date" required value={f.date} max={today()} onChange={set("date")} /></Field>
        {needsTicker && (
          <Field label="Cotation" hint={listing ? `${listing.instrument.name ?? ""} · ${listing.currency}` : "absente ? ajoutez-la dans Comptes et titres"}>
            <select required value={f.ticker} onChange={set("ticker")}>
              <option value="">Choisir…</option>
              {listings.data!.map((l) => <option key={l.id} value={l.ticker}>{l.ticker}</option>)}
            </select>
          </Field>
        )}
        {trade && <Field label={`Quantité`}><input inputMode="decimal" required value={f.quantity} onChange={set("quantity")} /></Field>}
        {trade && <Field label={`Prix unitaire ${currency}`}><input inputMode="decimal" required value={f.price} onChange={set("price")} /></Field>}
        <Field label={trade ? `Montant brut ${currency} (facultatif)` : f.type === "DIVIDENDE" ? `Montant net reçu ${currency}` : "Montant EUR"}
               hint={trade ? "sinon quantité × prix" : undefined}>
          <input inputMode="decimal" required={!trade} value={f.amount} onChange={set("amount")} />
        </Field>
        {trade && <Field label={`Frais ${currency}`}><input inputMode="decimal" value={f.fees} onChange={set("fees")} placeholder="0" /></Field>}
        {currency && currency !== "EUR" && (
          <Field label={`Taux courtier (€ pour 1 ${currency})`} hint="facultatif : sinon taux de marché du jour">
            <input inputMode="decimal" value={f.fx_rate} onChange={set("fx_rate")} />
          </Field>
        )}
        {f.type === "DIVIDENDE" && <Field label={`Retenue à la source ${currency}`}><input inputMode="decimal" value={f.withholding} onChange={set("withholding")} /></Field>}
        <Field label="Note"><input value={f.note} onChange={set("note")} maxLength={500} /></Field>
      </div>
      {blocked && <p className="text-sm text-warn">Ce compte est en convention « titres seuls » : il n'accepte ni dépôt ni retrait.</p>}
      <ErrorBox error={create.error} />
      <Button type="submit" disabled={create.isPending || blocked}>Enregistrer</Button>
      {create.isSuccess && <span className="ml-3 text-sm text-good">Transaction enregistrée.</span>}
    </form>
  );
}

function CsvImport() {
  const [file, setFile] = useState<File | null>(null);
  const [report, setReport] = useState<ImportReport | null>(null);
  const preview = useLedgerMutation((f: File) => api.importCsv(f, true));
  const commit = useLedgerMutation((f: File) => api.importCsv(f, false));
  const run = (m: typeof preview) => file && m.mutate(file, { onSuccess: setReport });

  return (
    <div className="space-y-3 text-sm">
      <p className="text-ink-2">
        Format : séparateur « ; », une ligne par opération, colonnes
        <code className="mx-1 break-all rounded bg-surface-2 px-1 text-xs">date;compte;type;ticker;isin;quantite;prix;montant;frais;devise;taux_change;retenue;note;classe</code>.
        Voir <code className="text-xs">docs/FORMAT_CSV.md</code> et <code className="text-xs">examples/transactions_exemple.csv</code>.
        Un aperçu est affiché avant tout enregistrement ; une seule erreur bloque tout l'import.
      </p>
      <input type="file" accept=".csv,text/csv" onChange={(e) => { setFile(e.target.files?.[0] ?? null); setReport(null); }} />
      <div className="flex gap-2">
        <Button variant="ghost" disabled={!file || preview.isPending} onClick={() => run(preview)}>Aperçu</Button>
        <Button disabled={!file || !report || report.errors.length > 0 || report.committed || commit.isPending}
                onClick={() => run(commit)}>Importer {report && !report.committed ? `${report.n_valid} lignes` : ""}</Button>
      </div>
      <ErrorBox error={preview.error ?? commit.error} />
      {report && (
        <div className="space-y-2 rounded-md border border-line p-3">
          <div>
            {report.committed ? <span className="font-medium text-good">Import terminé.</span> : <span className="font-medium">Aperçu (rien n'est encore enregistré).</span>}{" "}
            <span className="num text-ink-2">{report.n_rows} lignes lues, {report.n_valid} valides, {report.n_duplicates} doublons ignorés, {report.errors.length} erreurs.</span>
          </div>
          {report.errors.length > 0 && (
            <ul className="list-disc pl-5 text-bad">{report.errors.map((e, i) => <li key={i}>{e.line ? `Ligne ${e.line} : ` : ""}{e.message}</li>)}</ul>
          )}
          {report.new_listings.length > 0 && (
            <p className="text-ink-2">Cotations créées : {report.new_listings.map((l) => `${l.ticker} (${l.currency}${l.name ? `, ${l.name}` : ""})`).join(" ; ")}</p>
          )}
          {report.warnings.length > 0 && <ul className="list-disc pl-5 text-warn">{report.warnings.map((w, i) => <li key={i}>{w}</li>)}</ul>}
        </div>
      )}
    </div>
  );
}

export default function Transactions() {
  const txs = useTransactions();
  const accounts = useAccounts();
  const del = useLedgerMutation(api.deleteTransaction);
  const [filter, setFilter] = useState("");
  const names = useMemo(() => new Map(accounts.data?.map((a) => [a.id, a.name])), [accounts.data]);
  const rows = (txs.data ?? []).filter((t) => !filter || String(t.account_id) === filter);

  return (
    <>
      <h1 className="text-lg font-semibold">Transactions</h1>
      <Card title="Nouvelle transaction"><TransactionForm /></Card>
      <Card title="Import CSV"><CsvImport /></Card>
      <Card title={`Historique (${rows.length})`}
            aside={<select value={filter} onChange={(e) => setFilter(e.target.value)}>
              <option value="">Tous les comptes</option>
              {accounts.data?.map((a) => <option key={a.id} value={a.id}>{a.name}</option>)}
            </select>}>
        <ErrorBox error={del.error ?? txs.error} />
        {txs.isLoading ? <Loading /> : (
          <div className="max-h-[32rem] overflow-auto">
            <table className="data">
              <thead><tr><th>Date</th><th>Compte</th><th>Type</th><th>Titre</th><th className="r">Quantité</th><th className="r">Prix</th><th className="r">Montant</th><th className="r">Frais</th><th className="r">Taux</th><th></th></tr></thead>
              <tbody>
                {rows.map((t) => (
                  <tr key={t.id}>
                    <td className="num">{date(t.date)}</td>
                    <td className="text-ink-2">{names.get(t.account_id)}</td>
                    <td>{TX_LABEL[t.type]}</td>
                    <td>{t.ticker ?? ""}</td>
                    <td className="r num">{t.quantity ? qty(t.quantity) : ""}</td>
                    <td className="r num">{t.price ? money(t.price, t.currency) : ""}</td>
                    <td className="r num">{t.amount ? money(t.amount, t.currency) : ""}</td>
                    <td className="r num">{Number(t.fees) ? money(t.fees, t.currency) : ""}</td>
                    <td className="r num">{t.fx_rate ? num(t.fx_rate) : ""}</td>
                    <td className="r">
                      <button className="text-xs text-bad underline" disabled={del.isPending}
                              onClick={() => confirm("Supprimer cette transaction ?") && del.mutate(t.id)}>Supprimer</button>
                    </td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        )}
      </Card>
    </>
  );
}
