// DADOS DE EXEMPLO para revisão visual — não são dados reais de nenhuma
// empresa. Gerados de forma determinística a partir das datas pedidas, para
// que a troca de período altere os números como na página real.

import type {
  FbitsOrderRow,
  FbitsOrdersResponse,
  FbitsOrdersSummaryResponse,
  FbitsTrendPoint,
} from "../app/types";

export type ReviewScenario = "padrao" | "sem-comparacao" | "sem-vendas" | "pendente" | "erro" | "carregando";

export const REVIEW_SCENARIOS: Array<{ id: ReviewScenario; label: string }> = [
  { id: "padrao", label: "Com comparação" },
  { id: "sem-comparacao", label: "Sem base anterior" },
  { id: "sem-vendas", label: "Sem vendas" },
  { id: "pendente", label: "Aguardando sync" },
  { id: "erro", label: "Erro" },
  { id: "carregando", label: "Carregando" },
];

const PRODUCTS = [
  "Tinto Reserva", "Espumante Brut", "Branco Seco", "Malbec", "Kit Degustação",
  "Rosé", "Cabernet Sauvignon", "Tinto Gran Reserva",
];
const STATUSES = { paid: "Pagamento confirmado", waiting: "Aguardando pagamento", cancelled: "Pedido cancelado" };

function hash(text: string): number {
  let value = 2166136261;
  for (let index = 0; index < text.length; index += 1) {
    value ^= text.charCodeAt(index);
    value = Math.imul(value, 16777619);
  }
  return (value >>> 0) / 4294967295;
}

function addDays(day: string, amount: number): string {
  const date = new Date(`${day}T00:00:00Z`);
  date.setUTCDate(date.getUTCDate() + amount);
  return date.toISOString().slice(0, 10);
}

function daysBetween(start: string, end: string): string[] {
  const days: string[] = [];
  for (let cursor = start; cursor <= end && days.length < 400; cursor = addDays(cursor, 1)) days.push(cursor);
  return days;
}

function dailyPoint(day: string): FbitsTrendPoint {
  const weekday = new Date(`${day}T00:00:00Z`).getUTCDay();
  const weekend = weekday === 5 || weekday === 6 ? 1.35 : 1;
  const orders = Math.round((3 + hash(`o${day}`) * 9) * weekend);
  const revenue = Math.round(orders * (210 + hash(`t${day}`) * 140) * 100) / 100;
  return { date: day, revenue, orders, average_ticket: orders ? Math.round((revenue / orders) * 100) / 100 : 0 };
}

function bucketKey(day: string, granularity: "day" | "week" | "month"): string {
  if (granularity === "day") return day;
  if (granularity === "month") return `${day.slice(0, 7)}-01`;
  const date = new Date(`${day}T00:00:00Z`);
  date.setUTCDate(date.getUTCDate() - ((date.getUTCDay() + 6) % 7));
  return date.toISOString().slice(0, 10);
}

function totals(points: FbitsTrendPoint[]) {
  const revenue = points.reduce((sum, point) => sum + point.revenue, 0);
  const orders = points.reduce((sum, point) => sum + point.orders, 0);
  return { revenue: Math.round(revenue * 100) / 100, orders, ticket: orders ? Math.round((revenue / orders) * 100) / 100 : 0 };
}

function change(current: number, previous: number): number | null {
  return previous > 0 ? Math.round(((current - previous) / previous) * 1000) / 10 : null;
}

