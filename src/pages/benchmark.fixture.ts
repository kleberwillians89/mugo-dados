/** Dados de exemplo do Benchmarking (testes e revisão visual). */
import type { BenchmarkOverview } from "../app/benchmark";

const row = (name: string, handle: string, share: number, extra: Record<string, unknown> = {}) => ({
  name, handle, is_brand: name === "Sua marca", competitor_id: null, followers: 12000, posts_in_period: 8, posts_per_week: 1.9,
  avg_interactions: 340, engagement_rate: 2.83, interactions_in_period: 2720, share, sampled: false, hidden_likes: 0,
  top_post: { url: "https://www.instagram.com/p/x/", interactions: 900, type: "REELS" }, collected_at: "2026-11-11T20:00:00Z", ...extra,
});
export const BENCHMARK_FIXTURE: BenchmarkOverview = {
  client_id: "roove", days: 30, collected_at: "2026-11-11T20:00:00Z", limitations: ["Só dado público."],
  competitors: [{ id: "c1", name: "Live!", website: "https://www.liveoficial.com.br", instagram_handle: "liveoficial", youtube_handle: null, keywords: [], active: true, created_at: "x" },
    { id: "c2", name: "Alto Giro", website: null, instagram_handle: "altogiro", youtube_handle: null, keywords: [], active: true, created_at: "x" }],
  evidence: [{ id: "e1", competitor_id: "c1", category: "ads", title: "Campanha de Black Friday com 40% off", source_url: "https://www.facebook.com/ads/library/?id=1",
    observation: "Criativo em vídeo curto", metric_name: null, metric_value: null, unit: null, observed_at: "2026-11-10T00:00:00Z" }],
  public_mentions: [{ id: "n1", term: "Live!", title: "Live! abre loja conceito em SP", url: "https://exemplo.com.br/n", published_at: null, source: "Exame" }],
  evidence_by_category: { ads: 1, search: 0, ecommerce: 0, content: 0 },
  own: { totals: { meta_spend: 18500, shopify_net_revenue: 96400, shopify_orders: 412, instagram_reach: 182400 }, days_with_data: { meta_spend: 30 },
    period_days_with_rows: 30, methodology: "Soma de dias com dados." },
  instagram: { available: true, collected_at: "2026-11-11T20:00:00Z", rows: [row("Sua marca", "roove", 38.4), row("Live!", "liveoficial", 44.1, { followers: 980000, sampled: true }), row("Alto Giro", "altogiro", 17.5)] as never },
};

