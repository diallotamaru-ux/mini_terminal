import { type FormEvent, useEffect, useState } from "react";
import { Link, useParams } from "react-router-dom";

import { api, useValuation, useValuationMutation } from "../api/client";
import type { FundamentalField, KOut, ProfileIn, Valuation, ValuationProfile } from "../api/types";
import PriceChart from "../charts/PriceChart";
import { Button, Card, ErrorBox, Field, Loading, Source, Warnings } from "../components/ui";
import { big, date, dateTime, dec, num, pct, scaleDecimal } from "../lib/format";
import { growth, STATUS_LABEL } from "./Valorisation";

export const FIELDS: { key: FundamentalField; label: string; amount: boolean }[] = [
  { key: "revenue", label: "Chiffre d'affaires", amount: true },
  { key: "ocf", label: "Flux de trésorerie d'exploitation (OCF)", amount: true },
  { key: "capex", label: "Investissements (capex)", amount: true },
  { key: "fcf_reported", label: "Flux disponible publié (OCF + capex)", amount: true },
  { key: "sbc", label: "Rémunération en actions", amount: true },
  { key: "interest_expense", label: "Charge d'intérêts", amount: true },
  { key: "pretax_income", label: "Résultat avant impôt", amount: true },
  { key: "tax_provision", label: "Impôt sur les résultats", amount: true },
  { key: "total_debt", label: "Dette totale", amount: true },
  { key: "lease_liabilities", label: "dont dettes locatives", amount: true },
  { key: "cash_sti", label: "Trésorerie et placements", amount: true },
  { key: "minority_interest", label: "Intérêts minoritaires", amount: true },
  { key: "diluted_shares", label: "Actions diluées (moyenne)", amount: false },
];
const LABEL = Object.fromEntries(FIELDS.map((f) => [f.key, f.label])) as Record<string, string>;

const pctIn = (v: number | null) => (v === null ? "" : String(Math.round(v * 10000) / 100).replace(".", ","));
const pctOut = (s: string) => (s.trim() === "" ? null : String(Number(s.replace(",", ".")) / 100));

// ---------------------------------------------------------------------------

function KBox({ k, n, used }: { k: KOut | null; n: number; used: boolean }) {
  if (!k) return null;
  return (
    <div className={`rounded-md border p-3 ${used ? "border-accent" : "border-line"}`}>
      <div className="text-xs text-muted">Avec le k {k.label}{used ? " (retenu)" : ""}</div>
      {k.k === null ? (
        <div className="mt-1 text-sm text-warn">{k.error}</div>
      ) : (
        <>
          <div className="num mt-1 text-xl font-semibold">{k.g === null ? "—" : pct(k.g, 1)}
            <span className="ml-2 text-sm font-normal text-ink-2">par an pendant {n} ans, k = {pct(k.k, 2)}</span></div>
          {k.error && <div className="mt-1 text-xs text-warn">{k.error}</div>}
          <div className="mt-1 text-xs text-ink-2">{k.detail}</div>
        </>
      )}
    </div>
  );
}

