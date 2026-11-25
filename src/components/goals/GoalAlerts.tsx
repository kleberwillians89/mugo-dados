import { useState } from "react";
import { goalAlerts, type Goal } from "../../app/goals";

const KEY = "mugo:goal-alerts:dismissed";
const today = () => new Date().toISOString().slice(0, 10);
function dismissed(): Record<string, string> { try { return JSON.parse(window.localStorage.getItem(KEY) || "{}"); } catch { return {}; } }

/**
 * Alertas de metas dentro do Mugoverso: fora do ritmo, dados indisponíveis (problema de coleta, não de desempenho) e
 * meta atingida. "Dispensar" esconde aquele aviso até mudar o status ou virar o dia, para não repetir. Sem WhatsApp/e-mail.
 */
export default function GoalAlerts({ goals, onOpen, limit = 3 }: { goals: Goal[]; onOpen?: (goal: Goal) => void; limit?: number }) {
  const [hidden, setHidden] = useState(dismissed);
  const list = goalAlerts(goals).filter((a) => hidden[a.key] !== today()).slice(0, limit);
  if (!list.length) return null;
  function dismiss(key: string) {
    const next = { ...hidden, [key]: today() };
    setHidden(next);
    try { window.localStorage.setItem(KEY, JSON.stringify(next)); } catch { /* sem storage: só nesta tela */ }
  }
  return <ul className="goalAlerts" aria-label="Alertas de metas">{list.map((a) => {
    const goal = goals.find((g) => g.id === a.goal_id);
    return <li key={a.key} className={`is-${a.kind}`}>
      <strong>{a.kind === "dado" ? "Coleta de dados" : a.kind === "atingida" ? "Meta atingida" : "Fora do ritmo"} · {a.label}</strong>
      <span>{a.text}</span>
      <span className="goalAlertActions">
        {onOpen && goal ? <button type="button" onClick={() => onOpen(goal)}>Ver detalhes</button> : null}
        <button type="button" onClick={() => dismiss(a.key)}>Dispensar</button>
      </span>
    </li>;
  })}</ul>;
}
