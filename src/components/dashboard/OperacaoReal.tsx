import type { ExecutiveDashboardResponse } from "../../app/types";

type Props = {
  data: ExecutiveDashboardResponse | null;
  loading?: boolean;
  error?: string | null;
};

function currency(value: number | null | undefined): string {
  if (value == null) return "Sem dados";
  return value.toLocaleString("pt-BR", { style: "currency", currency: "BRL", maximumFractionDigits: 2 });
}

function integer(value: number | null | undefined): string {
  if (value == null) return "Sem dados";
  return value.toLocaleString("pt-BR");
}

function ratio(value: number | null | undefined): string {
  if (value == null) return "Sem dados";
  return `${value.toFixed(2)}x`;
}

// "Retorno sobre mídia conectada" quando só temos Meta persistido; "Retorno
// real sobre mídia" só quando Meta + Google Ads entrarem na soma — nunca
// apresentar um blended parcial como se fosse o total real de mídia paga.
function blendedRoasLabel(includedSources: string[]): string {
  const hasMeta = includedSources.includes("meta");
  const hasGoogle = includedSources.includes("google_ads");
  if (hasMeta && hasGoogle) return "Retorno real sobre mídia";
  if (hasMeta || hasGoogle) return "Retorno sobre mídia conectada";
  return "Retorno sobre mídia";
}

function sourceLabel(source: string): string {
  if (source === "meta") return "Meta";
  if (source === "google_ads") return "Google Ads";
  return source;
}

function todayIso(): string {
  return new Date().toISOString().slice(0, 10);
}

export default function OperacaoReal({ data, loading = false, error = null }: Props) {
  const shopify = data?.shopify ?? null;
  const totalPaidMedia = data?.total_paid_media ?? null;
  const includedSources = totalPaidMedia?.included_paid_sources ?? [];
  const today = todayIso();
  const periodIncludesToday = Boolean(data?.period && data.period.start <= today && data.period.end >= today);
  const todayRow = periodIncludesToday ? (data?.daily || []).find((row) => row.date === today) ?? null : null;

  if (loading && !data) {
    return (
      <section className="operacaoReal" aria-labelledby="operacao-real-title">
        <div className="executiveSkeleton" aria-label="Carregando operação real" />
      </section>
    );
  }

  if (!shopify?.connected) {
    return null;
  }

  const roasLabel = blendedRoasLabel(includedSources);
  const sourcesDetail = includedSources.length
    ? `Inclui: ${includedSources.map(sourceLabel).join(" + ")}`
    : "Nenhuma fonte de mídia paga conectada neste período";

  return (
    <section className="operacaoReal" aria-labelledby="operacao-real-title">
      <header className="operacaoRealHead">
        <span className="executiveEyebrow">Operação real</span>
        <h2 id="operacao-real-title">Receita real do e-commerce</h2>
      </header>

      {error ? <div className="executiveNotice isError">Não foi possível atualizar a operação real. A última leitura válida foi preservada.</div> : null}

      {periodIncludesToday ? (
        <div className="operacaoRealToday">
          <div className="operacaoRealTodayHead">
            <span className="executiveEyebrow">Hoje</span>
            <span className="operacaoRealTodayNotice">Os dados de hoje ainda podem sofrer alterações.</span>
          </div>
          <div className="operacaoRealTodayGrid">
            <div className="operacaoRealMetric">
              <span>Receita ecommerce</span>
              <strong>{currency(todayRow?.shopify?.net_revenue)}</strong>
            </div>
            <div className="operacaoRealMetric">
              <span>Investimento Meta</span>
              <strong>{currency(todayRow?.meta?.spend)}</strong>
            </div>
            <div className="operacaoRealMetric">
              <span>ROAS Meta</span>
              <strong>{ratio(todayRow?.meta?.roas)}</strong>
            </div>
            <div className="operacaoRealMetric">
              <span>Pedidos</span>
              <strong>{integer(todayRow?.shopify?.orders)}</strong>
            </div>
            <div className="operacaoRealMetric">
              <span>Ticket médio</span>
              <strong>{currency(todayRow?.shopify?.average_order_value)}</strong>
            </div>
          </div>
        </div>
      ) : null}

      <div className="operacaoRealGrid">
        <div className="operacaoRealMetric">
          <span>Receita real (líquida)</span>
          <strong>{currency(shopify.net_revenue)}</strong>
        </div>
        <div className="operacaoRealMetric">
          <span>Pedidos</span>
          <strong>{integer(shopify.orders)}</strong>
        </div>
        <div className="operacaoRealMetric">
          <span>Ticket médio</span>
          <strong>{currency(shopify.average_order_value)}</strong>
        </div>
        <div className="operacaoRealMetric">
          <span>Investimento em mídia</span>
          <strong>{currency(totalPaidMedia?.paid_media_spend ?? null)}</strong>
        </div>
        <div className="operacaoRealMetric" title={sourcesDetail}>
          <span>{roasLabel}</span>
          <strong>{ratio(totalPaidMedia?.blended_roas ?? null)}</strong>
          <small>{sourcesDetail}</small>
        </div>
      </div>
    </section>
  );
}