export function reviewSummary(scenario: ReviewScenario, start: string, end: string): FbitsOrdersSummaryResponse {
  const days = daysBetween(start, end);
  const empty = scenario === "sem-vendas" || scenario === "pendente";
  const daily = empty ? [] : days.map(dailyPoint);
  const granularity = days.length <= 31 ? "day" : days.length <= 120 ? "week" : "month";
  const buckets = new Map<string, FbitsTrendPoint>();
  for (const point of daily) {
    const key = bucketKey(point.date, granularity);
    const bucket = buckets.get(key) || { date: key, revenue: 0, orders: 0, average_ticket: 0 };
    bucket.revenue = Math.round((bucket.revenue + point.revenue) * 100) / 100;
    bucket.orders += point.orders;
    bucket.average_ticket = bucket.orders ? Math.round((bucket.revenue / bucket.orders) * 100) / 100 : 0;
    buckets.set(key, bucket);
  }
  const current = totals(daily);
  const previousEnd = addDays(start, -1);
  const previousStart = addDays(previousEnd, -(days.length - 1));
  const previous = totals(scenario === "padrao" ? daysBetween(previousStart, previousEnd).map((day) => {
    const point = dailyPoint(day);
    return { ...point, revenue: point.revenue * 0.86, orders: Math.max(0, point.orders - 1) };
  }) : []);
  const waiting = empty ? 0 : Math.max(1, Math.round(current.orders * 0.06));
  const cancelled = empty ? 0 : Math.max(1, Math.round(current.orders * 0.03));
  return {
    ok: true,
    connected: true,
    client_id: "vinhos",
    period: { start, end },
    previous_period: { start: previousStart, end: previousEnd },
    summary: {
      receita_oficial: current.revenue,
      pedidos: current.orders,
      ticket_medio: current.ticket,
      clientes: Math.round(current.orders * 0.82),
      produtos_vendidos: Math.round(current.orders * 2.3),
      descontos: Math.round(current.revenue * 0.031 * 100) / 100,
      frete: Math.round(current.orders * 23.9 * 100) / 100,
    },
    comparison: {
      receita_oficial: { current: current.revenue, previous: previous.revenue, change_percent: change(current.revenue, previous.revenue) },
      pedidos: { current: current.orders, previous: previous.orders, change_percent: change(current.orders, previous.orders) },
      ticket_medio: { current: current.ticket, previous: previous.ticket, change_percent: change(current.ticket, previous.ticket) },
    },
    status_distribution: empty ? [] : [
      { status_id: "1", status: STATUSES.paid, pedidos: current.orders, valor: current.revenue, counts_as_revenue: true, invalid_orders: 0 },
      { status_id: "2", status: STATUSES.waiting, pedidos: waiting, valor: Math.round(waiting * 268 * 100) / 100, counts_as_revenue: false, invalid_orders: 0 },
      { status_id: "3", status: STATUSES.cancelled, pedidos: cancelled, valor: Math.round(cancelled * 245 * 100) / 100, counts_as_revenue: false, invalid_orders: cancelled },
    ],
    trend: { granularity, items: [...buckets.values()] },
    last_sync_at: null,
  };
}

export function reviewOrders(scenario: ReviewScenario, start: string, end: string): FbitsOrdersResponse {
  const summary = reviewSummary(scenario, start, end);
  const revenue = summary.summary.receita_oficial;
  const weights = [0.21, 0.16, 0.12, 0.1, 0.08, 0.06, 0.05, 0.04];
  const products = summary.summary.pedidos ? PRODUCTS.map((name, index) => ({
    product_id: `exemplo-${index + 1}`,
    sku: `EX-${String(index + 1).padStart(3, "0")}`,
    produto: name,
    quantidade: Math.max(1, Math.round(summary.summary.produtos_vendidos * weights[index])),
    receita: Math.round(revenue * weights[index] * 100) / 100,
  })) : [];
  const days = daysBetween(start, end).reverse();
  const items: FbitsOrderRow[] = summary.summary.pedidos ? Array.from({ length: 10 }, (_, index) => {
    const day = days[Math.min(days.length - 1, Math.floor(index / 3))];
    const status = index === 3 ? "waiting" : index === 7 ? "cancelled" : "paid";
    return {
      pedido_id: String(208_410 - index * 7),
      pedido_codigo: String(208_410 - index * 7),
      situacao_pedido_id: status === "paid" ? 1 : status === "waiting" ? 2 : 3,
      situacao_pedido: STATUSES[status],
      data: `${day}T${String(21 - index).padStart(2, "0")}:15:00-03:00`,
      receita_oficial: Math.round((180 + hash(`v${index}${day}`) * 420) * 100) / 100,
      produtos_vendidos: 1 + (index % 3),
      cliente_id: String(48_210 + index * 13),
    };
  }) : [];
  return {
    ok: true,
    connected: true,
    client_id: "vinhos",
    period: { start, end },
    count: summary.summary.pedidos,
    detail_available: items.length > 0,
    items,
    top_products: products,
  };
}

// ===== Perfis e empresas de EXEMPLO (só harness) =====
// Na aplicação real a lista de empresas vem SEMPRE das memberships do
// usuário (bootstrap validado no backend); aqui ela é simulada para revisar
// o shell com 1, 2 ou várias empresas.

export type ReviewCompany = { client_id: string; name: string };

export const REVIEW_COMPANIES: ReviewCompany[] = [
  { client_id: "vinhos", name: "Curavino" },
  { client_id: "mugo", name: "Mugô" },
  { client_id: "origami", name: "Origami" },
  { client_id: "roove", name: "Roove" },
  { client_id: "ruah", name: "Ruah Parfums" },
  { client_id: "latina", name: "Latina" },
];