function ResultCard({ v }: { v: Valuation }) {
  const p = v.profile!;
  const extra = v.k_used && v.k_used.label === "personnalisé";
  return (
    <Card title="Ce que suppose le prix actuel">
      <p className="text-base text-ink">{v.sentence}</p>
      <div className={`mt-3 grid gap-3 ${extra ? "md:grid-cols-3" : "md:grid-cols-2"}`}>
        {extra && <KBox k={v.k_used} n={p.horizon} used />}
        <KBox k={v.k_common} n={p.horizon} used={v.k_used?.label === v.k_common?.label} />
        <KBox k={v.k_capm} n={p.horizon} used={v.k_used?.label === "MEDAF"} />
      </div>
      <div className="mt-3 grid grid-cols-2 gap-3 text-sm sm:grid-cols-4">
        <div><div className="text-xs text-muted">FCF de départ (moyenne {v.fcf_window.length} ex.)</div>
          <div className="num font-semibold">{big(v.fcff0, v.accounts_currency)}</div></div>
        <div><div className="text-xs text-muted">Croissance historique du FCF</div>
          <div className="num font-semibold">{growth(v.growth_fcff)}</div></div>
        <div><div className="text-xs text-muted">Croissance historique du chiffre d'affaires</div>
          <div className="num font-semibold">{growth(v.growth_revenue)}</div></div>
        <div><div className="text-xs text-muted">VE / FCF de départ</div>
          <div className="num font-semibold">{v.ev && v.fcff0 ? dec(v.ev.ev / v.fcff0, 1) : "manquant"}</div></div>
      </div>
      <p className="mt-3 text-xs text-ink-2">
        La croissance historique porte sur les exercices disponibles (nombre d'années entre parenthèses), pas sur les {p.horizon} ans
        du modèle : c'est un repère, pas une prévision. Lecture d'hypothèses, pas un conseil d'investissement.
      </p>
    </Card>
  );
}

function BlockedCard({ v, onProfile, busy }: { v: Valuation; onProfile: (b: ProfileIn) => void; busy: boolean }) {
  const p = v.profile;
  const fields = new Set(v.missing.map((m) => m.field));
  const keep = p ? profileToIn(p) : {};
  return (
    <Card title="Calcul bloqué : données manquantes">
      <p className="text-sm text-ink-2">Une donnée manquante n'est jamais remplacée par zéro. Saisissez-la dans le tableau des comptes
        ci-dessous (voie préférée), ou choisissez explicitement une autre option.</p>
      <ul className="mt-2 list-disc space-y-1 pl-5 text-sm">
        {v.missing.map((m, i) => <li key={i}><strong>{LABEL[m.field] ?? m.label}</strong>{m.fiscal_end ? ` (exercice clos le ${date(m.fiscal_end)})` : ""} : {m.remedy}.</li>)}
      </ul>
      <div className="mt-3 flex flex-wrap gap-2">
        {fields.has("interest_expense") && (
          <Button variant="ghost" disabled={busy} onClick={() => onProfile({ ...keep, accept_interest_approx: true })}>
            Accepter l'approximation OCF − capex</Button>
        )}
        {fields.has("minority_interest") && (
          <Button variant="ghost" disabled={busy} onClick={() => onProfile({ ...keep, accept_minority_approx: true })}>
            Accepter la VE sans minoritaires</Button>
        )}
        {fields.has("sbc") && (
          <Button variant="ghost" disabled={busy} onClick={() => onProfile({ ...keep, sbc_deduct: false })}>
            Ne pas retrancher la rémunération en actions</Button>
        )}
      </div>
      {fields.has("interest_expense") && (
        <p className="mt-2 text-xs text-ink-2">Approximation OCF − capex : le FCFF est alors sous-estimé des intérêts après impôt, donc le
          g implicite est surestimé. Le choix est mémorisé pour cette action et signalé partout.</p>
      )}
    </Card>
  );
}

function EvCard({ v }: { v: Valuation }) {
  const e = v.ev!;
  const cur = e.accounts_currency;
  return (
    <Card title="Valeur d'entreprise">
      <table className="data compact">
        <tbody>
          <tr><td>Cours ({date(e.price_date)})</td><td className="r num">{num(e.price, 2)} {e.price_currency}</td></tr>
          {e.price_currency !== cur && <tr><td>Change {e.price_currency} → {cur}</td><td className="r num">{num(e.fx, 6)}</td></tr>}
          <tr><td>× actions diluées</td><td className="r num">{big(e.shares)}</td></tr>
          <tr><td>= Capitalisation</td><td className="r num">{big(e.market_cap, cur)}</td></tr>
          <tr><td>+ Dette<div className="text-[11px] text-muted">{e.debt_rule}</div></td><td className="r num">{big(e.debt, cur)}</td></tr>
          <tr><td>− Trésorerie et placements</td><td className="r num">{big(e.cash, cur)}</td></tr>
          <tr><td>+ Intérêts minoritaires</td><td className="r num">{e.minority === null ? "manquant (approximation)" : big(e.minority, cur)}</td></tr>
          <tr className="font-semibold"><td>= Valeur d'entreprise</td><td className="r num">{big(e.ev, cur)}</td></tr>
        </tbody>
      </table>
      <p className="mt-2 text-xs text-ink-2">Dette, trésorerie, minoritaires et actions au bilan du {date(e.balance_date)} ; cours du
        {" "}{date(e.price_date)}. La VE est comparée au FCFF, flux avant paiement des créanciers : jamais la capitalisation seule.</p>
    </Card>
  );
}

function FundamentalsCard({ v, ticker }: { v: Valuation; ticker: string }) {
  const cur = v.accounts_currency;
  const save = useValuationMutation(ticker, (b: Parameters<typeof api.saveFundamental>[1]) => api.saveFundamental(ticker, b));
  const del = useValuationMutation(ticker, (b: { fiscal_end: string; field: string }) => api.deleteFundamental(ticker, b.fiscal_end, b.field));
  const firstMissing = v.missing.find((m) => m.fiscal_end && FIELDS.some((f) => f.key === m.field));
  const [form, setForm] = useState({ fiscal_end: "", field: "interest_expense" as FundamentalField, value: "", unit: 6, note: "" });
  useEffect(() => {
    if (firstMissing) setForm((f) => ({ ...f, fiscal_end: firstMissing.fiscal_end!, field: firstMissing.field as FundamentalField }));
    else if (v.years.length) setForm((f) => (f.fiscal_end ? f : { ...f, fiscal_end: v.years[v.years.length - 1].fiscal_end }));
  }, [firstMissing?.fiscal_end, firstMissing?.field, v.years.length]); // eslint-disable-line react-hooks/exhaustive-deps
  const scaled = scaleDecimal(form.value, form.unit);
  const submit = (e: FormEvent) => {
    e.preventDefault();
    if (scaled === null || !form.fiscal_end) return;
    save.mutate({ fiscal_end: form.fiscal_end, field: form.field, value: scaled, note: form.note.trim() || null });
  };
  const manual = v.years.flatMap((y) => FIELDS.filter((f) => y.values[f.key].manual).map((f) => ({ y, f, c: y.values[f.key] })));
  const window = new Set(v.fcf_window);

  return (
    <Card title={`Comptes annuels (${cur ?? "devise inconnue"})`}>
      {v.years.length === 0 ? <p className="text-sm text-muted">Aucun exercice chez le fournisseur : saisissez-les à la main.</p> : (
        <div className="overflow-x-auto">
          <table className="data compact">
            <thead><tr><th>Exercice clos le</th>{v.years.map((y) => (
              <th key={y.fiscal_end} className="r">{date(y.fiscal_end)}{window.has(y.fiscal_end) && <div className="text-[10px] font-normal text-muted">FCF de départ</div>}</th>
            ))}</tr></thead>
            <tbody>
              {FIELDS.map((f) => (
                <tr key={f.key}>
                  <td>{f.label}</td>
                  {v.years.map((y) => {
                    const c = y.values[f.key];
                    return (
                      <td key={y.fiscal_end} className={`r num ${c.value === null ? "text-muted" : ""}`}
                          title={c.manual ? `Saisie manuelle${c.note ? ` : ${c.note}` : ""}` : undefined}>
                        {f.amount ? big(c.value, cur) : big(c.value)}
                        {c.manual && <span className="ml-1 rounded border border-accent px-0.5 text-[10px] text-accent">manuel</span>}
                      </td>
                    );
                  })}
                </tr>
              ))}
              <tr className="font-semibold">
                <td>FCFF calculé</td>
                {v.years.map((y) => <td key={y.fiscal_end} className={`r num ${y.fcff === null ? "text-muted" : ""}`}>{big(y.fcff, cur)}</td>)}
              </tr>
            </tbody>
          </table>
        </div>
      )}
      {v.fcff_rule && (
        <p className="mt-2 text-xs text-ink-2"><strong className="text-ink">{v.fcff_rule}</strong>
          {v.tax_rate !== null && <> ; t = {pct(v.tax_rate, 1)} ({v.tax_source})</>}. Montants « manquant » : absents chez le fournisseur.</p>
      )}
      <p className="mt-1 text-xs text-muted">
        Source : {v.fundamentals_source ?? "aucune"}{v.fundamentals_fetched_at ? `, téléchargé le ${dateTime(v.fundamentals_fetched_at)}` : ""}.
        Les valeurs marquées « manuel » ont été saisies à la main et priment sur le fournisseur.
      </p>

      <form onSubmit={submit} className="mt-4 grid grid-cols-2 gap-3 border-t border-line pt-3 md:grid-cols-6">
        <div className="col-span-2 text-sm font-medium md:col-span-6">Saisir ou corriger une valeur</div>
        <Field label="Exercice clos le" hint="nouvel exercice possible">
          <input type="date" required value={form.fiscal_end} onChange={(e) => setForm({ ...form, fiscal_end: e.target.value })} />
        </Field>
        <Field label="Poste">
          <select value={form.field} onChange={(e) => setForm({ ...form, field: e.target.value as FundamentalField })}>
            {FIELDS.map((f) => <option key={f.key} value={f.key}>{f.label}</option>)}
          </select>
        </Field>
        <Field label="Valeur" hint={form.field === "capex" ? "négative (décaissement)" : "0 si la société n'en a pas"}>
          <input required inputMode="decimal" value={form.value} onChange={(e) => setForm({ ...form, value: e.target.value })} />
        </Field>
        <Field label="Unité">
          <select value={form.unit} onChange={(e) => setForm({ ...form, unit: Number(e.target.value) })}>
            <option value={0}>unités</option><option value={6}>millions</option><option value={9}>milliards</option>
          </select>
        </Field>
        <Field label="Note (source)" hint="ex. rapport annuel 2025, p. 112">
          <input maxLength={300} value={form.note} onChange={(e) => setForm({ ...form, note: e.target.value })} />
        </Field>
        <div className="flex items-end">
          <Button type="submit" disabled={save.isPending || scaled === null}>Enregistrer</Button>
        </div>
        {form.value && scaled !== null && (
          <div className="col-span-2 text-xs text-ink-2 md:col-span-6">Valeur enregistrée : {big(scaled, form.field === "diluted_shares" ? null : cur)}</div>
        )}
        <div className="col-span-2 md:col-span-6"><ErrorBox error={save.error ?? del.error} /></div>
      </form>

      {manual.length > 0 && (
        <div className="mt-3 border-t border-line pt-3 text-sm">
          <div className="font-medium">Saisies manuelles ({manual.length})</div>
          <ul className="mt-1 space-y-1">
            {manual.map(({ y, f, c }) => (
              <li key={`${y.fiscal_end}-${f.key}`} className="flex flex-wrap items-center gap-2">
                <span>{f.label}, {date(y.fiscal_end)} : <span className="num">{big(c.value, f.amount ? cur : null)}</span></span>
                <span className="text-xs text-muted">{c.note ?? "sans note"} · {dateTime(c.entered_at)}</span>
                <button className="text-xs text-bad underline" disabled={del.isPending}
                        onClick={() => del.mutate({ fiscal_end: y.fiscal_end, field: f.key })}>Supprimer</button>
              </li>
            ))}
          </ul>
        </div>
      )}
    </Card>
  );
}

function profileToIn(p: ValuationProfile): ProfileIn {
  const custom = new Set(p.custom);
  return {
    standard: p.standard_proposed ? null : p.standard,
    interest_class: p.interest_class,
    financial: p.financial,
    k: p.k === null ? null : String(p.k),
    horizon: custom.has("horizon") ? p.horizon : null,
    g_term: custom.has("g_term") ? String(p.g_term) : null,
    fcf_years: custom.has("fcf_years") ? p.fcf_years : null,
    sbc_deduct: custom.has("sbc_deduct") ? p.sbc_deduct : null,
    statutory_tax: p.statutory_tax === null ? null : String(p.statutory_tax),
    accept_interest_approx: p.accept_interest_approx,
    accept_minority_approx: p.accept_minority_approx,
  };
}

function ProfileCard({ v, ticker }: { v: Valuation; ticker: string }) {
  const p = v.profile!;
  const save = useValuationMutation(ticker, (b: ProfileIn) => api.saveProfile(ticker, b));
  const [f, setF] = useState(() => ({
    standard: p.standard, interest_class: p.interest_class, k: pctIn(p.k), horizon: String(p.horizon),
    g_term: pctIn(p.g_term), fcf_years: String(p.fcf_years), sbc_deduct: p.sbc_deduct,
    statutory_tax: pctIn(p.statutory_tax), ai: p.accept_interest_approx, am: p.accept_minority_approx,
    financial: p.financial,
  }));
  const submit = (e: FormEvent) => {
    e.preventDefault();
    save.mutate({
      standard: f.standard, interest_class: f.interest_class, financial: f.financial, k: pctOut(f.k),
      horizon: Number(f.horizon), g_term: pctOut(f.g_term), fcf_years: Number(f.fcf_years), sbc_deduct: f.sbc_deduct,
      statutory_tax: pctOut(f.statutory_tax), accept_interest_approx: f.ai, accept_minority_approx: f.am,
    });
  };
  return (
    <Card title="Hypothèses">
      <form onSubmit={submit} className="space-y-3">
        <div className="grid grid-cols-2 gap-3 md:grid-cols-4">
          <Field label="Norme comptable" hint={p.standard_proposed ? "proposée d'après la cotation : à vérifier" : "confirmée"}>
            <select value={f.standard} onChange={(e) => setF({ ...f, standard: e.target.value as "us_gaap" | "ifrs" })}>
              <option value="ifrs">IFRS</option><option value="us_gaap">US GAAP</option>
            </select>
          </Field>
          <Field label="Intérêts versés classés" hint={f.standard === "us_gaap" ? "toujours en exploitation en US GAAP" : "choix publié par la société"}>
            <select value={f.standard === "us_gaap" ? "exploitation" : f.interest_class} disabled={f.standard === "us_gaap"}
                    onChange={(e) => setF({ ...f, interest_class: e.target.value as "exploitation" | "financement" })}>
              <option value="exploitation">en exploitation</option><option value="financement">en financement</option>
            </select>
          </Field>
          <Field label="k personnalisé (%)" hint="vide = k commun ou MEDAF (réglages)">
            <input inputMode="decimal" value={f.k} onChange={(e) => setF({ ...f, k: e.target.value })} />
          </Field>
          <Field label="Horizon N (ans)">
            <input type="number" min={1} max={30} required value={f.horizon} onChange={(e) => setF({ ...f, horizon: e.target.value })} />
          </Field>
          <Field label="Croissance terminale (%)">
            <input inputMode="decimal" required value={f.g_term} onChange={(e) => setF({ ...f, g_term: e.target.value })} />
          </Field>
          <Field label="FCF de départ : moyenne sur" hint="exercices, pour lisser une année atypique">
            <select value={f.fcf_years} onChange={(e) => setF({ ...f, fcf_years: e.target.value })}>
              {[1, 2, 3, 4, 5].map((n) => <option key={n} value={n}>{n} exercice{n > 1 ? "s" : ""}</option>)}
            </select>
          </Field>
          <Field label="Taux d'impôt légal (%)" hint="vide = taux effectif moyen publié">
            <input inputMode="decimal" value={f.statutory_tax} onChange={(e) => setF({ ...f, statutory_tax: e.target.value })} />
          </Field>
          <Field label="Banque ou assurance">
            <select value={f.financial === null ? "auto" : f.financial ? "oui" : "non"}
                    onChange={(e) => setF({ ...f, financial: e.target.value === "auto" ? null : e.target.value === "oui" })}>
              <option value="auto">selon le secteur du fournisseur</option><option value="oui">oui (exclure)</option><option value="non">non</option>
            </select>
          </Field>
        </div>
        <div className="flex flex-col gap-1 text-sm">
          <label className="flex items-center gap-2"><input type="checkbox" checked={f.sbc_deduct} onChange={(e) => setF({ ...f, sbc_deduct: e.target.checked })} />
            Retrancher la rémunération en actions du FCF (elle dilue les actionnaires)</label>
          <label className="flex items-center gap-2"><input type="checkbox" checked={f.ai} onChange={(e) => setF({ ...f, ai: e.target.checked })} />
            Accepter l'approximation OCF − capex si la charge d'intérêts manque (g implicite surestimé)</label>
          <label className="flex items-center gap-2"><input type="checkbox" checked={f.am} onChange={(e) => setF({ ...f, am: e.target.checked })} />
            Accepter une VE sans intérêts minoritaires s'ils manquent</label>
        </div>
        <p className="text-xs text-ink-2">Norme et classement des intérêts : à vérifier dans le rapport annuel de la société (tableau des flux
          de trésorerie et note sur les contrats de location).</p>
        <ErrorBox error={save.error} />
        <div className="flex flex-wrap gap-2">
          <Button type="submit" disabled={save.isPending}>Recalculer</Button>
          <Button type="button" variant="ghost" disabled={save.isPending} onClick={() => save.mutate({})}>Valeurs par défaut</Button>
        </div>
      </form>
    </Card>
  );
}

function SensitivityCard({ v }: { v: Valuation }) {
  const grid = v.sensitivity;
  if (!grid.length) return null;
  const k0 = v.k_used!.k!;
  const gt0 = v.profile!.g_term;
  return (
    <Card title="Sensibilité du g implicite">
      <div className="overflow-x-auto">
        <table className="data compact">
          <thead>
            <tr><th>k \ croissance terminale</th>{grid[0].map((c) => <th key={c.g_term} className="r">{pct(c.g_term, 1)}</th>)}</tr>
          </thead>
          <tbody>
            {grid.map((row) => (
              <tr key={row[0].k}>
                <td className="num">{pct(row[0].k, 1)}</td>
                {row.map((c) => {
                  const center = Math.abs(c.k - k0) < 1e-9 && Math.abs(c.g_term - gt0) < 1e-9;
                  return (
                    <td key={c.g_term} className={`r num ${center ? "font-semibold outline outline-1 outline-accent" : ""} ${c.g === null ? "text-xs text-muted" : ""}`}
                        title={c.reason ?? undefined}>
                      {c.g === null ? (c.reason === "k ≤ g terminal" ? c.reason : "sans solution") : pct(c.g, 1)}
                    </td>
                  );
                })}
              </tr>
            ))}
          </tbody>
        </table>
      </div>
      <p className="mt-2 text-xs text-ink-2">Chaque case : la croissance annuelle sur {v.profile!.horizon} ans qui égalise la valeur actualisée
        des flux et la valeur d'entreprise. Un k plus élevé exige plus de croissance ; une croissance terminale plus élevée en exige
        moins. Case encadrée : hypothèses retenues.</p>
    </Card>
  );
}

// ---------------------------------------------------------------------------

export default function FicheValorisation() {
  const { ticker = "" } = useParams();
  const q = useValuation(ticker);
  const v = q.data;
  const quick = useValuationMutation(ticker, (b: ProfileIn) => api.saveProfile(ticker, b));
  return (
    <>
      <div className="flex flex-wrap items-baseline gap-x-3 gap-y-1">
        <Link to="/valorisation" className="text-sm text-accent">← Récapitulatif</Link>
        <h1 className="text-lg font-semibold">{v?.name ?? ticker}</h1>
        {v && <span className="text-sm text-muted">{v.ticker}{v.isin ? ` · ${v.isin}` : ""}{v.industry ? ` · ${v.sector} / ${v.industry}` : ""}</span>}
        {v && <span className={`rounded border border-line px-1 text-xs ${v.status === "ok" ? "text-good" : "text-warn"}`}>{STATUS_LABEL[v.status]}</span>}
      </div>
      {q.isLoading && <Loading label="Lecture des comptes annuels…" />}
      <ErrorBox error={q.error ?? quick.error} />
      {v && (
        <div className="space-y-4">
          {v.status === "exclue" && <Card title="Hors périmètre"><p className="text-sm">{v.reason}</p><Source meta={v.meta} /></Card>}
          {v.status === "impossible" && (
            <div className="rounded-md border border-line p-3 text-sm" role="alert" style={{ background: "var(--warn-bg)" }}>
              <strong className="text-warn">Pas de DCF inversé.</strong> <span className="text-ink-2">{v.reason}</span>
            </div>
          )}
          <Warnings items={[...v.warnings, ...v.meta.warnings]} />
          {v.status === "bloquee" && <BlockedCard v={v} onProfile={(b) => quick.mutate(b)} busy={quick.isPending} />}
          {v.status === "ok" && <ResultCard v={v} />}
          {v.status !== "exclue" && (
            <>
              <div className="grid gap-4 lg:grid-cols-2">
                {v.prices.length > 0 && (
                  <Card title="Cours (hebdomadaire, 5 ans)"><PriceChart points={v.prices} currency={v.ev?.price_currency ?? ""} /><Source meta={v.meta} /></Card>
                )}
                {v.ev && <EvCard v={v} />}
              </div>
              {v.status === "ok" && <SensitivityCard v={v} />}
              <FundamentalsCard v={v} ticker={ticker} />
              {v.profile && <ProfileCard key={JSON.stringify(v.profile)} v={v} ticker={ticker} />}
              <Source meta={v.meta} />
            </>
          )}
        </div>
      )}
    </>
  );
}
