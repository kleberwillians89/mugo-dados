import { http } from "./api";
import type { AppRoute } from "./routes";

/** "A Mugô IA notou": alertas por regra fixa (o servidor calcula; a tela só mostra e encaminha). */
export type NoticeAction = { label: string; route?: AppRoute; kind?: "remind"; team_only?: boolean; request_id?: string; contact_id?: string | null };
export type MugoNotice = {
  id: string; client_id: string; client_name: string; kind: string; icon: string; message: string;
  level: number; urgency: number; actions: NoticeAction[]; since: string | null;
};
export type NoticesResult = { notices: MugoNotice[]; total: number; unavailable?: boolean };

export const listNotices = (limit = 3) => http<NoticesResult>(`/api/me/notices?limit=${limit}`);
export const dismissNotice = (id: string, completed = false) =>
  http<{ ok: true }>("/api/me/notices/dismiss", { method: "POST", body: JSON.stringify(completed ? { id, completed } : { id }) });
/** "Cobrar o cliente no WhatsApp": o mesmo lembrete de aprovação do Calendário, na empresa do alerta. */
export const remindClient = (clientId: string, requestId: string, contactId?: string | null) =>
  http<{ ok?: boolean }>(`/api/clients/${encodeURIComponent(clientId)}/studio/messages/send`, {
    method: "POST", timeoutMs: 60_000,
    body: JSON.stringify({ kind: "lembrete", request_id: requestId, ...(contactId ? { contact_id: contactId } : {}) }),
  });