export type ReviewProfile = "agencia" | "cliente" | "viewer";

export const REVIEW_PROFILES: Record<ReviewProfile, { role: string; label: string; user: { name: string; email: string } }> = {
  agencia: { role: "agency_admin", label: "Agência (várias empresas)", user: { name: "Equipe Mugô", email: "equipe@exemplo.com.br" } },
  cliente: { role: "client_admin", label: "Administrador da empresa", user: { name: "Ana Souza", email: "ana@exemplo.com.br" } },
  viewer: { role: "viewer", label: "Somente leitura", user: { name: "Bruno Lima", email: "bruno@exemplo.com.br" } },
};

const SYNC_AT = "2026-10-01T11:42:00Z";

/**
 * Descoberta Meta de exemplo (IDs fictícios) para revisar o seletor agrupado:
 * Business da empresa com Página, Instagram e contas (uma sem acesso),
 * Business com consulta bloqueada, Business vazio e uma conta direta.
 */
export function reviewMetaDiscovery(clientId: string, companyName: string) {
  const own = { business_id: "100000000000001", business_name: companyName };
  const slug = companyName.toLowerCase().normalize("NFD").replace(/[^a-z0-9]+/g, "");
  return {
    ok: true,
    handoff: "revisao-meta",
    client_id: clientId,
    meta_user: { id: "900000000000001", name: "Pessoa autorizada (exemplo)" },
    authorized_user_name: "Pessoa autorizada (exemplo)",
    business_managers: [
      { ...own, discovery: { owned_ad_accounts: { status: "ok", count: 2 }, owned_pages: { status: "ok", count: 1 } } },
      { business_id: "100000000000002", business_name: "Agência parceira", discovery: { owned_ad_accounts: { status: "permission_denied" }, client_ad_accounts: { status: "permission_denied" } } },
      { business_id: "100000000000003", business_name: "Business sem ativos", discovery: { owned_ad_accounts: { status: "ok", count: 0 } } },
    ],
    pages: [{
      id: "400000000000001", page_id: "400000000000001", name: companyName, page_name: companyName,
      instagram: { id: "500000000000001", username: slug },
      discovery_sources: ["me_accounts", "business_owned"], businesses: [{ ...own, relation: "owned" }], access_status: "accessible",
    }],
    instagram_accounts: [{ ig_user_id: "500000000000001", username: slug, business_id: "400000000000001", business_name: companyName }],
    ad_accounts: [
      { ad_account_id: "act_200000000000001", ad_account_name: `${companyName} — Conversões`, access_status: "accessible", discovery_sources: ["business_owned"], businesses: [{ ...own, relation: "owned" }] },
      { ad_account_id: "act_200000000000002", ad_account_name: `${companyName} — Conta antiga`, access_status: "restricted", discovery_sources: ["business_owned"], businesses: [{ ...own, relation: "owned" }] },
      { ad_account_id: "act_300000000000001", ad_account_name: "Conta pessoal (exemplo)", access_status: "accessible", discovery_sources: ["me_adaccounts"], businesses: [] },
    ],
    scopes: ["business_management", "ads_read", "pages_show_list", "instagram_basic"],
  };
}

