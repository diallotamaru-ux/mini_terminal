import { useMutation } from "@tanstack/react-query";
import { type FormEvent, useMemo, useState } from "react";

import { api, useDiversification } from "../api/client";
import type { Diversification as Div, Period, Simulation } from "../api/types";
import CorrelationHeatmap from "../charts/CorrelationHeatmap";
import PairedBars from "../charts/PairedBars";
import PeriodSelector, { usePeriod } from "../components/PeriodSelector";
import { Button, Card, ErrorBox, Field, Loading, Source, Warnings } from "../components/ui";
import { date, pct } from "../lib/format";

const dec = (v: number | null, d = 1) =>
  v === null ? "n.d." : v.toLocaleString("fr-FR", { minimumFractionDigits: d, maximumFractionDigits: d });
const p1 = (v: number | null) => (v === null ? "n.d." : pct(v, 1));

// Composantes d'un vecteur propre : des coordonnées, pas des parts.
const fmtLoading = (v: number) => dec(v, 2);

type Group = "ligne" | "compte" | "classe";
const GROUPS: { key: Group; label: string }[] = [
  { key: "ligne", label: "Par ligne" }, { key: "compte", label: "Par compte" }, { key: "classe", label: "Par classe" }];

function EnbCard({ d }: { d: Div }) {
  return (
    <Card title="Nombre effectif de paris (ENB)">
      <div className="grid grid-cols-2 gap-4 sm:grid-cols-4">
        <div>
          <div className="text-xs text-muted">ENB par ACP</div>
          <div className="num text-2xl font-semibold">{dec(d.enb_pca)} <span className="text-sm font-normal text-muted">/ {d.n_lines}</span></div>
          <div className="text-xs text-ink-2">facteurs statistiques communs</div>
        </div>
        <div>
          <div className="text-xs text-muted">ENB par torsion minimale</div>
          <div className="num text-2xl font-semibold">{dec(d.enb_mt)} <span className="text-sm font-normal text-muted">/ {d.n_lines}</span></div>
          <div className="text-xs text-ink-2">facteurs collés aux lignes</div>
        </div>
        <div>
          <div className="text-xs text-muted">1er facteur</div>
          <div className="num text-2xl font-semibold">{p1(d.pc1_variance_share)}</div>
          <div className="text-xs text-ink-2">de la variance du portefeuille</div>
        </div>
        <div>
          <div className="text-xs text-muted">Volatilité annualisée</div>
          <div className="num text-2xl font-semibold">{p1(d.sigma_risky)}</div>
          <div className="text-xs text-ink-2">lignes analysées ; {d.sigma_total === null ? "portefeuille total non calculable" : `${p1(d.sigma_total)} espèces comprises`}</div>
        </div>
      </div>
      <p className="mt-3 text-sm text-ink">{d.text}</p>
      <div className="mt-3 grid gap-3 text-xs text-ink-2 md:grid-cols-2">
        <p><strong className="text-ink">ACP</strong> : les facteurs sont les composantes principales de la covariance. Elle
          détecte un facteur commun : si toutes les lignes montent et baissent ensemble, l'ENB tend vers 1.</p>
        <p><strong className="text-ink">Torsion minimale</strong> : les facteurs sont décorrélés mais restent le plus près
          possible des lignes. Lisible ligne par ligne, mais aveugle à un facteur commun quand les poids sont proches.
          ACP basse et torsion haute : un facteur commun domine.</p>
        <p><strong className="text-ink">Volatilités</strong> : {p1(d.sigma_risky)} est celle des seules lignes analysées
          (poids renormalisés).{" "}
          {d.sigma_total !== null && d.cash_share !== null
            ? <>Avec {p1(d.cash_share)} d'espèces, de variance nulle, le portefeuille total a une volatilité de
                (1 − {p1(d.cash_share)}) × {p1(d.sigma_risky)} = {p1(d.sigma_total)}.</>
            : <>La volatilité du portefeuille total n'est pas calculée : des lignes détenues sont exclues de l'analyse
                (risque inconnu) ou une valeur manque{d.cash_share !== null ? <> ; les espèces représentent {p1(d.cash_share)} du portefeuille entier</> : null}.</>}</p>
      </div>
      <Source meta={d.meta} />
    </Card>
  );
}

