import { http } from "./api";

export type AiActionKind = "campanha_reativacao" | "ligar_fluxo" | "ligar_carrinho" | "alerta_cac";
export type AiActionStatus = "proposta" | "executada" | "rejeitada" | "falhou" | "expirada" | "ciente";
export type AiAction = {
  id: string; kind: AiActionKind; title: string; rationale: string; evidence: Record<string, number | null>; payload: Record<string, unknown>;
  status: AiActionStatus; proposed_at: string; decided_at: string | null; executed_at: string | null; result: Record<string, unknown>; error: string | null;
  measurement?: { sent?: number; buyers?: number; revenue?: number; open_rate?: number | null; click_rate?: number | null } | null;
};

export const listAiActions = () => http<{ actions: AiAction[] }>("/api/ai-actions", { timeoutMs: 60_000 });
export const generateAiActions = () => http<{ created: number; actions: AiAction[] }>("/api/ai-actions/generate", { method: "POST", timeoutMs: 120_000 });
export const decideAiAction = (id: string, decision: "aprovar" | "rejeitar") =>
  http<{ action: AiAction }>(`/api/ai-actions/${encodeURIComponent(id)}/decide`, {
    method: "POST", body: JSON.stringify({ decision }), headers: { "Content-Type": "application/json" }, timeoutMs: 60_000,
  });

export const ACTION_LABEL: Record<AiActionKind, { tag: string; does: string }> = {
  campanha_reativacao: { tag: "Campanha", does: "Aprovar cria a campanha de e-mail e coloca na fila de envio." },
  ligar_fluxo: { tag: "Fluxo", does: "Aprovar liga o fluxo automático de segunda compra por e-mail." },
  ligar_carrinho: { tag: "Carrinho", does: "Aprovar liga o aviso de checkout na Shopify e a sequência de e-mails do carrinho." },
  alerta_cac: { tag: "Alerta", does: "Só informa. Aprovar marca como ciente." },
};
export const ACTION_STATUS: Record<AiActionStatus, string> = {
  proposta: "Aguardando aprovação", executada: "Executada", rejeitada: "Rejeitada", falhou: "Falhou", expirada: "Expirada", ciente: "Ciente",
};