/** Contrato canônico (/integrations) de exemplo: Meta, GA4, Google Ads e FBITS conectados (IDs fictícios). */
export function reviewCanonicalIntegrations(clientId: string, companyName: string, pending: boolean, channel: ReviewChannelScenario = "padrao") {
  const base = { authorization_status: "valid", assets: {}, last_error: null, updated_at: null };
  const auth = channel === "reautorizar" ? "invalid" : "valid";
  const slug = companyName.toLowerCase().normalize("NFD").replace(/[\u0300-\u036f]/g, "").replace(/[^a-z0-9]/g, "");
  const channels = channel === "desconectado" ? [] : [
    { ...base, provider: "meta", connection_id: "exemplo-meta", status: "connected", sync_status: "sync_success", authorization_status: auth,
      account: { name: "Pessoa autorizada (exemplo)" }, last_sync_at: SYNC_AT, last_successful_sync_at: SYNC_AT,
      assets: {
        facebook_page_id: "400000000000001", facebook_page_name: companyName,
        instagram_account_id: "500000000000001", instagram_account_name: slug,
        ad_account_id: "act_200000000000001", ad_account_name: `${companyName} — Conversões`,
      } },
    { ...base, provider: "ga4", connection_id: "exemplo-ga4", status: "connected", sync_status: "sync_success", authorization_status: auth,
      account: { name: `${companyName} — site` }, last_sync_at: SYNC_AT, last_successful_sync_at: SYNC_AT,
      assets: { property_id: "properties/300000001", property_name: `${companyName} — site`, stream_id: "7000001", stream_name: `www.${slug}.com.br` } },
    { ...base, provider: "google_ads", connection_id: "exemplo-ads", status: "connected", sync_status: "sync_success", authorization_status: auth,
      account: { id: "1234567890", name: companyName }, last_sync_at: SYNC_AT, last_successful_sync_at: SYNC_AT,
      assets: { customer_id: "1234567890", customer_name: companyName, login_customer_id: "9876543210" } },
  ];
  return {
    ok: true,
    client_id: clientId,
    connections: [
      ...channels,
      clientId === "roove"
        ? { ...base, provider: "shopify", connection_id: "exemplo-shopify", status: "connected", sync_status: "sync_success",
            account: { name: "Loja de exemplo", domain: "loja-exemplo.myshopify.com" }, last_sync_at: SYNC_AT, last_successful_sync_at: SYNC_AT }
        : { ...base, provider: "fbits", connection_id: "exemplo-fbits", status: "connected",
            sync_status: pending ? null : "sync_success", account: { name: "FBITS / Wake Commerce" },
            last_sync_at: pending ? null : SYNC_AT, last_successful_sync_at: pending ? null : SYNC_AT },
    ],
  };
}

/** Catálogo genérico (/api/connections) de exemplo, coerente com o contrato canônico. */
export function reviewGenericConnections(clientId: string, companyName: string) {
  const common = { client_id: clientId, status: "connected", token_available: true, disconnected_at: null, last_sync_at: SYNC_AT };
  const google = { ga4_authorized: false, ga4_configured: false, ga4_status: "", ads_authorized: false, ads_configured: false, ads_status: "" };
  return {
    ok: true,
    client_id: clientId,
    connections: [
      { ...common, id: "exemplo-meta", provider: "meta", account_name: companyName, external_key: "exemplo-meta",
        metadata: { selected_page_id: "100000000000001", selected_instagram_id: "17840000000000001", selected_ad_account_id: "act_100000000000001" } },
      { ...common, id: "exemplo-ga4", provider: "ga4", account_name: `${companyName} — site`,
        capabilities: { ...google, ga4_authorized: true, ga4_configured: true, ga4_status: "connected" } },
      { ...common, id: "exemplo-ads", provider: "google_ads", account_name: companyName,
        capabilities: { ...google, ads_authorized: true, ads_configured: true, ads_status: "connected" } },
      ...(clientId === "roove"
        ? [{ ...common, id: "exemplo-shopify", provider: "shopify", account_name: "loja-exemplo.myshopify.com",
            external_key: "loja-exemplo.myshopify.com", scopes: ["read_orders", "read_all_orders"],
            metadata: { shop_domain: "loja-exemplo.myshopify.com" } }]
        : []),
    ],
  };
}

/** Conexões Meta (/clients/{id}/connections) de exemplo: orgânico + Ads. */
export function reviewMetaConnections(clientId: string, companyName: string) {
  const handle = companyName.toLowerCase().normalize("NFD").replace(/[̀-ͯ]/g, "").replace(/[^a-z0-9]/g, "");
  return {
    ok: true,
    client_id: clientId,
    connections: [
      { id: "exemplo-ig", client_id: clientId, platform: "instagram", connection_type: "organic", username: handle,
        status: "active", last_sync_at: SYNC_AT, last_synced_at: SYNC_AT, connected_at: "2026-08-12T14:00:00Z" },
      { id: "exemplo-meta-ads", client_id: clientId, platform: "meta_ads", connection_type: "paid",
        ad_account_id: "act_100000000000001", ad_account_name: `${companyName} Ads`,
        status: "active", last_sync_at: SYNC_AT, last_synced_at: SYNC_AT, connected_at: "2026-08-12T14:05:00Z" },
    ],
  };
}

// ===== Shopify (Ecommerce da Roove no app real) — DADOS DE EXEMPLO =====
// Snapshot do read model semeado no cache de sessão que o próprio
// DashboardDataProvider usa ao iniciar (sem Supabase no harness).

const SHOPIFY_PRODUCTS = ["Hidratante Corporal", "Sérum Facial", "Kit Rotina", "Óleo Essencial", "Máscara Capilar", "Protetor Solar"];

