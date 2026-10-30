import { useCallback, useEffect, useState } from "react";
import { CRM_UNAVAILABLE_TEXT, listCrmConversations, listCrmMessages, samePhone, windowOpen, type CrmConversation, type CrmMessage, type CrmUnavailable } from "../../app/crm";
import type { ClientContact } from "../../app/studio";

const when = (iso: string | null) => {
  if (!iso) return "";
  const d = new Date(iso), now = new Date();
  return d.toDateString() === now.toDateString()
    ? d.toLocaleTimeString("pt-BR", { hour: "2-digit", minute: "2-digit" })
    : d.toLocaleString("pt-BR", { day: "2-digit", month: "2-digit", hour: "2-digit", minute: "2-digit" });
};

type Row = { key: string; label: string; sub: string; conversation: CrmConversation | null };

/**
 * Conversa do WhatsApp da Mugô com cada contato do cliente, lida do CRM (só agência).
 * Fica na aba Mensagens da Aprovação: o que foi enviado e o que o cliente respondeu, lado a lado.
 */
export default function CrmConversations({ contacts, clientId }: { contacts: ClientContact[]; clientId: string }) {
  const [conversations, setConversations] = useState<CrmConversation[]>([]);
  const [unavailable, setUnavailable] = useState<CrmUnavailable["reason"] | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [loading, setLoading] = useState(true);
  const [open, setOpen] = useState<string | null>(null);
  const [thread, setThread] = useState<CrmMessage[]>([]);
  const [loadingThread, setLoadingThread] = useState(false);

  const load = useCallback(async () => {
    setLoading(true); setError(null);
    try {
      const res = await listCrmConversations();
      if (!res.available) { setUnavailable(res.reason); setConversations([]); return; }
      setUnavailable(null); setConversations(res.conversations || []);
    } catch (cause) { setError(cause instanceof Error && cause.message ? cause.message : "Não foi possível ler o CRM agora."); }
    finally { setLoading(false); }
  }, []);
  useEffect(() => { void load(); }, [load, clientId]);

  const toggle = useCallback(async (id: string) => {
    if (open === id) { setOpen(null); return; }
    setOpen(id); setThread([]); setLoadingThread(true);
    try {
      const res = await listCrmMessages(id);
      if (res.available) setThread(res.messages || []);
    } catch (cause) { setError(cause instanceof Error && cause.message ? cause.message : "Não foi possível abrir a conversa."); }
    finally { setLoadingThread(false); }
  }, [open]);

  const used = new Set<string>();
  const rows: Row[] = contacts.map((c) => {
    const conv = conversations.find((x) => samePhone(x.contact.matched_phone, c.phone)) || null;
    if (conv) used.add(conv.id);
    return { key: `c:${c.id}`, label: c.name, sub: `+${c.phone}`, conversation: conv };
  });
  const others: Row[] = conversations.filter((x) => !used.has(x.id))
    .map((x) => ({ key: `x:${x.id}`, label: x.contact.name || "Contato", sub: `${x.contact.phone_masked} · só no CRM`, conversation: x }));

  const renderRow = (row: Row) => {
    const conv = row.conversation;
    const isOpen = conv && open === conv.id;
    return <li key={row.key} className={isOpen ? "is-open" : ""}>
      <button type="button" className="crmContactRow" disabled={!conv} onClick={() => conv && void toggle(conv.id)} aria-expanded={conv ? Boolean(isOpen) : undefined}>
        <span className="crmConvTop"><b>{row.label}</b><small>{conv ? when(conv.last_message_at) : ""}</small></span>
        <span className="crmConvPreview">{conv ? (conv.last_message ? `${conv.last_message.direction === "outbound" ? "Mugô: " : ""}${conv.last_message.text}` : "Sem mensagens") : `${row.sub} · ainda sem conversa no WhatsApp da Mugô`}</span>
        {conv?.unread_count ? <span className="crmUnread" aria-label={`${conv.unread_count} não lidas`}>{conv.unread_count}</span> : null}
      </button>
      {isOpen && conv ? <div className="crmThread is-inline">
        <header className="crmThreadHead">
          <div><b>{row.label}</b><small>{row.sub}</small></div>
          <span className={windowOpen(conv.service_window_expires_at) ? "crmWindow is-open" : "crmWindow"}>{windowOpen(conv.service_window_expires_at) ? "Janela de 24h aberta" : "Fora da janela de 24h"}</span>
        </header>
        {loadingThread ? <p className="crmThreadNote">Carregando…</p> : null}
        <ol className="crmMessages">{thread.map((m) => <li key={m.id} className={`crmMsg is-${m.direction}${m.failed ? " is-failed" : ""}`}>
          <p>{m.text || (m.template_name ? `Modelo: ${m.template_name}` : `[${m.type}]`)}</p>
          <small>{when(m.at)}{m.direction === "outbound" && m.read_at ? " · lida" : ""}{m.failed ? " · falhou" : ""}</small>
        </li>)}</ol>
        {!loadingThread && !thread.length ? <p className="crmThreadNote">Sem mensagens nesta conversa.</p> : null}
      </div> : null}
    </li>;
  };

  return <section className="crmConversations">
    <div className="crmSectionHead"><h3>Conversas no WhatsApp</h3>
      <button type="button" className="studioLink" onClick={() => void load()} disabled={loading}>Atualizar</button></div>
    <p className="libHint">Lidas do CRM Mugô. Só a Mugô vê esta parte. Para responder, use o CRM.</p>
    {error ? <p role="alert" className="studioError">{error}</p> : null}
    {unavailable ? <p className="studioEmpty">{CRM_UNAVAILABLE_TEXT[unavailable]}</p> : null}
    {loading && !conversations.length ? <p>Carregando conversas…</p> : null}
    {!unavailable && !loading ? <ul className="crmContactList">{rows.map(renderRow)}</ul> : null}
    {!unavailable && others.length ? <>
      <h4 className="crmSubhead">Outros contatos deste cliente no CRM</h4>
      <ul className="crmContactList">{others.map(renderRow)}</ul>
    </> : null}
  </section>;
}
