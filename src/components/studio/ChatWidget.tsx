import { useCallback, useEffect, useState } from "react";
import { CheckCircle2, ClipboardCheck, Image as ImageIcon, MessageCircle, MessageSquareText, X } from "lucide-react";
import { getActiveClientName } from "../../app/activeClient";
import { chatUnread, listTimeline, type ChatChannel, type TimelineEvent } from "../../app/studio";
import BrandChat from "./BrandChat";
import { ago } from "../../app/ago";

type Tab = "conversa" | "feito";
const DONE_KINDS = ["publicado", "pedido", "comentario_mugo", "referencia"];
const DONE_ICON: Record<string, typeof CheckCircle2> = { publicado: CheckCircle2, pedido: ClipboardCheck, comentario_mugo: MessageSquareText, referencia: ImageIcon };
const seenKey = (clientId: string) => `mugo.widget.seen.${clientId}`;
const autoKey = (clientId: string) => `mugo.widget.auto.${clientId}`;
const read = (store: Storage | undefined, key: string) => { try { return store?.getItem(key) || ""; } catch { return ""; } };
const write = (store: Storage | undefined, key: string, value: string) => { try { store?.setItem(key, value); } catch { /* sem armazenamento */ } };

/** Novidades feitas pela equipe depois da última vez que a pessoa olhou. */
export function newDone(events: TimelineEvent[], seenAt: string): number {
  return events.filter((e) => DONE_KINDS.includes(e.kind) && (!seenAt || e.at > seenAt)).length;
}

/**
 * Balão de conversa em todas as páginas. Para o cliente, abre sozinho uma vez por sessão quando há
 * mensagem nova da equipe ou coisa feita (post publicado, pedido de aprovação, comentário, referência).
 */
export default function ChatWidget({ clientId, team }: { clientId: string; team: boolean }) {
  const [open, setOpen] = useState(false);
  const [tab, setTab] = useState<Tab>("conversa");
  const [channel, setChannel] = useState<ChatChannel>("cliente");
  const [unread, setUnread] = useState<Partial<Record<ChatChannel, number>>>({});
  const [done, setDone] = useState<TimelineEvent[]>([]);
  const [seenAt, setSeenAt] = useState(() => read(globalThis.localStorage, seenKey(clientId)));

  const refresh = useCallback(async () => {
    const [u, t] = await Promise.all([chatUnread().catch(() => null), listTimeline().catch(() => null)]);
    setUnread(u?.unread || {});
    setDone((t?.events || []).filter((e) => DONE_KINDS.includes(e.kind)));
    return { unread: u?.unread || {}, events: t?.events || [] };
  }, []);

  useEffect(() => {
    setOpen(false); setTab("conversa"); setChannel("cliente"); setDone([]); setUnread({});
    const seen = read(globalThis.localStorage, seenKey(clientId));
    setSeenAt(seen);
    let alive = true;
    void refresh().then(({ unread: u, events }) => {
      if (!alive || team || read(globalThis.sessionStorage, autoKey(clientId))) return;
      const msgs = u.cliente || 0;
      const fresh = newDone(events, seen);
      if (msgs || fresh) { write(globalThis.sessionStorage, autoKey(clientId), "1"); setTab(msgs ? "conversa" : "feito"); setOpen(true); }
    });
    const timer = window.setInterval(() => void refresh(), 60000);
    return () => { alive = false; window.clearInterval(timer); };
  }, [clientId, team, refresh]);

  // Ao olhar "O que foi feito", marca como visto.
  useEffect(() => {
    if (!open || tab !== "feito" || !done.length) return;
    const latest = done[0].at;
    if (latest > seenAt) { write(globalThis.localStorage, seenKey(clientId), latest); setSeenAt(latest); }
  }, [open, tab, done, seenAt, clientId]);

  const msgCount = (unread.cliente || 0) + (team ? unread.equipe || 0 : 0);
  const doneCount = newDone(done, seenAt);
  const total = msgCount + doneCount;
  const markRead = useCallback(() => { window.setTimeout(() => void refresh(), 300); }, [refresh]);
  const brand = getActiveClientName() || "Cliente";

  return <div className="cw">
    {open ? <section className="cwPanel" role="dialog" aria-label={team ? `Conversa com ${brand}` : "Conversa com a Mugô"}>
      <header className="cwHead">
        <span className="cwAvatar" aria-hidden="true">{team ? brand.slice(0, 1).toUpperCase() : "M"}</span>
        <span className="cwTitle"><b>{team ? brand : "Equipe Mugô"}</b><small>{team ? "Conversa e o que foi feito" : "Fale com a gente e veja o que foi feito"}</small></span>
        <button type="button" className="cwClose" aria-label="Fechar" onClick={() => setOpen(false)}><X size={18} /></button>
      </header>
      <div className="cwTabs" role="tablist">
        <button type="button" role="tab" aria-selected={tab === "conversa"} className={tab === "conversa" ? "is-active" : ""} onClick={() => setTab("conversa")}>
          Conversa{msgCount ? <i className="hubBadge">{msgCount}</i> : null}</button>
        <button type="button" role="tab" aria-selected={tab === "feito"} className={tab === "feito" ? "is-active" : ""} onClick={() => setTab("feito")}>
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
    <button type="button" className="cwBubble" aria-label={open ? "Fechar conversa" : `Abrir conversa${total ? ` (${total} novidades)` : ""}`} aria-expanded={open} onClick={() => setOpen(!open)}>
      {open ? <X size={22} /> : <MessageCircle size={22} />}
      {!open && total ? <i className="cwBadge">{total > 9 ? "9+" : total}</i> : null}
    </button>
  </div>;
}
