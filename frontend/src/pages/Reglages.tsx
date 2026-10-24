import { type FormEvent, useEffect, useState } from "react";

import { api, useLedgerMutation, useSettings } from "../api/client";
import type { AnalysisSettings, ReferenceSetting } from "../api/types";
import { Button, Card, ErrorBox, Field, Loading } from "../components/ui";

const pctIn = (s: string) => String(Math.round(Number(s) * 10000) / 100);         // 0.15 -> "15"
const pctOut = (s: string) => String(Number(s.replace(",", ".")) / 100);          // "15" -> "0.15"

/** k saisi pour une devise ; une saisie vide retire la devise (retour au taux long + prime). */
function kManual(cur: Record<string, string>, ccy: string, v: string): Record<string, string> {
  const { [ccy]: _, ...rest } = cur;
  return v.trim() === "" ? rest : { ...rest, [ccy]: pctOut(v) };
}

function RefFields({ title, value, onChange }: {
  title: string;
  value: ReferenceSetting;
  onChange: (r: ReferenceSetting) => void;
}) {
  return (
    <fieldset className="space-y-2">
      <legend className="mb-1 text-sm font-medium">{title}</legend>
      <div className="grid grid-cols-2 gap-3 md:grid-cols-4">
        <Field label="Ticker Yahoo"><input required value={value.ticker} onChange={(e) => onChange({ ...value, ticker: e.target.value })} /></Field>
        <Field label="Nom affiché"><input required maxLength={80} value={value.name} onChange={(e) => onChange({ ...value, name: e.target.value })} /></Field>
        <Field label="Devise de cotation" hint="vérifiée auprès du fournisseur">
          <input required maxLength={3} value={value.currency} onChange={(e) => onChange({ ...value, currency: e.target.value.toUpperCase() })} />
        </Field>
        <Field label="Retenue sur dividendes (%)" hint="0 pour un fonds capitalisant">
          <input inputMode="decimal" value={pctIn(value.withholding)} onChange={(e) => onChange({ ...value, withholding: pctOut(e.target.value || "0") })} />
        </Field>
      </div>
    </fieldset>
  );
}

