// src/app/types.ts

// =========================
// Media (items do refresh_all)
// =========================
export type IgMediaItem = {
  id: string;
  media_type: string;
  media_product_type: string;
  caption?: string | null;
  timestamp?: string | null;
  permalink?: string | null;
  thumb_url?: string | null;
  thumbnail_url?: string | null;
  media_url?: string | null;
  insights?: Record<string, unknown>;
};

// =========================
// RefreshAll
// =========================
export type RefreshAllResponse = {
  ok: boolean;
  client_id: string;
  connection_id?: string | null;
  profile: {
    id: string;
    username: string;
    name?: string;
    followers_count: number;
    media_count: number;
  };
  kpis: {
    impressions: number;
    reach: number;
    total_interactions: number;
    website_clicks: number;
    profile_views: number;
    accounts_engaged: number;
  };
  media: IgMediaItem[];
  comments_saved?: number;
  block_status?: Record<string, unknown>;
  warnings?: string[];
};

// =========================
// Shopify
// =========================
export type ShopifyReportSummary = {
  revenue_total: number;
  orders: number;
  average_ticket: number;
  customers: number;
  paid_orders: number;
  cancelled_orders: number;
  refunds_count: number;
  refunded_amount: number;
};

export type ShopifyTrendPoint = {
  date: string;
  revenue: number;
  orders: number;
  customers: number;
  average_ticket: number;
};

export type ShopifyRecentOrder = {
  id?: string | null;
  shopify_order_id: string;
  order_number?: string | number | null;
  name?: string | null;
  customer_name: string;
  customer_email?: string | null;
  financial_status?: string | null;
  fulfillment_status?: string | null;
  total_price: number;
  currency: string;
  created_at_shopify?: string | null;
  updated_at_shopify?: string | null;
  items_count: number;
  shop_domain?: string | null;
};

export type ShopifyTopProduct = {
  product_id?: string | null;
  variant_id?: string | null;
  title: string;
  variant_title?: string | null;
  vendor?: string | null;
  quantity_sold: number;
  revenue: number;
};

export type ShopifyWebhookEvent = {
  id?: string | null;
  webhook_id?: string | null;
  topic?: string | null;
  shop_domain?: string | null;
  received_at?: string | null;
  processed_at?: string | null;
  status?: string | null;
  error_message?: string | null;
};

export type ShopifyTechnicalSummary = {
  last_success_at?: string | null;
  last_received_at?: string | null;
  processed_count: number;
  error_count: number;
  recent_errors: ShopifyWebhookEvent[];
  recent_webhooks: ShopifyWebhookEvent[];
};

export type ShopifyCustomerRow = {
  customer_key: string;
  shopify_customer_id?: string | null;
  name: string;
  email?: string | null;
  total_orders: number;
  total_spent: number;
  average_ticket: number;
  last_purchase_at?: string | null;
  first_purchase_at?: string | null;
  status: "new" | "recurring" | string;
  all_time_orders: number;
  shop_domain?: string | null;
};

export type ShopifyCustomerSummary = {
  total_customers: number;
  recurring_customers: number;
  multi_order_customers: number;
  top_customer?: {
    name?: string | null;
    email?: string | null;
    total_spent: number;
    total_orders: number;
    status?: string | null;
  } | null;
};

export type ShopifyCustomersResponse = {
  ok: boolean;
  client_id: string;
  period: {
    start: string;
    end: string;
    days: number;
  };
  count: number;
  summary: ShopifyCustomerSummary;
  items: ShopifyCustomerRow[];
};

export type ShopifyReportResponse = {
  ok: boolean;
  client_id: string;
  shop_domain?: string | null;
  period: {
    start: string;
    end: string;
    days: number;
  };
  summary: ShopifyReportSummary;
  trends: {
    daily: ShopifyTrendPoint[];
  };
  recent_orders: ShopifyRecentOrder[];
  top_products: ShopifyTopProduct[];
  technical: ShopifyTechnicalSummary;
};

// =========================
// FBits official sales
// =========================
export type FbitsOrdersSummary = {
  receita_oficial: number;
  pedidos: number;
  ticket_medio: number;
  clientes: number;
  produtos_vendidos: number;
};

export type FbitsOrdersSummaryResponse = {
  ok: boolean;
  connected: boolean;
  client_id: string;
  period: {
    start: string;
    end: string;
  };
  summary: FbitsOrdersSummary;
  message?: string | null;
};

