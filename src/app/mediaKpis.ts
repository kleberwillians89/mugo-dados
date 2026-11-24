import type { DashboardDailyMetric } from "./DashboardDataContext";

/** Indicadores compactos da Mídia On, por plataforma, a partir do mesmo read model dos painéis Meta e Google. */
export type MediaPlatform = "meta" | "google";
export type MediaKpi = { key: string; label: string; value: string };
export type MediaKpiSummary = { available: boolean; daysWithData: number; kpis: MediaKpi[] };

const brl = (n: number) => n.toLocaleString("pt-BR", { style: "currency", currency: "BRL" });
const int = (n: number) => Math.round(n).toLocaleString("pt-BR");
const dec = (n: number, digits = 2) => n.toLocaleString("pt-BR", { minimumFractionDigits: digits, maximumFractionDigits: digits });

const FIELDS = {
  meta: { spend: "meta_spend", results: "meta_purchases", value: "meta_attributed_revenue", clicks: "meta_link_clicks", impressions: "meta_impressions" },
  google: { spend: "google_ads_spend", results: "google_ads_conversions", value: "google_ads_conversion_value", clicks: "google_ads_clicks", impressions: "google_ads_impressions" },
} as const;
const LABELS = {
  meta: { results: "Compras (pixel)", cost: "Custo por compra", value: "Receita atribuída", clicks: "Cliques no link", cpc: "Custo por clique no link", ctr: "CTR do link" },
  google: { results: "Conversões", cost: "Custo por conversão", value: "Valor de conversão", clicks: "Cliques", cpc: "Custo por clique", ctr: "CTR" },
} as const;

/**
 * Soma só o que é somável entre dias (gasto, resultados, valor, cliques, impressões) e calcula as razões no total.
 * Não soma alcance diário (pessoas se repetem entre dias) nem mistura Meta com Google.
 * Indicador sem base no período fica fora (nada de "R$ 0,00" inventado para custo por resultado sem resultado).
 */
export function mediaKpis(platform: MediaPlatform, rows: DashboardDailyMetric[]): MediaKpiSummary {
  const f = FIELDS[platform];
  const l = LABELS[platform];
  const withData = rows.filter((r) => r[f.spend] != null);
  const sum = (key: keyof DashboardDailyMetric) => withData.reduce((total, r) => total + (Number(r[key]) || 0), 0);
  const spend = sum(f.spend), results = sum(f.results), value = sum(f.value), clicks = sum(f.clicks), impressions = sum(f.impressions);
  if (!withData.length) return { available: false, daysWithData: 0, kpis: [] };
  const kpis: MediaKpi[] = [{ key: "spend", label: "Investimento", value: brl(spend) }];
  if (results > 0) {
    kpis.push({ key: "results", label: l.results, value: int(results) });
    if (spend > 0) kpis.push({ key: "cost", label: l.cost, value: brl(spend / results) });
  }
  if (value > 0) {
    kpis.push({ key: "value", label: l.value, value: brl(value) });
    if (spend > 0) kpis.push({ key: "roas", label: "ROAS", value: dec(value / spend) });
  }
  if (clicks > 0) {
    kpis.push({ key: "clicks", label: l.clicks, value: int(clicks) });
    if (spend > 0) kpis.push({ key: "cpc", label: l.cpc, value: brl(spend / clicks) });
    if (impressions > 0) kpis.push({ key: "ctr", label: l.ctr, value: `${dec((clicks / impressions) * 100)}%` });
  }
  return { available: true, daysWithData: withData.length, kpis };
}

/** Últimos 30 dias fechados (até ontem), em datas locais AAAA-MM-DD. */
export function last30Days(today = new Date()): { start: string; end: string } {
  const iso = (d: Date) => `${d.getFullYear()}-${String(d.getMonth() + 1).padStart(2, "0")}-${String(d.getDate()).padStart(2, "0")}`;
  const end = new Date(today); end.setDate(end.getDate() - 1);
  const start = new Date(end); start.setDate(start.getDate() - 29);
  return { start: iso(start), end: iso(end) };
}