export default function Reglages() {
  const q = useSettings();
  const save = useLedgerMutation(api.saveSettings);
  const [f, setF] = useState<AnalysisSettings | null>(null);
  useEffect(() => { if (q.data && !f) setF(q.data.settings); }, [q.data, f]);
  if (q.isLoading || !f) return <Loading />;

  const submit = (e: FormEvent) => {
    e.preventDefault();
    save.mutate(f);
  };

  return (
    <>
      <h1 className="text-lg font-semibold">Réglages d'analyse</h1>
      <Card>
        <form onSubmit={submit} className="space-y-5">
          <RefFields title="Référence principale" value={f.reference_1} onChange={(r) => setF({ ...f, reference_1: r })} />
          <RefFields title="Seconde référence" value={f.reference_2} onChange={(r) => setF({ ...f, reference_2: r })} />
          <fieldset className="space-y-2">
            <legend className="mb-1 text-sm font-medium">Taux sans risque</legend>
            <div className="grid grid-cols-2 gap-3 md:grid-cols-4">
              <Field label="Série">
                <select value={f.rf_mode} onChange={(e) => setF({ ...f, rf_mode: e.target.value as AnalysisSettings["rf_mode"] })}>
                  <option value="estr">€STR (EONIA avant le 01/10/2019)</option>
                  <option value="fixe">Taux fixe</option>
                  <option value="zero">Taux nul</option>
                </select>
              </Field>
              {f.rf_mode === "fixe" && (
                <Field label="Taux annuel (%)" hint="convention ACT/360, comme le €STR">
                  <input required inputMode="decimal" value={f.rf_fixed_rate ?? ""}
                         onChange={(e) => setF({ ...f, rf_fixed_rate: e.target.value.replace(",", ".") || null })} />
                </Field>
              )}
              <Field label="Covariance (Diversification)" hint="Ledoit-Wolf : moins de bruit d'estimation">
                <select value={f.covariance} onChange={(e) => setF({ ...f, covariance: e.target.value as AnalysisSettings["covariance"] })}>
                  <option value="lw_cc">Ledoit-Wolf, corrélation constante</option>
                  <option value="lw_id">Ledoit-Wolf, identité réduite</option>
                  <option value="empirique">Empirique</option>
                </select>
              </Field>
              <Field label="Volatilité glissante (séances)" hint="63 ≈ 3 mois">
                <input type="number" min={21} max={252} value={f.rolling_window}
                       onChange={(e) => setF({ ...f, rolling_window: Number(e.target.value) })} />
              </Field>
            </div>
          </fieldset>
          <fieldset className="space-y-2">
            <legend className="mb-1 text-sm font-medium">Valorisation (DCF inversé)</legend>
            <div className="grid grid-cols-2 gap-3 md:grid-cols-4">
              <Field label="Coût du capital k" hint="le récapitulatif utilise toujours le k commun">
                <select value={f.k_mode} onChange={(e) => setF({ ...f, k_mode: e.target.value as AnalysisSettings["k_mode"] })}>
                  <option value="devise">k commun par devise</option>
                  <option value="medaf">MEDAF par action (β de Dimson, Blume)</option>
                </select>
              </Field>
              <Field label="Prime de risque actions (%)" hint="défaut 4,20 % : Damodaran, prime implicite du S&P 500 au 01/10/2026">
                <input inputMode="decimal" required value={pctIn(f.erp)} onChange={(e) => setF({ ...f, erp: pctOut(e.target.value || "0") })} />
              </Field>
              <Field label="k EUR saisi (%)" hint="vide = taux à 10 ans BCE + prime">
                <input inputMode="decimal" value={f.k_manual.EUR ? pctIn(f.k_manual.EUR) : ""} onChange={(e) => setF({ ...f, k_manual: kManual(f.k_manual, "EUR", e.target.value) })} />
              </Field>
              <Field label="k USD saisi (%)" hint="vide = Treasury 10 ans (FRED) + prime">
                <input inputMode="decimal" value={f.k_manual.USD ? pctIn(f.k_manual.USD) : ""} onChange={(e) => setF({ ...f, k_manual: kManual(f.k_manual, "USD", e.target.value) })} />
              </Field>
              <Field label="Croissance terminale (%)" hint="sous la croissance nominale de long terme">
                <input inputMode="decimal" required value={pctIn(f.g_term)} onChange={(e) => setF({ ...f, g_term: pctOut(e.target.value || "0") })} />
              </Field>
              <Field label="Horizon N (ans)">
                <input type="number" min={1} max={30} value={f.horizon} onChange={(e) => setF({ ...f, horizon: Number(e.target.value) })} />
              </Field>
              <Field label="FCF de départ : moyenne sur" hint="exercices">
                <select value={f.fcf_years} onChange={(e) => setF({ ...f, fcf_years: Number(e.target.value) })}>
                  {[1, 2, 3, 4, 5].map((n) => <option key={n} value={n}>{n}</option>)}
                </select>
              </Field>
              <label className="flex items-center gap-2 self-end pb-2 text-sm">
                <input type="checkbox" checked={f.sbc_deduct} onChange={(e) => setF({ ...f, sbc_deduct: e.target.checked })} />
                Retrancher la rémunération en actions
              </label>
            </div>
          </fieldset>
          <ErrorBox error={save.error} />
          {save.data?.warnings.length ? (
            <ul className="list-disc pl-5 text-sm text-warn">{save.data.warnings.map((w, i) => <li key={i}>{w}</li>)}</ul>
          ) : null}
          <div className="flex items-center gap-3">
            <Button type="submit" disabled={save.isPending}>{save.isPending ? "Vérification…" : "Enregistrer"}</Button>
            {save.isSuccess && <span className="text-sm text-good">Réglages enregistrés.</span>}
          </div>
        </form>
      </Card>
      <Card title="Valeurs par défaut et leur justification">
        <ul className="list-disc space-y-1 pl-5 text-sm text-ink-2">
          <li><strong className="text-ink">QQQ</strong> (Nasdaq 100), dividendes réinvestis nets d'une retenue de 15 %
            (convention fiscale France – États-Unis), converti en euros au taux du jour.</li>
          <li><strong className="text-ink">IWDA.AS</strong> (iShares Core MSCI World, coté en EUR à Amsterdam,
            capitalisant, réplication physique, frais 0,20 %) : les dividendes sont déjà réinvestis dans le cours.</li>
          <li><strong className="text-ink">€STR</strong>, publié par la BCE ; EONIA avant le 01/10/2019.</li>
          <li><strong className="text-ink">Ledoit-Wolf à corrélation constante</strong> : contracte chaque corrélation vers la
            moyenne sans l'effacer. La cible identité les tire vers zéro et fait paraître le portefeuille plus diversifié
            qu'il n'est quand un facteur commun domine.</li>
          <li><strong className="text-ink">k commun = taux d'État à 10 ans + prime de risque</strong> (β = 1, 4,20 % par défaut : prime implicite du S&P 500 publiée par A. Damodaran, pages.stern.nyu.edu/~adamodar, au 01/10/2026, méthode principale ; fourchette 3,30 % à 5,67 % selon la méthode) : courbe AAA de la zone euro
            (BCE) pour l'EUR, Treasury (FRED) pour l'USD. C'est le coût des fonds propres d'une entreprise moyenne, un peu au-dessus
            d'un WACC typique : le g implicite est donc légèrement prudent. Justification de la prime dans METHODE.md.</li>
          <li><strong className="text-ink">Croissance terminale de 2 %</strong> : la cible d'inflation, c'est-à-dire une
            croissance réelle nulle à perpétuité, sous la croissance nominale de long terme (inflation plus croissance réelle).</li>
          <li><strong className="text-ink">Horizon de 10 ans, FCF lissé sur 3 exercices, rémunération en actions retranchée</strong> :
            elle est payée en actions plutôt qu'en espèces, mais dilue les actionnaires.</li>
        </ul>
      </Card>
    </>
  );
}