export type FbitsOrderRow = {
  pedido_id: string;
  pedido_codigo?: string | null;
  situacao_pedido_id: number;
  situacao_pedido?: string | null;
  data: string;
  data_pagamento?: string | null;
  receita_oficial: number;
  produtos_vendidos: number;
  cliente_key?: string | null;
  cliente_id?: string | null;
  cliente_nome?: string | null;
  cliente_email?: string | null;
  cliente_documento?: string | null;
  forma_pagamento?: string | null;
  status_pagamento?: string | null;
  produtos?: FbitsProductRow[];
};

export type FbitsProductRow = {
  product_id?: string | null;
  sku?: string | null;
  produto: string;
  quantidade: number;
  valor_unitario?: number;
  receita: number;
  imagem?: string | null;
};

export type FbitsCustomerRow = {
  customer_id?: string | null;
  cliente: string;
  email?: string | null;
  pedidos: number;
  receita: number;
};

export type FbitsOrdersResponse = {
  ok: boolean;
  connected: boolean;
  client_id: string;
  period: {
    start: string;
    end: string;
  };
  count: number;
  items: FbitsOrderRow[];
  top_products?: FbitsProductRow[];
  top_customers?: FbitsCustomerRow[];
  detail_available?: boolean;
  message?: string | null;
};

// =========================
// Google Analytics 4
// =========================
export type Ga4Funnel = {
  view_item: number;
  add_to_cart: number;
  begin_checkout: number;
  add_payment_info: number;
  purchase: number;
};

export type Ga4EventGroupItem = {
  event_name: string;
  label: string;
  description?: string | null;
  event_count: number;
  total_users: number;
  first_seen_at?: string | null;
  last_seen_at?: string | null;
};

export type Ga4EventGroup = {
  key: string;
  title: string;
  description: string;
  total_events: number;
  total_users: number;
  items: Ga4EventGroupItem[];
};

export type Ga4CommerceJourney = {
  summary: {
    view_item: number;
    add_to_cart: number;
    begin_checkout: number;
    add_payment_info: number;
    purchase: number;
    add_to_cart_rate: number;
    checkout_rate: number;
    payment_info_rate: number;
    purchase_rate: number;
    purchase_rate_from_view_item: number;
  };
  items: Ga4EventGroupItem[];
};

export type Ga4DailyStatRow = {
  date: string;
  sessions: number;
  active_users: number;
  total_users: number;
  event_count: number;
  ecommerce_purchases: number;
  purchase_revenue: number;
  total_revenue: number;
  view_item_count: number;
  add_to_cart_count: number;
  begin_checkout_count: number;
  purchase_count: number;
};

export type Ga4Summary = {
  sessions: number;
  active_users: number;
  total_users: number;
  event_count: number;
  purchases: number;
  purchase_revenue: number;
  total_revenue: number;
  average_daily_active_users: number;
  average_daily_total_users: number;
};

export type Ga4ChannelRow = {
  source_medium: string;
  source?: string | null;
  medium?: string | null;
  sessions: number;
  active_users: number;
  total_users: number;
  event_count: number;
  ecommerce_purchases: number;
  purchase_revenue: number;
  total_revenue: number;
};

export type Ga4CampaignRow = {
  campaign_name: string;
  source_medium?: string | null;
  source?: string | null;
  medium?: string | null;
  sessions: number;
  active_users: number;
  total_users: number;
  event_count: number;
  ecommerce_purchases: number;
  purchase_revenue: number;
  total_revenue: number;
};

export type Ga4EventRow = {
  event_name: string;
  event_count: number;
  total_users: number;
  label?: string | null;
  description?: string | null;
  first_seen_at?: string | null;
  last_seen_at?: string | null;
};

export type Ga4ReportResponse = {
  ok: boolean;
  client_id: string;
  property_id: string;
  period: {
    start: string;
    end: string;
    days: number;
  };
  summary: Ga4Summary;
  funnel: Ga4Funnel;
  commerce_journey: Ga4CommerceJourney;
  behavior: Ga4EventGroup;
  engagement: Ga4EventGroup;
  merchandising: Ga4EventGroup;
  trends: {
    daily: Ga4DailyStatRow[];
  };
  channels: Ga4ChannelRow[];
  campaigns: Ga4CampaignRow[];
  events: Ga4EventRow[];
  meta: {
    last_synced_at?: string | null;
    daily_rows: number;
    channel_rows: number;
    campaign_rows: number;
    event_rows: number;
  };
};

