import { useCallback, useEffect, useMemo, useState } from "react";
import { getActiveClientId, getActiveClientName } from "../app/activeClient";
import {
  CHANNELS, CONFIDENCE, OBJECTIVES, allocationTotal, getBaseline, getPlan, money, num, percent, recommendPlan, runSimulation, savePlan,
  type Assumption, type Baseline, type Channel, type Objective, type PlanVsActual, type Recommendation, type Simulation,
} from "../app/media";
import Shell from "../components/Shell";
import PageHeader from "../components/data/PageHeader";
import "../styles/studio.css";

const MONTH_NAMES = ["janeiro", "fevereiro", "março", "abril", "maio", "junho", "julho", "agosto", "setembro", "outubro", "novembro", "dezembro"];
const SCENARIO_LABEL = { conservador: "Conservador", esperado: "Esperado", otimista: "Otimista" } as const;
const ASSUMPTION_FIELDS: { key: keyof Assumption; label: string; step: string; ratio?: boolean }[] = [
  { key: "cpm", label: "CPM (R$)", step: "0.01" }, { key: "cpc", label: "CPC (R$)", step: "0.01" },
  { key: "conversion_rate", label: "Conversão (%)", step: "0.01", ratio: true }, { key: "value_per_conversion", label: "Valor por conversão (R$)", step: "0.01" },
];
const message = (cause: unknown, fallback: string) => (cause instanceof Error && cause.message ? cause.message : fallback);
const nextMonth = () => { const d = new Date(); const n = new Date(d.getFullYear(), d.getMonth() + 1, 1); return `${n.getFullYear()}-${String(n.getMonth() + 1).padStart(2, "0")}`; };
const shiftMonth = (m: string, n: number) => { const d = new Date(Number(m.slice(0, 4)), Number(m.slice(5)) - 1 + n, 1); return `${d.getFullYear()}-${String(d.getMonth() + 1).padStart(2, "0")}`; };

