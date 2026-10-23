import { type FormEvent, useState } from "react";

import { api, useAccounts, useLedgerMutation, useListings } from "../api/client";
import type { AccountKind, AssetClass, CashMode } from "../api/types";
import { Button, Card, ErrorBox, Field, Loading } from "../components/ui";
import { CASH_MODE_LABEL } from "../lib/format";

function AccountForm() {
  const create = useLedgerMutation(api.createAccount);
  const [f, setF] = useState({ name: "", broker: "", kind: "CTO" as AccountKind, cash_mode: "" as CashMode | "" });
  const submit = (e: FormEvent) => {
    e.preventDefault();
    if (!f.cash_mode) return;
    create.mutate({ name: f.name, broker: f.broker || null, kind: f.kind, cash_mode: f.cash_mode },
      { onSuccess: () => setF({ name: "", broker: "", kind: "CTO", cash_mode: "" }) });
  };
  return (
    <form onSubmit={submit} className="space-y-3">
      <div className="grid grid-cols-2 gap-3 md:grid-cols-4">
        <Field label="Nom"><input required maxLength={80} value={f.name} onChange={(e) => setF({ ...f, name: e.target.value })} /></Field>
        <Field label="Courtier"><input maxLength={80} value={f.broker} onChange={(e) => setF({ ...f, broker: e.target.value })} /></Field>
        <Field label="Type">
          <select value={f.kind} onChange={(e) => setF({ ...f, kind: e.target.value as AccountKind })}>
            <option value="CTO">Compte-titres</option><option value="PEA">PEA</option>
            <option value="CRYPTO">Crypto</option><option value="AUTRE">Autre</option>
          </select>
        </Field>
        <Field label="Convention de flux">
          <select required value={f.cash_mode} onChange={(e) => setF({ ...f, cash_mode: e.target.value as CashMode })}>
            <option value="">Choisir…</option>
            <option value="avec_especes">Avec espèces</option>
            <option value="titres_seuls">Titres seuls</option>
          </select>
        </Field>
      </div>
      <div className="grid gap-2 text-xs text-ink-2 md:grid-cols-2">
        <p><strong className="text-ink">Avec espèces</strong> : vous saisissez les dépôts et retraits. Le solde
          d'espèces fait partie du compte. Seuls les dépôts et retraits sont des flux externes. Plus exact, mais
          l'historique des versements doit être complet.</p>
        <p><strong className="text-ink">Titres seuls</strong> : pas d'espèces suivies. Chaque achat est un apport,
          chaque vente ou dividende un retrait. Plus simple, mais l'argent qui dort sur le compte n'est pas compté.
          Dépôts et retraits sont refusés.</p>
      </div>
      <ErrorBox error={create.error} />
      <Button type="submit" disabled={create.isPending}>Créer le compte</Button>
    </form>
  );
}

function ListingForm() {
  const create = useLedgerMutation(api.createListing);
  const [f, setF] = useState({ ticker: "", isin: "", asset_class: "action" as AssetClass });
  const submit = (e: FormEvent) => {
    e.preventDefault();
    create.mutate({ ticker: f.ticker, isin: f.isin || null, asset_class: f.asset_class },
      { onSuccess: () => setF({ ticker: "", isin: "", asset_class: f.asset_class }) });
  };
  return (
    <form onSubmit={submit} className="space-y-3">
      <div className="grid grid-cols-2 gap-3 md:grid-cols-4">
        <Field label="Ticker Yahoo" hint="ex. PANX.PA, CW8.PA, AAPL, BTC-EUR">
          <input required maxLength={20} value={f.ticker} onChange={(e) => setF({ ...f, ticker: e.target.value })} />
        </Field>
        <Field label="ISIN (facultatif)" hint="identifie le titre ; absent pour une crypto">
          <input maxLength={12} value={f.isin} onChange={(e) => setF({ ...f, isin: e.target.value })} />
        </Field>
        <Field label="Classe">
          <select value={f.asset_class} onChange={(e) => setF({ ...f, asset_class: e.target.value as AssetClass })}>
            <option value="action">Action</option><option value="etf">ETF</option>
            <option value="crypto">Crypto</option><option value="autre">Autre</option>
          </select>
        </Field>
      </div>
      <p className="text-xs text-ink-2">La devise et le nom sont lus chez le fournisseur de données, qui vérifie aussi
        que le ticker existe.</p>
      <ErrorBox error={create.error} />
      <Button type="submit" disabled={create.isPending}>{create.isPending ? "Vérification…" : "Ajouter la cotation"}</Button>
    </form>
  );
}

export default function Comptes() {
  const accounts = useAccounts();
  const listings = useListings();
  const del = useLedgerMutation(api.deleteAccount);

  return (
    <>
      <h1 className="text-lg font-semibold">Comptes et titres</h1>
      <Card title="Comptes">
        {accounts.isLoading ? <Loading /> : (
          <div className="overflow-x-auto">
            <table className="data">
              <thead><tr><th>Nom</th><th>Courtier</th><th>Type</th><th>Convention</th><th className="r">Transactions</th><th></th></tr></thead>
              <tbody>
                {accounts.data?.map((a) => (
                  <tr key={a.id}>
                    <td className="font-medium">{a.name}</td><td className="text-ink-2">{a.broker ?? ""}</td><td>{a.kind}</td>
                    <td>{CASH_MODE_LABEL[a.cash_mode]}</td><td className="r num">{a.n_transactions}</td>
                    <td className="r">{a.n_transactions === 0 && (
                      <button className="text-xs text-bad underline" onClick={() => confirm(`Supprimer ${a.name} ?`) && del.mutate(a.id)}>Supprimer</button>)}
                    </td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        )}
        <ErrorBox error={del.error} />
      </Card>
      <Card title="Nouveau compte"><AccountForm /></Card>
      <Card title={`Cotations (${listings.data?.length ?? 0})`}>
        {listings.isLoading ? <Loading /> : (
          <div className="overflow-x-auto">
            <table className="data">
              <thead><tr><th>Ticker</th><th>Nom</th><th>ISIN</th><th>Classe</th><th>Devise</th><th>Place</th></tr></thead>
              <tbody>
                {listings.data?.map((l) => (
                  <tr key={l.id}>
                    <td className="font-medium">{l.ticker}</td><td className="text-ink-2">{l.instrument.name ?? ""}</td>
                    <td className="num">{l.instrument.isin ?? ""}</td><td>{l.instrument.asset_class}</td><td>{l.currency}</td><td>{l.exchange ?? ""}</td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        )}
      </Card>
      <Card title="Nouvelle cotation"><ListingForm /></Card>
    </>
  );
}
