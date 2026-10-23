import { useMemo, useState } from "react";

import { useRisk } from "../api/client";
import type { RiskRow } from "../api/types";
import LinesChart, { type LineDef } from "../charts/LinesChart";
import PeriodSelector, { usePeriod } from "../components/PeriodSelector";
import { Card, ErrorBox, Loading, Source, Warnings } from "../components/ui";
import { date, pct } from "../lib/format";

const ND = "n.d.";
const dec = (v: number | null, d = 2) =>
  v === null ? ND : `${v < 0 ? "−" : ""}${Math.abs(v).toLocaleString("fr-FR", { minimumFractionDigits: d, maximumFractionDigits: d })}`;
const p = (v: number | null, d = 1, signed = false) => (v === null ? ND : pct(v, d, signed));
const ci = (c: [number, number] | null) => (c ? `[${dec(c[0])} ; ${dec(c[1])}]` : "");
const fmtIndex = (v: number | null) => (v === null ? "manquant" : v.toLocaleString("fr-FR", { maximumFractionDigits: 1 }));
const fmtPct = (v: number | null) => (v === null ? "manquant" : pct(v, 1));

/** Une colonne du tableau comparatif. `weekly` : mesure croisée, calculée en hebdomadaire. */
const COLUMNS: { key: string; label: string; weekly?: boolean; render: (r: RiskRow) => React.ReactNode }[] = [
  { key: "ret", label: "Rendement", render: (r) => <><div>{p(r.total_return, 1, true)}</div>
      <div className="text-xs text-muted">{r.annual_return !== null ? `${p(r.annual_return, 1, true)} /an` : ""}</div></> },
  { key: "vol", label: "Volatilité", render: (r) => p(r.volatility) },
  { key: "sharpe", label: "Sharpe", render: (r) => <><div>{dec(r.sharpe)}</div><div className="text-xs text-muted">{ci(r.sharpe_ci)}</div></> },
  { key: "sortino", label: "Sortino", render: (r) => dec(r.sortino) },
  { key: "mdd", label: "Drawdown max.", render: (r) => p(r.max_drawdown) },
  { key: "calmar", label: "Calmar", render: (r) => dec(r.calmar) },
  { key: "var", label: "VaR 95 % 1 j", render: (r) => p(r.var95, 2) },
  { key: "beta", label: "Bêta", weekly: true, render: (r) => r.is_reference ? <span className="text-muted">réf.</span> :
      <><div>{dec(r.beta)}</div><div className="text-xs text-muted">{r.beta_dimson !== null ? `Dimson ${dec(r.beta_dimson)}` : ""}</div></> },
  { key: "corr", label: "Corrélation", weekly: true, render: (r) => r.is_reference ? "" : dec(r.correlation) },
  { key: "alpha", label: "Alpha", weekly: true, render: (r) => r.is_reference ? "" : p(r.alpha, 1, true) },
  { key: "te", label: "Tracking err.", weekly: true, render: (r) => r.is_reference ? "" : p(r.tracking_error) },
  { key: "ir", label: "Ratio d'info.", weekly: true, render: (r) => r.is_reference ? "" :
      <><div>{dec(r.information_ratio)}</div><div className="text-xs text-muted">{ci(r.information_ratio_ci)}</div></> },
];

function RowNotes({ r }: { r: RiskRow }) {
  const notes = Object.values(r.notes);
  if (!r.complete && r.first_missing) notes.unshift(`valeur manquante le ${date(r.first_missing)}`);
  return notes.length ? <div className="mt-0.5 text-xs text-warn">{notes.join(" · ")}</div> : null;
}

