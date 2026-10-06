// @vitest-environment jsdom
import React, { act, useEffect } from "react";
import { createRoot } from "react-dom/client";
import { expect, test, vi } from "vitest";
import { getGa4Report } from "../../app/api";
import useDashboardGa4 from "./useDashboardGa4";
import Ga4SiteBehaviorPanel from "../../components/dashboard/Ga4SiteBehaviorPanel";

const channels = Array.from({ length: 3 }, (_, index) => ({
  source_medium: `source-${index} / organic`,
  source: `source-${index}`,
  medium: "organic",
  sessions: 30 - index,
  active_users: 20 - index,
  total_users: 25 - index,
  event_count: 40 - index,
  ecommerce_purchases: 0,
  purchase_revenue: 0,
  total_revenue: 0,
}));
const campaigns = Array.from({ length: 2 }, (_, index) => ({
  campaign_name: `Campaign ${index + 1}`,
  source_medium: "google / cpc",
  source: "google",
  medium: "cpc",
  sessions: 20 - index,
  active_users: 10 - index,
  total_users: 12 - index,
  event_count: 30 - index,
  ecommerce_purchases: 0,
  purchase_revenue: 0,
  total_revenue: 0,
}));

vi.mock("../../app/api", () => ({
  getGa4Report: vi.fn(async () => ({
    ok: true, client_id: "amalie", property_id: "123",
    period: { start: "2026-08-01", end: "2026-08-10", days: 10 },
    summary: { sessions: 20, active_users: 12, total_users: 15, user_count_semantics: "sum_of_daily_users", event_count: 40, purchases: 2, purchase_revenue: 90 },
    channels, campaigns, events: [], trends: { daily: [] }, funnel: {},
    meta: { last_synced_at: "2026-08-10T12:00:00Z", data_available: true },
    commerce_journey: { summary: { purchase_rate_from_view_item: 0 }, items: [] },
    behavior: { title: "Comportamento", description: "", total_events: 0, total_users: 0, items: [] },
    engagement: { title: "Engajamento", description: "", total_events: 0, total_users: 0, items: [] },
    merchandising: { title: "Produtos", description: "", total_events: 0, total_users: 0, items: [] },
  })),
}));
vi.mock("../../app/DashboardDataContext", () => ({
  useDashboardSnapshot: () => ({
    snapshot: { fetchedAt: "x" },
    daily: [{ metric_date: "2026-08-10", ga4_sessions: 20, ga4_users: 12, ga4_events: 40, ga4_purchases: 2, ga4_revenue: 90 }],
    sources: [{provider: "ga4", last_success_at: "2026-08-10T12:00:00Z"}],
    campaigns: [],
    products: [],
    loading: false,
    refreshing: false,
    error: null,
    refetch: vi.fn(),
  }),
}));

function Harness() {
  const value = useDashboardGa4({
    isAuthenticated: true,
    activeClientId: "amalie",
    period: { start: "2026-08-01", end: "2026-08-10" },
  });
  return <div>{value.ga4Report?.summary.sessions}:{value.ga4Report?.channels.length}:{value.ga4Report?.campaigns.length}</div>;
}

test("consulta o relatório persistido com 3 canais e 2 campanhas reais", async () => {
  const node = document.createElement("div");
  const root = createRoot(node);
  await act(async () => root.render(<Harness />));
  for (let attempt = 0; attempt < 20 && node.textContent !== "20:3:2"; attempt += 1) {
    await act(async () => new Promise((resolve) => window.setTimeout(resolve, 5)));
  }
  expect(node.textContent).toBe("20:3:2");
  act(() => root.unmount());
});

test("Dashboard identifica a soma de usuários e não a apresenta como únicos do período", async () => {
  function Panel() {
    const value = useDashboardGa4({ isAuthenticated: true, activeClientId: "amalie", period: { start: "2026-08-01", end: "2026-08-10" } });
    if (value.ga4Report) expect(value.ga4Report.summary.user_count_semantics).toBe("sum_of_daily_users");
    return <Ga4SiteBehaviorPanel report={value.ga4Report} loading={false} refreshing={false} error={null} />;
  }
  const node = document.createElement("div"), root = createRoot(node);
  await act(async () => root.render(<Panel />));
  await act(async () => new Promise(resolve => window.setTimeout(resolve, 10)));
  expect(node.textContent).toContain("Usuários ativos (soma diária)");
  expect(node.textContent).toContain("A mesma pessoa pode ser contada em dias diferentes");
  expect(node.textContent).not.toContain("12 usuários totais");
  act(() => root.unmount());
});


test("falha na releitura preserva canais, campanhas e freshness do último sucesso", async () => {
  let current: ReturnType<typeof useDashboardGa4>;
  function Capture() {
    const value = useDashboardGa4({ isAuthenticated: true, activeClientId: "amalie", period: {start: "2026-08-01", end: "2026-08-10"} });
    useEffect(() => { current = value; }, [value]);
    return <div>{value.ga4Report?.channels.length}:{value.ga4Report?.campaigns.length}</div>;
  }
  const node = document.createElement("div");
  const root = createRoot(node);
  await act(async () => root.render(<Capture />));
  await act(async () => new Promise((resolve) => window.setTimeout(resolve, 10)));
  expect(node.textContent).toBe("3:2");
  vi.mocked(getGa4Report).mockRejectedValueOnce(new Error("indisponível"));
  await act(async () => { await current!.reloadGa4({force:true}); });
  expect(node.textContent).toBe("3:2");
  expect(current!.ga4UpdatedAt).toBe("2026-08-10T12:00:00Z");
  expect(current!.ga4Error).toBe("indisponível");
  act(() => root.unmount());
});
