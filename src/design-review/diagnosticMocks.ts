// Development harness only. No network, credentials or provider calls.
import {reviewChannelSnapshot, reviewGa4Channels, reviewGa4Campaigns} from "./fixtures";
import type { DataHealthResponse } from "../app/dataHealth";
import type { IntelligenceAnalysisRecord, IntelligenceSnapshot } from "../app/intelligenceTypes";

type Options = { clientId: string; name: string; start: string; end: string; scenario: string; viewer: boolean; refresh: string };
const json = (body: unknown, status = 200) => new Response(JSON.stringify(body), {status, headers: {"Content-Type": "application/json"}});
const timestamp = "2026-10-20T12:42:00Z";

export function reviewIntelligence({clientId, name, start, end}: Options) {
  // Amostra fictícia com o volume de uma análise real (vários indicadores,
  // insights e ações), para revisar hierarquia e repetição. Nenhum dado real.
  const sources: IntelligenceSnapshot["sources"] = [
    {id: "commerce", label: "Loja virtual", status: "available", connected: true, data_points: 30, covered_days: 30, last_sync_at: timestamp},
    {id: "meta_ads", label: "Meta Ads", status: "available", connected: true, data_points: 30, covered_days: 30, last_sync_at: timestamp},
    {id: "ga4", label: "Google Analytics", status: "available", connected: true, data_points: 30, covered_days: 30, last_sync_at: timestamp},
  ];
  const metric = (id: string, label: string, value: number, previous: number | null, format: IntelligenceSnapshot["metrics"][number]["format"], source: string) => ({
    id, label, value, previous_value: previous, format, source, status: "confirmed" as const,
    variation_percent: previous ? Math.round(((value - previous) / previous) * 1000) / 10 : null,
  });
  const snapshot: IntelligenceSnapshot = {
    client: {id: clientId, name}, period: {start, end, days: Math.max(1, Math.round((Date.parse(end) - Date.parse(start)) / 86400000) + 1), previous_start: start, previous_end: end},
    sources,
    quality: {score: 90, status: "good", available_sources: 3, total_sources: 3, errors: 0, message: "Dados fictícios para revisão visual."},
    last_sync_at: timestamp,
    metrics: [
      metric("revenue", "Faturamento", 182450, 158300, "currency", "commerce"),
      metric("orders", "Pedidos", 742, 701, "integer", "commerce"),
      metric("average_ticket", "Ticket médio", 245.89, 225.82, "currency", "commerce"),
      metric("investment", "Investimento", 15300, 12100, "currency", "paid_media"),
      metric("roas", "ROAS", 11.92, 13.08, "decimal", "commerce+paid_media"),
      metric("sessions", "Sessões", 48210, 51990, "integer", "ga4"),
      metric("conversion_rate", "Taxa de conversão", 1.54, 1.35, "percent", "ga4"),
      metric("new_customers", "Novos clientes", 418, 392, "integer", "commerce"),
      {id: "repeat_customers", label: "Clientes recorrentes", value: null, previous_value: null, variation_percent: null, format: "integer", source: "commerce", status: "unavailable"},
      {...metric("google_ads_investment", "Investimento Google Ads", 1608.14, null, "currency", "google_ads"), status: "partial"},
      {...metric("meta_campaign_a_spend", "Investimento · ROOVE | META | PURCHASE | BROAD | 25-44 | CAPITAIS | OUT26", 472.68, null, "currency", "meta_campaign_a"), status: "partial"},
      {...metric("meta_campaign_a_revenue", "Receita atribuída · ROOVE | META | PURCHASE | BROAD | 25-44 | CAPITAIS | OUT26", 1890.4, null, "currency", "meta_campaign_a"), status: "partial"},
      {...metric("meta_campaign_b_spend", "Investimento · ROOVE | META | ENGAGEMENT | PROFILE | CAPITAIS | OUT26", 69.83, null, "currency", "meta_campaign_b"), status: "partial"},
      {...metric("meta_campaign_b_revenue", "Receita atribuída · ROOVE | META | ENGAGEMENT | PROFILE | CAPITAIS | OUT26", 0, null, "currency", "meta_campaign_b"), status: "partial"},
    ],
    crossings: [
      {id: "paid_to_revenue", label: "Investimento × faturamento", sources: ["meta_ads", "commerce"], status: "available", note: "O investimento subiu mais que o faturamento no período.", metrics: ["investment", "revenue", "roas"]},
      {id: "ga4_to_sales", label: "GA4 × vendas", sources: ["ga4", "commerce"], status: "available", note: "Menos sessões, com conversão maior.", metrics: ["sessions", "conversion_rate", "orders"]},
    ],
    top_campaigns: [],
  };
  const analysis: IntelligenceAnalysisRecord = {
    id: `review-${clientId}`, client_id: clientId, period_start: start, period_end: end, status: "completed", provider: "visual-mock", model: "fixture",
    sources: snapshot.sources, data_quality: {...snapshot.quality, message: "Leitura fictícia. Comparações usam o período anterior de mesma duração."}, metrics_snapshot: snapshot.metrics,
    created_at: timestamp, completed_at: timestamp, error_code: null,
    analysis: {
      executive: {
        overall: "O faturamento cresceu com mais pedidos e ticket maior, mas o retorno da mídia caiu porque o investimento subiu mais rápido que as vendas.",
        main_change: "Ticket médio maior sustentou o crescimento.", opportunity: "Converter melhor o tráfego que já chega.",
        attention: "Retorno da mídia em queda.", priority_action: "Revisar a distribuição do investimento antes de ampliar orçamento.",
      },
      insights: [
        {category: "risk", title: "Retorno da mídia em queda", interpretation: "O investimento cresceu acima do faturamento; os dados sugerem saturação nas campanhas de maior gasto.", metric_ids: ["investment", "roas"], sources: ["meta_ads", "commerce"], impact: "high", confidence: "medium", action: "Revisar as campanhas de maior gasto antes de ampliar orçamento.", reason: "Evitar escalar onde o retorno marginal caiu."},
        {category: "positive", title: "Ticket médio sustentou o crescimento", interpretation: "Mais pedidos com ticket maior explicam a maior parte da alta do faturamento.", metric_ids: ["revenue", "average_ticket", "orders"], sources: ["commerce"], impact: "high", confidence: "high", action: "Manter as ofertas de maior valor em destaque.", reason: "Preservar o que está funcionando."},
        {category: "opportunity", title: "Tráfego converte melhor", interpretation: "Com menos sessões, a conversão subiu: há espaço para atrair mais visitas qualificadas.", metric_ids: ["sessions", "conversion_rate"], sources: ["ga4"], impact: "medium", confidence: "medium", action: "Testar ampliar o alcance das campanhas com melhor conversão.", reason: "Aproveitar a eficiência do site."},
        {category: "opportunity", title: "Base de novos clientes crescendo", interpretation: "Mais clientes novos no período abrem espaço para recompra.", metric_ids: ["new_customers"], sources: ["commerce"], impact: "medium", confidence: "medium", action: "Criar uma régua de recompra para quem comprou pela primeira vez.", reason: "Transformar aquisição em recorrência."},
        {category: "data_quality", title: "Dados de hoje ainda em formação", interpretation: "O período inclui o dia de hoje, ainda parcial.", metric_ids: ["revenue"], sources: ["commerce"], impact: "medium", confidence: "high", action: "Reavaliar após o fechamento do dia.", reason: "Evitar comparar dia incompleto."},
        {category: "data_quality", title: "Comparação com mesma duração", interpretation: "O período anterior tem a mesma quantidade de dias, não o mês calendário completo.", metric_ids: ["revenue"], sources: ["commerce"], impact: "low", confidence: "high", action: "Considerar a sazonalidade ao comparar.", reason: "Evitar leitura distorcida."},
      ],
      actions: [
        {priority: "now", recommendation: "Revisar as campanhas de maior gasto", justification: "O retorno caiu enquanto o investimento subiu.", sources: ["meta_ads"], impact_expected: "Recuperar parte do retorno sem cortar vendas.", confidence: "medium", metric_id: "roas"},
        {priority: "week", recommendation: "Testar ampliar alcance das campanhas que mais convertem", justification: "A conversão do site subiu com menos sessões.", sources: ["ga4"], impact_expected: "Mais pedidos com o mesmo nível de conversão.", confidence: "medium", metric_id: "sessions"},
        {priority: "monitor", recommendation: "Acompanhar o ticket médio semanalmente", justification: "Foi o principal motor do crescimento.", sources: ["commerce"], impact_expected: "Detectar cedo uma reversão.", confidence: "high", metric_id: "average_ticket"},
      ],
    },
  };
  return {snapshot, analysis};
}

