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

function todayIso(): string {
  return new Intl.DateTimeFormat("en-CA", {
    timeZone: "America/Sao_Paulo",
    year: "numeric",
    month: "2-digit",
    day: "2-digit",
  }).format(new Date());
}

function formatCivilDate(value: string): string {
  const [year, month, day] = value.split("-").map(Number);
  return new Intl.DateTimeFormat("pt-BR", {
    day: "2-digit",
    month: "2-digit",
    year: "numeric",
    timeZone: "America/Sao_Paulo",
  }).format(new Date(Date.UTC(year, month - 1, day, 12)));
}

export default function OperacaoReal({ data, loading = false, error = null }: Props) {
  const shopify = data?.shopify ?? null;
  const today = todayIso();
  const periodIncludesToday = Boolean(data?.period && data.period.start <= today && data.period.end >= today);
  const todayRow = periodIncludesToday ? (data?.daily || []).find((row) => row.date === today) ?? null : null;
  const todayCovered = Boolean(shopify?.data_max_available && shopify.data_max_available >= today);

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

  return (
    <section className="operacaoReal" aria-labelledby="operacao-real-title">
      <header className="operacaoRealHead">
        <span className="executiveEyebrow">Operação Shopify</span>
        <h2 id="operacao-real-title">Receita real da loja</h2>
      </header>

      {error ? <div className="executiveNotice isError">Não foi possível atualizar a operação real. A última leitura válida foi preservada.</div> : null}

      {periodIncludesToday ? (
        <div className="operacaoRealToday">
          <div className="operacaoRealTodayHead">
            <div>
              <span className="executiveEyebrow">Hoje</span>
              <strong className="operacaoRealDate">{formatCivilDate(today)}</strong>
            </div>
            <span className="operacaoRealTodayNotice">
              {todayCovered ? "Os dados de hoje ainda podem sofrer alterações." : "Ainda não atualizado hoje"}
            </span>
          </div>
          <div className="operacaoRealTodayGrid">
            <div className="operacaoRealMetric">
              <span>Receita real</span>
              <strong>{todayCovered ? currency(todayRow?.shopify?.net_revenue ?? 0) : "Ainda não atualizado"}</strong>
            </div>
            <div className="operacaoRealMetric">
              <span>Pedidos</span>
              <strong>{todayCovered ? integer(todayRow?.shopify?.orders ?? 0) : "Ainda não atualizado"}</strong>
            </div>
            <div className="operacaoRealMetric">
              <span>Ticket médio</span>
              <strong>{todayCovered ? currency(todayRow?.shopify?.average_order_value ?? 0) : "Ainda não atualizado"}</strong>
            </div>
          </div>
        </div>
      ) : null}

      <div className="operacaoRealPeriod">
        <div className="operacaoRealPeriodHead">
          <span className="executiveEyebrow">Período selecionado</span>
          <strong className="operacaoRealDate">
            {formatCivilDate(data!.period.start)} — {formatCivilDate(data!.period.end)}
          </strong>
        </div>
        <div className="operacaoRealGrid">
        <div className="operacaoRealMetric">
          <span>Receita real</span>
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
        </div>
      </div>
    </section>
  );
}