export function reviewShopifySnapshot(clientId: string, today: string) {
  const year = today.slice(0, 4);
  const daily = daysBetween(`${year}-01-01`, today).map((day) => {
    const weekday = new Date(`${day}T00:00:00Z`).getUTCDay();
    const weekend = weekday === 0 || weekday === 6 ? 1.3 : 1;
    const orders = Math.round((2 + hash(`so${day}`) * 7) * weekend);
    const net = Math.round(orders * (150 + hash(`st${day}`) * 110) * 100) / 100;
    const keys = Array.from({ length: orders }, (_, index) => `cliente-${Math.floor(hash(`sk${day}${index}`) * 900)}`);
    return {
      client_id: clientId, metric_date: day, updated_at: `${today}T11:42:00Z`,
      shopify_net_revenue: net, shopify_gross_revenue: Math.round(net * 1.06 * 100) / 100,
      shopify_orders: orders, shopify_paid_orders: orders, shopify_customers: new Set(keys).size,
      shopify_customer_keys: keys, shopify_refunds: hash(`sr${day}`) > 0.94 ? Math.round(net * 0.08 * 100) / 100 : 0,
      meta_spend: null, meta_attributed_revenue: null, meta_purchases: null, meta_impressions: null, meta_reach: null,
      meta_clicks: null, meta_link_clicks: null, meta_video_views: null, google_ads_spend: null, google_ads_conversion_value: null,
      google_ads_conversions: null, google_ads_impressions: null, google_ads_clicks: null, ga4_sessions: null, ga4_users: null,
      ga4_revenue: null, ga4_purchases: null, ga4_events: null, instagram_reach: null, instagram_impressions: null,
      instagram_interactions: null, instagram_profile_views: null, instagram_website_clicks: null, instagram_followers: null,
    };
  });
  const products = SHOPIFY_PRODUCTS.map((title, index) => ({
    metric_date: addDays(today, -index), product_id: `exemplo-${index + 1}`, product_title: title, variant: "",
    quantity: Math.round(40 - index * 5 + hash(`sp${index}`) * 6), net_revenue: Math.round((9200 - index * 1300) * 100) / 100,
  }));
  return {
    daily,
    sources: [{ provider: "shopify", last_success_at: `${today}T11:42:00Z`, data_max_available: today, data_min_available: `${year}-01-01`, updated_at: `${today}T11:42:00Z` }],
    campaigns: [],
    products,
    fetchedAt: `${today}T11:42:00Z`,
    queryCount: 4,
  };
}

const FIRST_NAMES = ["Ana", "Bruno", "Carla", "Diego", "Elisa", "Fábio", "Gabriela", "Heitor", "Isabela", "João", "Karina", "Lucas"];

export function reviewShopifyReport(clientId: string, start: string, end: string) {
  const recent_orders = Array.from({ length: 8 }, (_, index) => {
    const name = `${FIRST_NAMES[index % FIRST_NAMES.length]} (exemplo)`;
    return {
      shopify_order_id: `${910000 + index}`, order_number: 4810 - index, name: `#${4810 - index}`,
      customer_name: name, customer_email: null, financial_status: index === 2 ? "pending" : "paid",
      total_price: Math.round((140 + hash(`ro${index}`) * 260) * 100) / 100, currency: "BRL",
      created_at_shopify: `${addDays(end, -Math.floor(index / 3))}T1${index % 10}:20:00Z`, items_count: 1 + (index % 3),
    };
  });
  return {
    ok: true, client_id: clientId, period: { start, end, days: daysBetween(start, end).length },
    summary: { revenue_total: 0, net_revenue: 0, orders: 0, average_ticket: 0, customers: 0, paid_orders: 0, cancelled_orders: 0, refunds_count: 0, refunded_amount: 0, refunds_occurred_in_period_count: 0, refunds_occurred_in_period_amount: 0 },
    trends: { daily: [] }, recent_orders, top_products: [],
    technical: { last_success_at: `${end}T11:42:00Z`, last_received_at: `${end}T11:42:00Z`, processed_count: 0, error_count: 0, recent_errors: [], recent_webhooks: [] },
  };
}

