import { useCallback, useEffect, useState } from "react";
import { getActiveClientId } from "../../app/activeClient";
import {
  getTaskWhatsAppPreference, listTaskNotifications, markTaskNotificationRead,
  setTaskWhatsAppPreference, type TaskAssignmentMessage,
} from "../../app/crm";
import "./taskAssignmentInbox.css";

/** Private assignment messages: never mixes with public/client Studio conversations. */
export default function TaskAssignmentInbox() {
  const clientId = getActiveClientId();
  const [messages, setMessages] = useState<TaskAssignmentMessage[]>([]);
  const [unread, setUnread] = useState(0);
  const [optIn, setOptIn] = useState(false);
  const [providerConfigured, setProviderConfigured] = useState(false);
  const [open, setOpen] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [busy, setBusy] = useState(false);
  const refresh = useCallback(async () => {
    try {
      const [notifications, preferences] = await Promise.all([listTaskNotifications(), getTaskWhatsAppPreference()]);
      if (getActiveClientId() !== clientId) return;
      setMessages(notifications.messages);
      setUnread(notifications.unread);
      setOptIn(preferences.whatsapp_opt_in);
      setProviderConfigured(preferences.provider_configured);
      setError(null);
    } catch (cause) {
      if (getActiveClientId() === clientId) setError(cause instanceof Error ? cause.message : "Não foi possível carregar seus avisos.");
    }
  }, [clientId]);
  useEffect(() => {
    void refresh();
    const timer = window.setInterval(() => void refresh(), 30_000);
    return () => window.clearInterval(timer);
  }, [refresh]);

  async function toggle(value: boolean) {
    if (busy) return;
    setBusy(true); setError(null);
    try {
      const updated = await setTaskWhatsAppPreference(value);
      setOptIn(updated.whatsapp_opt_in);
    } catch (cause) {
      setError(cause instanceof Error ? cause.message : "Não foi possível atualizar os avisos.");
    } finally { setBusy(false); }
  }

  async function view(message: TaskAssignmentMessage) {
    if (!message.read_at) {
      try {
        await markTaskNotificationRead(message.id);
        setMessages((items) => items.map((item) => item.id === message.id
          ? { ...item, read_at: new Date().toISOString() } : item));
        setUnread((count) => Math.max(0, count - 1));
      } catch { /* still allow navigation if marking read fails */ }
    }
    const sameOrigin = new URL(message.task_url, window.location.origin);
    if (sameOrigin.origin === window.location.origin && sameOrigin.pathname === "/tarefas") {
      window.location.assign(sameOrigin.pathname + sameOrigin.search);
    } else {
      window.location.assign("/tarefas?task=" + encodeURIComponent(message.task_id));
    }
  }

  return <section className="taskAssignmentInbox" aria-label="Mensagens pessoais de tarefas">
    <div className="taskAssignmentInboxHeading">
      <div>
        <h2>Meu chat de tarefas {unread ? <span className="taskAssignmentUnread">{unread} novas</span> : null}</h2>
        <p>Quando alguém atribuir uma tarefa a você, o aviso aparecerá aqui, com orientações e prazo.</p>
      </div>
      <div className="taskAssignmentInboxActions">
        <button className="ds-button" type="button" onClick={() => setOpen((current) => !current)}>
          {open ? "Fechar mensagens" : "Abrir mensagens"}
        </button>
        <button className="ds-button" type="button" onClick={() => void refresh()}>Atualizar</button>
      </div>
    </div>
    {error ? <p className="studioError" role="alert">{error}</p> : null}
    {open ? <>
      <div className="taskAssignmentWhatsApp">
        <label><input type="checkbox" checked={optIn} disabled={busy || !providerConfigured}
          onChange={(event) => void toggle(event.target.checked)} />
          Receber novas atribuições também pelo WhatsApp</label>
        <small>{providerConfigured
          ? "Disponível apenas para telefone confirmado na sua conta. O modelo de mensagem precisa estar aprovado pela Meta."
          : "WhatsApp aguardando configuração de número e template aprovado. Os avisos no Mugô Dados já funcionam."}</small>
      </div>
      {messages.length ? <div className="taskAssignmentMessages">{messages.map((message) => <article key={message.id}
        className={message.read_at ? "is-read" : "is-unread"}>
        <div className="taskAssignmentMessageTop">
          <strong>{message.title}</strong>
          <span>{new Date(message.created_at).toLocaleString("pt-BR", { day: "2-digit", month: "2-digit", hour: "2-digit", minute: "2-digit" })}</span>
        </div>
        <p>{message.body}</p>
        <div className="taskAssignmentMessageActions">
          <button type="button" className="ds-button" onClick={() => void view(message)}>Abrir tarefa</button>
          <small>{message.whatsapp_status === "sent" ? "WhatsApp enviado"
            : message.whatsapp_status === "failed" ? "Falha no WhatsApp — aviso disponível aqui"
            : message.whatsapp_status === "skipped_demo" ? "WhatsApp desativado na demonstração"
            : "Aviso interno entregue"}</small>
        </div>
      </article>)}</div> : <p className="ds-caption">Você ainda não recebeu tarefas por aqui.</p>}
    </> : null}
  </section>;
}
