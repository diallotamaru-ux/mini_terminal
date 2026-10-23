import { Link } from "react-router-dom";

import { useHistory, useSummary } from "../api/client";
import AllocationBars from "../charts/AllocationBars";
import ValueChart from "../charts/ValueChart";
import { Card, ErrorBox, Loading, Source, Stat, Warnings } from "../components/ui";
import { CASH_MODE_LABEL, money, signClass, signedMoney } from "../lib/format";

export default function TableauDeBord() {
  const summary = useSummary();
  const history = useHistory();

  if (summary.isLoading) return <Loading />;
  if (summary.error) return <ErrorBox error={summary.error} />;
  const s = summary.data!;

  if (!s.accounts.length) {
    return (
      <Card title="Bienvenue">
        <p className="text-sm text-ink-2">
          Aucun compte pour l'instant. Commencez par <Link className="text-accent underline" to="/comptes">créer vos comptes</Link>,
          puis saisissez ou <Link className="text-accent underline" to="/transactions">importez vos transactions</Link>.
        </p>
      </Card>
    );
  }

  return (
    <>
      <h1 className="text-lg font-semibold">Tableau de bord</h1>
      <Warnings items={s.meta.warnings} />
      {!s.complete && (
        <div className="rounded-md border border-line p-3 text-sm" style={{ background: "var(--warn-bg)" }}>
          <span className="font-medium text-warn">Valorisation incomplète.</span>{" "}
          <span className="text-ink-2">Valeur manquante pour : {s.missing.join(", ")}. Le total n'est pas affiché
          plutôt que d'être sous-estimé.</span>
        </div>
      )}

      <Card>
        <div className="grid grid-cols-2 gap-4 md:grid-cols-5">
          <Stat label="Valeur totale" value={money(s.total_value_eur)} />
          <Stat label="Apports nets" value={money(s.net_contributions_eur)} hint="dépôts − retraits, selon la convention de chaque compte" />
          <Stat label="Plus-value latente" value={signedMoney(s.unrealized_eur)} valueClass={signClass(s.unrealized_eur)}
                hint={`sur un coût de ${money(s.cost_eur)}`} />
          <Stat label="Plus-value réalisée" value={signedMoney(s.realized_eur)} valueClass={signClass(s.realized_eur)} />
          <Stat label="Dividendes nets reçus" value={money(s.dividends_eur)} />
        </div>
        <Source meta={s.meta} />
      </Card>

      <Card title="Valeur du portefeuille">
        {history.isLoading ? <Loading /> : history.error ? <ErrorBox error={history.error} /> :
          history.data!.dates.length ? <ValueChart history={history.data!} /> :
            <p className="text-sm text-muted">Aucune transaction.</p>}
        <Source meta={history.data?.meta} />
      </Card>

      <div className="grid gap-4 lg:grid-cols-2">
        <Card title="Répartition par compte"><AllocationBars items={s.by_account} /><Source meta={s.meta} /></Card>
        <Card title="Répartition par actif"><AllocationBars items={s.by_asset} /><Source meta={s.meta} /></Card>
        <Card title="Répartition par devise de cotation"><AllocationBars items={s.by_currency} /><Source meta={s.meta} /></Card>
        <Card title="Répartition par classe d'actif"><AllocationBars items={s.by_class} /><Source meta={s.meta} /></Card>
      </div>

      <Card title="Comptes">
        <div className="overflow-x-auto">
          <table className="data">
            <thead>
              <tr><th>Compte</th><th>Convention</th><th className="r">Titres</th><th className="r">Espèces</th><th className="r">Valeur</th></tr>
            </thead>
            <tbody>
              {s.accounts.map((a) => (
                <tr key={a.id}>
                  <td>{a.name}</td>
                  <td className="text-ink-2">{CASH_MODE_LABEL[a.cash_mode]}</td>
                  <td className="r num">{money(a.securities_eur)}</td>
                  <td className="r num">{a.cash_mode === "titres_seuls" ? <span className="text-muted">non suivi</span> : money(a.cash_eur)}</td>
                  <td className="r num font-medium">{money(a.value_eur)}</td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
        <Source meta={s.meta} />
      </Card>
    </>
  );
}
