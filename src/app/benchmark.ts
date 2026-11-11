import { http, clientClientPath } from "./api";

export type BenchmarkCategory = "ads" | "search" | "ecommerce" | "content";
export type BenchmarkCompetitor = {
  id: string; name: string; website: string | null; instagram_handle: string | null;
  youtube_handle: string | null; keywords: string[]; active: boolean; created_at: string;
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
  collected_at: string; limitations: string[];
};
const path = (suffix = "") => clientClientPath(`/benchmark${suffix}`);
export const getBenchmarkOverview = (days = 30) => http<BenchmarkOverview>(path(`/overview?days=${days}`));
export const addBenchmarkCompetitor = (body: { name: string; website?: string | null; instagram_handle?: string | null; youtube_handle?: string | null; keywords?: string[] }) =>
  http<BenchmarkCompetitor>(path("/competitors"), { method: "POST", body: JSON.stringify(body) });
export const addBenchmarkEvidence = (body: { competitor_id: string; category: BenchmarkCategory; title: string; source_url: string; observation?: string | null }) =>
  http<BenchmarkEvidence>(path("/evidence"), { method: "POST", body: JSON.stringify(body) });
