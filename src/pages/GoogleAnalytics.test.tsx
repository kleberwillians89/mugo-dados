// @vitest-environment jsdom

import React, { act } from "react";
import { createRoot } from "react-dom/client";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import type { Ga4ReportResponse } from "../app/types";

globalThis.IS_REACT_ACT_ENVIRONMENT = true;

vi.mock("../app/activeClient", () => ({
  getActiveClientId: () => "amalie",
  getActiveClientName: () => "Amalie",
  getActiveClientConfigurationWarning: () => null,
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

const emptyGroup = { key: "g", title: "T", description: "D", total_events: 0, total_users: 0, items: [] };

const report: Ga4ReportResponse = {
  ok: true,
  client_id: "amalie",
  property_id: "properties/1",
  period: { start: "2026-08-01", end: "2026-08-31", days: 31 },
  summary: {
    sessions: 100, active_users: 80, total_users: 90, event_count: 500, purchases: 5,
    purchase_revenue: 1000, total_revenue: 1000, average_daily_active_users: 3, average_daily_total_users: 3,
  },
  funnel: { view_item: 10, add_to_cart: 5, begin_checkout: 3, add_payment_info: 2, purchase: 1 },
  commerce_journey: {
    summary: {
      view_item: 10, add_to_cart: 5, begin_checkout: 3, add_payment_info: 2, purchase: 1,
      add_to_cart_rate: 50, checkout_rate: 60, payment_info_rate: 66, purchase_rate: 50, purchase_rate_from_view_item: 10,
    },
    items: [],
  },
  behavior: emptyGroup,
  engagement: emptyGroup,
  merchandising: emptyGroup,
  trends: { daily: [] },
  channels: Array.from({ length: 3 }, (_, index) => ({
    source_medium: `source-${index} / organic`, sessions: 40 - index, active_users: 30 - index,
    total_users: 35 - index, event_count: 100 - index,
  } as Ga4ReportResponse["channels"][number])),
  campaigns: Array.from({ length: 2 }, (_, index) => ({
    campaign_name: `Campaign ${index + 1}`, source_medium: "google / cpc",
    sessions: 20 - index, active_users: 15 - index, total_users: 18 - index, event_count: 50 - index,
  } as Ga4ReportResponse["campaigns"][number])),
  events: [],
  meta: { daily_rows: 0, channel_rows: 3, campaign_rows: 2, event_rows: 0 },
};

vi.mock("../hooks/dashboard/useDashboardGa4", () => ({
  default: () => ({
    ga4Report: report,
    loadingGa4: false,
    refreshingGa4: false,
    ga4Error: null,
    ga4UpdatedAt: "2026-08-31T12:00:00Z",
    reloadGa4: vi.fn(),
  }),
}));

vi.mock("../app/api", () => ({
  syncGa4: vi.fn(),
}));

vi.mock("../components/dashboard/PerformanceChart", () => ({
  default: () => <div data-testid="google-ads-performance-chart" />,
}));

vi.mock("../app/DashboardDataContext", () => ({
  useDashboardSnapshot: () => ({
    daily: [{
      metric_date: "2026-08-10",
      google_ads_spend: 100,
      google_ads_conversion_value: 450,
      google_ads_conversions: 5,
      google_ads_impressions: 1000,
      google_ads_clicks: 50,
      shopify_net_revenue: null,
      shopify_orders: null,
    }, {
      metric_date: "2026-08-11",
      google_ads_spend: null,
      google_ads_conversion_value: null,
      google_ads_conversions: null,
      google_ads_impressions: null,
      google_ads_clicks: null,
      shopify_net_revenue: 646.52,
      shopify_orders: 1,
    }],
    sources: [
      { provider: "google_ads", last_success_at: "2026-08-10T12:00:00Z" },
      { provider: "shopify", last_success_at: "2026-08-11T12:00:00Z", data_min_available: "2026-08-01", data_max_available: "2026-08-11" },
    ],
  }),
}));

import GoogleAnalytics from "./GoogleAnalytics";

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

async function renderGa4() {
  await act(async () => {
    root.render(<GoogleAnalytics onLogout={() => {}} onOpenDashboard={() => {}} isAuthenticated />);
  });
  await act(async () => Promise.resolve());
}

function tabButton(label: string) {
  return [...container.querySelectorAll('[role="tab"]')].find((el) => el.textContent === label) as HTMLButtonElement;
}

describe("GoogleAnalytics — navegação por abas (não mostra tudo simultaneamente)", () => {
  it("mostra todos os 3 canais e as 2 campanhas disponíveis", async () => {
    await renderGa4();
    const lists = container.querySelectorAll(".googleSecondaryGrid .googleListRows");
    expect(lists[0]?.querySelectorAll(".googleListRow")).toHaveLength(3);
    expect(lists[1]?.querySelectorAll(".googleListRow")).toHaveLength(2);
  });

  it("começa em Visão geral e não mostra as seções de Aquisição/Comportamento", async () => {
    await renderGa4();
    expect(document.getElementById("google-summary")).toBeTruthy();
    expect(document.getElementById("google-channels")).toBeNull();
    expect(document.getElementById("google-events")).toBeNull();
  });

  it("troca para Aquisição e mostra Canais/Campanhas, escondendo Visão geral", async () => {
    await renderGa4();
    await act(async () => {
      tabButton("Aquisição").dispatchEvent(new MouseEvent("click", { bubbles: true }));
    });
    expect(document.getElementById("google-channels")).toBeTruthy();
    expect(document.getElementById("google-campaigns")).toBeTruthy();
    expect(document.getElementById("google-summary")).toBeNull();
  });

  it("troca para Comportamento e mostra Funnel/Eventos, escondendo Aquisição", async () => {
    await renderGa4();
    await act(async () => {
      tabButton("Comportamento").dispatchEvent(new MouseEvent("click", { bubbles: true }));
    });
    expect(document.getElementById("google-funnel")).toBeTruthy();
    expect(document.getElementById("google-events")).toBeTruthy();
    expect(document.getElementById("google-behavior")).toBeTruthy();
    expect(document.getElementById("google-merchandising")).toBeTruthy();
    expect(document.getElementById("google-channels")).toBeNull();
  });

  it("mostra a nota de fonte e o aviso de que os valores de receita seguem a atribuição do GA4", async () => {
    await renderGa4();
    expect(container.textContent).toContain("Fonte: Google Analytics 4");
    expect(container.textContent).toContain("podem diferir da loja e das plataformas de mídia");
  });

  it("usa exclusivamente os campos canônicos do Google Ads no resumo comercial", async () => {
    await renderGa4();
    const commercial = container.querySelector(".googleCommercialSection");
    expect(commercial?.textContent).toContain("R$ 646,52");
    expect(commercial?.textContent).toContain("Fonte: Shopify");
    expect(commercial?.textContent).toContain("R$ 450,00");
    expect(commercial?.textContent).toContain("R$ 100,00");
    expect(commercial?.textContent).toContain("4.50x");
    expect(commercial?.textContent).toContain("Receita atribuída");
    expect(commercial?.textContent).toContain("Compras atribuídas5");
  });

  it("o bloco Hoje contém somente vendas, pedidos e ticket", async () => {
    await renderGa4();
    const today = container.querySelector(".channelToday");
    expect(today?.textContent).toContain("Valor vendido hoje");
    expect(today?.textContent).toContain("Pedidos hoje");
    expect(today?.textContent).toContain("Ticket médio hoje");
    expect(today?.textContent).not.toContain("ROAS");
    expect(today?.textContent).not.toContain("Investimento");
    expect(today?.textContent).toContain("Fonte: Shopify");
    expect(today?.textContent).toContain("R$ 646,52");
  });
});
