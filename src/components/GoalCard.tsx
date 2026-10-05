import { GOAL_STATUS, goalNumber, type Goal } from "../app/goals";
export default function GoalCard({ goal, onEdit, onDelete }: { goal: Goal; onEdit?: () => void; onDelete?: () => void }) {
  return <article className="goalCard">
    <h2>{goal.label}</h2><small>{goal.period_start.split("-").reverse().join("/")} até {goal.period_end.split("-").reverse().join("/")}</small>
    <dl><div><dt>Meta</dt><dd>{goalNumber(goal.target_value, goal.metric)}</dd></div><div><dt>Realizado</dt><dd>{goalNumber(goal.actual, goal.metric)}</dd></div></dl>
    {goal.available ? <><p>{goal.progress_percent?.toLocaleString("pt-BR", { maximumFractionDigits: 1 })}% atingido</p><progress max="100" value={Math.max(0, Math.min(100, goal.progress_percent || 0))} aria-label={`Progresso de ${goal.label}`} /><p>Faltam {goalNumber(goal.remaining, goal.metric)}</p><small>Ritmo esperado: {goal.elapsed_percent.toLocaleString("pt-BR", { maximumFractionDigits: 1 })}%</small></> : <p>{goal.reason}</p>}
    <p className={`goalStatus is-${goal.status.toLowerCase()}`}>{GOAL_STATUS[goal.status] || "Indisponível"}</p>
    {goal.projected_value != null ? <p>Projeção ao fim do período: {goalNumber(goal.projected_value, goal.metric)}</p> : null}
    {goal.origin ? <small>{goal.origin}</small> : null}
    {onEdit || onDelete ? <div className="goalActions">{onEdit ? <button type="button" onClick={onEdit}>Editar</button> : null}{onDelete ? <button type="button" onClick={onDelete}>Excluir</button> : null}</div> : null}
  </article>;
}
