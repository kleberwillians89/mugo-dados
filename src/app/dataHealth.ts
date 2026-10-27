export type DataHealthSource = {
  provider: string; dataset: string; connected: boolean;
  last_attempt_at: string | null; last_successful_sync_at: string | null;
  last_data_at: string | null; last_data_semantics: string;
  coverage_end: string | null; sync_status: string; error_code: string | null;
  state: "synced" | "updating" | "stale" | "attention" | "reauth_required" | "no_data";
  expected_interval_seconds: number | null; stale_after_seconds: number | null;
  schedule_verified: boolean; requested_start: string; requested_end: string;
};
export type DataHealthResponse = { client_id: string; period: { start: string; end: string }; sources: DataHealthSource[] };
export const DATA_HEALTH_CHANGED = "mugo:data-health-changed";
export const HEALTH_LABELS: Record<DataHealthSource["state"], string> = {
  synced: "Sincronizado", updating: "Atualizando", stale: "Atrasado", attention: "Atenção",
  reauth_required: "Reconexão necessária", no_data: "Sem dados registrados no período",
};
export const SOURCE_LABELS: Record<string, string> = { meta_ads: "Meta Ads", instagram: "Instagram · insights do perfil", instagram_content: "Instagram · publicações", ga4: "Google Analytics 4", google_ads: "Google Ads", shopify: "Shopify", fbits: "FBITS · pedidos", fbits_official: "FBITS · indicadores oficiais" };