export type Ga4CollectionResponse<T> = {
  ok: boolean;
  client_id: string;
  property_id: string;
  period: {
    start: string;
    end: string;
    days: number;
  };
  count: number;
  items: T[];
};

// =========================
// Dashboard (Meta-like)
// =========================
export type DashboardDailyRow = {
  date: string;
  start?: string;
  end?: string;

  impressions: number;
  reach: number;

  // padronizado (Meta-like)
  total_interactions: number;

  website_clicks: number;
  profile_views: number;

  // pode vir 0 se backend não preencher ainda
  accounts_engaged: number;

  followers: number; // total no dia
};

export type DashboardTotals = {
  impressions: number;
  reach: number;
  total_interactions: number;
  website_clicks: number;
  profile_views: number;
  accounts_engaged: number;
};

export type DashboardPeriodTotals = DashboardTotals & {
  followers_growth: number;
  followers_current?: number;
};

export type DashboardSeries = {
  daily: DashboardDailyRow[];
  weekly: DashboardDailyRow[];
  monthly: DashboardDailyRow[];
};

export type DashboardGrowthPercent = {
  impressions: number;
  reach: number;
  total_interactions: number;
  website_clicks: number;
  profile_views: number;
  accounts_engaged: number;
  followers: number;
};

export type DashboardCoverage = {
  covered_days: number;
  expected_days: number;
  is_partial: boolean;
  missing_days: number;
};

export type DashboardResponse = {
  ok: boolean;
  client_id: string;
  days: number;
  start?: string;
  end?: string;

  daily: DashboardDailyRow[];
  series?: DashboardSeries;

  period_totals?: DashboardPeriodTotals;
  period_previous_totals?: DashboardPeriodTotals;

  totals_last_days: DashboardTotals;
  followers_growth_last_days: number;
  totals_previous_period?: DashboardTotals;
  followers_growth_previous_period?: number;
  period_growth_percent?: DashboardGrowthPercent;

  monthly_totals: DashboardTotals;
  last_month_totals: DashboardTotals;

  monthly_followers_growth: number;
  last_month_followers_growth: number;

  monthly_growth_percent: DashboardGrowthPercent;
  coverage?: DashboardCoverage;
};

// =========================
// Month Aggregation (conteúdo)
// =========================
export type MonthAgg = {
  month: string; // "YYYY-MM"

  // produção
  posts: number;
  reels: number;

  // performance (conteúdo)
  reach: number;
  views: number;
  interactions: number; // aqui pode continuar "interactions" (agregado por conteúdo)
  profile_visits: number;

  // breakdown
  likes: number;
  comments: number;
  shares: number;
  saved: number;

  // reels avançado
  avg_watch_ms: number;
  skip_rate_avg: number;
};

export type MetaConnection = {
  id: string;
  client_id: string;
  platform: "instagram" | "meta_ads" | string;
  connection_type: "organic" | "paid" | string;
  meta_user_id?: string;
  ig_user_id?: string;
  username?: string;
  business_id?: string;
  ad_account_id?: string;
  ad_account_name?: string;
  scopes_json?: string[];
  status: "active" | "needs_reauth" | "error" | "disconnected" | string;
  token_expires_at?: string | null;
  expires_at?: string | null;
  token_last_refreshed_at?: string | null;
  last_validated_at?: string | null;
  last_sync_at?: string | null;
  last_synced_at?: string | null;
  last_sync_status?: "never" | "success" | "error" | "partial" | "skipped" | string;
  last_error?: string | null;
  requires_reauth?: boolean;
  is_active?: boolean;
  connected_at?: string | null;
  updated_at?: string | null;
};

export type ClientConnectionsResponse = {
  ok: boolean;
  client_id: string;
  connections: MetaConnection[];
};

export type MetaOauthStartResponse = {
  ok: boolean;
  client_id: string;
  authorization_url: string;
};

export type MetaDiscoveredInstagramAsset = {
  ig_user_id: string;
  username?: string;
  business_id?: string;
  business_name?: string;
};

export type MetaDiscoveredAdAccount = {
  ad_account_id: string;
  ad_account_name?: string;
  account_status?: number;
  currency?: string;
};

export type MetaDiscoverAssetsResponse = {
  ok: boolean;
  handoff: string;
  client_id: string;
  meta_user: {
    id?: string;
    name?: string;
  };
  instagram_accounts: MetaDiscoveredInstagramAsset[];
  ad_accounts: MetaDiscoveredAdAccount[];
  scopes: string[];
  expires_at?: string | null;
};

