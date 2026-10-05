// @vitest-environment jsdom
// A página do Google mostra GA4 e campanhas do Google Ads. Atualizar precisa
// sincronizar os dois de forma independente: foi a falta do sync de Ads aqui
// que deixou a Curavino com GA4 do dia e Ads de dois dias antes.
import React, { act } from "react";
import { createRoot } from "react-dom/client";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import type { Ga4ReportResponse } from "../app/types";

globalThis.IS_REACT_ACT_ENVIRONMENT = true;

vi.mock("../app/activeClient", () => ({
  getActiveClient: () => ({ id: "curavino", name: "Curavino", role: "client_admin" }),
  getActiveClientId: () => "curavino",
  getActiveClientName: () => "Curavino",
  getActiveClientConfigurationWarning: () => null,
}));

vi.mock("../app/PeriodContext", () => ({
  usePeriod: () => ({
    period: { start: "2026-09-01", end: "2026-09-30" },
    periodDays: 30,
    setCurrentMonthPeriod: () => {},
    setMonthPeriod: () => {},
    setPresetPeriod: () => {},
  }),
}));

const emptyGroup = { key: "g", title: "T", description: "D", total_events: 0, total_users: 0, items: [] };
const report = {
  ok: true, client_id: "curavino", property_id: "properties/1",
  period: { start: "2026-09-01", end: "2026-09-30", days: 30 },
  summary: {
    sessions: 100, active_users: 80, total_users: 90, event_count: 500, purchases: 5,
    purchase_revenue: 1000, total_revenue: 1000, average_daily_active_users: 3, average_daily_total_users: 3,
  },
  funnel: { view_item: 10, add_to_cart: 5, begin_checkout: 3, add_payment_info: 2, purchase: 1 },
  commerce_journey: { summary: {}, items: [] },
  behavior: emptyGroup, engagement: emptyGroup, merchandising: emptyGroup,
  trends: { daily: [{date:"2026-09-29",sessions:40,active_users:30,total_users:35,event_count:200,ecommerce_purchases:2,purchase_revenue:400,total_revenue:400}, {date:"2026-09-30",sessions:60,active_users:80,total_users:90,event_count:500,ecommerce_purchases:5,purchase_revenue:1000,total_revenue:1000}] }, channels: [], campaigns: [], events: [],
  meta: { daily_rows: 0, channel_rows: 0, campaign_rows: 0, event_rows: 0 },
} as unknown as Ga4ReportResponse;

const hooks = vi.hoisted(() => ({ reloadGa4: vi.fn(), reloadCampaigns: vi.fn() }));
const api = vi.hoisted(() => ({ refreshProviderData: vi.fn(), getClientIntegrations: vi.fn() }));

vi.mock("../hooks/dashboard/useDashboardGa4", () => ({
  default: () => ({
    ga4Report: report, loadingGa4: false, refreshingGa4: false, ga4Error: null,
    ga4UpdatedAt: "2026-10-02T16:07:00Z", reloadGa4: hooks.reloadGa4,
  }),
}));

vi.mock("../hooks/dashboard/useCampaignsRanking", () => ({
  default: () => ({
    campaignsData: { ok: true, client_id: "curavino", date_range: { since: "2026-09-01", until: "2026-09-30" }, campaigns: [], total: 0 },
    loadingCampaigns: false, campaignsError: null, reloadCampaigns: hooks.reloadCampaigns,
  }),
}));

// Mock parcial: ApiError é usado por syncOrchestrator para classificar erros.
vi.mock("../app/api", async (importOriginal) => ({
  ...(await importOriginal<typeof import("../app/api")>()),
  ...api,
}));

vi.mock("../components/data/TrendChart", () => ({
  default: ({ testId }: { testId?: string }) => <div data-testid={testId} />,
}));

vi.mock("../app/DashboardDataContext", () => ({
  useDashboardSnapshot: () => ({
    daily: [], campaigns: [],
    sources: [
      { provider: "google_ads", last_success_at: "2026-09-30T23:20:00Z" },
      { provider: "ga4", last_success_at: "2026-10-02T16:07:00Z" },
    ],
  }),
}));

import GoogleAnalytics from "./GoogleAnalytics";

let container: HTMLDivElement;
let root: ReturnType<typeof createRoot>;

