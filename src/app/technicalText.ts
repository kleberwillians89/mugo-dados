/**
 * Segunda barreira contra identificadores técnicos no texto da IA.
 *
 * O backend já limpa (server/services/technical_text.py). Aqui a mesma regra
 * roda sobre tudo que chega da API, para que nenhum "metric_ids: orders"
 * apareça na tela mesmo que um registro antigo ou um caminho novo escape.
 * Campos estruturados (metric_ids, sources) não são alterados.
 */
import type {
  IntelligenceAnalysisContent,
  IntelligenceAnalysisRecord,
  IntelligenceAnswer,
  IntelligenceMessage,
} from "./intelligenceTypes";

export const DEFAULT_TECHNICAL_LABELS: Record<string, string> = {
  revenue: "Faturamento",
  investment: "Investimento",
  meta_investment: "Investimento Meta",
  google_ads_investment: "Investimento Google Ads",
  roas: "ROAS",
  cpa: "CPA",
  orders: "Pedidos",
  average_ticket: "Ticket médio",
  conversion_rate: "Taxa de conversão",
  new_customers: "Novos clientes",
  repeat_customers: "Clientes recorrentes",
  sessions: "Sessões",
  followers_growth: "Crescimento de seguidores",
  instagram_profile_views: "Visitas ao perfil",
  spend: "Investimento",
  clicks: "Cliques",
  impressions: "Impressões",
  conversions: "Conversões",
  reach: "Alcance",
  meta_ads: "Meta Ads",
  instagram: "Instagram",
  instagram_content: "Instagram · publicações",
  ga4: "Google Analytics 4",
  google_ads: "Google Ads",
  shopify: "Shopify",
  fbits: "FBITS",
  fbits_official: "FBITS · indicadores oficiais",
  paid_media: "mídia paga",
  commerce: "loja",
};

type Labeled = { id?: unknown; label?: unknown };

const KEY = String.raw`(?:metric_ids?|metricids?|source_ids?|sources?|evidence_ids?)`;
const ID = String.raw`[A-Za-z][A-Za-z0-9_+\-]*(?:\.[A-Za-z0-9_]+)*`;
const ID_LIST = String.raw`${ID}(?:\s*[,/]\s*${ID})*`;
const BRACKETED = new RegExp(String.raw`\s*[\(\[]\s*\x60?${KEY}\x60?\s*[:=]\s*\x60?\[?\s*${ID_LIST}\s*\]?\x60?\s*[\)\]]`, "gi");
const INLINE = new RegExp(String.raw`\x60?${KEY}\x60?\s*[:=]\s*\x60?\[?\s*(${ID_LIST})\s*\]?\x60?`, "gi");

const escapeRegExp = (value: string) => value.replace(/[.*+?^${}()|[\]\\]/g, "\\$&");

export function buildTechnicalLabels(metrics?: Labeled[] | null, sources?: Labeled[] | null): Record<string, string> {
  const labels: Record<string, string> = { ...DEFAULT_TECHNICAL_LABELS };
  for (const row of [...(sources || []), ...(metrics || [])]) {
    const id = String(row?.id ?? "").trim();
    const label = String(row?.label ?? "").trim();
    if (id && label) labels[id] = label;
  }
  return labels;
}

function labelList(raw: string, labels: Record<string, string>): string {
  const names: string[] = [];
  for (const piece of raw.replace(/[[\]`]/g, "").split(/\s*[,/]\s*/)) {
    const token = piece.trim().replace(/^['"]|['"]$/g, "");
    if (!token) continue;
    const label = labels[token] || labels[token.toLowerCase()] || (token.includes("_") ? "" : token);
    if (label && !names.includes(label)) names.push(label);
  }
  return names.join(", ");
}

export function humanizeTechnicalText<T>(text: T, labels: Record<string, string>): T {
  if (typeof text !== "string" || !text) return text;
  let out: string = text.replace(BRACKETED, "");
  out = out.replace(INLINE, (_match, ids: string) => labelList(ids, labels));
  const keys = Object.keys(labels).filter((key) => key.includes("_")).sort((a, b) => b.length - a.length);
  for (const key of keys) {
    if (!out.includes(key)) continue;
    out = out.replace(new RegExp(String.raw`\x60?(?<![\w])${escapeRegExp(key)}(?![\w])\x60?`, "g"), labels[key]);
  }
  out = out.replace(/\(\s*\)|\[\s*\]/g, "").replace(/\s+([,.;:!?])/g, "$1").replace(/[ \t]{2,}/g, " ").trim();
  return out as T;
}

export function humanizeAnalysisContent(
  content: IntelligenceAnalysisContent | null | undefined,
  labels: Record<string, string>,
): IntelligenceAnalysisContent | null | undefined {
  if (!content) return content;
  const clean = <T,>(value: T) => humanizeTechnicalText(value, labels);
  const executive = content.executive
    ? (Object.fromEntries(Object.entries(content.executive).map(([key, value]) => [key, clean(value)])) as IntelligenceAnalysisContent["executive"])
    : content.executive;
  return {
    ...content,
    executive,
    insights: (content.insights || []).map((insight) => ({
      ...insight,
      title: clean(insight.title),
      interpretation: clean(insight.interpretation),
      action: clean(insight.action),
      reason: clean(insight.reason),
    })),
    actions: (content.actions || []).map((action) => ({
      ...action,
      recommendation: clean(action.recommendation),
      justification: clean(action.justification),
      impact_expected: clean(action.impact_expected),
    })),
  };
}

export function humanizeAnalysisRecord<T extends IntelligenceAnalysisRecord | null | undefined>(record: T): T {
  if (!record || !record.analysis) return record;
  const labels = buildTechnicalLabels(record.metrics_snapshot, record.sources);
  return { ...record, analysis: humanizeAnalysisContent(record.analysis, labels) } as T;
}

const ANSWER_LIST_FIELDS = ["evidence", "attention_points", "recommendations", "next_steps"] as const;

export function humanizeMessage(message: IntelligenceMessage, labels?: Record<string, string>): IntelligenceMessage {
  if (message.role !== "assistant" || !message.content) return message;
  const resolved = labels || buildTechnicalLabels(null, (message as { sources?: Labeled[] }).sources);
  const content: IntelligenceMessage["content"] = { ...message.content };
  if (typeof content.direct_answer === "string") content.direct_answer = humanizeTechnicalText(content.direct_answer, resolved);
  for (const field of ANSWER_LIST_FIELDS) {
    const values = content[field] as IntelligenceAnswer[typeof field] | undefined;
    if (Array.isArray(values)) content[field] = values.map((item) => humanizeTechnicalText(item, resolved));
  }
  return { ...message, content };
}
