/**
 * Seleção do que merece atenção primeiro, a partir da análise que já existe.
 *
 * Nada aqui inventa precisão: a ordenação é **qualitativa** e usa só sinais
 * que o backend já produziu — impacto, confiança, categoria, evidência ligada
 * a métricas e possibilidade de ação. Não existe score numérico fingindo
 * exatidão, e nenhum texto novo é gerado: tudo vem dos campos da análise.
 *
 * Um item sem evidência (sem `metric_ids`) nunca é promovido a movimento
 * principal nem a oportunidade — é exatamente o que separa leitura aterrada
 * de frase genérica.
 */

import type {
  IntelligenceAnalysisContent,
  IntelligenceInsight,
  IntelligenceMetric,
} from "./intelligenceTypes";

export const MAX_MOVEMENTS = 3;
export const MAX_OPPORTUNITIES = 3;
export const MAX_IDEAS = 4;

const IMPACT_ORDER: Record<string, number> = { high: 3, medium: 2, low: 1 };
const CONFIDENCE_ORDER: Record<string, number> = { high: 3, medium: 2, low: 1 };

/**
 * Peso da categoria: risco e anomalia pedem decisão antes de uma leitura
 * positiva; qualidade de dado fica por último, porque é meta-informação.
 */
const CATEGORY_ORDER: Record<IntelligenceInsight["category"], number> = {
  risk: 5,
  anomaly: 4,
  attention: 4,
  opportunity: 3,
  positive: 2,
  data_quality: 1,
};

function hasEvidence(insight: IntelligenceInsight): boolean {
  return (insight.metric_ids || []).some((id) => String(id || "").trim());
}

function actionable(insight: IntelligenceInsight): boolean {
  return Boolean(String(insight.action || "").trim());
}

/** Métrica do período com variação conhecida conta como sinal recente. */
function recency(insight: IntelligenceInsight, metrics: Map<string, IntelligenceMetric>): number {
  return (insight.metric_ids || []).some((id) => {
    const metric = metrics.get(id);
    return metric?.variation_percent != null;
  })
    ? 1
    : 0;
}

export function rankInsights(
  insights: IntelligenceInsight[] | null | undefined,
  metrics: Map<string, IntelligenceMetric>
): IntelligenceInsight[] {
  return [...(insights || [])].sort((left, right) => {
    const signals = (insight: IntelligenceInsight) => [
      hasEvidence(insight) ? 1 : 0,
      CATEGORY_ORDER[insight.category] ?? 0,
      IMPACT_ORDER[insight.impact] ?? 0,
      CONFIDENCE_ORDER[insight.confidence] ?? 0,
      recency(insight, metrics),
      actionable(insight) ? 1 : 0,
    ];
    const leftSignals = signals(left);
    const rightSignals = signals(right);
    for (let index = 0; index < leftSignals.length; index += 1) {
      if (leftSignals[index] !== rightSignals[index]) return rightSignals[index] - leftSignals[index];
    }
    return 0;
  });
}

/** Até três movimentos, sempre com evidência. Menos de três é resposta válida. */
export function selectMovements(
  insights: IntelligenceInsight[] | null | undefined,
  metrics: Map<string, IntelligenceMetric>
): IntelligenceInsight[] {
  return rankInsights(insights, metrics)
    .filter(hasEvidence)
    .slice(0, MAX_MOVEMENTS);
}

/**
 * Oportunidades: só as aterradas em dado, e sem repetir o que já está em
 * destaque nos movimentos. Sem candidata aterrada, devolve lista vazia — a
 * seção não é preenchida por obrigação.
 */
export function selectOpportunities(
  insights: IntelligenceInsight[] | null | undefined,
  metrics: Map<string, IntelligenceMetric>,
  movements: IntelligenceInsight[] = []
): IntelligenceInsight[] {
  const shown = new Set(movements.map((insight) => insight.title));
  return rankInsights(insights, metrics)
    .filter((insight) => insight.category === "opportunity" && hasEvidence(insight) && !shown.has(insight.title))
    .slice(0, MAX_OPPORTUNITIES);
}

export type TestIdea = {
  title: string;
  whyNow: string;
  action: string;
  hypothesis: string;
  metricLabel: string;
  metricId: string;
};

const IDEA_ACTION_LABEL: Record<string, string> = {
  week: "Testar nesta semana",
  investigate: "Investigar antes de escalar",
  monitor: "Acompanhar antes de mudar",
  now: "Agir agora",
};

/**
 * Ideias para testar, derivadas das recomendações da própria análise.
 *
 * Nada é inventado: título, motivo e hipótese vêm dos campos que o modelo já
 * preencheu, e só entram recomendações ligadas a uma métrica existente. Ainda
 * não é tarefa, calendário nem publicação — é leitura para decidir.
 */
export function buildTestIdeas(
  analysis: IntelligenceAnalysisContent | null | undefined,
  metrics: Map<string, IntelligenceMetric>
): TestIdea[] {
  const ideas: TestIdea[] = [];
  const seen = new Set<string>();
  for (const action of analysis?.actions || []) {
    const metricId = String(action.metric_id || "").trim();
    const metric = metrics.get(metricId);
    const title = String(action.recommendation || "").trim();
    if (!title || !metric || seen.has(title)) continue;
    seen.add(title);
    ideas.push({
      title,
      whyNow: String(action.justification || "").trim(),
      action: IDEA_ACTION_LABEL[action.priority] || "Testar",
      // Resultado esperado é hipótese, nunca promessa.
      hypothesis: String(action.impact_expected || "").trim(),
      metricLabel: metric.label,
      metricId,
    });
    if (ideas.length >= MAX_IDEAS) break;
  }
  return ideas;
}

/**
 * Fontes para a nota discreta de procedência.
 *
 * Nome humano, sem id, tabela ou detalhe interno. O comércio aparece pelo
 * provider real do tenant, e um FBITS em fallback não é anunciado como
 * indicador oficial.
 */
/** Nome público da plataforma de vendas: sem "/Wake" nem detalhe interno. */
const COMMERCE_PUBLIC_LABEL: Record<string, string> = {
  fbits: "FBITS",
  shopify: "Shopify",
};

export function commercePublicLabel(provider: string | null | undefined): string | null {
  return COMMERCE_PUBLIC_LABEL[String(provider || "").toLowerCase()] || null;
}

export function describeSources(snapshot: {
  sources?: Array<{ id: string; label: string; status: string }>;
  commerce_context?: { provider?: string | null; official_kpis?: boolean } | null;
} | null | undefined): string[] {
  const commerceLabel = commercePublicLabel(snapshot?.commerce_context?.provider);
  return (snapshot?.sources || [])
    .filter((source) => ["available", "partial"].includes(source.status))
    .map((source) => (source.id === "commerce" && commerceLabel ? commerceLabel : source.label));
}
