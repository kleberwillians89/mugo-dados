import { useCallback, useEffect, useRef, useState, type PointerEvent as ReactPointerEvent } from "react";
import { CheckCircle2, ClipboardCheck, Image as ImageIcon, MessageCircle, MessageSquareText, X } from "lucide-react";
import { getActiveClientName } from "../../app/activeClient";
import { chatUnread, listTimeline, type ChatChannel, type TimelineEvent } from "../../app/studio";
import BrandChat from "./BrandChat";
import { ago } from "../../app/ago";
import { DONE_KINDS, newDone } from "./chatWidget.helpers";

type Tab = "conversa" | "feito";
type Activity = { unread: Partial<Record<ChatChannel, number>>; events: TimelineEvent[] };

/** Lê mensagens não lidas e o que a equipe fez (sem estado). */
async function fetchActivity(): Promise<Activity> {
  const [u, t] = await Promise.all([chatUnread().catch(() => null), listTimeline().catch(() => null)]);
  return { unread: u?.unread || {}, events: t?.events || [] };
}
const DONE_ICON: Record<string, typeof CheckCircle2> = { publicado: CheckCircle2, pedido: ClipboardCheck, comentario_mugo: MessageSquareText, referencia: ImageIcon };
const seenKey = (clientId: string) => `mugo.widget.seen.${clientId}`;
const autoKey = (clientId: string) => `mugo.widget.auto.${clientId}`;
const positionKey = "mugo.widget.position.v1";
type WidgetPosition = { x: number; y: number };
const widgetSize = 54;
const edgeGap = 12;
const positionBounds = (pos: WidgetPosition): WidgetPosition => ({
  x: Math.max(edgeGap, Math.min(pos.x, window.innerWidth - widgetSize - edgeGap)),
  y: Math.max(edgeGap, Math.min(pos.y, window.innerHeight - widgetSize - edgeGap)),
});
const initialPosition = (): WidgetPosition => {
  const defaultPosition = { x: window.innerWidth - widgetSize - 20, y: window.innerHeight - widgetSize - 20 };
  try {
    const saved = JSON.parse(localStorage.getItem(positionKey) || "null") as WidgetPosition | null;
    if (saved && Number.isFinite(saved.x) && Number.isFinite(saved.y)) return positionBounds(saved);
  } catch { /* posição padrão */ }
  return positionBounds(defaultPosition);
};

const read = (store: Storage | undefined, key: string) => { try { return store?.getItem(key) || ""; } catch { return ""; } };
const write = (store: Storage | undefined, key: string, value: string) => { try { store?.setItem(key, value); } catch { /* sem armazenamento */ } };


/**
 * Balão de conversa em todas as páginas. Para o cliente, abre sozinho uma vez por sessão quando há
 * mensagem nova da equipe ou coisa feita (post publicado, pedido de aprovação, comentário, referência).
 */
