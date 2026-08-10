import { renderToStaticMarkup } from "react-dom/server";
import { describe, expect, it } from "vitest";
import OperacaoReal from "./OperacaoReal";
import type { ExecutiveDashboardResponse } from "../../app/types";

function todayIso(): string {
  return new Intl.DateTimeFormat("en-CA", {
    timeZone: "America/Sao_Paulo", year: "numeric", month: "2-digit", day: "2-digit",
  }).format(new Date());
}

function baseData(overrides: Partial<ExecutiveDashboardResponse>): ExecutiveDashboardResponse {
  return {
    ok: true,
    client_id: "amalie",
    period: { start: "2026-08-01", end: "2026-08-08", days: 8 },
    shopify: {
      connected: true,
      gross_revenue: 1000,
      net_revenue: 900,
      orders: 10,
      paid_orders: 10,
      cancelled_orders: 0,
      refunds: 1,
      refunded_amount: 100,
      refunds_occurred_in_period_count: 1,
      refunds_occurred_in_period_amount: 100,
      average_order_value: 90,
      new_customers: 3,
      returning_customers: 7,
      daily: [],
    },
    meta: { connected: true, spend: 200, attributed_revenue: 800, roas: 4, daily: [] },
    google_ads: { connected: false, spend: null, attributed_revenue: null, roas: null },
    total_paid_media: { paid_media_spend: 200, included_paid_sources: ["meta"], blended_roas: 4.5 },
    ga4: null,
    daily: [],
    previous_period: null,
    deltas: null,
    ...overrides,
  };
}

describe("OperacaoReal — painel HOJE", () => {
  it("mostra o aviso de dado parcial e os números do dia quando o período inclui hoje", () => {
    const today = todayIso();
    const data = baseData({
      period: { start: today, end: today, days: 1 },
      shopify: { ...baseData({}).shopify!, data_max_available: today },
      daily: [
        {
          date: today,
          shopify: { date: today, gross_revenue: 500, net_revenue: 480, orders: 4, paid_orders: 4, cancelled_orders: 0, refund_amount: 20, average_order_value: 120 },
          meta: { date: today, spend: 100, attributed_revenue: 400, purchases: 3, roas: 4 },
          connected_paid_spend: 100,
          blended_roas: 4.8,
        },
      ],
    });
    const markup = renderToStaticMarkup(<OperacaoReal data={data} />);
    expect(markup).toContain("Os dados de hoje ainda podem sofrer alterações.");
    expect(markup).toMatch(/480,00/);
    expect(markup).toMatch(/100,00/);
    expect(markup).toContain("4.00x");
  });

  it("distingue ausência de cobertura hoje de zero real", () => {
    const today = todayIso();
    const missing = renderToStaticMarkup(<OperacaoReal data={baseData({
      period: { start: today, end: today, days: 1 },
      shopify: { ...baseData({}).shopify!, data_max_available: "2020-01-01" },
    })} />);
    expect(missing).toContain("Ainda não atualizado hoje");
    expect(missing).not.toContain("<span>Receita real</span><strong>Sem dados</strong>");
    expect(missing).not.toContain("<span>Pedidos</span><strong>Sem dados</strong>");

    const coveredZero = renderToStaticMarkup(<OperacaoReal data={baseData({
      period: { start: today, end: today, days: 1 },
      shopify: { ...baseData({}).shopify!, data_max_available: today },
    })} />);
    expect(coveredZero).toMatch(/R\$.*0,00/);
    expect(coveredZero).toContain(">0<");
  });

  it("não mostra o bloco HOJE quando o período selecionado não inclui o dia atual", () => {
    const data = baseData({ period: { start: "2020-01-01", end: "2020-01-07", days: 7 } });
    const markup = renderToStaticMarkup(<OperacaoReal data={data} />);
    expect(markup).not.toContain("Os dados de hoje ainda podem sofrer alterações.");
  });

  it("retorno sobre mídia mostra rótulo correto conforme fontes incluídas", () => {
    const onlyMeta = baseData({});
    const markup = renderToStaticMarkup(<OperacaoReal data={onlyMeta} />);
    expect(markup).toContain("Retorno sobre mídia conectada");
    expect(markup).not.toContain("Retorno real sobre mídia");
  });

  it("sem Shopify conectado, o bloco inteiro não é renderizado", () => {
    const data = baseData({ shopify: { ...baseData({}).shopify!, connected: false } });
    const markup = renderToStaticMarkup(<OperacaoReal data={data} />);
    expect(markup).toBe("");
  });
});