export function reviewShopifyCustomers(clientId: string, start: string, end: string) {
  const items = Array.from({ length: 12 }, (_, index) => {
    const orders = 1 + Math.floor(hash(`co${index}`) * 4);
    const spent = Math.round(orders * (160 + hash(`cs${index}`) * 120) * 100) / 100;
    return {
      customer_key: `exemplo-${index}`, name: `${FIRST_NAMES[index % FIRST_NAMES.length]} (exemplo)`, email: null,
      total_orders: orders, total_spent: spent, average_ticket: Math.round((spent / orders) * 100) / 100,
      last_purchase_at: `${addDays(end, -index)}T12:00:00Z`, first_purchase_at: `${addDays(start, index)}T12:00:00Z`,
      status: orders > 1 ? "recurring" : "new", all_time_orders: orders + (index % 2),
    };
  }).sort((left, right) => right.total_spent - left.total_spent);
  return {
    ok: true, client_id: clientId, period: { start, end, days: daysBetween(start, end).length }, count: items.length,
    summary: { total_customers: items.length, recurring_customers: items.filter((item) => item.status === "recurring").length, multi_order_customers: items.filter((item) => item.total_orders > 1).length },
    items,
  };
}

// ===== Canais (Meta, Google Ads, GA4) — DADOS DE EXEMPLO =====
// Read model (dashboard_daily_metrics + campanhas + fontes) semeado no
// cache de sessão que o DashboardDataProvider lê ao iniciar; nada de
// Supabase no harness. Cenários: estados que a página precisa distinguir.

// Embaralha a chave antes do hash: dias vizinhos ficam realmente diferentes.
function noise(key: string): number {
  return hash(`${key.split("").reverse().join("")}|${key}|${key.length * 7919}`);
}

export type ReviewChannelScenario = "padrao" | "sem-comparacao" | "sem-dados" | "desconectado" | "reautorizar" | "erro" | "carregando";

export const REVIEW_CHANNEL_SCENARIOS: Array<{ id: ReviewChannelScenario; label: string }> = [
  { id: "padrao", label: "Com comparação" },
  { id: "sem-comparacao", label: "Sem base anterior" },
  { id: "sem-dados", label: "Sem dados no período" },
  { id: "desconectado", label: "Desconectado" },
  { id: "reautorizar", label: "Autorização expirada" },
  { id: "erro", label: "Erro" },
  { id: "carregando", label: "Carregando" },
];

const META_CAMPAIGNS = ["Conversões — catálogo", "Remarketing 30 dias", "Prospecção — interesses", "Lançamento da coleção"];
const GOOGLE_CAMPAIGNS = ["Pesquisa — marca", "Performance Max", "Pesquisa — categorias"];

