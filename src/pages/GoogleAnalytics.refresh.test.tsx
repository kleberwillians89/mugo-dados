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
  trends: { daily: [] }, channels: [], campaigns: [], events: [],
  meta: { daily_rows: 0, channel_rows: 0, campaign_rows: 0, event_rows: 0 },
} as unknown as Ga4ReportResponse;

const hooks = vi.hoisted(() => ({ reloadGa4: vi.fn(), reloadCampaigns: vi.fn() }));
const api = vi.hoisted(() => ({ syncGa4: vi.fn(), syncGoogleConnection: vi.fn(), getClientIntegrations: vi.fn() }));

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

vi.mock("../components/dashboard/PerformanceChart", () => ({
  default: () => <div data-testid="chart" />,
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
  api.syncGa4.mockResolvedValue({ ok: true });
  api.syncGoogleConnection.mockResolvedValue({ ok: true, rows_upserted: 12 });
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
    root.render(<GoogleAnalytics onLogout={() => {}} onOpenDashboard={() => {}} isAuthenticated canSync />);
  });
  await act(async () => Promise.resolve());
  await act(async () => Promise.resolve());
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

describe("GoogleAnalytics — atualizar sincroniza GA4 e Google Ads", () => {
  it("dispara os dois syncs e recarrega GA4 e campanhas", async () => {
    await render();
    await refresh();
    expect(api.syncGa4).toHaveBeenCalledTimes(1);
    expect(api.syncGoogleConnection).toHaveBeenCalledTimes(1);
    expect(api.syncGoogleConnection).toHaveBeenCalledWith("ads-1");
    expect(hooks.reloadGa4).toHaveBeenCalledWith({ force: true });
    expect(hooks.reloadCampaigns).toHaveBeenCalledTimes(1);
  });

  it("GA4 falhando não impede o Google Ads de sincronizar", async () => {
    api.syncGa4.mockRejectedValue(new Error("GA4 fora do ar"));
    await render();
    await refresh();
    expect(api.syncGoogleConnection).toHaveBeenCalledTimes(1);
    // O aviso diz qual provider falhou (a mensagem crua é generalizada).
    expect(container.textContent).toContain("Google Analytics: ");
    expect(container.textContent).not.toContain("Google Ads: ");
    // Falha de refresh não apaga o que já estava na tela.
    expect(hooks.reloadGa4).toHaveBeenCalled();
  });

  it("Google Ads falhando é identificado sem derrubar o GA4", async () => {
    api.syncGoogleConnection.mockRejectedValue(new Error("Conta sem permissão"));
    await render();
    await refresh();
    expect(api.syncGa4).toHaveBeenCalledTimes(1);
    expect(container.textContent).toContain("Google Ads: ");
    expect(container.textContent).not.toContain("Google Analytics: Não foi");
  });

  it("sem conexão Google Ads, atualizar segue funcionando só com GA4", async () => {
    api.getClientIntegrations.mockResolvedValue({
      ok: true,
      client_id: "curavino",
      connections: [{
        provider: "ga4", connection_id: "ga4-1", status: "connected", authorization_status: "valid",
        sync_status: null, account: {}, assets: { property_id: "properties/1" },
        last_sync_at: null, last_successful_sync_at: null, last_error: null, updated_at: null,
      }],
    });
    await render();
    await refresh();
    expect(api.syncGa4).toHaveBeenCalledTimes(1);
    expect(api.syncGoogleConnection).not.toHaveBeenCalled();
  });
});
