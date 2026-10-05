import { getActiveClientId } from "../app/activeClient";
import { usePeriod } from "../app/PeriodContext";
import { goalNumber } from "../app/goals";
import useGoals from "../hooks/useGoals";
import "../styles/goals.css";
export default function GoalsSummary({ onOpen }: { onOpen: () => void }) {
  const { period } = usePeriod();
  const model = useGoals(getActiveClientId(), period.start, period.end);
  return <section className="goalsSummary ds-page" aria-label="Progresso das metas"><h2>Progresso das metas</h2>
    {model.error ? <p role="status">Metas indisponíveis no momento.</p> : null}
    {!model.loading && !model.error && !model.goals.length ? <p>Nenhuma meta neste período.</p> : null}
    <div className="goalsGrid">{model.goals.slice(0, 3).map((goal) => <article key={goal.id}><strong>{goal.label}</strong>{goal.available ? <><progress max="100" value={Math.max(0, Math.min(100, goal.progress_percent || 0))} aria-label={goal.label} /><p>{goal.progress_percent?.toLocaleString("pt-BR", { maximumFractionDigits: 1 })}% · {goalNumber(goal.actual, goal.metric)} / {goalNumber(goal.target_value, goal.metric)}</p></> : <p>Indisponível</p>}</article>)}</div>
    <button className="ds-button" onClick={onOpen}>Ver todas as metas</button>
  </section>;
}
