import { useCallback, useEffect, useMemo, useState } from "react";
import { CartesianGrid, Line, LineChart, ReferenceDot, ResponsiveContainer, Tooltip, XAxis, YAxis } from "recharts";
import { getActiveClientId, getActiveClientName } from "../app/activeClient";
import {
  ACTIONS, CHANNELS, CONFIDENCE, OBJECTIVES, curvePoints, generateStrategy, getPlan, metricValue, money, num, outcomeFor, percent, ratio, savePlan, shortDate,
  type Channel, type Objective, type Outcome, type PlanVsActual, type SavedStrategy, type Scenario, type ScenarioKey, type Strategy,
} from "../app/media";
import { navigateToAppRoute } from "../app/routes";
import Shell from "../components/Shell";
import PageHeader from "../components/data/PageHeader";
import HeroFigure from "../components/data/HeroFigure";
import KpiFigure from "../components/data/KpiFigure";
import Delta from "../components/data/Delta";
import SegmentedControl from "../components/data/SegmentedControl";
import "../styles/studio.css";

const MONTH_NAMES = ["janeiro", "fevereiro", "março", "abril", "maio", "junho", "julho", "agosto", "setembro", "outubro", "novembro", "dezembro"];
const PHASE = { base: "Base", aquecimento: "Aquecimento", pico: "Pico" } as const;
const CHANNEL_COLOR: Record<Channel, string> = { meta: "#004f6e", google_ads: "#b7791f" };
const message = (cause: unknown, fallback: string) => (cause instanceof Error && cause.message ? cause.message : fallback);
const nextMonth = () => { const d = new Date(); const n = new Date(d.getFullYear(), d.getMonth() + 1, 1); return `${n.getFullYear()}-${String(n.getMonth() + 1).padStart(2, "0")}`; };
const shiftMonth = (m: string, n: number) => { const d = new Date(Number(m.slice(0, 4)), Number(m.slice(5)) - 1 + n, 1); return `${d.getFullYear()}-${String(d.getMonth() + 1).padStart(2, "0")}`; };
const changePct = (now: number | null | undefined, before: number | null | undefined) => (now == null || !before ? null : ((now - before) / Math.abs(before)) * 100);

type View = { strategy: Strategy | SavedStrategy; scenarios: Scenario[]; saved: boolean };