export function reviewChannelSnapshot(clientId: string, today: string, scenario: ReviewChannelScenario) {
  const year = today.slice(0, 4);
  const firstDay = scenario === "sem-comparacao" ? addDays(today, -29) : `${year}-01-01`;
  const withData = scenario !== "sem-dados" && scenario !== "desconectado";
  let followers = 12_400;
  const daily = daysBetween(`${year}-01-01`, today).map((day) => {
    const active = withData && day >= firstDay;
    const weekday = new Date(`${day}T00:00:00Z`).getUTCDay();
    const weekend = weekday === 0 || weekday === 6 ? 1.25 : 1;
    const metaSpend = Math.round((320 + noise(`ms${day}`) * 380) * 100) / 100;
    const purchases = Math.round((3 + noise(`mp${day}`) * 9) * weekend);
    const googleSpend = Math.round((160 + noise(`gs${day}`) * 220) * 100) / 100;
    const conversions = Math.round((2 + noise(`gc${day}`) * 6) * weekend);
    const sessions = Math.round((900 + noise(`ss${day}`) * 1100) * weekend);
    if (active) followers += Math.round(4 + noise(`fl${day}`) * 22);
    return {
      client_id: clientId, metric_date: day, updated_at: `${today}T11:42:00Z`,
      shopify_net_revenue: null, shopify_gross_revenue: null, shopify_orders: null, shopify_paid_orders: null,
      shopify_customers: null, shopify_customer_keys: null, shopify_refunds: null,
      meta_spend: active ? metaSpend : null,
      meta_attributed_revenue: active ? Math.round(purchases * (190 + noise(`mr${day}`) * 90) * 100) / 100 : null,
      meta_purchases: active ? purchases : null,
      meta_impressions: active ? Math.round(18_000 + noise(`mi${day}`) * 22_000) : null,
      meta_reach: active ? Math.round(11_000 + noise(`mh${day}`) * 13_000) : null,
      meta_clicks: active ? Math.round(380 + noise(`mc${day}`) * 520) : null,
      meta_link_clicks: active ? Math.round(260 + noise(`ml${day}`) * 320) : null,
      meta_video_views: active ? Math.round(2_000 + noise(`mv${day}`) * 3_500) : null,
      google_ads_spend: active ? googleSpend : null,
      google_ads_conversion_value: active ? Math.round(conversions * (210 + noise(`gv${day}`) * 120) * 100) / 100 : null,
      google_ads_conversions: active ? conversions : null,
      google_ads_impressions: active ? Math.round(5_000 + noise(`gi${day}`) * 9_000) : null,
      google_ads_clicks: active ? Math.round(210 + noise(`gk${day}`) * 290) : null,
      ga4_sessions: active ? sessions : null,
      ga4_users: active ? Math.round(sessions * 0.81) : null,
      ga4_revenue: active ? Math.round(Math.round(6 + noise(`gp${day}`) * 14) * (230 + noise(`gr${day}`) * 60) * 100) / 100 : null,
      ga4_purchases: active ? Math.round(6 + noise(`gp${day}`) * 14) : null,
      ga4_events: active ? Math.round(sessions * (5.5 + noise(`ge${day}`) * 2)) : null,
      instagram_reach: active ? Math.round(1_500 + noise(`ir${day}`) * 2_600) : null,
      instagram_impressions: active ? Math.round(3_200 + noise(`ii${day}`) * 4_800) : null,
      instagram_interactions: active ? Math.round(80 + noise(`it${day}`) * 220) : null,
      instagram_profile_views: active ? Math.round(60 + noise(`ip${day}`) * 140) : null,
      instagram_website_clicks: active ? Math.round(10 + noise(`iw${day}`) * 50) : null,
      instagram_followers: active ? followers : null,
    };
  });
  const campaigns = withData ? daily.filter((row) => row.metric_date >= firstDay).flatMap((row) => [
    ...META_CAMPAIGNS.map((name, index) => {
      const share = [0.42, 0.27, 0.19, 0.12][index];
      const conversions = Math.round(Number(row.meta_purchases) * share * (index === 2 ? 0.4 : 1));
      return {
        client_id: clientId, metric_date: row.metric_date, provider: "meta", campaign_id: `exemplo-meta-${index + 1}`, campaign_name: name,
        spend: Math.round(Number(row.meta_spend) * share * 100) / 100, impressions: Math.round(Number(row.meta_impressions) * share),
        reach: Math.round(Number(row.meta_reach) * share), clicks: Math.round(Number(row.meta_clicks) * share),
        conversions, revenue: Math.round(conversions * 225 * 100) / 100,
      };
    }),
    ...GOOGLE_CAMPAIGNS.map((name, index) => {
      const share = [0.35, 0.45, 0.2][index];
      const conversions = Math.round(Number(row.google_ads_conversions) * share);
      return {
        client_id: clientId, metric_date: row.metric_date, provider: "google_ads", campaign_id: `exemplo-google-${index + 1}`, campaign_name: name,
        spend: Math.round(Number(row.google_ads_spend) * share * 100) / 100, impressions: Math.round(Number(row.google_ads_impressions) * share),
        clicks: Math.round(Number(row.google_ads_clicks) * share), conversions, conversion_value: Math.round(conversions * 260 * 100) / 100,
      };
    }),
  ]) : [];
  const source = (provider: string) => ({ provider, last_success_at: `${today}T11:42:00Z`, data_max_available: today, data_min_available: firstDay, updated_at: `${today}T11:42:00Z` });
  return {
    daily,
    sources: scenario === "desconectado" ? [] : ["meta", "instagram", "google_ads", "ga4"].map(source),
    campaigns,
    products: [],
    fetchedAt: `${today}T11:42:00Z`,
    queryCount: 4,
  };
}

const CAPTIONS = [
  "Nova coleção chegou: peças pensadas para o dia a dia",
  "Bastidores do ensaio de primavera",
  "Como escolher o tamanho certo em três passos",
  "Os favoritos da semana, escolhidos por vocês",
  "Promoção de aniversário: só até domingo",
  "Detalhes que fazem diferença no acabamento",
  "Look completo com três peças da coleção",
  "Perguntas frequentes sobre trocas e envios",
];