export type CommentItem = {
  id?: number;
  client_id: string;
  media_id: string;
  comment_id: string;
  text?: string;
  username?: string;
  timestamp?: string;
};

export type TopWord = {
  word: string;
  count: number;
};

export type CommentsResponse = {
  ok: boolean;
  client_id: string;
  connection_id?: string | null;
  days: number;
  start?: string;
  end?: string;
  limit?: number;
  offset?: number;
  has_more?: boolean;
  next_offset?: number | null;
  total?: number;
  comments: CommentItem[];
  top_words: TopWord[];
};

export type NoteItem = {
  id: string;
  client_id: string;
  title: string;
  body: string;
  created_at: string;
  updated_at: string;
};

export type NotesResponse = {
  ok: boolean;
  client_id: string;
  connection_id?: string | null;
  limit?: number;
  available?: boolean;
  message?: string;
  notes: NoteItem[];
};

export type StoryItem = {
  id: string;
  media_type?: string;
  media_url?: string;
  thumbnail_url?: string;
  timestamp?: string;
  permalink?: string;
};

export type StoriesResponse = {
  ok: boolean;
  available: boolean;
  client_id: string;
  connection_id?: string | null;
  message?: string;
  error?: string | null;
  stories: StoryItem[];
};

export type MonthsResponse = {
  ok: boolean;
  client_id: string;
  connection_id?: string | null;
  months: string[];
};

export type MediaResponse = {
  ok: boolean;
  client_id: string;
  connection_id?: string | null;
  days: number;
  start?: string;
  end?: string;
  limit?: number;
  offset?: number;
  has_more?: boolean;
  next_offset?: number | null;
  media: IgMediaItem[];
};

export type MediaMonthlyItem = {
  month: string;
  posts: number;
  reels: number;
  reach: number;
  views: number;
  interactions: number;
  profile_visits: number;
  likes: number;
  comments: number;
  shares: number;
  saved: number;
};

export type MediaMonthlyResponse = {
  ok: boolean;
  client_id: string;
  connection_id?: string | null;
  days: number;
  start?: string;
  end?: string;
  months: MediaMonthlyItem[];
};

export type PaidTotals = {
  spend: number;
  impressions: number;
  reach: number;
  clicks: number;
  cpc: number;
  cpm: number;
  ctr: number;
  conversions: number;
  revenue: number;
  roas: number;
};

export type PaidManagerMetrics = {
  link_clicks: number;
  video_views: number;
  page_engagement: number;
  post_engagement: number;
  profile_visits: number;
};

export type PaidDashboardResponse = {
  ok: boolean;
  client_id: string;
  connection_id?: string | null;
  connection_status?: MetaConnection | null;
  days: number;
  month?: string | null;
  date_range?: { since: string; until: string };
  has_data?: boolean;
  message?: string;
  row_count?: number;
  first_stat_date?: string | null;
  last_stat_date?: string | null;
  daily: Array<{ date: string } & PaidTotals>;
  totals: PaidTotals;
  manager_metrics?: PaidManagerMetrics;
  accounts: Array<{
    ad_account_id: string;
    ad_account_name?: string;
  } & PaidTotals>;
  top_creatives?: Array<
    {
      ad_id: string;
      ad_name?: string | null;
      post_id?: string | null;
      story_id?: string | null;
      source_platform?: string | null;
      campaign_id?: string | null;
      campaign_name?: string | null;
      adset_id?: string | null;
      adset_name?: string | null;
    } & PaidTotals
  >;
  top_boosted_posts?: Array<
    {
      ad_id: string;
      ad_name?: string | null;
      post_id?: string | null;
      story_id?: string | null;
      source_platform?: string | null;
      campaign_id?: string | null;
      campaign_name?: string | null;
      adset_id?: string | null;
      adset_name?: string | null;
    } & PaidTotals
  >;
  sources?: {
    mode_account?: string;
    mode_ad?: string;
    mode_promoted?: string;
    rows?: {
      ad_account_daily_stats?: number;
      ad_daily_stats?: number;
      promoted_post_daily_stats?: number;
      promoted_post_unique?: number;
      aggregated_rows?: number;
    };
    totals?: {
      classic_ads?: PaidTotals;
      boosted_posts?: PaidTotals;
      consolidated?: PaidTotals;
    };
    manager_metrics?: {
      classic_ads?: PaidManagerMetrics;
      boosted_posts?: PaidManagerMetrics;
      consolidated?: PaidManagerMetrics;
    };
  };
};