/** Mídia On: estratégia de mídia paga calculada com os dados da conta, cruzada com o calendário editorial. */
export default function MediaOn({ canManage }: { canManage: boolean }) {
  const clientId = getActiveClientId();
  const clientName = getActiveClientName() || "marca";
  const [month, setMonth] = useState(nextMonth);
  const [objective, setObjective] = useState<Objective>("vendas");
  const [margin, setMargin] = useState("");
  const [customBudget, setCustomBudget] = useState("");
  const [view, setView] = useState<View | null>(null);
  const [selected, setSelected] = useState<ScenarioKey | null>(null);
  const [allocation, setAllocation] = useState<Partial<Record<Channel, number>>>({});
  const [tracking, setTracking] = useState<PlanVsActual | null>(null);
  const [notes, setNotes] = useState("");
  const [busy, setBusy] = useState<string | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [saved, setSaved] = useState<string | null>(null);

  const monthLabel = MONTH_NAMES[Number(month.slice(5)) - 1];

  const loadPlan = useCallback(async () => {
    setError(null); setSaved(null); setView(null); setTracking(null);
    try {
      const data = await getPlan(month);
      if (getActiveClientId() !== clientId) return;
      setTracking(data);
      const plan = data.plan;
      const strategy = plan?.strategy && "scenario" in plan.strategy ? plan.strategy as SavedStrategy : null;
      if (plan && strategy) {
        setObjective(plan.objective); setMargin(plan.margin ? String(Math.round(plan.margin * 100)) : ""); setNotes(plan.notes || "");
        setView({ strategy, scenarios: strategy.scenarios?.length ? strategy.scenarios : [strategy.scenario], saved: true });
        setSelected(strategy.scenario.key); setAllocation(plan.allocation);
      }
    } catch (cause) { setError(message(cause, "Não foi possível carregar o plano.")); }
  }, [month, clientId]);
  useEffect(() => { void loadPlan(); }, [loadPlan]);

  async function generate() {
    const m = margin ? Number(margin) / 100 : undefined;
    const b = customBudget ? Number(customBudget) : undefined;
    setBusy("generate"); setError(null); setSaved(null);
    try {
      const s = await generateStrategy({ month, objective, margin: m, budget: b });
      setView({ strategy: s, scenarios: s.scenarios, saved: false });
      const chosen = s.scenarios.find((x) => x.key === s.selected) || s.scenarios[0];
      setSelected(chosen.key); setAllocation(chosen.allocation);
    } catch (cause) { setError(message(cause, "Não foi possível gerar a estratégia.")); }
    finally { setBusy(null); }
  }

  const strategy = view?.strategy || null;
  const scenario = useMemo(() => view?.scenarios.find((s) => s.key === selected) || null, [view, selected]);
  const edited = useMemo(() => !!scenario && (Object.keys(CHANNELS) as Channel[]).some((c) => Math.abs((allocation[c] || 0) - (scenario.allocation[c] || 0)) > 1), [allocation, scenario]);
  const result: Outcome | null = useMemo(() => {
    if (!strategy || !scenario) return null;
    return edited ? outcomeFor(strategy.curves, allocation, strategy.days) : scenario.result;
  }, [strategy, scenario, allocation, edited]);
  const ritmo = view?.scenarios.find((s) => s.key === "ritmo_atual") || null;
  const budget = Object.values(allocation).reduce((s, v) => s + (Number(v) || 0), 0);
  const metric = strategy?.metric || "revenue";

  function pickScenario(key: ScenarioKey) {
    const s = view?.scenarios.find((x) => x.key === key);
    if (s) { setSelected(key); setAllocation(s.allocation); setSaved(null); }
  }

  function setShare(channel: Channel, pct: number) {
    const others = (Object.keys(allocation) as Channel[]).filter((c) => c !== channel);
    const total = budget || scenario?.budget || 0;
    const value = Math.round(total * pct / 100);
    const rest = total - value;
    const othersTotal = others.reduce((s, c) => s + (allocation[c] || 0), 0) || 1;
    const next: Partial<Record<Channel, number>> = { [channel]: value };
    for (const c of others) next[c] = Math.round(rest * (allocation[c] || 0) / othersTotal);
    setAllocation(next);
  }

  async function save(status: "rascunho" | "aprovado") {
    if (!strategy || !scenario || !result) return;
    setBusy("save"); setError(null);
    const frozen: SavedStrategy = { ...(strategy as Strategy), scenarios: view!.scenarios,
      scenario: { ...scenario, allocation, budget, result, why: edited ? `${scenario.why} Divisão ajustada pela equipe.` : scenario.why } };
    try {
      await savePlan({ month, objective: strategy.objective, scenario: scenario.key, budget: Math.round(budget * 100) / 100, allocation,
        margin: strategy.margin || undefined, strategy: frozen, notes: notes || undefined, status });
      setSaved(status === "aprovado" ? "Plano aprovado. O calendário passa a mostrar os impulsionamentos." : "Rascunho salvo.");
      setTracking(await getPlan(month));
      setView((v) => v && { ...v, saved: true });
    } catch (cause) { setError(message(cause, "Não foi possível salvar o plano.")); }
    finally { setBusy(null); }
  }

  const narrative = strategy?.narrative || null;
  const notesByCampaign = new Map((narrative?.campaign_notes || []).map((n) => [n.campaign, n.note]));
  const roles = new Map((narrative?.channel_roles || []).map((r) => [r.channel, r]));
  const activeDiagnosis = (strategy?.diagnosis || []).filter((d) => d.confidence !== "sem_dados");
  const plan = tracking?.plan;

  return <Shell title="Mídia On" variant="editorial"><div className="ds-page mediaPage">
    <PageHeader company={clientName} title="Mídia On" controls={<div className="mediaMonth">
      <button type="button" className="ds-button" aria-label="Mês anterior" onClick={() => setMonth(shiftMonth(month, -1))}>‹</button>
      <strong>{monthLabel} {month.slice(0, 4)}</strong>
      <button type="button" className="ds-button" aria-label="Próximo mês" onClick={() => setMonth(shiftMonth(month, 1))}>›</button>
    </div>} dateline={plan ? <span>Plano {plan.status === "aprovado" ? "aprovado" : "em rascunho"}{plan.updated_at ? ` · atualizado em ${new Date(plan.updated_at).toLocaleDateString("pt-BR")}` : ""}</span>
      : <span>Estratégia calculada com Meta Ads, Google Ads, loja, metas e calendário editorial.</span>} />

    {canManage ? <section className="mediaControls" aria-label="Parâmetros da estratégia">
      <div><span className="mediaControlLabel">Objetivo</span>
        <SegmentedControl ariaLabel="Objetivo" value={objective} onSelect={(id) => setObjective(id as Objective)} options={(Object.keys(OBJECTIVES) as Objective[]).map((o) => ({ id: o, label: OBJECTIVES[o] }))} /></div>
      <label>Margem de contribuição <small>(opcional, %)</small><input type="number" min={2} max={95} step={1} value={margin} placeholder="ex.: 40" onChange={(e) => setMargin(e.target.value)} /></label>
      <label>Verba definida <small>(opcional, R$)</small><input type="number" min={0} step={100} value={customBudget} placeholder="deixe vazio para recomendar" onChange={(e) => setCustomBudget(e.target.value)} /></label>
      <button type="button" className="ds-button is-primary" disabled={Boolean(busy)} onClick={() => void generate()}>{busy === "generate" ? "Calculando estratégia… (até 1 min)" : strategy ? "Recalcular estratégia" : "Gerar estratégia"}</button>
    </section> : null}

    {error ? <p role="alert" className="studioError">{error}</p> : null}
    {!strategy && !busy ? <div className="ds-notice"><p className="ds-noticeTitle">{plan ? "Plano salvo sem estratégia detalhada." : `Nenhuma estratégia para ${monthLabel} ainda.`}</p>
      <p className="ds-noticeText">{canManage ? "Escolha o objetivo e clique em Gerar estratégia. O cálculo usa os últimos 90 dias de Meta Ads e Google Ads, a meta do mês e o calendário editorial." : "A equipe ainda não publicou a estratégia deste mês."}</p></div> : null}

    {strategy && scenario && result ? <>
      {narrative ? <section className="ds-section mediaThesis">
        <p className="ds-headline">{narrative.headline}</p>
        <p>{narrative.thesis}</p>
      </section> : strategy.narrative_error ? <p className="ds-footnote">Leitura da IA indisponível agora ({strategy.narrative_error}). Os números abaixo valem normalmente.</p> : null}

      <section className="ds-section">
        <div className="mediaHero">
          <HeroFigure value={money(budget)} rawValue={budget} label={`de verba para ${monthLabel}${edited ? " (divisão ajustada)" : ` · ${scenario.label.toLowerCase()}`}`}
            delta={ritmo && scenario.key !== "ritmo_atual" ? <Delta change={changePct(budget, ritmo.budget)} reference="ritmo atual" showReference sentiment="neutral" /> : undefined} />
          <div className="ds-kpis">
            <KpiFigure label={metric === "revenue" ? "Receita atribuída projetada" : `${strategy.metric_label} projetadas`} value={metricValue(metric, result.totals[metric])}
              delta={ritmo ? <Delta change={changePct(result.totals[metric], ritmo.result.totals[metric])} reference="ritmo atual" /> : null} />
            <KpiFigure label="ROAS projetado" value={ratio(result.totals.roas)} delta={ritmo ? <Delta change={changePct(result.totals.roas, ritmo.result.totals.roas)} reference="ritmo atual" /> : null} />
            <KpiFigure label="Custo por conversão" value={money(result.totals.cpa)} delta={ritmo ? <Delta change={changePct(result.totals.cpa, ritmo.result.totals.cpa)} reference="ritmo atual" sentiment="lower-is-better" /> : null} />
            <KpiFigure label="Conversões projetadas" value={num(result.totals.conversions)} delta={null} />
            {!edited && scenario.marginal_roas != null ? <KpiFigure label="Retorno do próximo R$ 1" value={money(scenario.marginal_roas, 2)} delta={null} /> : null}
          </div>
        </div>
        {strategy.goal_revenue ? <p className="ds-footnote">Meta de faturamento do mês: {money(strategy.goal_revenue)}. Faturamento da loja nos últimos 30 dias: {money(strategy.store.revenue)} com {money(strategy.store.investment)} em mídia.</p> : null}
      </section>

      <section className="ds-section" aria-labelledby="media-scenarios">
        <div className="ds-sectionHead"><div className="ds-sectionHeadText"><h2 id="media-scenarios" className="ds-sectionTitle">Cenários de verba</h2>
          <p className="ds-caption">Cada cenário divide a verba pela curva de retorno medida em cada canal.</p></div></div>
        <div className="mediaScenarioGrid" role="radiogroup" aria-label="Cenário">
          {view!.scenarios.map((s) => <button key={s.key} type="button" role="radio" aria-checked={s.key === selected} className={`mediaScenarioCard ${s.key === selected ? "is-selected" : ""}`} onClick={() => pickScenario(s.key)} disabled={view!.saved && !canManage}>
            <span className="mediaScenarioName">{s.label}{s.key === strategy.recommended ? <em>recomendado</em> : null}</span>
            <strong>{money(s.budget)}</strong>
            <span>{metricValue(metric, s.result.totals[metric])} · ROAS {ratio(s.result.totals.roas)} · CPA {money(s.result.totals.cpa)}</span>
            <small>{s.why}</small>
          </button>)}
        </div>
      </section>

      <section className="ds-section" aria-labelledby="media-split">
        <div className="ds-sectionHead"><div className="ds-sectionHeadText"><h2 id="media-split" className="ds-sectionTitle">Divisão por canal</h2>
          <p className="ds-caption">{edited ? "Divisão ajustada: a projeção foi recalculada pelas mesmas curvas." : "Divisão que maximiza o resultado do objetivo."}</p></div>
          {edited ? <button type="button" className="ds-link" onClick={() => setAllocation(scenario.allocation)}>Voltar à divisão recomendada</button> : null}</div>
        <ol className="mediaSplit">{(Object.keys(allocation) as Channel[]).map((c) => {
          const out = result.channels[c]; const pct = budget ? (allocation[c] || 0) / budget : 0; const role = roles.get(c);
          return <li key={c}>
            <div className="mediaSplitHead"><span className="mediaDot" style={{ background: CHANNEL_COLOR[c] }} /><strong>{CHANNELS[c]}</strong>
              <span className="mediaSplitValue">{money(allocation[c])} <small>{percent(pct, 0)}</small></span></div>
            <span className="ds-rankBar" aria-hidden="true"><span style={{ width: `${Math.max(pct * 100, 2)}%`, background: CHANNEL_COLOR[c], opacity: 0.8 }} /></span>
            <p className="ds-caption">{metricValue(metric, out?.[metric])} · ROAS {ratio(out?.roas)} · CPA {money(out?.cpa)} · CPM {money(out?.cpm)}
              {scenario.change_vs_current[c] != null && !edited ? ` · ${scenario.change_vs_current[c]! > 0 ? "+" : ""}${num(scenario.change_vs_current[c], 0)}% vs hoje` : ""}</p>
            {role ? <p className="mediaRole"><b>{role.role}.</b> {role.rationale}</p> : null}
            {canManage && Object.keys(allocation).length > 1 ? <label className="mediaSlider">Ajustar participação
              <input type="range" min={0} max={100} step={1} value={Math.round(pct * 100)} onChange={(e) => setShare(c, Number(e.target.value))} /></label> : null}
          </li>;
        })}</ol>
      </section>

      <section className="ds-section" aria-labelledby="media-curve">
        <div className="ds-sectionHead"><div className="ds-sectionHeadText"><h2 id="media-curve" className="ds-sectionTitle">Curva de retorno</h2>
          <p className="ds-caption">Quanto cada canal devolve em {strategy.metric_label} conforme a verba do mês. O ponto é a verba planejada.</p></div></div>
        <CurveChart strategy={strategy} allocation={allocation} />
        <ul className="mediaCurveNotes">{(Object.keys(strategy.curves) as Channel[]).map((c) => { const cv = strategy.curves[c]![metric];
          return <li key={c}><span className="mediaDot" style={{ background: CHANNEL_COLOR[c] }} />{CHANNELS[c]}: elasticidade {ratio(cv.b)} ({cv.fit === "medida" ? `medida em ${cv.points} semanas` : "estimada, pouca variação de verba no histórico"}).</li>; })}</ul>
      </section>

      <section className="ds-section" aria-labelledby="media-diagnosis">
        <div className="ds-sectionHead"><div className="ds-sectionHeadText"><h2 id="media-diagnosis" className="ds-sectionTitle">Diagnóstico</h2>
          <p className="ds-caption">Últimos 30 dias em relação aos 30 anteriores.</p></div></div>
        {activeDiagnosis.map((d) => <div key={d.channel} className="mediaDiag">
          <h3><span className="mediaDot" style={{ background: CHANNEL_COLOR[d.channel] }} />{d.label} <small>{CONFIDENCE[d.confidence]}</small></h3>
          <div className="ds-kpis">
            <KpiFigure label="Investimento" value={money(d.recent.spend)} delta={<Delta change={d.changes.spend} sentiment="neutral" />} />
            <KpiFigure label="ROAS" value={ratio(d.recent.roas)} delta={<Delta change={d.changes.roas} />} />
            <KpiFigure label="CPA" value={money(d.recent.cpa)} delta={<Delta change={d.changes.cpa} sentiment="lower-is-better" />} />
            <KpiFigure label="CPM" value={money(d.recent.cpm)} delta={<Delta change={d.changes.cpm} sentiment="lower-is-better" />} />
            <KpiFigure label="CTR" value={percent(d.recent.ctr, 2)} delta={<Delta change={d.changes.ctr} />} />
          </div>
        </div>)}
        {strategy.findings.length ? <ul className="mediaFindings">{strategy.findings.map((f) => <li key={f.text} className={`is-${f.level}`}>{f.text}</li>)}</ul> : null}
      </section>

      <section className="ds-section" aria-labelledby="media-campaigns">
        <div className="ds-sectionHead"><div className="ds-sectionHeadText"><h2 id="media-campaigns" className="ds-sectionTitle">O que fazer em cada campanha</h2>
          <p className="ds-caption">Últimos 30 dias, comparando cada campanha com a média do próprio canal.{strategy.waste ? ` ${money(strategy.waste)} foram para campanhas sem conversão.` : ""}</p></div></div>
        {strategy.campaigns.length ? <div className="ds-tableWrap"><table className="ds-table mediaCampaigns">
          <thead><tr><th>Campanha</th><th>Ação</th><th>Investido</th><th>ROAS</th><th>CPA</th><th>Por quê</th></tr></thead>
          <tbody>{strategy.campaigns.map((r) => <tr key={`${r.channel}:${r.campaign}`}>
            <td><span className="mediaDot" style={{ background: CHANNEL_COLOR[r.channel] }} />{r.campaign}{notesByCampaign.get(r.campaign) ? <span className="ds-tableSub">{notesByCampaign.get(r.campaign)}</span> : null}</td>
            <td><span className={`mediaAction is-${r.action}`}>{ACTIONS[r.action]}</span></td>
            <td>{money(r.spend)}</td><td>{ratio(r.roas)}</td><td>{money(r.cpa)}</td><td className="mediaWhy">{r.why}</td></tr>)}</tbody></table></div>
          : <p className="ds-emptyLine">Sem campanhas com investimento relevante nos últimos 30 dias.</p>}
      </section>

      <section className="ds-section" aria-labelledby="media-weeks">
        <div className="ds-sectionHead"><div className="ds-sectionHeadText"><h2 id="media-weeks" className="ds-sectionTitle">Calendário de investimento</h2>
          <p className="ds-caption">A verba sobe nas semanas que antecedem as datas comerciais do mês.</p></div></div>
        <ol className="mediaWeeks">{strategy.weeks.map((w) => { const max = Math.max(...strategy.weeks.map((x) => x.daily), 1);
          return <li key={w.start} className={`is-${w.phase}`}>
            <span className="mediaWeekRange">{shortDate(w.start)} – {shortDate(w.end)}</span>
            <span className="mediaWeekBar"><span style={{ width: `${(w.daily / max) * 100}%` }} /></span>
            <span className="mediaWeekValue">{money(w.budget)} <small>{money(w.daily)}/dia</small></span>
            <span className="mediaWeekPhase">{PHASE[w.phase]}{w.dates.length ? ` · ${w.dates.join(", ")}` : ""}{w.prepares.length ? ` · prepara ${w.prepares.join(", ")}` : ""}</span>
          </li>; })}</ol>
      </section>

      <section className="ds-section" aria-labelledby="media-boosts">
        <div className="ds-sectionHead"><div className="ds-sectionHeadText"><h2 id="media-boosts" className="ds-sectionTitle">Impulsionamento dos posts do calendário</h2>
          <p className="ds-caption">{strategy.boosts.posts.length ? `${money(strategy.boosts.pool)} da verba de Meta (${percent(strategy.boosts.share, 0)}) reservados para impulsionar as pautas com mais chance de resultado.` : strategy.boosts.note}</p></div>
          <button type="button" className="ds-link" onClick={() => navigateToAppRoute("calendar")}>Abrir calendário</button></div>
        {strategy.boosts.posts.length ? <div className="ds-tableWrap"><table className="ds-table">
          <thead><tr><th>Post</th><th>Publica</th><th>Impulsionar</th><th>Verba</th><th>Por dia</th><th>Impressões estimadas</th></tr></thead>
          <tbody>{strategy.boosts.posts.map((b) => <tr key={b.item_id}>
            <td>{b.title}<span className="ds-tableSub">{b.format} · {b.why}</span></td>
            <td>{shortDate(b.posted)}</td><td><b>{shortDate(b.start)}</b> a {shortDate(b.end)}</td><td>{money(b.budget)}</td><td>{money(b.daily)}</td><td>{num(b.impressions)}</td></tr>)}</tbody></table></div> : null}
      </section>

      <section className="ds-section" aria-labelledby="media-guardrails">
        <div className="ds-sectionHead"><div className="ds-sectionHeadText"><h2 id="media-guardrails" className="ds-sectionTitle">Limites para a operação</h2>
          <p className="ds-caption">{strategy.margin ? `Com margem de ${percent(strategy.margin, 0)}, o ROAS de equilíbrio é ${ratio(1 / strategy.margin)}.` : "Informe a margem de contribuição para calcular o ROAS de equilíbrio."}</p></div></div>
        <div className="ds-tableWrap"><table className="ds-table">
          <thead><tr><th>Canal</th><th>Verba diária</th><th>CPA alvo</th><th>CPA máximo</th><th>ROAS alvo</th><th>ROAS mínimo</th></tr></thead>
          <tbody>{strategy.guardrails.map((g) => <tr key={g.channel}><td>{g.label}</td><td>{money(g.daily_budget)}</td><td>{money(g.target_cpa)}</td><td>{money(g.max_cpa)}</td><td>{ratio(g.target_roas)}</td><td>{ratio(g.min_roas)}</td></tr>)}</tbody></table></div>
        {strategy.guardrails[0] ? <p className="ds-footnote">{strategy.guardrails[0].rule}</p> : null}
      </section>

      {narrative && (narrative.next_7_days.length || narrative.creative_guidance.length || narrative.risks.length) ? <section className="ds-section mediaColumns">
        {narrative.next_7_days.length ? <div><h2 className="ds-sectionTitle">Próximos 7 dias</h2><ol className="mediaList">{narrative.next_7_days.map((x) => <li key={x}>{x}</li>)}</ol></div> : null}
        {narrative.creative_guidance.length ? <div><h2 className="ds-sectionTitle">Criativos</h2><ul className="mediaList">{narrative.creative_guidance.map((x) => <li key={x}>{x}</li>)}</ul></div> : null}
        {narrative.risks.length ? <div><h2 className="ds-sectionTitle">Riscos</h2><ul className="mediaList">{narrative.risks.map((x) => <li key={x}>{x}</li>)}</ul></div> : null}
      </section> : null}

      {canManage ? <section className="ds-section mediaSave">
        <label>Observações do plano<textarea rows={2} maxLength={2000} value={notes} onChange={(e) => setNotes(e.target.value)} placeholder="Ofertas, lançamentos, restrições do cliente…" /></label>
        <div className="mediaSaveActions">
          {saved ? <span className="studioOk">{saved}</span> : null}
          <button type="button" className="ds-button" disabled={Boolean(busy)} onClick={() => void save("rascunho")}>Salvar rascunho</button>
          <button type="button" className="ds-button is-primary" disabled={Boolean(busy)} onClick={() => void save("aprovado")}>{busy === "save" ? "Salvando…" : "Aprovar plano"}</button>
        </div>
      </section> : null}

      <details className="ds-footnote mediaMethod"><summary>Como a estratégia é calculada</summary><p>{strategy.method}</p>
        <p>Janela analisada: {shortDate(strategy.window.start)} a {shortDate(strategy.window.end)}.</p></details>
    </> : null}

    {tracking && tracking.channels.length ? <section className="ds-section" aria-labelledby="media-tracking">
      <div className="ds-sectionHead"><div className="ds-sectionHeadText"><h2 id="media-tracking" className="ds-sectionTitle">Planejado x realizado</h2>
        <p className="ds-caption">Até {tracking.through ? shortDate(tracking.through) : "—"} · {tracking.elapsed_days} de {tracking.days_in_month} dias.</p></div></div>
      <div className="ds-tableWrap"><table className="ds-table">
        <thead><tr><th>Canal</th><th>Planejado</th><th>Esperado até hoje</th><th>Investido</th><th>Projeção do mês</th><th>Ritmo</th><th>CPA (alvo)</th><th>ROAS (alvo)</th></tr></thead>
        <tbody>{tracking.channels.map((r) => <tr key={r.channel}><td>{r.label}</td><td>{money(r.planned_spend)}</td><td>{money(r.expected_to_date)}</td><td>{money(r.spent)}</td><td>{money(r.projected_spend)}</td>
          <td className={r.pace == null ? "" : r.pace > 1.1 ? "is-over" : r.pace < 0.9 ? "is-under" : "is-ok"}>{r.pace == null ? "—" : `${num(r.pace * 100)}%`}</td>
          <td className={r.cpa != null && r.target_cpa != null && r.cpa > r.target_cpa * 1.3 ? "is-over" : ""}>{money(r.cpa)} <small>({money(r.target_cpa)})</small></td>
          <td>{ratio(r.roas)} <small>({ratio(r.target_roas)})</small></td></tr>)}</tbody></table></div>
    </section> : null}
  </div></Shell>;
}

