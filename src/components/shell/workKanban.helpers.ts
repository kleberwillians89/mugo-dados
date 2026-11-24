import type { AppRoute } from "../../app/routes";

/**
 * Telas dos quatro processos (Planejar, Criar conteúdo, Lançar campanha, Analisar resultados) e das ferramentas
 * abertas a partir deles. Fora daqui (Início, Tarefas, Aprovações, Configurações, páginas públicas) o Kanban não aparece.
 */
export const KANBAN_ROUTES: ReadonlySet<AppRoute> = new Set<AppRoute>([
  "process_planning", "process_content", "process_campaign", "process_analysis",
  "radar", "benchmark", "planning", "goals", "campaigns", "calendar",
  "redacao", "production", "briefing", "creators", "email_marketing", "capture",
  "media",
  "brand_health", "meta", "google", "channels", "origins", "ecommerce", "customers", "clipping", "social_report", "whatsapp", "engagement",
]);

export type KanbanCounts = { progress: number; approval: number; late: number };

// A faixa aparece em muitas telas: guarda as pendências por 30 s para não buscar a cada troca de tela.
const CACHE_MS = 30_000;
let cache: { key: string; at: number; counts: KanbanCounts } | null = null;
export const kanbanCache = {
  get: (key: string): KanbanCounts | null => (cache && cache.key === key && Date.now() - cache.at < CACHE_MS ? cache.counts : null),
  set: (key: string, counts: KanbanCounts) => { cache = { key, at: Date.now(), counts }; },
  clear: () => { cache = null; },
};

/** Pede ao quadro aberto para mostrar uma tarefa (o quadro só abre tarefas que ele mesmo carregou: escopo preservado). */
export const OPEN_TASK_EVENT = "mugo:open-task";
