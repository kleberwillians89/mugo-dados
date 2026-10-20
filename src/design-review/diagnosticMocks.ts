// Development harness only. No network, credentials or provider calls.
import type { DataHealthResponse } from "../app/dataHealth";
import type { IntelligenceAnalysisRecord, IntelligenceSnapshot } from "../app/intelligenceTypes";

type Options = { clientId: string; name: string; start: string; end: string; scenario: string; viewer: boolean; refresh: string };
const json = (body: unknown, status = 200) => new Response(JSON.stringify(body), {status, headers: {"Content-Type": "application/json"}});
const timestamp = "2026-10-20T12:42:00Z";

export function reviewIntelligence({clientId, name, start, end}: Options) {
  const snapshot: IntelligenceSnapshot = {
    client: {id: clientId, name}, period: {start, end, days: Math.max(1, Math.round((Date.parse(end) - Date.parse(start)) / 86400000) + 1), previous_start: start, previous_end: end},
    sources: [{id: "meta_ads", label: "Meta Ads", status: "available", connected: true, data_points: 1, covered_days: 1, last_sync_at: timestamp}],
    quality: {score: 90, status: "good", available_sources: 1, total_sources: 1, errors: 0, message: "Dados fictícios para revisão visual."},
    last_sync_at: timestamp,
    metrics: [{id: "spend", label: "Investimento", value: 1000, previous_value: 900, variation_percent: null, format: "currency", source: "meta_ads", status: "confirmed"}],
    crossings: [], top_campaigns: [],
  };
  const analysis: IntelligenceAnalysisRecord = {
    id: `review-${clientId}`, client_id: clientId, period_start: start, period_end: end, status: "completed", provider: "visual-mock", model: "fixture",
    sources: snapshot.sources, data_quality: snapshot.quality, metrics_snapshot: snapshot.metrics,
    created_at: timestamp, completed_at: timestamp, error_code: null,
    analysis: {executive: {overall: "Leitura de exemplo do período selecionado.", main_change: "O investimento merece acompanhamento.", opportunity: "Compare os canais antes de decidir.", attention: "Amostra fictícia, sem recomendação real.", priority_action: "Conferir a leitura das campanhas."},
      insights: [{category: "attention", title: "Acompanhe o investimento", interpretation: "Exemplo de interpretação com evidência visível.", metric_ids: ["spend"], sources: ["meta_ads"], impact: "medium", confidence: "medium", action: "Comparar os períodos.", reason: "Acompanhar a distribuição do investimento."}], actions: []},
  };
  return {snapshot, analysis};
}

/** Unknown endpoints remain with the existing harness; never delegates IO. */
export async function diagnosticResponse(url: URL, method: string, options: Options): Promise<Response | null> {
  const {clientId, start, end, scenario, viewer, refresh} = options;
  const {snapshot, analysis} = reviewIntelligence(options);
  const status = /^\/api\/clients\/[^/]+\/data-refresh\/(meta|google)\/status$/.exec(url.pathname);
  const refreshPost = /^\/api\/clients\/[^/]+\/data-refresh\/(meta|google)$/.exec(url.pathname);
  if (status || refreshPost) {
    if (viewer) return json({detail: "Perfil sem permissão para atualizar os dados."}, 403);
    if (refreshPost) return json({detail: "Atualização simulada indisponível; nenhum provider foi chamado."}, 503);
    return json({client_id: clientId, provider: status![1], authorized: true, running: refresh === "running", cooldown_seconds: refresh === "cooldown" ? 30 : 0});
  }
  if (url.pathname.endsWith("/data-health")) {
    const response: DataHealthResponse = {client_id: clientId, period: {start, end}, sources: ["meta_ads", "instagram", "google_ads", "ga4", clientId === "roove" ? "shopify" : "fbits"].map(provider => ({
      provider, dataset: provider, connected: true, last_attempt_at: timestamp,
      last_successful_sync_at: scenario === "sem-dados" ? null : timestamp,
      last_data_at: timestamp, last_data_semantics: "fixture", coverage_end: end, sync_status: refresh === "running" ? "running" : "success", error_code: null,
      state: refresh === "running" ? "updating" : scenario === "sem-dados" ? "no_data" : "synced",
      expected_interval_seconds: null, stale_after_seconds: null, schedule_verified: false, requested_start: start, requested_end: end,
    }))};
    return json(response);
  }
  if (!url.pathname.startsWith("/api/intelligence/")) return null;
  if (scenario === "carregando") await new Promise(resolve => setTimeout(resolve, 3000));
  if (scenario === "erro" || method !== "GET") return json({detail: "Não foi possível concluir a análise simulada. Nenhuma IA foi chamada."}, 502);
  if (url.pathname.endsWith("/context")) return json({ok: true, snapshot});
  if (url.pathname.endsWith("/latest")) return json({ok: true, provider_configured: true, analysis: scenario === "sem-dados" ? null : analysis});
  if (url.pathname.endsWith("/history")) return json({ok: true, items: scenario === "sem-dados" ? [] : [analysis]});
  return json({detail: "Rota de Inteligência não simulada."}, 404);
}
