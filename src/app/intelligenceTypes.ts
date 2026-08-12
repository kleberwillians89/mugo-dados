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
  historical_context?: {
    coverage_start: string | null;
    coverage_end: string | null;
    monthly_summary: Array<Record<string, unknown>>;
    source_coverage: Record<string, { start: string | null; end: string | null }>;
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
