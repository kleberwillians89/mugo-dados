import { useEffect, useState } from "react";
import { listClientMeetings, when, type Meeting } from "../../app/automations";

/**
 * Reuniões do Google Calendar da Mugô com esta empresa, na própria agenda do Mugô Dados.
 * Sem conexão com o Google (ou sem reuniões no mês) o bloco não aparece.
 */
export default function MeetingsStrip({ month, clientId }: { month: string; clientId: string }) {
  const [items, setItems] = useState<Meeting[]>([]);
  useEffect(() => {
    let alive = true;
    const [year, mon] = month.split("-").map(Number);
    const start = new Date(Date.UTC(year, mon - 1, 1, 3)).toISOString();
    const end = new Date(Date.UTC(year, mon, 1, 3)).toISOString();
    listClientMeetings(start, end).then((res) => { if (alive) setItems(res.items || []); }).catch(() => { if (alive) setItems([]); });
    return () => { alive = false; };
  }, [month, clientId]);
  if (!items.length) return null;
  return <section className="meetingsStrip" aria-label="Reuniões do mês">
    <h2 className="crmGroupTitle">Reuniões do mês <span>{items.length}</span></h2>
    <ul className="crmTaskList">{items.map((m) => <li key={m.google_event_id} className="crmTask">
      <div className="crmTaskMain"><b>{m.summary || "Reunião"}</b><small>Google Calendar da Mugô</small></div>
      <div className="crmTaskSide"><span className="crmDue">{m.all_day ? "dia todo" : when(m.start_at)}</span></div>
    </li>)}</ul>
  </section>;
}
