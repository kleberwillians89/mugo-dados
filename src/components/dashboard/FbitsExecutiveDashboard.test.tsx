// @vitest-environment jsdom
import { act } from "react";
import { createRoot } from "react-dom/client";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import type { FbitsOrdersResponse, FbitsOrdersSummaryResponse } from "../../app/types";

globalThis.IS_REACT_ACT_ENVIRONMENT = true;

vi.mock("recharts", () => ({
  ResponsiveContainer: ({ children }: { children: React.ReactNode }) => <div>{children}</div>,
  ComposedChart: ({ children }: { children: React.ReactNode }) => <div>{children}</div>,
  Area: () => null,
  Bar: () => null,
  CartesianGrid: () => null,
  Line: () => null,
  Tooltip: () => null,
  XAxis: () => null,
  YAxis: () => null,
}));

import FbitsExecutiveDashboard from "./FbitsExecutiveDashboard";

const data: FbitsOrdersSummaryResponse = {
  ok: true,
  connected: true,
  client_id: "vinhos",
  period: { start: "2026-09-01", end: "2026-09-30" },
  summary: { receita_oficial: 200, pedidos: 1, ticket_medio: 200, clientes: 1, produtos_vendidos: 2, descontos: 20, frete: 12 },
  comparison: {
    receita_oficial: { current: 200, previous: 0, change_percent: null },
    pedidos: { current: 1, previous: 0, change_percent: null },
    ticket_medio: { current: 200, previous: 0, change_percent: null },
  },
  status_distribution: [
    { status: "Pago", status_id: "1", pedidos: 1, valor: 200, counts_as_revenue: true, invalid_orders: 0 },
    { status: "Cancelado", status_id: "3", pedidos: 1, valor: 900, counts_as_revenue: false, invalid_orders: 1 },
  ],
  trend: { granularity: "day", items: [{ date: "2026-09-01", revenue: 200, orders: 1, average_ticket: 200 }] },
};

const orders: FbitsOrdersResponse = {
  ok: true,
  connected: true,
  client_id: "vinhos",
  period: data.period,
  count: 1,
  detail_available: true,
  items: [{ pedido_id: "1", pedido_codigo: "PED-1", situacao_pedido_id: 1, situacao_pedido: "Pago", data: "2026-09-01T12:00:00Z", data_pagamento: "2026-09-05T12:00:00Z", receita_oficial: 200, produtos_vendidos: 2, cliente_id: "cliente-1" }],
  top_products: [{ product_id: "wine", sku: "VINHO-1", produto: "Vinho Tinto", quantidade: 2, receita: 100 }],
};

