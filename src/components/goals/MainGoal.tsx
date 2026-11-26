import { GOAL_STATUS, goalNumber, goalReading, type Goal } from "../../app/goals";

/** "Minha meta": a leitura executiva da meta principal. Tudo vem calculado do servidor; projeção só com cobertura. */
export default function MainGoal({ goal, owner, onExplore }: { goal: Goal; owner?: string | null; onExplore: () => void }) {
  const n = (v: number | null | undefined) => goalNumber(v, goal.metric);
  const ceiling = goal.direction === "max";
  const attention = ["ABAIXO_DO_RITMO", "ABAIXO_DA_META", "ATENCAO", "RISCO_DE_PASSAR", "ACIMA_DO_TETO", "INDISPONIVEL"].includes(goal.status);
  return <section className={`goalMain${attention ? " needs-attention" : ""}`} aria-labelledby="goal-main-title">
    <div className="goalMainHead">
      <div><span>Minha meta</span><h3 id="goal-main-title">{goal.label}</h3>
        <small>{ceiling ? "Não passar de " : "Alcançar "}{n(goal.target_value)} · {goal.period_start.split("-").reverse().join("/")} a {goal.period_end.split("-").reverse().join("/")}{owner ? ` · responsável: ${owner}` : ""}</small></div>
      <b className={`goalStatus is-${goal.status.toLowerCase()}`}>{GOAL_STATUS[goal.status] || "Dados indisponíveis"}</b>
    </div>
    <dl className="goalMainNumbers">
      <div><dt>{ceiling ? "Teto" : "O que queremos"}</dt><dd>{n(goal.target_value)}</dd></div>
      <div><dt>{ceiling ? "Usado até agora" : "Já alcançamos"}</dt><dd>{n(goal.actual)}</dd></div>
      <div><dt>{ceiling ? "Folga até o teto" : "Falta"}</dt><dd>{goal.available ? n(goal.remaining) : "—"}</dd></div>
      <div><dt>Dias restantes</dt><dd>{goal.days_left ?? "—"}</dd></div>
      {goal.required_daily != null ? <div><dt>{ceiling ? "Pode usar por dia" : "Necessário por dia"}</dt><dd>{n(goal.required_daily)}</dd></div> : null}
      {goal.required_today != null ? <div><dt>Necessário hoje (dias da semana)</dt><dd>{n(goal.required_today)}</dd></div> : null}
      {goal.observed_daily != null ? <div><dt>Ritmo observado por dia</dt><dd>{n(goal.observed_daily)}</dd></div> : null}
      {goal.projected_value != null ? <div><dt>Projeção ao fim ({goal.pace_model === "sazonal" ? "ritmo dos dias da semana" : "ritmo linear"})</dt><dd>{n(goal.projected_value)}</dd></div> : null}
    </dl>
    <p className="goalMainReading">{goalReading(goal)}{goal.pace_note ? ` ${goal.pace_note}` : ""}</p>
    <div className="goalMainFoot">
      <small>{goal.origin || ""}{goal.pace_model === "linear" ? " · ritmo linear (sem sazonalidade)" : goal.pace_model === "sazonal" ? " · ritmo pelos dias da semana da marca (8 semanas anteriores)" : ""}</small>
      <button type="button" className="ds-button" onClick={onExplore}>Explorar indicadores e cenários</button>
    </div>
  </section>;
}