/** Unknown endpoints remain with the existing harness; never delegates IO. */
export async function diagnosticResponse(url: URL, method: string, options: Options): Promise<Response | null> {
  const {clientId, start, end, scenario, viewer, refresh} = options;
  const {snapshot, analysis} = reviewIntelligence(options);
  if (scenario === "parcial") analysis.data_quality = {...analysis.data_quality, status: "partial", message: "Análise parcial: comparações sem cobertura compatível foram excluídas."};
  const status = /^\/api\/clients\/[^/]+\/data-refresh\/(meta|google|shopify|fbits)\/status$/.exec(url.pathname);
  const refreshPost = /^\/api\/clients\/[^/]+\/data-refresh\/(meta|google|shopify|fbits)$/.exec(url.pathname);
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
  if (url.pathname.endsWith("/sales-by-origin")) return json({
    ok: true, status: "available", provider: "shopify", period: {start: "2026-10-01", end: "2026-10-26"},
    attribution_model: "last_click_utm", attribution_model_label: "Último clique com UTM registrado pela loja",
    notes: ["Pedidos sem origem aparecem como “Origem não identificada” e nunca são distribuídos entre campanhas."],
    totals: {orders: 412, revenue: 98234.5, average_ticket: 238.43, orders_with_origin: 301, orders_with_utm: 188, origin_coverage_percent: 73.06, utm_coverage_percent: 45.63},
    channels: [
      {channel: "paid_social", label: "Mídia paga · redes sociais", orders: 141, revenue: 36120.4, average_ticket: 256.17, share_of_revenue: 36.77},
      {channel: "unknown", label: "Origem não identificada", orders: 111, revenue: 24410.9, average_ticket: 219.92, share_of_revenue: 24.85},
      {channel: "organic_search", label: "Busca orgânica", orders: 64, revenue: 15880.0, average_ticket: 248.13, share_of_revenue: 16.17},
      {channel: "paid_search", label: "Mídia paga · busca", orders: 47, revenue: 12410.2, average_ticket: 264.05, share_of_revenue: 12.63},
      {channel: "email", label: "E-mail", orders: 31, revenue: 6213.0, average_ticket: 200.42, share_of_revenue: 6.32},
      {channel: "direct", label: "Direto", orders: 18, revenue: 3200.0, average_ticket: 177.78, share_of_revenue: 3.26},
    ],
    campaigns: [
      {channel: "paid_social", channel_label: "Mídia paga · redes sociais", source: "facebook", medium: "cpc", campaign: "conversao_colecao_verao_2026", orders: 88, revenue: 23110.4, average_ticket: 262.62, share_of_revenue: 23.53},
      {channel: "paid_search", channel_label: "Mídia paga · busca", source: "google", medium: "cpc", campaign: "pmax_marca", orders: 47, revenue: 12410.2, average_ticket: 264.05, share_of_revenue: 12.63},
      {channel: "paid_social", channel_label: "Mídia paga · redes sociais", source: "instagram", medium: "paid", campaign: "remarketing_carrinho", orders: 22, revenue: 5400.0, average_ticket: 245.45, share_of_revenue: 5.5},
      {channel: "email", channel_label: "E-mail", source: "klaviyo", medium: "email", campaign: "newsletter_outubro", orders: 31, revenue: 6213.0, average_ticket: 200.42, share_of_revenue: 6.32},
    ],
  });
  if (url.pathname === "/api/ig/stories") return json({ok: true, stories: [], available: true, message: "Sem stories na amostra fictícia."});
  if (url.pathname === "/api/google/ga4/report") {
    if (scenario === "erro") return json({detail: "Falha simulada na leitura GA4."}, 502);
    const empty = ["sem-dados", "desconectado"].includes(scenario);
    const rows = empty ? [] : reviewChannelSnapshot(clientId, end, "padrao").daily.filter(row => row.metric_date >= start && row.metric_date <= end);
    const total = (field: "ga4_sessions" | "ga4_users" | "ga4_events" | "ga4_purchases" | "ga4_revenue") => rows.reduce((sum, row) => sum + Number(row[field] || 0), 0);
    return json({ok: true, client_id: clientId, property_id: "properties/300000001", period: {start, end, days: rows.length},
      summary: {sessions: total("ga4_sessions"), active_users: total("ga4_users"), total_users: total("ga4_users"), user_count_semantics: "sum_of_daily_users", event_count: total("ga4_events"), purchases: total("ga4_purchases"), purchase_revenue: total("ga4_revenue"), total_revenue: total("ga4_revenue")},
      trends: {daily: rows.map(row => ({date: row.metric_date, sessions: row.ga4_sessions, active_users: row.ga4_users, total_users: row.ga4_users, event_count: row.ga4_events, ecommerce_purchases: row.ga4_purchases, purchase_revenue: row.ga4_revenue}))},
      channels: empty ? [] : reviewGa4Channels(start, end).items, campaigns: empty ? [] : reviewGa4Campaigns(start, end).items,
      events: [], funnel: {}, meta: {last_synced_at: timestamp, data_available: !empty, daily_rows: rows.length}});
  }
  if (!url.pathname.startsWith("/api/intelligence/")) return null;
  if (scenario === "carregando") await new Promise(resolve => setTimeout(resolve, 3000));
  if (method === "POST" && url.pathname.endsWith("/ask") && scenario !== "erro") {
    const now = new Date().toISOString();
    const base = {conversation_id: `review-${clientId}`, period_start: start, period_end: end, sources: snapshot.sources};
    return json({ok: true, conversation_id: base.conversation_id, snapshot,
      user_message: {...base, id: "q1", role: "user", content: {question: "Minha mídia está eficiente?"}, created_at: now},
      assistant_message: {...base, id: "a1", role: "assistant", created_at: now, content: {
        direct_answer: "A mídia não está se pagando neste início de mês: o Google Ads consumiu R$ 1.608,14 e a Meta R$ 542,51 sem receita atribuída relevante, enquanto a loja registrou poucos pedidos. Vale revisar as campanhas de compra antes de aumentar o orçamento.",
        metric_ids: ["investment", "orders", "roas"],
        evidence: ["Investimento Google Ads: R$ 1.608,14 · Google Ads · parcial, dados até 20/10", "Investimento Meta: R$ 542,51 · Meta Ads · parcial, dados até 20/10", "Pedidos: 742 · Loja virtual · parcial, dados até 19/10"],
        attention_points: ["O investimento cresceu mais rápido que as vendas da loja.", "A campanha de engajamento não gera receita atribuída.",
          "Resposta parcial: indicadores apresentados separadamente; conclusões entre fontes sem compatibilidade comprovada foram omitidas.",
          "Os dados de hoje ainda estão em formação."],
        recommendations: ["Pausar ou reduzir a campanha de engajamento sem retorno.", "Revisar públicos e criativos da campanha de compra antes de ampliar orçamento."],
        next_steps: ["Comparar a semana fechada com a anterior antes de decidir."],
      }}});
  }
  if (scenario === "erro" || method !== "GET") return json({detail: "Não foi possível concluir a análise simulada. Nenhuma IA foi chamada."}, 502);
  if (url.pathname.endsWith("/context")) return json({ok: true, snapshot});
  if (url.pathname.endsWith("/latest")) return json({ok: true, provider_configured: true, analysis: scenario === "sem-dados" ? null : analysis});
  if (url.pathname.endsWith("/history")) return json({ok: true, items: scenario === "sem-dados" ? [] : [analysis]});
  return json({detail: "Rota de Inteligência não simulada."}, 404);
}
