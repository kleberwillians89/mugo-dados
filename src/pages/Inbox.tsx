import { useCallback, useEffect, useState } from "react";
import { getActiveClientId, getActiveClientName } from "../app/activeClient";
import { CRM_UNAVAILABLE_TEXT, listCrmConversations, listCrmMessages, windowOpen, type CrmConversation, type CrmMessage, type CrmUnavailable } from "../app/crm";
import Shell from "../components/Shell";
import PageHeader from "../components/data/PageHeader";
import "../styles/studio.css";

const message = (cause: unknown, fallback: string) => (cause instanceof Error && cause.message ? cause.message : fallback);
const when = (iso: string | null) => {
  if (!iso) return "";
  const d = new Date(iso), now = new Date();
  return d.toDateString() === now.toDateString()
    ? d.toLocaleTimeString("pt-BR", { hour: "2-digit", minute: "2-digit" })
    : d.toLocaleString("pt-BR", { day: "2-digit", month: "2-digit", hour: "2-digit", minute: "2-digit" });
};

/** Atendimento WhatsApp da empresa ativa, lido do CRM Mugô. Somente leitura: responder continua no CRM. */
export default function Inbox() {
  const clientId = getActiveClientId();
  const clientName = getActiveClientName() || "empresa";
  const [conversations, setConversations] = useState<CrmConversation[]>([]);
  const [unavailable, setUnavailable] = useState<CrmUnavailable["reason"] | null>(null);
  const [selected, setSelected] = useState<string | null>(null);
  const [messages, setMessages] = useState<CrmMessage[]>([]);
  const [loading, setLoading] = useState(true);
  const [loadingThread, setLoadingThread] = useState(false);
  const [error, setError] = useState<string | null>(null);

  const load = useCallback(async () => {
    setLoading(true); setError(null);
    try {
      const res = await listCrmConversations();
      if (getActiveClientId() !== clientId) return;
      if (!res.available) { setUnavailable(res.reason); setConversations([]); return; }
      setUnavailable(null); setConversations(res.conversations || []);
    } catch (cause) { setError(message(cause, "Não foi possível ler o atendimento do CRM.")); }
    finally { setLoading(false); }
  }, [clientId]);
  useEffect(() => { void load(); }, [load]);

  const open = useCallback(async (id: string) => {
    setSelected(id); setLoadingThread(true); setMessages([]); setError(null);
    try {
      const res = await listCrmMessages(id);
      if (res.available) setMessages(res.messages || []);
    } catch (cause) { setError(message(cause, "Não foi possível abrir a conversa.")); }
    finally { setLoadingThread(false); }
  }, []);

  const current = conversations.find((c) => c.id === selected) || null;

  return <Shell title="Atendimento" variant="editorial"><div className="ds-page studioPage">
    <PageHeader company={clientName} title="Atendimento WhatsApp" controls={<button type="button" className="ds-button" onClick={() => void load()} disabled={loading}>Atualizar</button>} />
    <p className="libHint">Conversas do WhatsApp da Mugô com os contatos de {clientName}, lidas do CRM. Para responder, use o CRM.</p>
    {error ? <p role="alert" className="studioError">{error}</p> : null}
    {unavailable ? <div className="studioEmpty"><p>{CRM_UNAVAILABLE_TEXT[unavailable]}</p></div> : null}
    {loading && !conversations.length ? <p>Carregando…</p> : null}
    {!loading && !unavailable && !error && !conversations.length ? <div className="studioEmpty"><p>Nenhuma conversa com contatos de {clientName} no CRM. As conversas aparecem aqui quando o contato está vinculado a este cliente no CRM.</p></div> : null}
    {conversations.length ? <div className={`crmInbox${selected ? " has-thread" : ""}`}>
      <ul className="crmConvList" aria-label="Conversas">{conversations.map((c) => <li key={c.id}>
        <button type="button" className={c.id === selected ? "is-active" : ""} onClick={() => void open(c.id)}>
          <span className="crmConvTop"><b>{c.contact.name || c.contact.phone_masked}</b><small>{when(c.last_message_at)}</small></span>
          <span className="crmConvPreview">{c.last_message ? `${c.last_message.direction === "outbound" ? "Mugô: " : ""}${c.last_message.text}` : "Sem mensagens"}</span>
          {c.unread_count ? <span className="crmUnread" aria-label={`${c.unread_count} não lidas`}>{c.unread_count}</span> : null}
        </button>
      </li>)}</ul>
      <section className="crmThread" aria-live="polite">
        {!current ? <div className="studioEmpty"><p>Escolha uma conversa para ler.</p></div> : <>
          <header className="crmThreadHead">
            <button type="button" className="ds-button crmBack" onClick={() => setSelected(null)}>‹ Conversas</button>
            <div><b>{current.contact.name || "Contato"}</b><small>{current.contact.phone_masked}</small></div>
            <span className={windowOpen(current.service_window_expires_at) ? "crmWindow is-open" : "crmWindow"}>{windowOpen(current.service_window_expires_at) ? "Janela de 24h aberta" : "Fora da janela de 24h"}</span>
          </header>
          {loadingThread ? <p>Carregando…</p> : null}
          <ol className="crmMessages">{messages.map((m) => <li key={m.id} className={`crmMsg is-${m.direction}${m.failed ? " is-failed" : ""}`}>
            <p>{m.text || (m.template_name ? `Modelo: ${m.template_name}` : `[${m.type}]`)}</p>
            <small>{when(m.at)}{m.direction === "outbound" && m.read_at ? " · lida" : ""}{m.failed ? " · falhou" : ""}</small>
          </li>)}</ol>
        </>}
      </section>
    </div> : null}
  </div></Shell>;
}
