import { http, clientClientPath } from "./api";

/** Leitura do CRM Mugô (fonte da verdade) — só agência. Nada é copiado para o Dados. */
export type CrmUnavailable = { available: false; reason: "not_configured" | "not_linked" | "auth_failed" };

export const CRM_UNAVAILABLE_TEXT: Record<CrmUnavailable["reason"], string> = {
  not_configured: "A ligação com o CRM ainda não foi configurada no servidor do Dados.",
  not_linked: "Esta empresa ainda não está ligada a um cliente do CRM.",
  auth_failed: "O CRM recusou a chave de acesso. Confira a chave nos dois lados.",
};

export const TASK_STATUS = { pending: "Pendente", in_progress: "Em andamento", completed: "Concluída", cancelled: "Cancelada" } as const;
export type TaskStatus = keyof typeof TASK_STATUS;
export const TASK_PRIORITY: Record<string, string> = { low: "Baixa", medium: "Média", high: "Alta", urgent: "Urgente" };

export type CrmTask = {
  id: string; title: string; status: TaskStatus; priority: string | null; due_date: string | null; due_time: string | null;
  starts_at: string | null; category: string | null; task_type: string | null; tags: string[]; notes: string | null;
  updated_at: string | null; assignee: { name: string; color: string | null } | null;
};
export type CrmConversation = {
  id: string; status: string | null; attendance_mode: string | null; unread_count: number | null; last_message_at: string | null;
  service_window_expires_at: string | null; contact: { name: string | null; phone_masked: string };
  last_message: { direction: "inbound" | "outbound"; at: string; text: string } | null;
};
export type CrmMessage = {
  id: string; direction: "inbound" | "outbound"; type: string; status: string | null; text: string | null;
  template_name: string | null; at: string; read_at: string | null; failed: boolean; error_code: string | null;
};

type Result<T> = ({ available: true } & T) | CrmUnavailable;
const base = (path: string) => clientClientPath(`/crm${path}`);

export function listCrmTasks(status?: TaskStatus) {
  return http<Result<{ tasks: CrmTask[] }>>(base(`/tasks${status ? `?status=${status}` : ""}`));
}
export function listCrmConversations() {
  return http<Result<{ conversations: CrmConversation[] }>>(base("/conversations"));
}
export function listCrmMessages(conversationId: string) {
  return http<Result<{ messages: CrmMessage[] }>>(base(`/conversations/${encodeURIComponent(conversationId)}/messages`));
}

/** Data de vencimento → rótulo e se está atrasada (comparação por dia local). */
export function dueInfo(due: string | null, today = new Date()): { label: string; late: boolean } {
  if (!due) return { label: "Sem prazo", late: false };
  const [y, m, d] = due.slice(0, 10).split("-").map(Number);
  const date = new Date(y, m - 1, d);
  const start = new Date(today.getFullYear(), today.getMonth(), today.getDate());
  const diff = Math.round((date.getTime() - start.getTime()) / 86400000);
  const label = diff === 0 ? "Hoje" : diff === 1 ? "Amanhã" : diff === -1 ? "Ontem"
    : date.toLocaleDateString("pt-BR", { day: "2-digit", month: "short" });
  return { label, late: diff < 0 };
}

export function windowOpen(expiresAt: string | null, now = new Date()) {
  return !!expiresAt && new Date(expiresAt).getTime() > now.getTime();
}