beforeEach(() => {
  Object.values(api).forEach((fn) => fn.mockReset());
  Object.values(hooks).forEach((fn) => fn.mockReset());
  api.getClientIntegrations.mockResolvedValue({
    ok: true,
    client_id: "curavino",
    connections: [
      {
        provider: "google_ads", connection_id: "ads-1", status: "connected", authorization_status: "valid",
        sync_status: null, account: {}, assets: { customer_id: "1234567890" },
        last_sync_at: "2026-09-30T23:20:00Z", last_successful_sync_at: "2026-09-30T23:20:00Z",
        last_error: null, updated_at: null,
      },
      {
        provider: "ga4", connection_id: "ga4-1", status: "connected", authorization_status: "valid",
        sync_status: null, account: {}, assets: { property_id: "properties/1" },
        last_sync_at: "2026-10-02T16:07:00Z", last_successful_sync_at: "2026-10-02T16:07:00Z",
        last_error: null, updated_at: null,
      },
    ],
  });
  api.refreshProviderData.mockResolvedValue({ ok: true });
  container = document.createElement("div");
  document.body.appendChild(container);
  root = createRoot(container);
});

afterEach(async () => {
  await act(async () => root.unmount());
  container.remove();
});

async function render() {
  await act(async () => {
    root.render(<GoogleAnalytics onLogout={() => {}} onOpenDashboard={() => {}} isAuthenticated canSync={false} />);
  });
  await act(async () => Promise.resolve());
  await act(async () => Promise.resolve());
  await act(async () => button("Google Analytics")?.dispatchEvent(new MouseEvent("click", {bubbles:true})));
}

function button(label: string) {
  return [...container.querySelectorAll("button")].find((el) => el.textContent === label) as HTMLButtonElement | undefined;
}

async function refresh() {
  await act(async () => {
    button("Atualizar dados")?.dispatchEvent(new MouseEvent("click", { bubbles: true }));
  });
  await act(async () => Promise.resolve());
  await act(async () => Promise.resolve());
}

describe("GoogleAnalytics — refresh seguro para viewer", () => {
  it("solicita a fachada sem IDs e relê o snapshot", async () => {
    await render();
    await refresh();
    expect(api.refreshProviderData).toHaveBeenCalledExactlyOnceWith("google", { start: "2026-09-01", end: "2026-09-30" });
    expect(hooks.reloadGa4).toHaveBeenCalledWith({ force: true });
    expect(hooks.reloadCampaigns).toHaveBeenCalledTimes(1);
  });

  it("falha preserva cards e freshness sem reler snapshot parcial", async () => {
    api.refreshProviderData.mockRejectedValue(new Error("provider indisponível"));
    await render();
    const card = container.querySelector('[data-testid="ga4-sessions"]');
    expect(card).not.toBeNull();
    const before = card?.textContent;
    const freshness = container.querySelector(".ds-dateline")?.textContent;
    await refresh();
    expect(container.textContent).toContain("Mantendo a última leitura disponível");
    expect(container.querySelector('[data-testid="ga4-sessions"]')?.textContent).toBe(before);
    expect(container.querySelector(".ds-dateline")?.textContent).toBe(freshness);
    expect(hooks.reloadGa4).not.toHaveBeenCalled();
    expect(hooks.reloadCampaigns).not.toHaveBeenCalled();
  });

  it("clique duplo compartilha um sync e mantém gráficos montados", async () => {
    let finish!: (value: unknown) => void;
    api.refreshProviderData.mockImplementation(() => new Promise((resolve) => { finish = resolve; }));
    await render();
    const chart = container.querySelector('[data-testid="ga4-sessions-chart"]');
    expect(chart).not.toBeNull();
    await act(async () => {
      const action = button("Atualizar dados")!;
      action.dispatchEvent(new MouseEvent("click", { bubbles: true }));
      action.dispatchEvent(new MouseEvent("click", { bubbles: true }));
    });
    expect(api.refreshProviderData).toHaveBeenCalledTimes(1);
    expect(button("Atualizando...")?.disabled).toBe(true);
    expect(container.querySelector('[data-testid="ga4-sessions-chart"]')).toBe(chart);
    expect(container.querySelector('[class*="skeleton"]')).toBeNull();
    await act(async () => finish({ ok: true }));
  });
});