function Simulator({ d, period }: { d: Div; period: Period }) {
  const [ticker, setTicker] = useState(d.lines[0]?.ticker ?? "");
  const [pctValue, setPct] = useState("10");
  const [mode, setMode] = useState<"frais" | "realloc">("frais");
  const run = useMutation({ mutationFn: api.simulate });
  const r: Simulation | undefined = run.data;
  const submit = (e: FormEvent) => {
    e.preventDefault();
    run.mutate({ period, ticker: ticker.trim().toUpperCase(), pct: Number(pctValue.replace(",", ".")), mode });
  };
  const rows: { label: string; f: (s: Simulation["before"]) => string }[] = [
    { label: "ENB par ACP", f: (s) => dec(s.enb_pca, 2) },
    { label: "ENB par torsion minimale", f: (s) => dec(s.enb_mt, 2) },
    { label: "Volatilité des lignes risquées", f: (s) => p1(s.sigma_risky) },
    { label: "Volatilité espèces comprises", f: (s) => p1(s.sigma_total) },
    { label: "Drawdown historique maximal", f: (s) => p1(s.max_drawdown) },
  ];
  return (
    <Card title="Simulateur : et si j'ajoutais… ?">
      <p className="mb-3 rounded-md border border-line p-2 text-xs text-ink-2" style={{ background: "var(--warn-bg)" }}>
        Simulation sur données passées : elle décrit ce qui se serait passé, pas ce qui se passera. Ce n'est pas un conseil
        d'investissement, et rien n'est enregistré.
      </p>
      <form onSubmit={submit} className="grid grid-cols-2 items-end gap-3 md:grid-cols-5">
        <Field label="Ligne ou nouveau ticker" hint="ex. IWDA.AS, GLD">
          <input list="sim-lines" required value={ticker} onChange={(e) => setTicker(e.target.value)} />
          <datalist id="sim-lines">{d.lines.map((l) => <option key={l.key} value={l.ticker}>{l.label}</option>)}</datalist>
        </Field>
        <Field label="Montant (% des lignes risquées)">
          <input inputMode="decimal" required value={pctValue} onChange={(e) => setPct(e.target.value)} />
        </Field>
        <Field label="Opération">
          <select value={mode} onChange={(e) => setMode(e.target.value as "frais" | "realloc")}>
            <option value="frais">Argent frais (rien n'est vendu)</option>
            <option value="realloc">Réallocation (le reste réduit au prorata)</option>
          </select>
        </Field>
        <Button type="submit" disabled={run.isPending}>{run.isPending ? "Calcul…" : "Simuler"}</Button>
      </form>
      <ErrorBox error={run.error} />
      {r && (
        <div className="mt-4 space-y-3">
          <div className="overflow-x-auto">
            <table className="data">
              <thead><tr><th>{r.target_label} : +{dec(r.pct, 1)} %</th><th className="r">Avant</th><th className="r">Après</th></tr></thead>
              <tbody>{rows.map((x) => (
                <tr key={x.label}><td>{x.label}</td><td className="r num">{x.f(r.before)}</td><td className="r num">{x.f(r.after)}</td></tr>
              ))}</tbody>
            </table>
          </div>
          <div className="overflow-x-auto">
            <table className="data">
              <thead><tr><th>Ligne</th><th className="r">Poids avant</th><th className="r">Poids après</th>
                <th className="r">Contribution avant</th><th className="r">Contribution après</th></tr></thead>
              <tbody>{r.contributions.map((c) => (
                <tr key={c.key} className={c.key === r.target ? "font-medium" : ""}>
                  <td>{c.label}</td><td className="r num">{p1(c.weight_before)}</td><td className="r num">{p1(c.weight_after)}</td>
                  <td className="r num">{p1(c.before)}</td><td className="r num">{p1(c.after)}</td>
                </tr>
              ))}</tbody>
            </table>
          </div>
          <p className="text-xs text-ink-2"><strong className="text-ink">Formule</strong> : {r.formula} Covariance :
            {" "}{r.estimator_label}. Drawdown à poids constants (rééquilibrage quotidien), du
            {" "}{date(r.drawdown_start)} au {date(r.drawdown_end)}.</p>
          {r.notes.map((n, i) => <p key={i} className="text-xs text-muted">{n}</p>)}
        </div>
      )}
    </Card>
  );
}

export default function Diversification() {
  const [period, setPeriod] = usePeriod();
  const [partial, setPartial] = useState<"inclure" | "exclure">("inclure");
  const [group, setGroup] = useState<Group>("ligne");
  const q = useDiversification(period, partial);
  const d = q.data;
  const contrib = useMemo(() => (d ? d.contributions[group].map((i) => ({ label: i.label, a: i.weight, b: i.contribution })) : []), [d, group]);
  const loadings = useMemo(() => (d ? d.pc1_loadings.map((i) => ({ label: i.label, a: null, b: i.contribution })) : []), [d]);

  return (
    <>
      <div className="flex flex-wrap items-center justify-between gap-3">
        <h1 className="text-lg font-semibold">Diversification</h1>
        <PeriodSelector value={period} onChange={setPeriod} available={d?.available_periods} />
      </div>
      {q.isLoading && <Loading />}
      <ErrorBox error={q.error} />
      {d && (
        <div className={`space-y-4 ${q.isFetching ? "opacity-60" : ""}`}>
          <p className="text-xs text-muted">
            Fenêtre : du {date(d.window_start)} au {date(d.window_end)}, {d.window_weeks} semaines de rendements en euros
            (minimum {d.min_weeks} par ligne). Poids réels au {date(d.meta.as_of)}, espèces exclues. Covariance :
            {" "}{d.estimator_label}{d.shrinkage !== null ? `, intensité de contraction ${dec(d.shrinkage, 2)}` : ""}.
          </p>
          {d.partial_mode === "exclure" && (
            <div className="flex flex-wrap items-center gap-3 rounded-md border border-line p-3 text-sm">
              <span>Comparaison : lignes à historique partiel exclues.</span>
              <Button variant="ghost" onClick={() => setPartial("inclure")}>Revenir à l'analyse complète</Button>
            </div>
          )}
          {d.higham.warning && (
            <div className="flex flex-wrap items-center gap-3 rounded-md border border-line p-3 text-sm" role="alert" style={{ background: "var(--warn-bg)" }}>
              <span className="text-ink-2"><strong className="text-warn">Correction importante de la matrice.</strong> Les lignes à
                historique partiel rendent la covariance incohérente ; un coefficient a bougé de {dec(d.higham.max_corr_change, 2)}
                (seuil {dec(d.higham.threshold, 2)}).</span>
              <Button variant="ghost" onClick={() => setPartial("exclure")}>Comparer en excluant les lignes partielles</Button>
            </div>
          )}
          <Warnings items={d.meta.warnings} />
          <EnbCard d={d} />

          <div className="grid gap-4 lg:grid-cols-2">
            <Card title="Corrélations (hebdomadaires, en euros)">
              <CorrelationHeatmap labels={d.correlation.labels} values={d.correlation.values} />
              <details className="mt-2 text-xs text-muted">
                <summary className="cursor-pointer">Voir le tableau</summary>
                <div className="mt-1 overflow-x-auto">
                  <table className="data">
                    <thead><tr><th></th>{d.correlation.labels.map((l) => <th key={l} className="r">{l}</th>)}</tr></thead>
                    <tbody>{d.correlation.values.map((row, i) => (
                      <tr key={i}><td>{d.correlation.labels[i]}</td>{row.map((v, j) => <td key={j} className="r num">{dec(v, 2)}</td>)}</tr>
                    ))}</tbody>
                  </table>
                </div>
              </details>
              <Source meta={d.meta} />
            </Card>

            <Card title="Contributions au risque (Euler)"
                  aside={<div className="flex gap-1" role="radiogroup" aria-label="Regroupement">
                    {GROUPS.map((g) => (
                      <button key={g.key} role="radio" aria-checked={group === g.key} onClick={() => setGroup(g.key)}
                              className={`rounded-md border px-2 py-0.5 text-xs ${group === g.key ? "border-accent bg-surface-2" : "border-line text-ink-2"}`}>{g.label}</button>
                    ))}</div>}>
              <PairedBars rows={contrib} nameA="Poids" nameB="Contribution au risque" />
              <p className="mt-2 text-xs text-ink-2">Une ligne dont la contribution dépasse le poids porte plus de risque que de
                capital. La somme des contributions vaut 100 %.</p>
              <Source meta={d.meta} />
            </Card>
          </div>

          <Card title="Qui porte le premier facteur ?">
            <PairedBars rows={loadings} nameB="Composante du 1er facteur" format={fmtLoading} />
            <p className="mt-2 text-xs text-ink-2">Composantes du premier vecteur propre de la covariance (part de variance du
              portefeuille : {p1(d.pc1_variance_share)} ; part de la première valeur propre : {p1(d.pc1_eigen_share)}). Plus une
              composante est grande, plus la ligne suit ce facteur commun.</p>
          </Card>

          <Card title={`Lignes analysées (${d.lines.length})`}>
            <div className="overflow-x-auto">
              <table className="data">
                <thead><tr><th>Ligne</th><th>Classe</th><th className="r">Poids</th><th className="r">Semaines</th><th></th></tr></thead>
                <tbody>{d.lines.map((l) => (
                  <tr key={l.key}><td>{l.label} <span className="text-xs text-muted">{l.ticker}</span></td><td>{l.asset_class}</td>
                    <td className="r num">{p1(l.weight)}</td><td className="r num">{l.n_weeks}</td>
                    <td className="text-xs text-warn">{l.partial ? "historique partiel" : ""}</td></tr>
                ))}</tbody>
              </table>
            </div>
            {d.excluded.length > 0 && (
              <div className="mt-3 text-sm">
                <div className="font-medium text-warn">Lignes exclues ({d.excluded.length})</div>
                <ul className="list-disc pl-5 text-ink-2">{d.excluded.map((e) => <li key={e.key}>{e.label} : {e.reason}</li>)}</ul>
              </div>
            )}
          </Card>

          <Simulator d={d} period={period} />
        </div>
      )}
    </>
  );
}