function CurveChart({ strategy, allocation }: { strategy: Strategy | SavedStrategy; allocation: Partial<Record<Channel, number>> }) {
  const channels = Object.keys(strategy.curves) as Channel[];
  const metric = strategy.metric;
  const reference = Math.max(...channels.map((c) => allocation[c] || strategy.diagnosis.find((d) => d.channel === c)?.monthly_spend || 0), 1);
  const series = channels.map((c) => ({ c, points: curvePoints(strategy.curves[c]?.[metric], reference, strategy.days) }));
  const rows = series[0]?.points.map((p, i) => ({ spend: p.spend, ...Object.fromEntries(series.map((s) => [s.c, s.points[i].value])) })) || [];
  const fmt = (v: number) => (metric === "revenue" ? money(v) : num(v));
  return <div className="ds-chart mediaCurve" role="img" aria-label={`Curva de retorno por canal em ${strategy.metric_label}`}>
    <ResponsiveContainer width="100%" height="100%">
      <LineChart data={rows} margin={{ top: 8, right: 12, left: 0, bottom: 0 }}>
        <CartesianGrid vertical={false} stroke="rgba(21, 24, 27, .06)" />
        <XAxis dataKey="spend" type="number" domain={[0, "dataMax"]} tickFormatter={(v) => money(Number(v))} tick={{ fontSize: 11, fill: "#687178" }} axisLine={false} tickLine={false} tickCount={6} />
        <YAxis tickFormatter={(v) => fmt(Number(v))} tick={{ fontSize: 11, fill: "#687178" }} axisLine={false} tickLine={false} width={84} tickCount={4} />
        <Tooltip content={({ active, payload }) => active && payload?.length ? <div className="ds-tooltip">
          <b>Verba {money(Number(payload[0].payload.spend))}</b>{payload.map((p) => <div key={String(p.dataKey)}>{CHANNELS[p.dataKey as Channel]}: {fmt(Number(p.value))}</div>)}</div> : null} />
        {channels.map((c) => <Line key={c} dataKey={c} type="monotone" stroke={CHANNEL_COLOR[c]} strokeWidth={2.5} dot={false} isAnimationActive={false} />)}
        {channels.map((c) => allocation[c] ? <ReferenceDot key={`dot-${c}`} x={allocation[c]} y={outcomeFor(strategy.curves, { [c]: allocation[c] }, strategy.days).totals[metric]} r={5} fill={CHANNEL_COLOR[c]} stroke="#fff" strokeWidth={2} /> : null)}
      </LineChart>
    </ResponsiveContainer>
  </div>;
}
