// @vitest-environment jsdom

import React, { act } from "react";
import { createRoot } from "react-dom/client";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import type { Ga4ReportResponse } from "../app/types";

globalThis.IS_REACT_ACT_ENVIRONMENT = true;

vi.mock("../app/activeClient", () => ({
  getActiveClient: () => ({ id: "amalie", name: "Amalie", role: "viewer" }),
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
  getClientIntegrations: vi.fn(async () => ({
    ok: true,
    client_id: "amalie",
    connections: [{
      provider: "google_ads", connection_id: "ads-1", status: "connected", authorization_status: "valid", sync_status: null,
      account: { id: "5927993611", name: "Amalie Ads" },
      assets: { customer_id: "5927993611", customer_name: "Amalie Ads", login_customer_id: "5903562384" },
      last_sync_at: null, last_successful_sync_at: null, last_error: null, updated_at: null,
    }],
  })),
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
    campaigns: [{
      metric_date: "2026-08-10", provider: "google_ads", campaign_id: "c-1", campaign_name: "Pesquisa — marca",
      spend: 100, conversion_value: 450, conversions: 5, impressions: 1000, clicks: 50,
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
  await act(async () => Promise.resolve());
}

function pressed(label: string) {
  return [...container.querySelectorAll("button")].find((el) => el.textContent === label) as HTMLButtonElement;
}

async function click(label: string) {
  await act(async () => {
    pressed(label).dispatchEvent(new MouseEvent("click", { bubbles: true }));
  });
}

// Contrato atualizado na migração visual do GA4 (sem abas Visão geral /
// Aquisição / Comportamento): a leitura principal é linear e só o
// detalhamento alterna entre tabelas — nunca todas ao mesmo tempo.
describe("GoogleAnalytics — GA4 em leitura linear, detalhamento alternado", () => {
  it("mostra todos os 3 canais e as 2 campanhas disponíveis na aquisição", async () => {
    await renderGa4();
    await click("Google Analytics");
    expect(container.querySelectorAll('[data-testid="ga4-top-channels"] li')).toHaveLength(3);
    expect(container.querySelectorAll('[data-testid="ga4-top-campaigns"] li')).toHaveLength(2);
  });

  it("detalhamento começa no dia a dia e não mostra canais, campanhas ou eventos ao mesmo tempo", async () => {
    await renderGa4();
    await click("Google Analytics");
    expect(document.getElementById("google-summary")).toBeTruthy();
    expect(document.getElementById("google-daily")).toBeTruthy();
    expect(document.getElementById("google-channels")).toBeNull();
    expect(document.getElementById("google-events")).toBeNull();
  });

  it("troca o detalhamento para Canais e depois Campanhas, escondendo o anterior", async () => {
    await renderGa4();
    await click("Google Analytics");
    await click("Canais");
    expect(document.getElementById("google-channels")).toBeTruthy();
    expect(document.getElementById("google-daily")).toBeNull();
    await click("Campanhas");
    expect(document.getElementById("google-campaigns")).toBeTruthy();
    expect(document.getElementById("google-channels")).toBeNull();
  });

  it("mostra o funil só quando o GA4 traz as etapas; sem eventos, não oferece a aba Eventos", async () => {
    await renderGa4();
    await click("Google Analytics");
    expect(document.getElementById("google-funnel")?.textContent).toContain("Adicionou ao carrinho");
    expect(pressed("Eventos")).toBeUndefined();
    expect(document.getElementById("google-behavior")).toBeNull();
  });

  it("com eventos e grupos, a aba Eventos mostra a tabela e os grupos preenchidos", async () => {
    const previous = { events: report.events, behavior: report.behavior };
    report.events = [{ event_name: "page_view", label: "Visualização de página", event_count: 300, total_users: 80 } as Ga4ReportResponse["events"][number]];
    report.behavior = { ...emptyGroup, title: "Comportamento", total_events: 300, total_users: 80, items: [{ event_name: "page_view", label: "Visualização de página", event_count: 300, total_users: 80 }] } as Ga4ReportResponse["behavior"];
    try {
      await renderGa4();
      await click("Google Analytics");
      await click("Eventos");
      expect(document.getElementById("google-events")?.textContent).toContain("Visualização de página");
      expect(document.getElementById("google-behavior")).toBeTruthy();
      expect(document.getElementById("google-merchandising")).toBeNull();
    } finally {
      report.events = previous.events;
      report.behavior = previous.behavior;
    }
  });

  it("mostra a nota de fonte e o aviso de que os valores de receita seguem a atribuição do GA4", async () => {
    await renderGa4();
    await click("Google Analytics");
    expect(container.textContent).toContain("Fonte: Google Analytics 4");
    expect(container.textContent).toContain("podem diferir da loja e das plataformas de mídia");
  });

  it("usa exclusivamente os campos canônicos do Google Ads no resumo comercial", async () => {
    await renderGa4();
    const commercial = container.querySelector(".googleCommercialSection");
    expect(commercial?.querySelector('[data-testid="google-ads-spend"] data')?.getAttribute("value")).toBe("100");
    expect(commercial?.textContent).toContain("Conversões");
    expect(commercial?.textContent).toContain("Valor de conversão");
    expect(commercial?.textContent).toContain("4,50x");
    expect(commercial?.textContent).toContain("Loja · Shopify");
    expect(commercial?.textContent).toContain("R$\u00a0646,52");
    expect(commercial?.textContent).toContain("R$\u00a0450,00");
    expect(commercial?.textContent).toContain("Pesquisa — marca");
  });

  it("identifica a conta Google Ads e o acesso pela MCC sem campo manual", async () => {
    await renderGa4();
    const account = container.querySelector('[data-testid="google-ads-account"]');
    expect(account?.textContent).toContain("Amalie Ads");
    expect(account?.textContent).toContain("pela conta gerenciadora (MCC)");
    expect(container.querySelector('input[name*="customer"]')).toBeNull();
  });

  it("viewer não vê a ação de atualizar", async () => {
    await renderGa4();
    expect(pressed("Atualizar dados")).toBeUndefined();
  });

  it("o bloco Hoje contém somente vendas, pedidos e ticket", async () => {
    vi.useFakeTimers();
    vi.setSystemTime(new Date("2026-08-11T12:00:00-03:00"));

    try {
      await renderGa4();
      const today = container.querySelector('[aria-label="Resultado Shopify de hoje"]');
      expect(today?.textContent).toContain("Valor vendido hoje");
      expect(today?.textContent).toContain("Pedidos hoje");
      expect(today?.textContent).toContain("Ticket médio hoje");
      expect(today?.textContent).not.toContain("ROAS");
      expect(today?.textContent).not.toContain("Investimento");
      expect(today?.textContent).toContain("Fonte: Shopify");
      expect(today?.textContent).toContain("R$\u00a0646,52");
    } finally {
      vi.useRealTimers();
    }
  });
});
