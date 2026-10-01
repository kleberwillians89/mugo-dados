// @vitest-environment jsdom
import { act } from "react";
import { createRoot } from "react-dom/client";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import type { FbitsOrdersResponse, FbitsOrdersSummaryResponse } from "../../app/types";

globalThis.IS_REACT_ACT_ENVIRONMENT = true;

vi.mock("recharts", () => ({
  ResponsiveContainer: ({ children }: { children: React.ReactNode }) => <div>{children}</div>,
  ComposedChart: ({ children }: { children: React.ReactNode }) => <div>{children}</div>,
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
    expect(content).toContain("— vs. período anterior");
    expect(content).not.toContain("0% vs. período anterior");
    expect(content).toContain("Cancelados / inválidos1");
    expect(content).toContain("Vinho Tinto");
    expect(content).toContain("50%");
    expect(content).toContain("PED-1");
  });

  it("distingue período sem vendas de integração desconectada", async () => {
    const empty = { ...data, summary: { ...data.summary, receita_oficial: 0, pedidos: 0, ticket_medio: 0 }, trend: { granularity: "day" as const, items: [] } };
    await act(async () => root.render(<FbitsExecutiveDashboard data={empty} orders={{ ...orders, count: 0, items: [], top_products: [] }} loading={false} error={null} />));
    expect(container.textContent).toContain("Não houve vendas neste período.");
    expect(container.textContent).not.toContain("FBITS ainda não conectado");
  });
});