/** Mídia On: plano de mídia paga com os CPM/CPC/CPA reais da empresa e planejado x realizado. */
export default function MediaOn({ canManage }: { canManage: boolean }) {
  const clientId = getActiveClientId();
  const clientName = getActiveClientName() || "marca";
  const [month, setMonth] = useState(nextMonth);
  const [base, setBase] = useState<Baseline | null>(null);
  const [plan, setPlan] = useState<PlanVsActual | null>(null);
  const [objective, setObjective] = useState<Objective>("vendas");
  const [budget, setBudget] = useState(0);
  const [allocation, setAllocation] = useState<Partial<Record<Channel, number>>>({});
  const [assumptions, setAssumptions] = useState<Partial<Record<Channel, Assumption>>>({});
  const [notes, setNotes] = useState("");
  const [sim, setSim] = useState<Simulation | null>(null);
  const [rec, setRec] = useState<Recommendation | null>(null);
  const [busy, setBusy] = useState<string | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [saved, setSaved] = useState<string | null>(null);

  const load = useCallback(async () => {
    setError(null); setSim(null); setRec(null); setSaved(null);
    try {
      const [b, p] = await Promise.all([getBaseline(), getPlan(month)]);
      if (getActiveClientId() !== clientId) return;
      setBase(b); setPlan(p);
      const usable = (Object.keys(CHANNELS) as Channel[]).filter((c) => ["boa", "baixa"].includes(b.channels[c]?.confidence));
      if (p.plan) {
        setObjective(p.plan.objective); setBudget(Number(p.plan.budget)); setAllocation(p.plan.allocation); setNotes(p.plan.notes || "");
        setAssumptions({ ...b.assumptions, ...p.plan.assumptions });
      } else {
        const monthly = usable.reduce((s, c) => s + (b.channels[c].monthly_spend || 0), 0);
        setBudget(Math.round(monthly / 100) * 100 || 0);
        setAllocation(Object.fromEntries(usable.map((c) => [c, Math.round((b.channels[c].monthly_spend / (monthly || 1)) * 100)])));
        setAssumptions(b.assumptions); setNotes("");
      }
    } catch (cause) { setError(message(cause, "Não foi possível carregar o Mídia On.")); }
  }, [month, clientId]);
  useEffect(() => { void load(); }, [load]);

  const total = allocationTotal(allocation);
  const ready = budget > 0 && Math.abs(total - 100) <= 0.5;

  const simulate = useCallback(async () => {
    if (!ready || !canManage) return;
    setBusy("sim");
    try { setSim(await runSimulation({ budget, allocation, assumptions })); setError(null); }
    catch (cause) { setError(message(cause, "Não foi possível simular.")); }
    finally { setBusy((b) => (b === "sim" ? null : b)); }
  }, [ready, canManage, budget, allocation, assumptions]);
  useEffect(() => { const t = window.setTimeout(() => void simulate(), 500); return () => window.clearTimeout(t); }, [simulate]);

  async function recommend() {
    if (budget <= 0) { setError("Informe a verba do mês."); return; }
    setBusy("rec"); setError(null);
    try {
      const r = await recommendPlan({ month, budget, objective });
      setRec(r); setAllocation(r.allocation); setAssumptions((a) => ({ ...r.assumptions, ...a })); setSim(r.simulation);
    } catch (cause) { setError(message(cause, "A IA não conseguiu sugerir agora.")); }
    finally { setBusy(null); }
  }

  async function save(status: "rascunho" | "aprovado") {
    setBusy("save"); setError(null);
    try {
      await savePlan({ month, objective, budget, allocation, assumptions, notes: notes || undefined, status });
      setSaved(status === "aprovado" ? "Plano aprovado ✓" : "Rascunho salvo ✓");
      setPlan(await getPlan(month));
    } catch (cause) { setError(message(cause, "Não foi possível salvar o plano.")); }
    finally { setBusy(null); }
  }

  const setAssumption = (channel: Channel, key: keyof Assumption, value: string, ratio?: boolean) =>
    setAssumptions((a) => ({ ...a, [channel]: { ...(a[channel] || {}), [key]: value === "" ? null : Number(value) / (ratio ? 100 : 1) } as Assumption }));
  const channels = useMemo(() => Object.keys(CHANNELS) as Channel[], []);

  return <Shell title="Mídia On" variant="editorial"><div className="ds-page studioPage mediaPage">
    <PageHeader company={clientName} title="Mídia On" controls={<div className="calNav">
      <button type="button" className="ds-button" aria-label="Mês anterior" onClick={() => setMonth(shiftMonth(month, -1))}>‹</button>
      <h2 className="calRange">{MONTH_NAMES[Number(month.slice(5)) - 1]} {month.slice(0, 4)}</h2>
      <button type="button" className="ds-button" aria-label="Próximo mês" onClick={() => setMonth(shiftMonth(month, 1))}>›</button>
    </div>} />
    {error ? <p role="alert" className="studioError">{error}</p> : null}
    {!base ? <p>Carregando dados de mídia…</p> : <>
      <section className="mediaCard">
        <h3>Desempenho real (últimos {base.period.days} dias)</h3>
        <div className="mediaTableWrap"><table className="mediaTable">
          <thead><tr><th>Canal</th><th>Investido</th><th>CPM</th><th>CPC</th><th>CTR</th><th>Conversão</th><th>CPA</th><th>ROAS</th><th>Dados</th></tr></thead>
          <tbody>{channels.map((c) => { const m = base.channels[c]; return <tr key={c}>
            <td>{CHANNELS[c]}</td><td>{money(m.spend)}</td><td>{money(m.cpm)}</td><td>{money(m.cpc)}</td><td>{percent(m.ctr)}</td>
            <td>{percent(m.conversion_rate)}</td><td>{money(m.cpa)}</td><td>{num(m.roas, 2)}</td><td><span className={`studioChip is-${m.confidence}`}>{CONFIDENCE[m.confidence]}</span></td>
          </tr>; })}</tbody></table></div>
        <p className="libHint">ROAS e conversões são os atribuídos por cada plataforma; não some as duas como faturamento.</p>
      </section>

      <section className="mediaCard">
        <h3>Plano de {MONTH_NAMES[Number(month.slice(5)) - 1]}</h3>
        <div className="studioRow">
          <label>Objetivo<select value={objective} disabled={!canManage} onChange={(e) => setObjective(e.target.value as Objective)}>
            {(Object.keys(OBJECTIVES) as Objective[]).map((o) => <option key={o} value={o}>{OBJECTIVES[o]}</option>)}</select></label>
          <label>Verba do mês (R$)<input type="number" min={0} step={100} value={budget || ""} disabled={!canManage} onChange={(e) => setBudget(Number(e.target.value))} /></label>
          {canManage ? <button type="button" className="ds-button" onClick={() => void recommend()} disabled={Boolean(busy)}>{busy === "rec" ? "Analisando…" : "✦ Sugerir divisão com IA"}</button> : null}
        </div>
        {rec ? <div className="aiResult"><p className="aiText">{rec.rationale}</p>{rec.main_risk ? <p className="studioError">Risco: {rec.main_risk}</p> : null}
          {rec.next_steps.length ? <ul className="aiList">{rec.next_steps.map((s) => <li key={s}>→ {s}</li>)}</ul> : null}</div> : null}
        <div className="mediaChannels">{channels.map((c) => <fieldset key={c} className={`mediaChannel ${base.channels[c].confidence === "boa" || base.channels[c].confidence === "baixa" ? "" : "is-off"}`}>
          <legend>{CHANNELS[c]}</legend>
          <label>% da verba<input type="number" min={0} max={100} step={1} value={allocation[c] ?? 0} disabled={!canManage} onChange={(e) => setAllocation({ ...allocation, [c]: Number(e.target.value) })} /></label>
          <p className="mediaSpend">{money(budget * (allocation[c] || 0) / 100)}</p>
          {ASSUMPTION_FIELDS.map((f) => { const raw = assumptions[c]?.[f.key]; return <label key={f.key}>{f.label}
            <input type="number" min={0} step={f.step} disabled={!canManage} value={raw == null ? "" : Math.round(Number(raw) * (f.ratio ? 10000 : 100)) / 100}
              placeholder="sem dado" onChange={(e) => setAssumption(c, f.key, e.target.value, f.ratio)} /></label>; })}
        </fieldset>)}</div>
        <p className={Math.abs(total - 100) <= 0.5 ? "libHint" : "studioError"}>Divisão: {num(total, 1)}% {Math.abs(total - 100) <= 0.5 ? "✓" : "(precisa somar 100%)"}</p>
      </section>

      {sim ? <section className="mediaCard">
        <h3>Projeção {busy === "sim" ? "(atualizando…)" : ""}</h3>
        <div className="mediaScenarios">{(Object.keys(SCENARIO_LABEL) as (keyof typeof SCENARIO_LABEL)[]).map((s) => <div key={s} className={`mediaScenario ${s === "esperado" ? "is-main" : ""}`}>
          <span>{SCENARIO_LABEL[s]}</span><b>{num(sim.totals[s].conversions, 0)} conversões</b>
          <small>{money(sim.totals[s].revenue)} · CPA {money(sim.totals[s].cpa)} · ROAS {num(sim.totals[s].roas, 2)}</small></div>)}</div>
        <div className="mediaTableWrap"><table className="mediaTable"><thead><tr><th>Canal</th><th>Verba</th><th>Impressões</th><th>Cliques</th><th>Conversões</th><th>Receita</th></tr></thead>
          <tbody>{sim.channels.map((row) => { const e = row.scenarios.esperado; return <tr key={row.channel}>
            <td>{CHANNELS[row.channel]}{row.saturation && row.saturation < 1 ? " ⚠" : ""}</td><td>{money(row.spend)}</td>
            <td>{row.missing ? "sem premissa" : num(e?.impressions)}</td><td>{num(e?.clicks)}</td><td>{num(e?.conversions, 1)}</td><td>{money(e?.revenue)}</td></tr>; })}</tbody></table></div>
        {sim.warnings.length ? <ul className="studioNotes">{sim.warnings.map((w) => <li key={w}>{w}</li>)}</ul> : null}
        <details className="postWhy"><summary>Como calculamos</summary><p>{sim.method}</p></details>
      </section> : null}

      {canManage ? <section className="mediaCard">
        <label>Observações do plano<textarea rows={2} maxLength={2000} value={notes} onChange={(e) => setNotes(e.target.value)} placeholder="Campanhas previstas, datas, criativos…" /></label>
        <div className="studioActions">
          {saved ? <span className="studioOk">{saved}</span> : null}
          <button type="button" className="ds-button" disabled={Boolean(busy) || !ready} onClick={() => void save("rascunho")}>Salvar rascunho</button>
          <button type="button" className="ds-button is-primary" disabled={Boolean(busy) || !ready} onClick={() => void save("aprovado")}>Aprovar plano</button>
        </div>
      </section> : null}

      {plan && plan.channels.length ? <section className="mediaCard">
        <h3>Planejado x realizado {plan.plan ? `· plano ${plan.plan.status === "aprovado" ? "aprovado" : "em rascunho"}` : "· sem plano salvo"}</h3>
        <p className="libHint">Até {plan.through ? new Date(`${plan.through}T12:00:00`).toLocaleDateString("pt-BR") : "—"} · {plan.elapsed_days} de {plan.days_in_month} dias.</p>
        <div className="mediaTableWrap"><table className="mediaTable"><thead><tr><th>Canal</th><th>Planejado</th><th>Esperado até hoje</th><th>Investido</th><th>Projeção do mês</th><th>Ritmo</th><th>CPA</th><th>ROAS</th></tr></thead>
          <tbody>{plan.channels.map((r) => <tr key={r.channel}><td>{r.label}</td><td>{money(r.planned_spend)}</td><td>{money(r.expected_to_date)}</td><td>{money(r.spent)}</td>
            <td>{money(r.projected_spend)}</td><td className={r.pace == null ? "" : r.pace > 1.1 ? "is-over" : r.pace < 0.9 ? "is-under" : "is-ok"}>{r.pace == null ? "—" : `${num(r.pace * 100)}%`}</td>
            <td>{money(r.cpa)}</td><td>{num(r.roas, 2)}</td></tr>)}</tbody></table></div>
      </section> : null}
    </>}
  </div></Shell>;
}
