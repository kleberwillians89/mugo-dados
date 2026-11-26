import { useMemo } from "react";
import { getActiveClientId } from "../../app/activeClient";
import { GOAL_STATUS, goalNumber, goalReading, type GoalMetric } from "../../app/goals";
import useGoals from "../../hooks/useGoals";
import GoalAlerts from "./GoalAlerts";

/** Indicadores de mídia paga. Faturamento total fica de fora: não é receita atribuída à mídia. */
const MEDIA_METRICS = new Set<GoalMetric>(["ad_spend", "roas", "cpa_meta", "conversions", "google_conversions"]);

function monthRange(today = new Date()) {
  const iso = (d: Date) => `${d.getFullYear()}-${String(d.getMonth() + 1).padStart(2, "0")}-${String(d.getDate()).padStart(2, "0")}`;
  return { start: iso(new Date(today.getFullYear(), today.getMonth(), 1)), end: iso(new Date(today.getFullYear(), today.getMonth() + 1, 0)) };
}

/**
 * Metas ligadas à mídia no mês, na Mídia On: leitura e alertas. Mesmo cadastro de Metas (não duplica);
 * não mexe em orçamento. Para criar ou mudar metas, o caminho é o Planejamento.
 */
export default function MediaGoals({ onOpenPlanning }: { onOpenPlanning: () => void }) {
  const clientId = getActiveClientId();
  const range = useMemo(() => monthRange(), []);
  const model = useGoals(clientId, range.start, range.end);
  const goals = model.goals.filter((g) => MEDIA_METRICS.has(g.metric));
  if (!goals.length) return null;
  return <section className="mediaGoals" aria-labelledby="media-goals-title">
    <div><h2 id="media-goals-title">Metas ligadas à mídia</h2>
      <small>Do mês, do mesmo cadastro de Metas. Receita e compras atribuídas por cada plataforma, que não são somadas nem confundidas com o faturamento da loja.</small></div>
    <GoalAlerts goals={goals} limit={2} />
    <ul>{goals.map((g) => <li key={g.id}>
      <strong>{g.label}</strong>
      <span>{g.direction === "max" ? "Teto" : "Meta"} {goalNumber(g.target_value, g.metric)} · realizado {goalNumber(g.actual, g.metric)}</span>
      <small>{GOAL_STATUS[g.status] || "Dados indisponíveis"} · {goalReading(g)}</small>
    </li>)}</ul>
    <button type="button" className="ds-button" style={{ justifySelf: "start" }} onClick={onOpenPlanning}>Abrir metas no Planejamento</button>
  </section>;
}
