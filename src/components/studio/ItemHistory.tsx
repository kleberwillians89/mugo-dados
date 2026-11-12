import { Settings } from "lucide-react";
import { useEffect, useState } from "react";
import { ago } from "../../app/ago";
import { getItemHistory, type ItemEvent } from "../../app/studio";

/** Quem fez o quê nesta pauta (kanban interno da equipe). */
export default function ItemHistory({ itemId, refreshKey }: { itemId: string; refreshKey?: string }) {
  const [events, setEvents] = useState<ItemEvent[] | null>(null);
  useEffect(() => {
    let alive = true;
    getItemHistory(itemId).then((r) => { if (alive) setEvents(r.events); }).catch(() => { if (alive) setEvents([]); });
    return () => { alive = false; };
  }, [itemId, refreshKey]);
  return <details className="postHistory">
    <summary>Histórico {events?.length ? <span>{events.length}</span> : null}</summary>
    {events === null ? <p className="libHint">Carregando…</p> : !events.length ? <p className="libHint">Ainda sem registro. Daqui em diante, cada ação nesta pauta aparece aqui.</p>
      : <ol className="itemHistory">{events.map((e) => <li key={e.id} className={`is-${e.actor_side}`}>
        <span className="itemHistoryWho" aria-hidden="true">{e.actor_side === "sistema" ? <Settings className="uiGlyph" size={13} aria-hidden="true" /> : (e.actor_name || "?").slice(0, 1).toUpperCase()}</span>
        <span><b>{e.actor_name || (e.actor_side === "cliente" ? "Cliente" : "Equipe Mugô")}</b> {e.action}
          <small title={new Date(e.created_at).toLocaleString("pt-BR")}>{ago(e.created_at)}</small>
          {e.detail ? <q>{e.detail}</q> : null}</span>
      </li>)}</ol>}
  </details>;
}