export default function Risque() {
  const [period, setPeriod] = usePeriod();
  const [reference, setReference] = useState(1);
  const q = useRisk(period, reference);
  const d = q.data;

  const base100: LineDef[] = useMemo(() => !d ? [] : d.base100.map((c, i) => ({
    name: c.name, values: c.values, colorVar: (["--series-1", "--series-2", "--series-3"] as const)[i], dashed: i > 0,
  })), [d]);
  const drawdown: LineDef[] = useMemo(() => !d ? [] : d.drawdown.map((c, i) => ({
    name: c.name, values: c.values, colorVar: i === 0 ? "--series-1" : (reference === 1 ? "--series-2" : "--series-3"),
    area: i === 0, dashed: i > 0,
  })), [d, reference]);
  const vol: LineDef[] = useMemo(() => !d ? [] : d.rolling_volatility.map((c, i) => ({
    name: c.name, values: c.values, colorVar: i === 0 ? "--series-1" : (reference === 1 ? "--series-2" : "--series-3"),
    dashed: i > 0,
  })), [d, reference]);

  return (
    <>
      <div className="flex flex-wrap items-center justify-between gap-3">
        <h1 className="text-lg font-semibold">Risque et comparaison</h1>
        <PeriodSelector value={period} onChange={setPeriod} available={d?.available_periods} />
      </div>
      {q.isLoading && <Loading />}
      <ErrorBox error={q.error} />
      {d && (
        <div className={q.isFetching ? "opacity-60 transition-opacity" : ""}>
          <div className="space-y-4">
            <div className="flex flex-wrap items-center gap-x-4 gap-y-2 text-sm">
              <span className="text-muted">Comparer à :</span>
              {d.references.map((r) => (
                <label key={r.index} className="flex items-center gap-1.5">
                  <input type="radio" name="ref" checked={reference === r.index} onChange={() => setReference(r.index)} />
                  {r.name}
                </label>
              ))}
              <span className="text-xs text-muted">
                {d.period_label} : du {date(d.base_date)} au {date(d.meta.as_of)} ({d.span_days} jours)
              </span>
            </div>
            {d.short_history && (
              <div className="rounded-md border border-line p-3 text-sm" role="alert" style={{ background: "var(--warn-bg)" }}>
                <span className="font-medium text-warn">Prudence. </span><span className="text-ink-2">{d.short_history}</span>
              </div>
            )}
            <Warnings items={d.meta.warnings} />

            <Card title="Évolution comparée (base 100, TWR)">
              <LinesChart dates={d.dates} lines={base100} format={fmtIndex} />
              <p className="mt-2 text-xs text-muted">
                Portefeuille : rendement pondéré par le temps, apports neutralisés. Références en euros, dividendes
                réinvestis ({d.references.map((r) => `${r.ticker} : retenue ${pct(r.withholding, 0)}`).join(" ; ")}).
              </p>
              <Source meta={d.meta} />
            </Card>

            <div className="grid gap-4 lg:grid-cols-2">
              <Card title="Drawdown (perte depuis le plus haut)">
                <LinesChart dates={d.dates} lines={drawdown} format={fmtPct} height={220} />
                <Source meta={d.meta} />
              </Card>
              <Card title={`Volatilité glissante (${d.rolling_window} séances, annualisée)`}>
                <LinesChart dates={d.dates} lines={vol} format={fmtPct} height={220} />
                <Source meta={d.meta} />
              </Card>
            </div>

            <Card title="Tableau comparatif"
                  aside={<span className="text-xs text-muted">IC 95 % entre crochets (Lo, 2002) · « hebdo. » : rendements hebdomadaires</span>}>
              <p className="mb-2 text-xs text-ink-2">
                Taux sans risque : {d.risk_free.label} ({d.risk_free.source}
                {d.risk_free.last_date ? `, dernière valeur ${d.risk_free.last_value?.toLocaleString("fr-FR")} % au ${date(d.risk_free.last_date)}` : ""}).
                Mesures relatives par rapport à <strong className="text-ink">{d.reference.name}</strong>.
              </p>
              {/* Grand écran : tableau. Petit écran : une carte par série. */}
              <div className="hidden overflow-x-auto md:block">
                <table className="data compact">
                  <thead>
                    <tr>
                      <th>Série</th>
                      {COLUMNS.map((c) => <th key={c.key} className="r">{c.label}{c.weekly && <div className="text-[10px] font-normal">hebdo.</div>}</th>)}
                    </tr>
                  </thead>
                  <tbody>
                    {d.rows.map((r) => (
                      <tr key={r.name} className={r.kind === "portefeuille" ? "font-medium" : ""}>
                        <td className="max-w-48">
                          <div className="truncate">{r.name}</div>
                          <div className="text-xs font-normal text-muted">{r.kind === "reference" ? "référence" : r.kind}
                            {r.start && r.kind === "compte" && d.dates.length > 1 && r.start > d.dates[1] ? ` · depuis le ${date(r.start)}` : ""}</div>
                          <RowNotes r={r} />
                        </td>
                        {COLUMNS.map((c) => <td key={c.key} className="r num align-top">{c.render(r)}</td>)}
                      </tr>
                    ))}
                  </tbody>
                </table>
              </div>
              <ul className="space-y-2 md:hidden">
                {d.rows.map((r) => (
                  <li key={r.name} className="rounded-md border border-line p-3 text-sm">
                    <div className="font-medium">{r.name}</div>
                    <RowNotes r={r} />
                    <dl className="mt-2 grid grid-cols-2 gap-2 text-xs">
                      {COLUMNS.map((c) => (
                        <div key={c.key}><dt className="text-muted">{c.label}{c.weekly ? " (hebdo.)" : ""}</dt><dd className="num">{c.render(r)}</dd></div>
                      ))}
                    </dl>
                  </li>
                ))}
              </ul>
              <p className="mt-2 text-xs text-muted">n.d. : non disponible (raison indiquée sous la série). Aucun indicateur
                annualisé n'est affiché sur moins d'un an.</p>
              <Source meta={d.meta} />
            </Card>

            <Card title="Lire ces chiffres">
              <div className="grid gap-4 text-sm text-ink-2 md:grid-cols-2">
                <p><strong className="text-ink">Intervalles de confiance.</strong> Un Sharpe est une estimation. Sur 3 ans, son
                  intervalle à 95 % fait environ ± 1,1 : deux portefeuilles à 0,6 et 0,9 ne sont pas distinguables.
                  Si l'intervalle du ratio d'information contient 0, la surperformance n'est pas démontrée.</p>
                <p><strong className="text-ink">Pourquoi des rendements hebdomadaires ?</strong> Euronext clôture à 17 h 30,
                  New York à 22 h. En quotidien, un mouvement américain de fin de journée n'apparaît que le lendemain
                  à Paris : corrélation et bêta sont sous-estimés. Le bêta de Dimson ajoute les semaines voisines pour
                  mesurer le biais qui subsiste.</p>
                <p><strong className="text-ink">Bêta et alpha.</strong> Un bêta de 1,2 : quand la référence gagne 10 %, le
                  portefeuille gagne 12 % en moyenne. L'alpha est le rendement annuel non expliqué par ce bêta, au-delà du
                  taux sans risque.</p>
                <p><strong className="text-ink">Tracking error et ratio d'information.</strong> La tracking error mesure
                  l'écart de trajectoire avec la référence ; le ratio d'information, la surperformance par unité de cet
                  écart. Au-delà de 0,5 de façon durable, c'est rare.</p>
              </div>
            </Card>
          </div>
        </div>
      )}
    </>
  );
}
