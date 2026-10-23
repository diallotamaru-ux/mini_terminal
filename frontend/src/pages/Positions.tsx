import { useState } from "react";

import { usePositions } from "../api/client";
import { Card, ErrorBox, Loading, Source, Warnings } from "../components/ui";
import { date, money, num, pct, qty, signClass, signedMoney, TX_LABEL } from "../lib/format";

export default function Positions() {
  const q = usePositions();
  const [closed, setClosed] = useState(false);
  if (q.isLoading) return <Loading />;
  if (q.error) return <ErrorBox error={q.error} />;
  const { meta, positions, split_adjustments: splits } = q.data!;
  const open = positions.filter((p) => p.is_open);
  const done = positions.filter((p) => !p.is_open);

  return (
    <>
      <h1 className="text-lg font-semibold">Positions</h1>
      <Warnings items={meta.warnings} />
      <Card title={`Positions ouvertes (${open.length})`}
            aside={<span className="text-xs text-muted">PRU : coût moyen pondéré, frais d'achat inclus</span>}>
        {/* Petits écrans : une carte par position, mêmes chiffres que le tableau. */}
        <ul className="space-y-2 md:hidden">
          {open.map((p) => (
            <li key={`${p.account_id}-${p.ticker}`} className="rounded-md border border-line p-3 text-sm">
              <div className="flex items-baseline justify-between gap-2">
                <span className="font-medium">{p.ticker}</span>
                <span className="num font-medium">{money(p.market_value_eur)}</span>
              </div>
              <div className="flex items-baseline justify-between gap-2 text-xs text-muted">
                <span className="truncate">{p.account_name}</span>
                <span className={`num ${signClass(p.unrealized_eur)}`}>{signedMoney(p.unrealized_eur)} ({pct(p.unrealized_pct, 1, true)})</span>
              </div>
              <dl className="mt-2 grid grid-cols-3 gap-2 text-xs">
                <div><dt className="text-muted">Quantité</dt><dd className="num">{qty(p.quantity)}</dd></div>
                <div><dt className="text-muted">PRU</dt><dd className="num">{money(p.pru, p.currency)}</dd></div>
                <div>
                  <dt className="text-muted">Cours{p.price_date ? ` au ${date(p.price_date)}` : ""}</dt>
                  <dd className={`num ${p.price_stale ? "text-warn" : ""}`}>{money(p.price, p.currency)}</dd>
                </div>
              </dl>
            </li>
          ))}
        </ul>
        <div className="hidden overflow-x-auto md:block">
          <table className="data">
            <thead>
              <tr>
                <th>Titre</th><th>Compte</th><th className="r">Quantité</th><th className="r">PRU</th>
                <th className="r">Cours</th><th className="r">Valeur</th><th className="r">Valeur EUR</th>
                <th className="r">PV latente EUR</th><th className="r">Poids</th>
              </tr>
            </thead>
            <tbody>
              {open.map((p) => (
                <tr key={`${p.account_id}-${p.ticker}`}>
                  <td>
                    <div className="font-medium">{p.ticker}</div>
                    <div className="max-w-56 truncate text-xs text-muted">{p.name ?? ""}{p.isin ? ` · ${p.isin}` : ""}</div>
                  </td>
                  <td className="text-ink-2">{p.account_name}</td>
                  <td className="r num">{qty(p.quantity)}</td>
                  <td className="r num">{money(p.pru, p.currency)}</td>
                  <td className="r num">
                    <div>{money(p.price, p.currency)}</div>
                    <div className={`text-xs ${p.price_stale ? "text-warn" : "text-muted"}`}
                         title={p.price_source ?? undefined}>
                      {p.price_date ? `au ${date(p.price_date)}` : ""}{p.price_stale ? " · ancien" : ""}
                    </div>
                  </td>
                  <td className="r num">{money(p.market_value, p.currency)}</td>
                  <td className="r num">
                    <div>{money(p.market_value_eur)}</div>
                    {p.currency !== "EUR" && <div className="text-xs text-muted">1 {p.currency} = {num(p.fx_rate)} €</div>}
                  </td>
                  <td className={`r num ${signClass(p.unrealized_eur)}`}>
                    <div>{signedMoney(p.unrealized_eur)}</div>
                    <div className="text-xs">{pct(p.unrealized_pct, 1, true)}</div>
                  </td>
                  <td className="r num">{pct(p.weight, 1)}</td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
        <p className="mt-2 text-xs text-muted">
          La PV latente en % est calculée en devise de cotation. En EUR, elle inclut l'effet de change
          entre la date d'achat et aujourd'hui. Le poids est rapporté à la valeur totale, espèces comprises.
        </p>
        <Source meta={meta} />
      </Card>

      {splits.length > 0 && (
        <Card title={`Ajustements pour divisions d'actions (${splits.length})`}
              aside={<span className="text-xs text-muted">appliqués au calcul ; vos transactions saisies ne sont pas modifiées</span>}>
          <p className="mb-2 text-xs text-ink-2">
            Les cours du fournisseur sont ajustés des divisions. Chaque achat ou vente antérieur à une division
            est donc converti en actions nouvelles : quantité × ratio, prix ÷ ratio. Le montant de l'opération,
            le coût total et les plus-values sont inchangés.
          </p>
          <div className="overflow-x-auto">
            <table className="data">
              <thead>
                <tr><th>Titre</th><th>Opération</th><th>Compte</th><th>Division</th>
                  <th className="r">Quantité saisie</th><th className="r">Quantité retenue</th>
                  <th className="r">Prix saisi</th><th className="r">Prix retenu</th></tr>
              </thead>
              <tbody>
                {splits.map((a, i) => (
                  <tr key={i}>
                    <td className="font-medium">{a.ticker}</td>
                    <td className="num">{TX_LABEL[a.tx_type as keyof typeof TX_LABEL] ?? a.tx_type} du {date(a.tx_date)}</td>
                    <td className="text-ink-2">{a.account_name}</td>
                    <td>{a.splits.map((s) => `${s.label} le ${date(s.date)}`).join(", ")}{a.splits.length > 1 ? ` (× ${a.factor})` : ""}</td>
                    <td className="r num">{qty(a.quantity_before)}</td>
                    <td className="r num">{qty(a.quantity_after)}</td>
                    <td className="r num">{money(a.price_before, a.currency || "EUR")}</td>
                    <td className="r num">{money(a.price_after, a.currency || "EUR")}</td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
          <Source meta={meta} />
        </Card>
      )}

      <Card title={`Positions soldées (${done.length})`}
            aside={<button className="text-xs text-accent underline" onClick={() => setClosed(!closed)}>{closed ? "Masquer" : "Afficher"}</button>}>
        {closed && (
          <div className="overflow-x-auto">
            <table className="data">
              <thead><tr><th>Titre</th><th>Compte</th><th className="r">PV réalisée</th><th className="r">PV réalisée EUR</th><th className="r">Dividendes EUR</th><th className="r">Frais</th></tr></thead>
              <tbody>
                {done.map((p) => (
                  <tr key={`${p.account_id}-${p.ticker}`}>
                    <td className="font-medium">{p.ticker}</td>
                    <td className="text-ink-2">{p.account_name}</td>
                    <td className={`r num ${signClass(p.realized)}`}>{signedMoney(p.realized, p.currency)}</td>
                    <td className={`r num ${signClass(p.realized_eur)}`}>{signedMoney(p.realized_eur)}</td>
                    <td className="r num">{money(p.dividends_eur)}</td>
                    <td className="r num">{money(p.fees, p.currency)}</td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        )}
      </Card>

      <Card title="Plus-values réalisées et dividendes des positions ouvertes">
        <div className="overflow-x-auto">
          <table className="data">
            <thead><tr><th>Titre</th><th>Compte</th><th className="r">PV réalisée EUR</th><th className="r">Dividendes EUR</th><th className="r">Frais payés</th></tr></thead>
            <tbody>
              {open.map((p) => (
                <tr key={`${p.account_id}-${p.ticker}`}>
                  <td className="font-medium">{p.ticker}</td>
                  <td className="text-ink-2">{p.account_name}</td>
                  <td className={`r num ${signClass(p.realized_eur)}`}>{signedMoney(p.realized_eur)}</td>
                  <td className="r num">{money(p.dividends_eur)}</td>
                  <td className="r num">{money(p.fees, p.currency)}</td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      </Card>
    </>
  );
}
