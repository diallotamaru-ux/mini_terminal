import { type FormEvent, useEffect, useState } from "react";

import { api, useLedgerMutation, useSettings } from "../api/client";
import type { AnalysisSettings, ReferenceSetting } from "../api/types";
import { Button, Card, ErrorBox, Field, Loading } from "../components/ui";

const pctIn = (s: string) => String(Math.round(Number(s) * 10000) / 100);         // 0.15 -> "15"
const pctOut = (s: string) => String(Number(s.replace(",", ".")) / 100);          // "15" -> "0.15"

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
              <Field label="Volatilité glissante (séances)" hint="63 ≈ 3 mois">
                <input type="number" min={21} max={252} value={f.rolling_window}
                       onChange={(e) => setF({ ...f, rolling_window: Number(e.target.value) })} />
              </Field>
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
        </ul>
      </Card>
    </>
  );
}