describe("FbitsExecutiveDashboard", () => {
  let container: HTMLDivElement;
  let root: ReturnType<typeof createRoot>;

  beforeEach(() => {
    container = document.createElement("div");
    document.body.appendChild(container);
    root = createRoot(container);
  });

  afterEach(async () => {
    await act(async () => root.unmount());
    container.remove();
  });

  it("mostra KPIs, comparação sem falso 0%, cancelados e produtos", async () => {
    await act(async () => root.render(<FbitsExecutiveDashboard data={data} orders={orders} loading={false} error={null} />));
    const content = container.textContent?.replace(/\u00a0/g, " ") || "";
    expect(content).toContain("R$ 200,00");
    // Sem base anterior: "—" com explicação acessível, nunca um 0% falso.
    for (const kpi of ["kpi-receita", "kpi-pedidos", "kpi-ticket"]) {
      const delta = container.querySelector(`[data-testid="${kpi}"] .ds-delta`)?.textContent || "";
      expect(delta).toContain("—");
      expect(delta).toContain("sem base de comparação");
      expect(delta).not.toMatch(/\d%/);
    }
    // Valor abreviado para leitura, exato preservado.
    const revenue = container.querySelector('[data-testid="kpi-receita"] data');
    expect(revenue?.textContent?.replace(/\u00a0/g, " ")).toBe("R$ 200");
    expect(revenue?.getAttribute("title")?.replace(/\u00a0/g, " ")).toBe("R$ 200,00");
    expect(content).toContain("Cancelados / inválidos1");
    expect(content).toContain("Vinho Tinto");
    expect(content).toContain("50%");
    expect(content).toContain("PED-1");
  });

  it("variações derivam só da comparação disponível", async () => {
    const compared: FbitsOrdersSummaryResponse = {
      ...data,
      comparison: {
        receita_oficial: { current: 200, previous: 160, change_percent: 25 },
        pedidos: { current: 1, previous: 2, change_percent: -50 },
        ticket_medio: { current: 200, previous: 199, change_percent: 0.5 },
      },
    };
    await act(async () => root.render(<FbitsExecutiveDashboard data={compared} orders={orders} loading={false} error={null} />));
    const revenueDelta = container.querySelector('[data-testid="kpi-receita"] .ds-delta');
    expect(revenueDelta?.className).toContain("is-positive");
    // Dado principal: referência escrita por extenso (uma vez na página) e
    // direção anunciada para leitor de tela.
    expect(revenueDelta?.textContent).toContain("↑");
    expect(revenueDelta?.querySelector(".ds-deltaValue")?.textContent).toBe("25%");
    expect(revenueDelta?.textContent).toContain("em relação ao período anterior");
    expect(revenueDelta?.querySelector(".ds-srOnly")?.textContent).toBe("alta de ");
    // Nos KPIs secundários a referência não se repete visualmente.
    expect(container.querySelector('[data-testid="kpi-pedidos"]')?.textContent).not.toContain("em relação ao");
    const ordersDelta = container.querySelector('[data-testid="kpi-pedidos"] .ds-delta');
    expect(ordersDelta?.className).toContain("is-negative");
    expect(ordersDelta?.textContent).toContain("↓50%");
    // Variação abaixo de 1 p.p. não ganha cor (só seta e número).
    const ticketDelta = container.querySelector('[data-testid="kpi-ticket"] .ds-delta');
    expect(ticketDelta?.className).not.toMatch(/is-positive|is-negative/);
    expect(ticketDelta?.textContent).toContain("↑0,5%");
  });

  it("distingue período sem vendas de integração desconectada", async () => {
    const empty = { ...data, summary: { ...data.summary, receita_oficial: 0, pedidos: 0, ticket_medio: 0 }, trend: { granularity: "day" as const, items: [] } };
    await act(async () => root.render(<FbitsExecutiveDashboard data={empty} orders={{ ...orders, count: 0, items: [], top_products: [] }} loading={false} error={null} />));
    expect(container.textContent).toContain("Não houve vendas neste período.");
    expect(container.textContent).not.toContain("FBITS ainda não conectado");
  });

  it("primeira sincronização pendente: sem zeros nem 'não houve vendas'", async () => {
    const empty = { ...data, summary: { ...data.summary, receita_oficial: 0, pedidos: 0, ticket_medio: 0 }, trend: { granularity: "day" as const, items: [] } };
    await act(async () => root.render(
      <FbitsExecutiveDashboard data={empty} orders={{ ...orders, count: 0, items: [], top_products: [] }} loading={false} error={null} syncPending />,
    ));
    expect(container.textContent).not.toContain("Não houve vendas neste período.");
    expect(container.querySelector('[data-testid="kpi-receita"]')).toBeNull();
  });

  it("título do gráfico aponta o pico só quando ele é único (não repete a receita)", async () => {
    const trend = {
      granularity: "day" as const,
      items: [
        { date: "2026-09-11", revenue: 120, orders: 1, average_ticket: 120 },
        { date: "2026-09-12", revenue: 520, orders: 3, average_ticket: 173.33 },
        { date: "2026-09-13", revenue: 80, orders: 1, average_ticket: 80 },
      ],
    };
    await act(async () => root.render(<FbitsExecutiveDashboard data={{ ...data, trend }} orders={orders} loading={false} error={null} />));
    expect(container.querySelector("#fbits-trend-title")?.textContent).toBe("12 de setembro concentrou o maior volume de vendas");
    expect(container.querySelector("#fbits-trend-title")?.textContent).not.toContain("R$");

    const tied = { ...trend, items: trend.items.map((item) => ({ ...item, revenue: 300 })) };
    await act(async () => root.render(<FbitsExecutiveDashboard data={{ ...data, trend: tied }} orders={orders} loading={false} error={null} />));
    expect(container.querySelector("#fbits-trend-title")?.textContent).toBe("Vendas ao longo do período");
  });

  it("legenda só fala em variação quando há base de comparação", async () => {
    const withPrevious = { ...data, previous_period: { start: "2026-08-02", end: "2026-08-31" } };
    await act(async () => root.render(<FbitsExecutiveDashboard data={withPrevious} orders={orders} loading={false} error={null} />));
    expect(container.textContent).toContain("Sem base de comparação em 02/08/2026–31/08/2026.");
    expect(container.textContent).not.toContain("Variação comparada a");
  });
});
