import { http, clientClientPath } from "./api";
import type { GuardIssue } from "./studio";

/** Engajamento no Instagram (tipo ManyChat) — só a equipe Mugô. */
const base = (path: string) => clientClientPath(`/studio/engagement${path}`);

export type EngagementAction = { comment_id: string; kind: "resposta_publica" | "direct" | "resposta_manual"; status: "enviado" | "simulado" | "falhou"; text: string; actor: string | null; created_at: string; rule_id: string | null };
export type InboxComment = {
  comment_id: string; media_id: string; username: string; text: string; like_count: number | null; timestamp: string;
  answered: boolean; direct_open: boolean; actions: EngagementAction[];
  media: { permalink: string | null; caption: string; thumb: string | null } | null;
};
export type EngagementRule = { id: string; name: string; keywords: string[]; media_id: string | null; public_reply: string | null; dm_message: string | null; active: boolean };
export type RuleInput = Omit<EngagementRule, "id">;

export const getInbox = (openOnly: boolean) => http<{ items: InboxComment[]; autoreply_enabled: boolean }>(base(`/comments?open_only=${openOnly}`));
export const refreshInbox = () => http<{ comments: number; can: { reply: boolean; direct: boolean } }>(base("/refresh"), { method: "POST", timeoutMs: 90_000 });
export const suggestReply = (commentId: string) =>
  http<{ reply: string; needs_human: boolean; reason: string; guard: GuardIssue[] }>(base(`/comments/${encodeURIComponent(commentId)}/suggest`), { method: "POST", timeoutMs: 60_000 });
export const sendReply = (commentId: string, text: string, direct: boolean) =>
  http<{ status: string }>(base(`/comments/${encodeURIComponent(commentId)}/reply`), { method: "POST", body: JSON.stringify({ text, direct }) });
export const listRules = () => http<{ rules: EngagementRule[]; autoreply_enabled: boolean }>(base("/rules"));
export const saveRule = (input: RuleInput, id?: string) =>
  http<{ rule: EngagementRule }>(base(`/rules${id ? `/${encodeURIComponent(id)}` : ""}`), { method: id ? "PUT" : "POST", body: JSON.stringify(input) });
export const deleteRule = (id: string) => http<{ ok: true }>(base(`/rules/${encodeURIComponent(id)}`), { method: "DELETE" });
export const runRules = () => http<{ sent: number; simulated: number; failed: number; live: boolean }>(base("/rules/run"), { method: "POST", timeoutMs: 120_000 });
