import { Pin } from "lucide-react";
import { useCallback, useEffect, useRef, useState } from "react";
import { listChat, sendChat, type ChatChannel, type ChatMessage } from "../../app/studio";
import Linkified from "./Linkified";

type PostRef = { id: string; title: string };
const when = (iso: string) => new Date(iso).toLocaleString("pt-BR", { day: "2-digit", month: "short", hour: "2-digit", minute: "2-digit" });

/** Fio da conversa da marca. Canal "cliente": cliente + Mugô. Canal "equipe": só Mugô. Atualiza sozinho a cada 20 s. */
export default function BrandChat({ channel, posts = [], onOpenItem, onRead, initialItemId = "", placeholder }: {
  channel: ChatChannel; posts?: PostRef[]; onOpenItem?: (id: string) => void; onRead?: () => void; initialItemId?: string; placeholder?: string }) {
  const [messages, setMessages] = useState<ChatMessage[] | null>(null);
  const [text, setText] = useState("");
  const [itemId, setItemId] = useState(initialItemId);
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const end = useRef<HTMLDivElement>(null);

  const load = useCallback(async () => {
    try { const res = await listChat(channel); setMessages(res.messages); setError(null); onRead?.(); }
    catch (cause) { setMessages((m) => m ?? []); setError(cause instanceof Error ? cause.message : "Não foi possível ler a conversa."); }
  }, [channel, onRead]);
  useEffect(() => { setMessages(null); void load(); const t = window.setInterval(() => void load(), 20000); return () => window.clearInterval(t); }, [load]);
  useEffect(() => { end.current?.scrollIntoView?.({ block: "nearest" }); }, [messages?.length]);

  async function send() {
    const body = text.trim();
    if (!body || busy) return;
    setBusy(true); setError(null);
    try {
      const res = await sendChat(channel, body, itemId || null);
      setMessages((m) => [...(m || []), res.message]); setText(""); setItemId("");
    } catch (cause) { setError(cause instanceof Error ? cause.message : "Não foi possível enviar."); }
    finally { setBusy(false); }
  }

  return <div className="chatPanel">
    <div className="chatThread" aria-live="polite">
      {messages === null ? <p className="libHint">Carregando…</p> : null}
      {messages && !messages.length ? <p className="chatEmpty">{channel === "equipe" ? "Combinados internos da equipe sobre esta marca. O cliente não vê este canal." : "Comece a conversa. O cliente e a equipe Mugô veem tudo aqui; mensagem do cliente avisa o time no WhatsApp."}</p> : null}
      {(messages || []).map((m) => <div key={m.id} className={`chatMsg is-${m.author_side}${m.mine ? " is-mine" : ""}`}>
        <small>{m.mine ? "Você" : m.author_name || (m.author_side === "mugo" ? "Equipe Mugô" : "Cliente")}{m.author_side === "cliente" && !m.mine ? " · cliente" : ""} · {when(m.created_at)}</small>
        {m.item_id ? <button type="button" className="chatPost" onClick={() => m.item_id && onOpenItem?.(m.item_id)}><Pin className="uiGlyph" size={13} aria-hidden="true" /> {m.item_title || "Post"}</button> : null}
        <p><Linkified text={m.body} /></p>
      </div>)}
      <div ref={end} />
    </div>
    {error ? <p role="alert" className="studioError">{error}</p> : null}
    <div className="chatComposer">
      <textarea rows={2} value={text} placeholder={placeholder || (channel === "equipe" ? "Mensagem para a equipe…" : "Escreva uma mensagem…")} maxLength={4000}
        onChange={(e) => setText(e.target.value)} onKeyDown={(e) => { if (e.key === "Enter" && !e.shiftKey) { e.preventDefault(); void send(); } }} aria-label="Mensagem" />
      <div className="chatActions">
        {posts.length ? <select value={itemId} onChange={(e) => setItemId(e.target.value)} aria-label="Citar um post">
          <option value="">Citar um post…</option>
          {posts.map((p) => <option key={p.id} value={p.id}>{p.title}</option>)}
        </select> : null}
        <button type="button" className="ds-button is-primary" onClick={() => void send()} disabled={busy || !text.trim()}>{busy ? "Enviando…" : "Enviar"}</button>
      </div>
    </div>
  </div>;
}
