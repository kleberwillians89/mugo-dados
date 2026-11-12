import { http, clientClientPath } from "./api";

export type RadarTrend = {
  id: string;
  topic: string;
  approx_traffic: string | null;
  news_title: string | null;
  source_url: string;
  researched_at: string;
  /** Por que importa para ESTA marca e uma ideia de pauta (seleção por marca). */
  why?: string | null;
  idea?: string | null;
};

export type RadarCreator = {
  id: string;
  network: string;
  handle: string;
  display_name: string | null;
  followers: number | null;
  engagement_rate: number | null;
  sample_size: number | null;
  profile_url: string | null;
  source: string | null;
  collected_at: string | null;
  missing_fields: string[];
};

export type RadarOverview = {
  client_id: string;
  collected_at: string;
  sources: Record<string, string>;
  trends: { status: string; items: RadarTrend[]; method?: "ia" | "termos" | null; public_count?: number };
  creators: RadarCreator[];
  methodology: Record<string, string>;
};

export function getRadarOverview(): Promise<RadarOverview> {
  return http<RadarOverview>(clientClientPath("/radar/overview"));
}