export default function ChatWidget({ clientId, team }: { clientId: string; team: boolean }) {
  const [open, setOpen] = useState(false);
  const [position, setPosition] = useState<WidgetPosition>(initialPosition);
  const drag = useRef<{ id: number; x: number; y: number; origin: WidgetPosition; moved: boolean } | null>(null);
  const suppressClick = useRef(false);
  useEffect(() => {
    const onResize = () => setPosition((current) => positionBounds(current));
    window.addEventListener("resize", onResize);
    return () => window.removeEventListener("resize", onResize);
  }, []);
  const onPointerDown = (event: ReactPointerEvent<HTMLButtonElement>) => {
    if (event.button !== 0) return;
    drag.current = { id: event.pointerId, x: event.clientX, y: event.clientY, origin: position, moved: false };
    event.currentTarget.setPointerCapture(event.pointerId);
  };
  const onPointerMove = (event: ReactPointerEvent<HTMLButtonElement>) => {
    const current = drag.current;
    if (!current || current.id !== event.pointerId) return;
    const dx = event.clientX - current.x, dy = event.clientY - current.y;
    if (!current.moved && Math.hypot(dx, dy) < 7) return;
    current.moved = true;
    setPosition(positionBounds({ x: current.origin.x + dx, y: current.origin.y + dy }));
  };
  const finishDrag = (event: ReactPointerEvent<HTMLButtonElement>) => {
    const current = drag.current;
    if (!current || current.id !== event.pointerId) return;
    drag.current = null;
    if (current.moved) {
      suppressClick.current = true;
      const updated = positionBounds({
        x: current.origin.x + event.clientX - current.x,
        y: current.origin.y + event.clientY - current.y,
      });
      setPosition(updated);
      try { localStorage.setItem(positionKey, JSON.stringify(updated)); } catch { /* sem armazenamento */ }
    }
    if (event.currentTarget.hasPointerCapture(event.pointerId)) event.currentTarget.releasePointerCapture(event.pointerId);
  };
  const cancelDrag = (event: ReactPointerEvent<HTMLButtonElement>) => {
    drag.current = null;
    if (event.currentTarget.hasPointerCapture(event.pointerId)) event.currentTarget.releasePointerCapture(event.pointerId);
  };
  const [tab, setTab] = useState<Tab>("conversa");
  const [channel, setChannel] = useState<ChatChannel>("cliente");
  const [unread, setUnread] = useState<Partial<Record<ChatChannel, number>>>({});
  const [done, setDone] = useState<TimelineEvent[]>([]);
  const [seenAt, setSeenAt] = useState(() => read(globalThis.localStorage, seenKey(clientId)));

  const apply = useCallback((data: Activity) => {
    setUnread(data.unread);
    setDone(data.events.filter((e) => DONE_KINDS.includes(e.kind)));
  }, []);
  const refresh = useCallback(() => fetchActivity().then((data) => { apply(data); return data; }), [apply]);

  // O widget é remontado a cada troca de empresa (key no App), então o estado já começa limpo.
  useEffect(() => {
    const seen = read(globalThis.localStorage, seenKey(clientId));
    let alive = true;
    void fetchActivity().then((data) => {
      if (!alive) return;
      apply(data);
      const { unread: u, events } = data;
      if (team || read(globalThis.sessionStorage, autoKey(clientId))) return;
      const msgs = u.cliente || 0;
      const fresh = newDone(events, seen);
      if (msgs || fresh) { write(globalThis.sessionStorage, autoKey(clientId), "1"); setTab(msgs ? "conversa" : "feito"); setOpen(true); }
    });
    const timer = window.setInterval(() => void fetchActivity().then((data) => { if (alive) apply(data); }), 60000);
    return () => { alive = false; window.clearInterval(timer); };
  }, [clientId, team, apply]);

  // Ao olhar "O que foi feito", conta como visto na hora (derivado, sem setState no efeito); o efeito só
  // grava no navegador, e o estado é atualizado quando a pessoa sai da aba ou fecha o balão.
  const latestDone = done[0]?.at || "";
  const viewingDone = open && tab === "feito" && Boolean(latestDone);
  const effectiveSeen = viewingDone && latestDone > seenAt ? latestDone : seenAt;
  useEffect(() => {
    if (viewingDone && latestDone > read(globalThis.localStorage, seenKey(clientId))) write(globalThis.localStorage, seenKey(clientId), latestDone);
  }, [viewingDone, latestDone, clientId]);
  const commitSeen = () => { if (effectiveSeen !== seenAt) setSeenAt(effectiveSeen); };
  const close = () => { commitSeen(); setOpen(false); };
  const showTab = (next: Tab) => { commitSeen(); setTab(next); };

  const msgCount = (unread.cliente || 0) + (team ? unread.equipe || 0 : 0);
  const doneCount = newDone(done, effectiveSeen);
  const total = msgCount + doneCount;
  const markRead = useCallback(() => { window.setTimeout(() => void refresh(), 300); }, [refresh]);
  const brand = getActiveClientName() || "Cliente";

  const panelBelow = position.y < Math.min(575, window.innerHeight * 0.57);
  const panelOnLeft = position.x < 390;
  return <div className={`cw${panelBelow ? " is-below" : ""}${panelOnLeft ? " is-left" : ""}`}
    style={{ left: position.x, top: position.y, right: "auto", bottom: "auto" }}>
    {open ? <section className="cwPanel" role="dialog" aria-label={team ? `Conversa com ${brand}` : "Conversa com a Mugô"}>
      <header className="cwHead">
        <span className="cwAvatar" aria-hidden="true">{team ? brand.slice(0, 1).toUpperCase() : "M"}</span>
        <span className="cwTitle"><b>{team ? brand : "Equipe Mugô"}</b><small>{team ? "Conversa e o que foi feito" : "Fale com a gente e veja o que foi feito"}</small></span>
        <button type="button" className="cwClose" aria-label="Fechar" onClick={close}><X size={18} /></button>
      </header>
      <div className="cwTabs" role="tablist">
        <button type="button" role="tab" aria-selected={tab === "conversa"} className={tab === "conversa" ? "is-active" : ""} onClick={() => showTab("conversa")}>
          Conversa{msgCount ? <i className="hubBadge">{msgCount}</i> : null}</button>
        <button type="button" role="tab" aria-selected={tab === "feito"} className={tab === "feito" ? "is-active" : ""} onClick={() => showTab("feito")}>
          O que foi feito{doneCount ? <i className="hubBadge">{doneCount}</i> : null}</button>
      </div>
      <div className="cwBody">
        {tab === "conversa" ? <>
          {team ? <div className="hubViews" role="tablist" aria-label="Canal">
            <button type="button" role="tab" aria-selected={channel === "cliente"} className={channel === "cliente" ? "is-active" : ""} onClick={() => setChannel("cliente")}>Com o cliente</button>
            <button type="button" role="tab" aria-selected={channel === "equipe"} className={channel === "equipe" ? "is-active" : ""} onClick={() => setChannel("equipe")}>Só equipe</button>
          </div> : null}
          <BrandChat key={`${clientId}-${channel}`} channel={channel} onRead={markRead} />
        </> : done.length ? <ul className="cwDone">{done.slice(0, 30).map((e) => {
          const Icon = DONE_ICON[e.kind] || CheckCircle2;
          const fresh = !seenAt || e.at > seenAt;
          return <li key={e.id} className={`is-${e.kind}${fresh ? " is-new" : ""}`}>
            <Icon size={16} aria-hidden="true" />
            <span><b>{e.text}</b>{e.detail ? <p>{e.detail}</p> : null}
              <small>{ago(e.at)}{e.link ? <> · <a href={e.link} target="_blank" rel="noreferrer noopener">ver no Instagram ↗</a></> : null}</small></span>
          </li>;
        })}</ul> : <p className="chatEmpty">Assim que a equipe publicar um post ou enviar algo para aprovação, aparece aqui.</p>}
      </div>
    </section> : null}
    <button type="button" className="cwBubble" aria-label={open ? "Fechar conversa" : `Abrir conversa${total ? ` (${total} novidades)` : ""}`} aria-expanded={open}
      title="Clique para abrir ou arraste para reposicionar o chat" onPointerDown={onPointerDown} onPointerMove={onPointerMove} onPointerUp={finishDrag} onPointerCancel={cancelDrag}
      onClick={() => { if (suppressClick.current) { suppressClick.current = false; return; } if (open) close(); else setOpen(true); }}>
      {open ? <X size={22} /> : <MessageCircle size={22} />}
      {!open && total ? <i className="cwBadge">{total > 9 ? "9+" : total}</i> : null}
    </button>
  </div>;
}