export function reviewInstagramMedia(start: string, end: string) {
  const days = daysBetween(start, end).reverse();
  return {
    ok: true,
    media: CAPTIONS.map((caption, index) => {
      const day = days[Math.min(days.length - 1, index * 3)];
      const reels = index % 3 === 0;
      return {
        id: `exemplo-midia-${index + 1}`,
        media_type: reels ? "VIDEO" : index % 3 === 1 ? "CAROUSEL_ALBUM" : "IMAGE",
        media_product_type: reels ? "REELS" : "FEED",
        caption: `${caption} (exemplo)`,
        timestamp: `${day}T15:30:00Z`,
        permalink: null,
        insights: {
          reach: Math.round(1_800 + noise(`mr${index}`) * 6_000),
          views: reels ? Math.round(4_000 + noise(`mv${index}`) * 9_000) : 0,
          total_interactions: Math.round(90 + noise(`mt${index}`) * 420),
          likes: Math.round(70 + noise(`ml${index}`) * 300),
          comments: Math.round(4 + noise(`mc${index}`) * 40),
          shares: Math.round(2 + noise(`ms${index}`) * 30),
          saved: Math.round(5 + noise(`mz${index}`) * 60),
          available_metrics: ["reach", "views", "total_interactions", "likes", "comments", "shares", "saved"],
        },
      };
    }),
  };
}

export function reviewInstagramComments() {
  const texts = ["Amei a coleção!", "Tem no tamanho M?", "Chegou super rápido, obrigada", "Qual o prazo de entrega para o Sul?", "Lindo demais", "Vocês têm loja física?"];
  return {
    ok: true,
    total: 37,
    comments: texts.map((text, index) => ({
      id: index + 1, client_id: "exemplo", media_id: `exemplo-midia-${index + 1}`, comment_id: `exemplo-comentario-${index + 1}`,
      text, username: `pessoa_${index + 1}_exemplo`, timestamp: `2026-09-${String(20 + index).padStart(2, "0")}T14:00:00Z`,
    })),
    top_words: [
      { word: "coleção", count: 14 }, { word: "tamanho", count: 9 }, { word: "entrega", count: 8 }, { word: "lindo", count: 7 },
      { word: "prazo", count: 5 }, { word: "loja", count: 4 }, { word: "cores", count: 3 }, { word: "troca", count: 3 },
    ],
  };
}

export function reviewInstagramMonthly(today: string) {
  const months: string[] = [];
  for (let month = 1; month <= Number(today.slice(5, 7)); month += 1) months.push(`${today.slice(0, 4)}-${String(month).padStart(2, "0")}`);
  return {
    ok: true,
    months: months.map((month, index) => ({
      month, posts: 8 + Math.round(noise(`p${month}`) * 10), reels: 4 + Math.round(noise(`r${month}`) * 6),
      reach: Math.round(38_000 + noise(`a${month}`) * 40_000 + index * 2_000), views: Math.round(60_000 + noise(`v${month}`) * 70_000),
      interactions: Math.round(3_000 + noise(`i${month}`) * 4_000), profile_visits: Math.round(1_800 + noise(`f${month}`) * 2_200),
      likes: 0, comments: 0, shares: 0, saved: 0,
    })),
  };
}

export function reviewGa4Channels(start: string, end: string) {
  const rows = [
    ["google / organic", "google", "organic", 0.34], ["(direct) / (none)", "(direct)", "(none)", 0.22],
    ["google / cpc", "google", "cpc", 0.18], ["instagram / social", "instagram", "social", 0.14], ["newsletter / email", "newsletter", "email", 0.07],
  ] as const;
  const total = daysBetween(start, end).length * 1_400;
  return {
    ok: true, client_id: "exemplo", property_id: "properties/300000001", period: { start, end, days: daysBetween(start, end).length }, count: rows.length,
    items: rows.map(([sourceMedium, source, medium, share]) => ({
      source_medium: sourceMedium, source, medium, sessions: Math.round(total * share), active_users: Math.round(total * share * 0.78),
      total_users: Math.round(total * share * 0.84), event_count: Math.round(total * share * 6.2), ecommerce_purchases: 0, purchase_revenue: 0, total_revenue: 0,
    })),
  };
}

export function reviewGa4Campaigns(start: string, end: string) {
  const rows = [["pmax_colecao", "google / cpc", 0.12], ["newsletter_setembro", "newsletter / email", 0.05], ["remarketing_ig", "instagram / social", 0.04]] as const;
  const total = daysBetween(start, end).length * 1_400;
  return {
    ok: true, client_id: "exemplo", property_id: "properties/300000001", period: { start, end, days: daysBetween(start, end).length }, count: rows.length,
    items: rows.map(([name, sourceMedium, share]) => ({
      campaign_name: name, source_medium: sourceMedium, source: sourceMedium.split(" / ")[0], medium: sourceMedium.split(" / ")[1],
      sessions: Math.round(total * share), active_users: Math.round(total * share * 0.8), total_users: Math.round(total * share * 0.86),
      event_count: Math.round(total * share * 6), ecommerce_purchases: 0, purchase_revenue: 0, total_revenue: 0,
    })),
  };
}
