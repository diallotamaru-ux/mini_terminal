import { Link } from "react-router-dom";

import { useValuationSummary } from "../api/client";
import type { GrowthOut, ValuationRow } from "../api/types";
import { Card, ErrorBox, Loading, Source, Warnings } from "../components/ui";
import { date, dec, pct } from "../lib/format";

export const STATUS_LABEL = { ok: "analysable", bloquee: "bloquée", impossible: "non calculable", exclue: "hors périmètre" };

/** Croissance historique avec son nombre d'exercices : « 4,2 % (4 ans) », « non significatif (3 ans) ». */
export function growth(g: GrowthOut | null): string {
  if (!g || g.status === "manquant") return "manquant";
  const span = `${g.years} an${g.years > 1 ? "s" : ""}`;
  if (g.status === "non_significatif") return `non significatif (${span})`;
  return `${pct(g.value, 1)} (${span})`;
}

function Flags({ r }: { r: ValuationRow }) {
  return (
    <>
      {r.manual && <span className="ml-2 rounded border border-line px-1 text-[11px] text-ink-2" title="Au moins une valeur saisie à la main">saisie manuelle</span>}
      {r.approximations && <span className="ml-2 rounded border border-line px-1 text-[11px] text-warn" title="Approximation acceptée : voir la fiche">approximation</span>}
    </>
  );
}

export default function Valorisation() {
  const q = useValuationSummary();
  const d = q.data;
  return (
    <>
      <h1 className="text-lg font-semibold">Valorisation : DCF inversé</h1>
      {q.isLoading && <Loading label="Lecture des comptes annuels…" />}
      <ErrorBox error={q.error} />
      {d && (
        <div className="space-y-4">
          <p className="text-sm text-ink-2">
            Pour chaque action détenue, la croissance annuelle du flux disponible pour l'entreprise (FCFF) que le prix
            actuel suppose pendant {d.horizon} ans, suivie de {pct(d.g_term, 1)} par an à perpétuité. Le coût du capital est
            le k commun de la devise des comptes, le même pour toutes les lignes, pour qu'elles restent comparables. C'est une
            lecture d'hypothèses, pas un conseil d'investissement.
          </p>
          <Warnings items={d.meta.warnings} />
          <Card title={`Actions analysables (${d.rows.length}), par g implicite décroissant`}>
            {d.rows.length === 0 ? (
              <p className="text-sm text-muted">Aucune action analysable : voir les raisons ci-dessous.</p>
            ) : (
              <>
                <div className="hidden overflow-x-auto md:block">
                  <table className="data">
                    <thead>
                      <tr>
                        <th>Action</th><th className="r">g implicite</th><th className="r">FCF historique</th>
                        <th className="r">Chiffre d'affaires historique</th><th className="r">VE / FCF</th>
                        <th className="r">k</th><th className="r">Bilan au</th>
                      </tr>
                    </thead>
                    <tbody>
                      {d.rows.map((r) => (
                        <tr key={r.ticker}>
                          <td><Link className="text-accent underline-offset-2 hover:underline" to={`/valorisation/${encodeURIComponent(r.ticker)}`}>{r.name}</Link>
                            {" "}<span className="text-xs text-muted">{r.ticker}</span><Flags r={r} /></td>
                          <td className="r num font-semibold">{pct(r.g, 1)}</td>
                          <td className="r num">{growth(r.growth_fcff)}</td>
                          <td className="r num">{growth(r.growth_revenue)}</td>
                          <td className="r num">{dec(r.ev_multiple, 1)}</td>
                          <td className="r num" title={r.k_label ?? ""}>{pct(r.k, 1)}</td>
                          <td className="r num">{date(r.balance_date)}</td>
                        </tr>
                      ))}
                    </tbody>
                  </table>
                </div>
                <ul className="space-y-2 md:hidden">
                  {d.rows.map((r) => (
                    <li key={r.ticker} className="rounded-md border border-line p-3">
                      <div className="flex items-baseline justify-between gap-2">
                        <Link className="font-medium text-accent" to={`/valorisation/${encodeURIComponent(r.ticker)}`}>{r.name}</Link>
                        <span className="num text-lg font-semibold">{pct(r.g, 1)}</span>
                      </div>
                      <div className="mt-1 grid grid-cols-2 gap-x-3 gap-y-0.5 text-xs text-ink-2">
                        <span>FCF historique</span><span className="num text-right">{growth(r.growth_fcff)}</span>
                        <span>CA historique</span><span className="num text-right">{growth(r.growth_revenue)}</span>
                        <span>VE / FCF</span><span className="num text-right">{dec(r.ev_multiple, 1)}</span>
                        <span>k ({r.k_label})</span><span className="num text-right">{pct(r.k, 1)}</span>
                      </div>
                      <div className="mt-1"><Flags r={r} /></div>
                    </li>
                  ))}
                </ul>
              </>
            )}
            <p className="mt-3 text-xs text-ink-2">
              Lecture : un g implicite élevé signifie que le prix actuel suppose une forte croissance future du flux disponible ;
              la croissance historique, sur les exercices disponibles, sert de repère. « Non significatif » : le flux de départ
              ou d'arrivée est négatif, un taux composé n'a pas de sens.
            </p>
            <Source meta={d.meta} />
          </Card>
          {d.others.length > 0 && (
            <Card title={`Autres lignes (${d.others.length})`}>
              <ul className="space-y-2 text-sm">
                {d.others.map((r) => (
                  <li key={r.ticker}>
                    <span className="font-medium">{r.name}</span> <span className="text-xs text-muted">{r.ticker}</span>
                    <span className={`ml-2 rounded border border-line px-1 text-[11px] ${r.status === "exclue" ? "text-muted" : "text-warn"}`}>
                      {STATUS_LABEL[r.status]}</span>
                    <p className="text-ink-2">{r.reason}</p>
                    {r.status !== "exclue" && (
                      <Link className="text-xs text-accent underline" to={`/valorisation/${encodeURIComponent(r.ticker)}`}>
                        Ouvrir la fiche pour compléter</Link>
                    )}
                  </li>
                ))}
              </ul>
            </Card>
          )}
        </div>
      )}
    </>
  );
}
