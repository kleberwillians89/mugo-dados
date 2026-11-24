import { useEffect, useState } from "react";
import Drawer from "../Drawer";
import Premises from "./GoalPremises";
import { GOAL_STATUS, getGoalDrivers, getGoalHistory, goalNumber, suggestGoal, type Goal, type GoalDriver, type GoalHistoryEvent,
  type GoalMetric, type GoalSuggestion } from "../../app/goals";

type Tab = "indicadores" | "cenarios" | "fonte" | "historico";
const TABS: [Tab, string][] = [["indicadores", "Indicadores relacionados"], ["cenarios", "Cenários"], ["fonte", "Fonte e limitações"], ["historico", "Histórico"]];
const when = (iso: string) => new Date(iso).toLocaleString("pt-BR", { day: "2-digit", month: "2-digit", year: "numeric", hour: "2-digit", minute: "2-digit" });

/**
 * Detalhamento de uma meta: indicadores que a influenciam (com o valor necessário), cenários com premissas,
 * fonte, cobertura e limitações, e o histórico de alterações. Criar submeta só com confirmação da pessoa.
 */
export default function GoalExplore({ goal, onClose, onCreateSubgoal, ownerName }: { goal: Goal | null; onClose: () => void;
  onCreateSubgoal?: (driver: GoalDriver, relation: string | null) => void; ownerName?: (id?: string | null) => string | null }) {
  const [tab, setTab] = useState<Tab>("indicadores");
  const [drivers, setDrivers] = useState<{ relation: string | null; drivers: GoalDriver[]; note: string } | null>(null);
  const [suggestion, setSuggestion] = useState<GoalSuggestion | null>(null);
  const [history, setHistory] = useState<{ available: boolean; events: GoalHistoryEvent[] } | null>(null);
  const [error, setError] = useState<string | null>(null);
  const id = goal?.id;

  useEffect(() => {
    if (!goal) return undefined;
    let alive = true;
    const t = window.setTimeout(() => {
      setTab("indicadores"); setDrivers(null); setSuggestion(null); setHistory(null); setError(null);
      getGoalDrivers(goal.id).then((r) => { if (alive) setDrivers(r); }).catch(() => { if (alive) setError("Não foi possível ler os indicadores relacionados."); });
    }, 0);
    return () => { alive = false; window.clearTimeout(t); };
  }, [id]);  // eslint-disable-line react-hooks/exhaustive-deps

  function open(next: Tab) {
    setTab(next);
    if (!goal) return;
    if (next === "cenarios" && !suggestion) suggestGoal(goal.metric, goal.period_start, goal.period_end).then(setSuggestion).catch(() => setSuggestion({ available: false, reason: "Não foi possível ler o histórico agora." }));
    if (next === "historico" && !history) getGoalHistory(goal.id).then(setHistory).catch(() => setHistory({ available: false, events: [] }));
  }

  const n = (v: number | null | undefined, metric: GoalMetric = goal?.metric || "revenue") => goalNumber(v, metric);
  return <Drawer open={Boolean(goal)} width="lg" title={goal ? goal.label : ""} description="Indicadores, cenários, fontes e histórico desta meta." onClose={onClose}>
    {goal ? <div className="goalExplore">
      <div className="studioTabs" role="tablist" aria-label="Detalhes da meta">{TABS.map(([key, label]) =>
        <button key={key} type="button" role="tab" aria-selected={tab === key} className={tab === key ? "is-active" : ""} onClick={() => open(key)}>{label}</button>)}</div>
      {error ? <p role="alert" className="studioError">{error}</p> : null}

      {tab === "indicadores" ? <div>
        {!drivers ? <p className="libHint">Lendo os indicadores…</p> : <>
          {drivers.relation ? <p className="goalRelation">{drivers.relation}</p> : null}
          {!drivers.drivers.length ? <p className="libHint">{drivers.note}</p> : <ul className="goalDrivers">{drivers.drivers.map((d) => <li key={d.metric}>
            <strong>{d.label}</strong>
            {d.available ? <span>Hoje: {n(d.actual, d.metric)}{d.needed != null ? ` · para bater a meta: ${n(d.needed, d.metric)}` : ""}</span>
              : <span className="goalUnavailable">{d.reason?.includes("integração") ? "Integração necessária" : "Dados indisponíveis"}: {d.reason}</span>}
            {d.origin ? <small>{d.origin}</small> : null}
            {onCreateSubgoal && d.available ? <button type="button" className="ds-button" onClick={() => onCreateSubgoal(d, drivers.relation)}>Transformar em submeta</button> : null}
          </li>)}</ul>}
          {drivers.drivers.length ? <p className="libHint">{drivers.note} Nada é criado sozinho: a submeta só existe se você confirmar.</p> : null}
        </>}
      </div> : null}

      {tab === "cenarios" ? <div>
        {!suggestion ? <p className="libHint">Lendo o histórico…</p> : !suggestion.available ? <p className="libHint">{suggestion.reason}</p> : <>
          <ul className="goalScenarios">{suggestion.scenarios!.map((s) => <li key={s.key}><small>{s.label}</small><b>{n(s.value)}</b></li>)}</ul>
          <p className="libHint">Incerteza: {suggestion.uncertainty}{suggestion.trend_percent != null ? ` · evolução entre os períodos: ${suggestion.trend_percent.toLocaleString("pt-BR", { maximumFractionDigits: 1 })}%` : ""}.</p>
        </>}
        {suggestion?.premises ? <Premises premises={suggestion.premises} format={(v) => n(v)} /> : null}
      </div> : null}

      {tab === "fonte" ? <dl className="goalSource">
        <dt>Fonte</dt><dd>{goal.origin || "—"}</dd>
        <dt>Status</dt><dd>{GOAL_STATUS[goal.status] || "Dados indisponíveis"}</dd>
        <dt>Cobertura</dt><dd>{goal.covered_days != null && goal.days_total ? `${goal.covered_days} dia(s) com dado no período de ${goal.days_total}` : "Não informada pela fonte"}</dd>
        <dt>Ritmo</dt><dd>{goal.additive ? "Linear: distribui o que falta igualmente pelos dias restantes, sem sazonalidade (Black Friday, fins de semana)." : "Indicador de razão ou nível: comparado ao alvo pelo valor do período, sem ritmo de calendário."}</dd>
        <dt>Projeção</dt><dd>{goal.projected_value != null ? n(goal.projected_value) : "Não exibida: precisa de cobertura completa da fonte e de parte do período já passada."}</dd>
        {goal.reason ? <><dt>Limitação</dt><dd>{goal.reason}</dd></> : null}
        {goal.suggestion ? <><dt>Origem do alvo</dt><dd>Cenário {goal.suggestion.label} ({n(goal.suggestion.value)}), escolhido na criação.</dd></> : null}
        {ownerName?.(goal.owner_user_id) ? <><dt>Responsável</dt><dd>{ownerName(goal.owner_user_id)}</dd></> : null}
      </dl> : null}

      {tab === "historico" ? <div>
        {!history ? <p className="libHint">Lendo o histórico…</p> : !history.available ? <p className="libHint">O histórico de alterações ainda não está ativo nesta instalação.</p>
          : !history.events.length ? <p className="libHint">Sem alterações registradas.</p>
          : <ol className="goalHistory">{history.events.map((e, i) => <li key={i}>
            <strong>{e.action === "criada" ? "Criada" : e.action === "editada" ? "Editada" : "Excluída"}</strong> · {when(e.created_at)}{ownerName?.(e.actor) ? ` · ${ownerName(e.actor)}` : ""}
            {e.action === "editada" && e.before && e.after && e.before.target_value !== e.after.target_value
              ? <small>Alvo: {n(e.before.target_value as number)} → {n(e.after.target_value as number)}</small> : null}
          </li>)}</ol>}
      </div> : null}
    </div> : null}
  </Drawer>;
}
