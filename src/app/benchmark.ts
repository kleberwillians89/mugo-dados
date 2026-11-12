import { http, clientClientPath } from "./api";

export type BenchmarkCategory = "ads" | "search" | "ecommerce" | "content";
export type BenchmarkCompetitor = {
  id: string; name: string; website: string | null; instagram_handle: string | null;
  youtube_handle: string | null; facebook_page?: string | null; keywords: string[]; active: boolean; created_at: string;
};
export type BenchmarkEvidence = {
  id: string; competitor_id: string; category: BenchmarkCategory; title: string; source_url: string;
  observation: string | null; metric_name: string | null; metric_value: number | null;
  unit: string | null; observed_at: string;
};
export type BenchmarkMention = {
  id: string; term: string; title: string; url: string; published_at: string | null; source: string | null;
};
export type BenchmarkOverview = {
  client_id: string; days: number; competitors: BenchmarkCompetitor[]; evidence: BenchmarkEvidence[];
  public_mentions: BenchmarkMention[]; evidence_by_category: Record<BenchmarkCategory, number>;
  own: { totals: Record<string, number | null>; days_with_data: Record<string, number>; period_days_with_rows: number; methodology: string };
  instagram?: BenchmarkInstagram;
  collected_at: string; limitations: string[];
};
/** Instagram público (Business Discovery): marca x concorrentes no mesmo critério. */
export type BenchmarkInstagramRow = {
  name: string; handle: string; is_brand: boolean; competitor_id: string | null; followers: number | null;
  posts_in_period: number; posts_per_week: number; avg_interactions: number | null; engagement_rate: number | null;
  interactions_in_period: number; share: number | null; sampled: boolean; hidden_likes: number;
  top_post: { url: string | null; interactions: number | null; type: string | null } | null; collected_at: string | null;
};
export type BenchmarkInstagram = { rows: BenchmarkInstagramRow[]; collected_at: string | null; available: boolean };
const path = (suffix = "") => clientClientPath(`/benchmark${suffix}`);
export const getBenchmarkOverview = (days = 30) => http<BenchmarkOverview>(path(`/overview?days=${days}`));
export const addBenchmarkCompetitor = (body: { name: string; website?: string | null; instagram_handle?: string | null; youtube_handle?: string | null;
  facebook_page?: string | null; keywords?: string[] }) =>
  http<BenchmarkCompetitor>(path("/competitors"), { method: "POST", body: JSON.stringify(body) });
export const addBenchmarkEvidence = (body: { competitor_id: string; category: BenchmarkCategory; title: string; source_url: string; observation?: string | null }) =>
  http<BenchmarkEvidence>(path("/evidence"), { method: "POST", body: JSON.stringify(body) });
export type BenchmarkAutoResult = { status: "feito" | "nada_novo" | "ja_tem" | "aguardando" | "limite_do_plano" | "sem_ia"; added: (BenchmarkCompetitor & { why?: string | null })[] };
// A IA monta a lista (Clipping + contexto do negócio). Sem force, só age quando não há concorrente ativo.
export const autoBenchmarkCompetitors = (force = false) =>
  http<BenchmarkAutoResult>(path(`/competitors/auto${force ? "?force=true" : ""}`), { method: "POST", timeoutMs: 90_000 });
export const removeBenchmarkCompetitor = (id: string) =>
  http<{ removed: string }>(path(`/competitors/${encodeURIComponent(id)}`), { method: "DELETE" });
export const refreshBenchmarkInstagram = () =>
  http<{ updated: number; errors: { handle: string; error: string }[] }>(path("/instagram/refresh"), { method: "POST", timeoutMs: 90_000 });

/** Preços públicos de produtos (concorrentes e a própria marca), lidos todo dia. */
export type BenchmarkProduct = {
  id: string; competitor_id: string | null; url: string; title: string | null; image: string | null; price: number | null; compare_at: number | null;
  currency: string | null; available: boolean | null; source: "shopify" | "json_ld" | "meta_tag" | null; checked_at: string | null; error: string | null;
  history: { date: string; price: number | null }[]; change: { on: string; from: number; to: number; pct: number | null } | null;
};
export type BenchmarkPrices = { products: BenchmarkProduct[]; ad_library: { competitor_id: string; name: string; url: string }[] };
export type CatalogItem = { title: string; url: string; price: number | null; image: string | null };
export const getBenchmarkPrices = (days = 90) => http<BenchmarkPrices>(path(`/prices?days=${days}`), { timeoutMs: 30_000 });
export const addBenchmarkProduct = (body: { url: string; competitor_id: string | null }) =>
  http<BenchmarkProduct>(path("/prices"), { method: "POST", body: JSON.stringify(body), timeoutMs: 45_000 });
export const checkBenchmarkProduct = (id: string) => http<BenchmarkProduct>(path(`/prices/${encodeURIComponent(id)}/check`), { method: "POST", timeoutMs: 45_000 });
export const removeBenchmarkProduct = (id: string) => http<{ removed: string }>(path(`/prices/${encodeURIComponent(id)}`), { method: "DELETE" });
export const getStoreCatalog = (website: string) =>
  http<{ products: CatalogItem[] }>(path("/catalog"), { method: "POST", body: JSON.stringify({ website }), timeoutMs: 45_000 });
