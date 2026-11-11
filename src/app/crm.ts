import { http, clientClientPath } from "./api";

/** Leitura do CRM Mugô (fonte da verdade) — só agência. Nada é copiado para o Dados. */
export type CrmUnavailable = { available: false; reason: "not_configured" | "not_linked" | "auth_failed" | "function_missing" | "migration_pending" };

export const CRM_UNAVAILABLE_TEXT: Record<CrmUnavailable["reason"], string> = {
  not_configured: "A ligação com o CRM ainda não foi configurada no servidor do Dados.",
  not_linked: "Esta empresa ainda não está ligada a um cliente do CRM.",
  auth_failed: "O CRM recusou a chave de acesso. Confira a chave nos dois lados.",
  function_missing: "A ponte do CRM ainda não foi publicada (ou está desatualizada). Rode o deploy da dados-ops-api no CRM.",
  migration_pending: "As tarefas ainda não foram ativadas no banco (falta a migração 000089).",
};

export const TASK_STATUS = {
  pending: "Pendente", in_progress: "Em produção", internal_review: "Aprovação interna", client_review: "Aprovação do cliente",
  changes: "Ajustes", completed: "Aprovada / concluída", cancelled: "Cancelada",
} as const;
export type TaskStatus = keyof typeof TASK_STATUS;
export const TASK_PRIORITY: Record<string, string> = { low: "Baixa", medium: "Média", high: "Alta", urgent: "Urgente" };

export type CrmTask = {
  id: string; title: string; status: TaskStatus; priority: string | null; due_date: string | null; due_time: string | null;
  starts_at: string | null; category: string | null; task_type: string | null; tags: string[]; notes: string | null;
  updated_at: string | null; assignee: { name: string; color: string | null } | null;
  /** Tarefas do Mugoverso: aparece também para o cliente. */
  visible_to_client?: boolean;
  /** Link da entrega (Drive, Canva, Figma…) que vai para aprovação. */
  deliverable_url?: string | null;
  needs_client_approval?: boolean;
  approval_round?: number;
  approved_at?: string | null;
};
export type CrmConversation = {
  id: string; status: string | null; attendance_mode: string | null; unread_count: number | null; last_message_at: string | null;
  service_window_expires_at: string | null; contact: { name: string | null; phone_masked: string; matched_phone: string | null };
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
/** Tarefas guardadas no Mugoverso (criar, editar, mover de etapa, excluir). */
export type TaskInput = Partial<{ title: string; notes: string | null; status: TaskStatus; priority: string | null; due_date: string | null;
  due_time: string | null; category: string | null; assignee_name: string | null; visible_to_client: boolean ; needs_client_approval: boolean; deliverable_url: string | null}>;
export function createTask(input: TaskInput) {
  return http<{ task: CrmTask }>(base("/tasks"), { method: "POST", body: JSON.stringify(input) });
}
export function updateTask(id: string, input: TaskInput) {
  return http<{ task: CrmTask }>(base(`/tasks/${encodeURIComponent(id)}`), { method: "PATCH", body: JSON.stringify(input) });
}
export function deleteTask(id: string) {
  return http<{ ok: true }>(base(`/tasks/${encodeURIComponent(id)}`), { method: "DELETE" });
}
/** Tarefas que a Mugô marcou com a etiqueta "cliente" no CRM — visíveis a qualquer membro da empresa. */
export type ClientTask = { id: string; title: string; status: TaskStatus; due_date: string | null; updated_at: string | null };
export function listClientTasks() {
  return http<Result<{ tasks: ClientTask[] }>>(base("/client-tasks"));
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

/** Mesma pessoa com ou sem o 9º dígito do celular BR. */
export function samePhone(a: string | null | undefined, b: string | null | undefined) {
  const norm = (v: string | null | undefined) => {
    const d = String(v || "").replace(/\D/g, "");
    return d.startsWith("55") && d.length === 13 && d[4] === "9" ? d.slice(0, 4) + d.slice(5) : d;
  };
  return !!a && !!b && norm(a) === norm(b);
}

export function windowOpen(expiresAt: string | null, now = new Date()) {
  return !!expiresAt && new Date(expiresAt).getTime() > now.getTime();
}


/** Aprovação de tarefa (fluxo do iAgência): interna (equipe Mugô) e do cliente. */
export type TaskAction = "submit" | "internal_approve" | "internal_changes" | "client_approve" | "client_changes" | "comment";
export type TaskEvent = { id: string; kind: "enviado_interno" | "aprovado_interno" | "ajuste_interno" | "enviado_cliente" | "aprovado_cliente" | "ajuste_cliente" | "comentario";
  internal: boolean; comment: string | null; actor_name: string | null; actor_side: "mugo" | "cliente"; created_at: string };
export const TASK_EVENT: Record<TaskEvent["kind"], string> = {
  enviado_interno: "Enviou para aprovação interna", aprovado_interno: "Aprovou internamente", ajuste_interno: "Pediu ajuste (interno)",
  enviado_cliente: "Enviada para o cliente aprovar", aprovado_cliente: "Cliente aprovou", ajuste_cliente: "Cliente pediu ajuste", comentario: "Comentou",
};
export function taskApproval(id: string, action: TaskAction, comment?: string, internal = false) {
  return http<{ task: CrmTask; events: TaskEvent[] }>(base(`/tasks/${encodeURIComponent(id)}/approval`), { method: "POST", body: JSON.stringify({ action, comment: comment || null, internal }) });
}
export function taskHistory(id: string) {
  return http<{ events: TaskEvent[] }>(base(`/tasks/${encodeURIComponent(id)}/history`));
}
