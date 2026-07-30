/**
 * Tipos para relatórios dinâmicos (Junho em diante)
 * 
 * Separação clara:
 * - FBitsMetrics = fonte oficial de vendas
 * - Ga4Metrics = fonte de atribuição/origem
 */

export type FbitsMetrics = {
  receita_oficial: number;
  pedidos: number;
  ticket_medio: number;
  clientes: number;
  produtos_vendidos: number;
  daily?: Array<{
    data: string;
    receita: number;
    pedidos: number;
    clientes: number;
  }>;
};

export type Ga4Metrics = {
  sessions: number;
  active_users: number;
  purchases: number;
  purchase_revenue: number;
  channels: Array<{
    source_medium: string;
    sessions: number;
    purchases: number;
    revenue: number;
  }>;
};

export type DynamicMonthReport = {
  month: string; // "YYYY-MM"
  period: {
    start: string; // "YYYY-MM-DD"
    end: string; // "YYYY-MM-DD"
  };
  
  // Fonte oficial de vendas
  fbits: FbitsMetrics;
  
  // Atribuição e origem do tráfego
  ga4: Ga4Metrics;
  
  // Comparação com período anterior
  comparison?: {
    previous_month: string;
    fbits_growth_percent: number;
    customers_growth_percent: number;
  };
  
  // Insights gerados
  insights?: string[];
};

export type DynamicReportResponse = {
  ok: boolean;
  client_id: string;
  data: DynamicMonthReport;
  generated_at: string;
  message?: string;
};
