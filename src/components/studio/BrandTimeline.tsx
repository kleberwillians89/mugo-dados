import { useEffect, useState } from "react";
import { listTimeline, type TimelineEvent } from "../../app/studio";

const when = (iso: string) => new Date(iso).toLocaleString("pt-BR", { day: "2-digit", month: "short", hour: "2-digit", minute: "2-digit" });

/** Linha do tempo automática: aprovações, ajustes, pedidos enviados, comentários e referências. */
export default function BrandTimeline({ onOpenItem }: { onOpenItem?: (id: string) => void }) {
  const [events, setEvents] = useState<TimelineEvent[] | null>(null);
  useEffect(() => {
    let alive = true;
    listTimeline().then((r) => { if (alive) setEvents(r.events); }).catch(() => { if (alive) setEvents([]); });
    return () => { alive = false; };
  }, []);
  if (events === null) return <p className="libHint">Carregando…</p>;
  if (!events.length) return <p className="chatEmpty">Ainda não há movimentação registrada para esta marca.</p>;
  return <ol className="timeline">{events.map((e) => <li key={e.id} className={`is-${e.side} is-${e.kind}`}>
    <small>{when(e.at)}</small>
    {e.item_id && onOpenItem ? <button type="button" className="kanbanTitle" onClick={() => onOpenItem(e.item_id!)}>{e.text}</button> : <b>{e.text}</b>}
    {e.detail ? <p>{e.detail}</p> : null}
  </li>)}</ol>;
}
