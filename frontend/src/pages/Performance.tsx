import { usePerformance } from "../api/client";
import type { Mwr, PerformanceBlock, Twr } from "../api/types";
import { Card, ErrorBox, Loading, Source, Warnings } from "../components/ui";
import { CASH_MODE_LABEL, date, pct, signClass } from "../lib/format";

function period(start: string | null, end: string | null, days: number) {
  if (!start) return "aucune période";
  return `du ${date(start)} au ${date(end)} (${days} jours)`;
}

function TwrCell({ t, label }: { t: Twr; label: string }) {
  return (
    <div>
      <div className="text-xs text-muted">{label}</div>
      <div className={`num text-xl font-semibold ${signClass(t.total)}`}>{pct(t.total, 2, true)}</div>
      <div className="num text-xs text-ink-2">
        {t.annualized !== null ? `${pct(t.annualized, 2, true)} par an` : t.total !== null ? "non annualisé (moins d'un an)" : ""}
      </div>
      {t.warnings.map((w, i) => <div key={i} className="mt-1 text-xs text-warn">{w}</div>)}
    </div>
  );
}

function MwrCell({ m }: { m: Mwr }) {
  return (
    <div>
      <div className="text-xs text-muted">TRI (pondéré par les capitaux)</div>
      <div className={`num text-xl font-semibold ${signClass(m.rate)}`}>{pct(m.rate, 2, true)}</div>
      <div className="text-xs text-ink-2">{m.rate === null ? "" : m.annualized ? "par an" : "sur la période, non annualisé"}</div>
      {m.warnings.map((w, i) => <div key={i} className="mt-1 text-xs text-warn">{w}</div>)}
    </div>
  );
}

function Block({ b, main = false }: { b: PerformanceBlock; main?: boolean }) {
  return (
    <Card title={main ? "Portefeuille complet" : b.name}
          aside={<span className="text-xs text-muted">{b.cash_mode ? `${CASH_MODE_LABEL[b.cash_mode]} · ` : ""}{period(b.twr.start, b.twr.end, b.twr.days)}</span>}>
      <div className="grid grid-cols-1 gap-4 sm:grid-cols-3">
        <TwrCell t={b.twr} label={b.cash_mode === "avec_especes" ? "TWR du compte (espèces comprises)" : "TWR (pondéré par le temps)"} />
        {b.twr_securities ? <TwrCell t={b.twr_securities} label="TWR des titres seuls" /> : <div className="hidden sm:block" />}
        <MwrCell m={b.mwr} />
      </div>
    </Card>
  );
}

export default function Performance() {
  const q = usePerformance();
  if (q.isLoading) return <Loading />;
  if (q.error) return <ErrorBox error={q.error} />;
  const p = q.data!;
  return (
    <>
      <h1 className="text-lg font-semibold">Performance depuis l'origine</h1>
      <Warnings items={p.meta.warnings} />
      <Block b={p.total} main />

      <Card title="Lire ces deux mesures">
        <div className="grid gap-4 text-sm text-ink-2 md:grid-cols-2">
          <div>
            <h3 className="mb-1 font-medium text-ink">TWR : la qualité des choix</h3>
            <p>
              Le rendement pondéré par le temps enchaîne les rendements de chaque jour,
              <span className="num"> TWR = ∏ (1 + r<sub>t</sub>) − 1</span>, en retirant l'effet des apports et des retraits.
              Il ne dépend pas du moment où vous avez versé de l'argent. C'est la mesure à comparer à un indice
              (le Nasdaq 100 en phase 2).
            </p>
          </div>
          <div>
            <h3 className="mb-1 font-medium text-ink">TRI : ce que vous avez vécu</h3>
            <p>
              Le rendement pondéré par les capitaux est le taux r qui annule
              <span className="num"> Σ CF<sub>t</sub> / (1 + r)<sup>(t − t₀)/365</sup></span>. Il pèse davantage les
              périodes où beaucoup d'argent était investi. En DCA, un TRI inférieur au TWR signifie que vos plus gros
              versements sont arrivés avant des baisses, ou après des hausses.
            </p>
          </div>
          <div>
            <h3 className="mb-1 font-medium text-ink">Compte avec espèces : deux TWR</h3>
            <p>
              Le TWR du compte inclut les espèces qui attendent d'être investies : elles diluent la performance.
              Le TWR des titres seuls mesure uniquement les lignes détenues. C'est le même calcul que pour un compte
              en convention « titres seuls ».
            </p>
          </div>
          <div>
            <h3 className="mb-1 font-medium text-ink">Conventions</h3>
            <p>
              Apports en début de journée, retraits en fin de journée. Pas d'annualisation sous un an : un +2 % sur
              trois mois ne devient pas « +8 % par an ». Ces chiffres ne contiennent aucun intervalle de confiance :
              les ratios de risque et leurs marges d'erreur arrivent en phase 2.
            </p>
          </div>
        </div>
      </Card>

      {p.accounts.map((b) => <Block key={b.id} b={b} />)}
      <Source meta={p.meta} />
    </>
  );
}
