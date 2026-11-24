import { http, clientClientPath } from "./api";

/** Contexto da Marca: saúde (regras fixas, sem IA) e aprender com o uso (IA só no clique; grava só o aprovado). */
export type HealthLevel = "ok" | "atencao" | "falta";
export type HealthItem = { id: string; level: HealthLevel; title: string; detail: string; action: { tab?: string; route?: string } | null };
export type LearningStatus = { since: string | null; last_learning_at: string | null; new_signals: number };
export type ContextHealth = { ok: true; score: number; items: HealthItem[]; learning: LearningStatus };

export type LearningSource = "ajuste" | "comentario" | "reescrita" | "aprovacao" | "whatsapp" | "criadores" | "equipe" | "resultados";
export type SuggestedFact = { fato: string; origem: LearningSource; origem_rotulo: string; evidencia: string; confianca: "alta" | "media" };
export type LearningSuggestion = { ok: true; facts: SuggestedFact[]; signals: number; since: string | null; message: string | null };

const base = (path: string) => clientClientPath(`/studio/knowledge${path}`);

export function getContextHealth() {
  return http<ContextHealth>(base("/health"));
}
export function suggestLearning() {
  return http<LearningSuggestion>(base("/learn/suggest"), { method: "POST", timeoutMs: 150_000 });
}
export function confirmLearning(facts: string[]) {
  return http<{ ok: true; saved: number; knowledge: string | null; sources: number | null }>(base("/learn/confirm"),
    { method: "POST", body: JSON.stringify({ facts }) });
}
