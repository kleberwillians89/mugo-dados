import { useEffect, useRef, useState, type FormEvent } from "react";
import { createIntelligenceConversation, deleteIntelligenceConversation, getIntelligenceConversations,
  getIntelligenceMessages, renameIntelligenceConversation, resumeIntelligenceConversation } from "../../app/api";
import type { IntelligenceConversation, IntelligenceMessage } from "../../app/intelligenceTypes";
import "../../styles/intelligence-conversations.css";

type Props = {
  clientId: string; userId: string | null; activeId: string | null; revision: string; busy: boolean;
  onRestore: (id: string, messages: IntelligenceMessage[]) => void;
  onLoadingChange: (busy: boolean) => void;
};
export default function ConversationHistory({ clientId, userId, activeId, revision, busy, onRestore, onLoadingChange }: Props) {
  const [items, setItems] = useState<IntelligenceConversation[]>([]);
  const [more, setMore] = useState(false);
  const [loading, setLoading] = useState(Boolean(userId));
  const [error, setError] = useState("");
  const [editing, setEditing] = useState<string | null>(null);
  const [title, setTitle] = useState("");
  const [deleting, setDeleting] = useState<string | null>(null);
  const request = useRef<AbortController | null>(null);
  const initialized = useRef(false);
  const active = useRef(activeId);
  useEffect(() => { active.current = activeId; }, [activeId]);
  const owned = (item: IntelligenceConversation) => item.client_id === clientId && item.user_id === userId;

  useEffect(() => {
    if (!userId || !clientId) return;
    const controller = new AbortController(); request.current = controller;
    queueMicrotask(async () => {
      if (controller.signal.aborted) return;
      setLoading(true); setError(""); onLoadingChange(true);
      try {
        const result = await getIntelligenceConversations(0, { signal: controller.signal });
        if (controller.signal.aborted) return;
        if (result.items.some(item => item.client_id !== clientId || item.user_id !== userId)) throw new Error("OWNER_MISMATCH");
        setItems(result.items); setMore(result.has_more);
        if (!initialized.current && !active.current && result.items[0]) {
          const response = await getIntelligenceMessages(result.items[0].id, { signal: controller.signal });
          if (controller.signal.aborted) return;
          if (response.conversation.client_id !== clientId || response.conversation.user_id !== userId || response.conversation.id !== result.items[0].id) throw new Error("OWNER_MISMATCH");
          onRestore(response.conversation.id, response.messages);
        }
        initialized.current = true;
      } catch {
        if (!controller.signal.aborted) setError("Não foi possível recuperar seu histórico. Tente novamente selecionando uma conversa ou recarregando a página.");
      } finally {
        if (request.current === controller) { request.current = null; setLoading(false); onLoadingChange(false); }
      }
    });
    return () => { controller.abort(); };
  }, [clientId, userId, revision, onRestore, onLoadingChange]);

  useEffect(() => () => { request.current?.abort(); }, []);

  async function perform(work: (controller: AbortController) => Promise<void>) {
    if (busy || request.current || !userId) return;
    const controller = new AbortController(); request.current = controller;
    initialized.current = true;
    setLoading(true); setError(""); onLoadingChange(true);
    try { await work(controller); }
    catch { if (!controller.signal.aborted) setError("Não foi possível concluir esta ação. Sua conversa exibida foi preservada."); }
    finally { if (request.current === controller) { request.current = null; setLoading(false); onLoadingChange(false); } }
  }
  async function choose(item: IntelligenceConversation, controller: AbortController) {
    if (!owned(item)) throw new Error("OWNER_MISMATCH");
    const response = await getIntelligenceMessages(item.id, { signal: controller.signal });
    if (controller.signal.aborted) return;
    if (!owned(response.conversation) || response.conversation.id !== item.id) throw new Error("OWNER_MISMATCH");
    await resumeIntelligenceConversation(item.id, { signal: controller.signal });
    if (!controller.signal.aborted) onRestore(item.id, response.messages);
  }
  function rename(event: FormEvent, item: IntelligenceConversation) {
    event.preventDefault();
    void perform(async controller => {
      if (!owned(item)) throw new Error("OWNER_MISMATCH");
      const response = await renameIntelligenceConversation(item.id, title.trim(), { signal: controller.signal });
      if (controller.signal.aborted) return;
      if (!owned(response.conversation) || response.conversation.id !== item.id) throw new Error("OWNER_MISMATCH");
      setItems(current => current.map(row => row.id === item.id ? response.conversation : row)); setEditing(null);
    });
  }
  return <section className="intelConversationHistory" aria-label="Suas conversas">
    <header><h3>Suas conversas</h3><button className="btn" type="button" disabled={busy || loading || !userId} onClick={() => void perform(async controller => {
      const response = await createIntelligenceConversation({ signal: controller.signal });
      if (controller.signal.aborted) return;
      if (!owned(response.conversation)) throw new Error("OWNER_MISMATCH");
      setItems(current => [response.conversation, ...current].slice(0, 200)); onRestore(response.conversation.id, []);
    })}>Nova conversa</button></header>
    {loading ? <p role="status">Recuperando seu histórico…</p> : null}
    {error ? <p role="alert">{error}</p> : null}
    <details><summary>Conversas anteriores</summary>
      <p>Histórico privado desta empresa e do seu usuário. Até 200 conversas nesta lista e as últimas 100 mensagens por conversa; registros anteriores continuam no backend.</p>
      {!items.length && !loading ? <p>Nenhuma conversa salva.</p> : null}
      <ul>{items.map(item => <li key={item.id}>
        <button type="button" className={activeId === item.id ? "isActive" : ""} disabled={loading || busy} aria-current={activeId === item.id ? "true" : undefined} onClick={() => void perform(controller => choose(item, controller))}>{item.title}</button>
        <span><button type="button" disabled={loading || busy} onClick={() => { setEditing(item.id); setTitle(item.title); }}>Renomear</button><button type="button" disabled={loading || busy} onClick={() => setDeleting(item.id)}>Excluir</button></span>
        {editing === item.id ? <form onSubmit={event => rename(event, item)}><label>Título<input value={title} onChange={event => setTitle(event.target.value)} maxLength={120} required disabled={loading || busy} /></label><button disabled={loading || busy || !title.trim()}>Salvar título</button><button type="button" onClick={() => setEditing(null)}>Cancelar</button></form> : null}
        {deleting === item.id ? <div role="alert"><p>Excluir esta conversa e todas as mensagens salvas? Esta ação não altera dados das integrações.</p><button type="button" disabled={loading || busy} onClick={() => void perform(async controller => {
          if (!owned(item)) throw new Error("OWNER_MISMATCH");
          await deleteIntelligenceConversation(item.id, { signal: controller.signal });
          if (controller.signal.aborted) return;
          setItems(current => current.filter(row => row.id !== item.id)); setDeleting(null);
          if (activeId === item.id) onRestore("", []);
        })}>Confirmar exclusão</button><button type="button" onClick={() => setDeleting(null)}>Cancelar exclusão</button></div> : null}
      </li>)}</ul>
      {more && items.length < 200 ? <button className="btn" type="button" disabled={loading || busy} onClick={() => void perform(async controller => {
        const response = await getIntelligenceConversations(items.length, { signal: controller.signal });
        if (controller.signal.aborted) return;
        if (response.items.some(row => !owned(row))) throw new Error("OWNER_MISMATCH");
        setItems(current => [...current, ...response.items.filter(row => !current.some(old => old.id === row.id))].slice(0, 200)); setMore(response.has_more);
      })}>Carregar mais conversas</button> : null}
    </details>
  </section>;
}
