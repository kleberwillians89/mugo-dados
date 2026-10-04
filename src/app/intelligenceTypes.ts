export type IntelligenceMetricStatus =
  | "confirmed"
  | "unavailable"
  | "disconnected"
  | "partial"
  | "error";

export type IntelligenceMetric = {
  id: string;
  label: string;
  value: number | null;
  format: "currency" | "percent" | "decimal" | "integer";
  status: IntelligenceMetricStatus;
  source: string;
  previous_value: number | null;
  variation_percent: number | null;
};

export type IntelligenceSource = {
  id: string;
  label: string;
  status: "available" | "partial" | "no_data" | "disconnected" | "error";
  connected: boolean;
  data_points: number;
  covered_days: number | null;
  last_sync_at: string | null;
};

/** Item de pesquisa externa. Só é exibido com evidência verificável. */
export type ExternalResearchItem = {
  kind: "CONTENT_REFERENCE" | "POTENTIAL_UGC_CREATOR";
  handle: string | null;
  platform: string | null;
  profile_url: string | null;
  category: string | null;
  reason_relevant: string | null;
  observed_format: string | null;
  public_signal: string | null;
  source_url: string | null;
  researched_at: string | null;
};

export type IntelligenceSnapshot = {
  client: { id: string; name: string };
  period: {
    start: string;
    end: string;
    days: number;
    previous_start: string;
    previous_end: string;
  };
  sources: IntelligenceSource[];
  quality: {
    score: number;
    status: "good" | "partial" | "limited";
    available_sources: number;
    total_sources: number;
    errors: number;
    message: string;
  };
  last_sync_at: string | null;
  metrics: IntelligenceMetric[];
  crossings: Array<{
    id: string;
    label: string;
    sources: string[];
    status: "available" | "insufficient_data";
    note: string;
    metrics: string[];
    funnel?: Record<string, number | string>;
  }>;
  top_campaigns: Array<{
    name: string;
    spend: number;
    revenue: number;
    conversions: number;
  }>;
  /** Provider de e-commerce resolvido pela conexão do tenant, com procedência. */
  commerce_context?: {
    provider: "fbits" | "shopify" | null;
    provider_label: string | null;
    connected: boolean;
    status: string;
    kpi_source: string | null;
    official_kpis: boolean;
    provenance?: Record<string, string | null>;
    ambiguous?: boolean;
    active_providers?: string[];
  };
  business_context?: {
    available: boolean;
    context: Record<string, string | null>;
    updated_at?: string | null;
  };
  /** Pesquisa externa: sem provider real vem "not_configured" e nada é exibido. */
  external_research?: {
    status: "ok" | "not_configured" | "unavailable";
    provider: string | null;
    market_signals: ExternalResearchItem[];
    content_references: ExternalResearchItem[];
    ugc_creators: ExternalResearchItem[];
  };
  historical_context?: {
    coverage_start: string | null;
    coverage_end: string | null;
    monthly_summary: Array<Record<string, unknown>>;
    source_coverage: Record<string, { start: string | null; end: string | null }>;
    instagram_account_context?: Record<string, unknown>;
    instagram_content_context?: Record<string, unknown>;
    instagram_story_context?: Record<string, unknown>;
  };
};

export type IntelligenceInsight = {
  category: "opportunity" | "attention" | "risk" | "positive" | "anomaly" | "data_quality";
  title: string;
  interpretation: string;
  metric_ids: string[];
  sources: string[];
  impact: "high" | "medium" | "low";
  confidence: "high" | "medium" | "low";
  action: string;
  reason: string;
};

export type IntelligenceAction = {
  priority: "now" | "week" | "monitor" | "investigate";
  recommendation: string;
  justification: string;
  sources: string[];
  impact_expected: string;
  confidence: "high" | "medium" | "low";
  metric_id: string;
};

export type IntelligenceAnalysisContent = {
  executive: {
    overall: string;
    main_change: string;
    opportunity: string;
    attention: string;
    priority_action: string;
  };
  insights: IntelligenceInsight[];
  actions: IntelligenceAction[];
};

export type IntelligenceAnalysisRecord = {
  id: string;
  client_id: string;
  period_start: string;
  period_end: string;
  status: "completed" | "configuration_pending" | "failed";
  provider: string | null;
  model: string | null;
  sources: IntelligenceSource[];
  data_quality: IntelligenceSnapshot["quality"];
  metrics_snapshot: IntelligenceMetric[];
  analysis: IntelligenceAnalysisContent | null;
  error_code: string | null;
  created_at: string;
  completed_at: string | null;
};

export type IntelligenceAnswer = {
  direct_answer: string;
  metric_ids: string[];
  evidence: string[];
  attention_points: string[];
  recommendations: string[];
  next_steps: string[];
};

export type IntelligenceMessage = {
  id: string;
  role: "user" | "assistant";
  content: { question?: string } & Partial<IntelligenceAnswer>;
  period_start: string;
  period_end: string;
  sources: IntelligenceSource[];
  created_at: string;
};

/** Customer 360: contrato único, independente do provider de e-commerce. */
export type CustomerSummary = {
  id: string;
  external_id: string | null;
  client_id: string;
  provider: "fbits" | "shopify";
  provider_label: string;
  identity_kind: "external_id" | "email" | "phone";
  name: string | null;
  email: string | null;
  phone: string | null;
  orders_count: number;
  total_revenue: number;
  average_ticket: number | null;
  first_order_at: string | null;
  last_order_at: string | null;
  status: "recurring" | "single" | "no_purchase";
};

export type CustomerBaseTotals = {
  customers: number;
  recurring_customers: number;
  buyers: number;
  total_revenue: number;
  total_orders: number;
  average_ticket: number | null;
};

export type CustomerListResponse = {
  ok: true;
  client_id: string;
  provider: "fbits" | "shopify" | null;
  provider_label: string | null;
  connected: boolean;
  totals: CustomerBaseTotals;
  customers: CustomerSummary[];
  page: number;
  page_size: number;
  total: number;
  truncated: boolean;
  contact_details_available: boolean;
  orders_unattributed: number;
};

export type CustomerOrder = {
  order_id: string;
  reference: string;
  happened_at: string | null;
  value: number;
  status: string | null;
  counts_as_revenue: boolean;
};

export type CustomerDetailResponse = {
  ok: true;
  client_id: string;
  customer: CustomerSummary;
  orders: CustomerOrder[];
};
