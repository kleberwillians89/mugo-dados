import { useEffect, useState } from "react";
import { ArrowRight } from "lucide-react";
import { listProduced, type ProducedItem } from "../../app/taskWork";
import { getPathForRoute, type AppRoute } from "../../app/routes";

/** "Ir para o job": no detalhe da tarefa, o que foi produzido a partir dela; cada item abre direto no lugar dele. */
export default function TaskProduced({ taskId }: { taskId: string }) {
  const [items, setItems] = useState<ProducedItem[] | null>(null);
  useEffect(() => {
    let alive = true;
    listProduced(taskId).then((r) => { if (alive) setItems(r.items); }).catch(() => { if (alive) setItems([]); });
    return () => { alive = false; };
  }, [taskId]);
  if (!items || !items.length) return null;
  function open(item: ProducedItem) {
    if (!item.route) return;
    window.history.pushState({}, document.title, `${getPathForRoute(item.route as AppRoute)}${item.query ? `?${item.query}` : ""}`);
    window.dispatchEvent(new PopStateEvent("popstate"));
  }
  return <section className="taskProduced" aria-label="Produzido a partir desta tarefa">
    <h3>Produzido a partir desta tarefa</h3>
    <ul>{items.map((item) => <li key={`${item.module}:${item.record_id}`}>
      <button type="button" disabled={!item.route} onClick={() => open(item)}>
        <span><small>{item.module_label}{item.deliverable ? ` · ${item.deliverable}` : ""}</small>
          <b>{item.name}</b>{item.status ? <em>{item.status}</em> : null}</span>
        {item.route ? <ArrowRight size={16} aria-hidden="true" /> : null}
      </button>
    </li>)}</ul>
  </section>;
}
