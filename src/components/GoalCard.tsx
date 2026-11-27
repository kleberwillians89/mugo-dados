import { GOAL_STATUS, goalNumber, goalReading, type Goal } from "../app/goals";

const br = (iso: string) => iso.split("-").reverse().join("/");

/** Cartão de uma meta: alvo, realizado, leitura do que falta (ou da folga até o teto) e status pela direção da meta. */
export default function GoalCard({ goal, owner, parentLabel, onEdit, onDelete, onExplore }: { goal: Goal; owner?: string | null; parentLabel?: string | null;
  onEdit?: () => void; onDelete?: () => void; onExplore?: () => void }) {
  const ceiling = goal.direction === "max";
  return <article className={`goalCard${ceiling ? " is-ceiling" : ""}`} data-goal={goal.id}>
    <h2>{goal.label}</h2>
    <small>{br(goal.period_start)} até {br(goal.period_end)} · {ceiling ? "Meta máxima (não passar de)" : "Meta mínima (atingir ou superar)"}</small>
    {parentLabel ? <small>Submeta de {parentLabel}{goal.relation ? ` · ${goal.relation}` : ""}</small> : null}
    <dl><div><dt>{ceiling ? "Teto" : "Meta"}</dt><dd>{goalNumber(goal.target_value, goal.metric)}</dd></div><div><dt>Realizado</dt><dd>{goalNumber(goal.actual, goal.metric)}</dd></div></dl>
    {goal.available && goal.progress_percent != null ? <>
      <p>{goal.progress_percent.toLocaleString("pt-BR", { maximumFractionDigits: 1 })}% {ceiling ? "do teto usado" : "atingido"}</p>
      <progress max="100" value={Math.max(0, Math.min(100, goal.progress_percent))} aria-label={`Progresso de ${goal.label}`} />
    </> : null}
    <p className="goalReading">{goalReading(goal)}</p>
    <p className={`goalStatus is-${goal.status.toLowerCase()}`}>{GOAL_STATUS[goal.status] || "Dados indisponíveis"}</p>
    {goal.projected_value != null ? <p>Projeção ao fim do período (ritmo linear): {goalNumber(goal.projected_value, goal.metric)}</p> : null}
    {owner ? <small>Responsável: {owner}</small> : null}
    {goal.origin ? <small>{goal.origin}</small> : null}
    {onEdit || onDelete || onExplore ? <div className="goalActions">
      {onExplore ? <button type="button" onClick={onExplore}>Explorar</button> : null}
      {onEdit ? <button type="button" onClick={onEdit}>Editar</button> : null}
      {onDelete ? <button type="button" onClick={onDelete}>Excluir</button> : null}</div> : null}
  </article>;
}
