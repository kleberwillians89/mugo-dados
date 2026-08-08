// @vitest-environment jsdom

import React, { act } from "react";
import { createRoot } from "react-dom/client";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";

globalThis.IS_REACT_ACT_ENVIRONMENT = true;

vi.mock("../app/activeClient", () => ({
  getActiveClientId: () => "amalie",
  getActiveClientName: () => "Amalie",
  MUGO_APP_NAME: "Mugô Dados",
}));

vi.mock("../app/PeriodContext", () => ({
  usePeriod: () => ({
    period: { start: "2026-08-01", end: "2026-08-31" },
    periodDays: 31,
    setCurrentMonthPeriod: () => {},
    setMonthPeriod: () => {},
    setPresetPeriod: () => {},
  }),
}));

const report = {
  ok: true,
  client_id: "amalie",
  shop_domain: "amalie.myshopify.com",
  period: { start: "2026-08-01", end: "2026-08-31", days: 31 },
  summary: {
    revenue_total: 15000,
    orders: 40,
    average_ticket: 375,
    customers: 30,
    paid_orders: 38,
    cancelled_orders: 1,
    refunds_count: 1,
    refunded_amount: 100,
  },
  trends: { daily: [{ date: "2026-08-01", revenue: 500, orders: 2, customers: 2, average_ticket: 250 }] },
  recent_orders: [],
  top_products: [{ title: "Produto A", quantity_sold: 10, revenue: 1000 }],
  technical: { processed_count: 10, error_count: 0, recent_errors: [], recent_webhooks: [] },
};

const customers = {
  ok: true,
  client_id: "amalie",
  period: { start: "2026-08-01", end: "2026-08-31", days: 31 },
  count: 2,
  summary: { total_customers: 2, recurring_customers: 1, multi_order_customers: 1, top_customer: null },
  items: [
    { customer_key: "c1", name: "Cliente A", total_orders: 3, total_spent: 900, average_ticket: 300, status: "recurring" as const, all_time_orders: 3 },
    { customer_key: "c2", name: "Cliente B", total_orders: 1, total_spent: 200, average_ticket: 200, status: "new" as const, all_time_orders: 1 },
  ],
};

vi.mock("../app/api", async (importOriginal) => {
  const actual = await importOriginal<typeof import("../app/api")>();
  return {
    ...actual,
    getShopifyReport: vi.fn(async () => report),
    getShopifyCustomers: vi.fn(async () => customers),
    resolveShopifyConnectionIdForRead: vi.fn(async () => "8e1780ef-17b0-4b0a-843e-f8c323141412"),
    syncShopifyConnection: vi.fn(async () => ({ ok: true })),
  };
});

import Shopify from "./Shopify";
import { ApiError, getShopifyCustomers, getShopifyReport, syncShopifyConnection } from "../app/api";

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
  vi.clearAllMocks();
});

function clickRefreshButton() {
  const button = container.querySelector<HTMLButtonElement>(".shopifyRefreshButton");
  return act(async () => {
    button?.dispatchEvent(new MouseEvent("click", { bubbles: true, cancelable: true }));
    await Promise.resolve();
    await Promise.resolve();
    await Promise.resolve();
  });
}

async function renderShopify() {
  await act(async () => {
    root.render(<Shopify onLogout={() => {}} onOpenDashboard={() => {}} onOpenGoogleReport={() => {}} />);
  });
  for (let i = 0; i < 5; i += 1) {
    await act(async () => {
      await Promise.resolve();
    });
  }
}

describe("Shopify — atribuição sem soma indevida", () => {
  it("mostra a receita real da loja e nunca soma plataformas diferentes", async () => {
    await renderShopify();
    expect(container.textContent).toContain("Shopify, Meta, GA4 e Google Ads");
    expect(container.textContent).toContain(
      "Essas plataformas utilizam modelos de atribuição diferentes. Os valores não devem ser somados."
    );
  });

  it("mostra a distribuição de novos × recorrentes com base nos clientes filtrados", async () => {
    await renderShopify();
    expect(container.textContent).toContain("Novos — 1");
    expect(container.textContent).toContain("Recorrentes — 1");
  });

  it("regressão: filtros vazios (valor máximo, pedidos mínimos) não escondem clientes com gasto positivo", async () => {
    await renderShopify();
    // Antes da correção, "Valor máximo" e "Pedidos mínimos" vazios eram
    // tratados como 0 (Number("")===0), filtrando toda a base por padrão.
    expect(container.textContent).toContain("Total de clientes2");
    expect(container.textContent).not.toContain("Nenhum cliente encontrado com os filtros atuais.");
  });
});

describe("Shopify — botão 'Atualizar dados' dispara sync real antes de reler", () => {
  it("clicar chama syncShopifyConnection exatamente 1 vez, com o connection_id resolvido e days=60", async () => {
    await renderShopify();
    await clickRefreshButton();

    expect(syncShopifyConnection).toHaveBeenCalledTimes(1);
    expect(syncShopifyConnection).toHaveBeenCalledWith("8e1780ef-17b0-4b0a-843e-f8c323141412", 60);
  });

  it("após o sync (200), relê report e customers", async () => {
    await renderShopify();
    vi.mocked(getShopifyReport).mockClear();
    vi.mocked(getShopifyCustomers).mockClear();

    await clickRefreshButton();

    expect(getShopifyReport).toHaveBeenCalledTimes(1);
    expect(getShopifyCustomers).toHaveBeenCalledTimes(1);
  });

  it("409 SYNC_ALREADY_RUNNING vira aviso neutro, não erro vermelho, e ainda relê os dados", async () => {
    await renderShopify();
    vi.mocked(syncShopifyConnection).mockRejectedValueOnce(
      new ApiError("conflict", { status: 409, code: "SYNC_ALREADY_RUNNING" })
    );
    vi.mocked(getShopifyReport).mockClear();

    await clickRefreshButton();

    expect(container.textContent).toContain("Importação já está em andamento.");
    expect(container.querySelector(".shopifyFeedbackCard.isError")?.textContent || "").not.toContain(
      "Importação já está em andamento."
    );
    expect(getShopifyReport).toHaveBeenCalledTimes(1);
  });

  it("erro real do sync preserva os dados antigos na tela e mostra mensagem humana, sem reler", async () => {
    await renderShopify();
    expect(container.textContent).toContain("Produto A"); // dado já carregado
    vi.mocked(syncShopifyConnection).mockRejectedValueOnce(
      new ApiError("upstream failed", { status: 502, code: "SHOPIFY_SYNC_UNEXPECTED_ERROR" })
    );
    vi.mocked(getShopifyReport).mockClear();

    await clickRefreshButton();

    expect(getShopifyReport).not.toHaveBeenCalled();
    // Dado antigo continua visível — nunca zera o relatório por causa do erro de sync.
    expect(container.textContent).toContain("Produto A");
  });
});
