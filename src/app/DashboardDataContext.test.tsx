// @vitest-environment jsdom
import React, { act } from "react";
import { createRoot } from "react-dom/client";
import { beforeEach, expect, test, vi } from "vitest";

globalThis.IS_REACT_ACT_ENVIRONMENT = true;
const mocks = vi.hoisted(() => ({ calls: [] as string[], deferred: new Map<string, { resolve: (value: unknown) => void }>() }));

function query(table: string) {
  const builder: Record<string, unknown> = {};
  for (const method of ["select", "eq", "gte", "lte", "order", "limit", "range"]) builder[method] = () => builder;
  builder.then = (resolve: (value: unknown) => void) => {
    mocks.calls.push(table);
    const pending = mocks.deferred.get(table);
    if (pending) pending.resolve = resolve;
    else resolve({ data: [], error: null });
  };
  return builder;
}

vi.mock("./supabase", () => ({ supabase: { from: (table: string) => query(table) } }));
import { DashboardDataProvider, useDashboardSnapshot } from "./DashboardDataContext";

function Consumer({ period = "7d" }: { period?: string }) {
  const state = useDashboardSnapshot(period === "7d" ? "2026-08-04" : "2026-07-12", "2026-08-10");
  return <span>{state.snapshot?.daily.length ?? "pending"}</span>;
}

beforeEach(() => { mocks.calls.length = 0; mocks.deferred.clear(); sessionStorage.clear(); });

test("tenant unresolved faz zero queries; tenant canônico faz quatro; trocar período refaz a consulta", async () => {
  const node = document.createElement("div"); const root = createRoot(node);
  await act(async () => root.render(<DashboardDataProvider clientId="" tenantReady={false} enabled><Consumer /></DashboardDataProvider>));
  expect(mocks.calls).toHaveLength(0);
  await act(async () => root.render(<DashboardDataProvider clientId="tenant-bootstrap-1" tenantReady enabled period={{start:"2026-08-04",end:"2026-08-10"}}><Consumer /></DashboardDataProvider>));
  expect(mocks.calls).toHaveLength(4);
  await act(async () => root.render(<DashboardDataProvider clientId="tenant-bootstrap-1" tenantReady enabled period={{start:"2026-07-12",end:"2026-08-10"}}><Consumer period="30d" /></DashboardDataProvider>));
  expect(mocks.calls).toHaveLength(8);
  act(() => root.unmount());
});

test("resposta atrasada do tenant anterior não sobrescreve o tenant atual", async () => {
  const held = ["dashboard_daily_metrics", "dashboard_source_snapshots", "dashboard_campaign_metrics", "dashboard_product_metrics"];
  for (const table of held) mocks.deferred.set(table, { resolve: () => undefined });
  const node = document.createElement("div"); const root = createRoot(node);
  act(() => root.render(<DashboardDataProvider clientId="tenant-race-old" tenantReady enabled period={{start:"2026-08-04",end:"2026-08-10"}}><Consumer /></DashboardDataProvider>));
  await act(async () => Promise.resolve());
  const oldResolvers = held.map((table) => mocks.deferred.get(table)!.resolve);
  mocks.deferred.clear();
  await act(async () => root.render(<DashboardDataProvider clientId="tenant-race-new" tenantReady enabled period={{start:"2026-08-04",end:"2026-08-10"}}><Consumer /></DashboardDataProvider>));
  expect(node.textContent).toBe("0");
  await act(async () => { oldResolvers.forEach((resolve) => resolve({ data: [{ metric_date: "2026-08-10" }], error: null })); await Promise.resolve(); });
  expect(node.textContent).toBe("0");
  act(() => root.unmount());
});

test("releitura após sync espera consulta antiga e inicia quatro queries novas", async () => {
  const held = ["dashboard_daily_metrics", "dashboard_source_snapshots", "dashboard_campaign_metrics", "dashboard_product_metrics"];
  for (const table of held) mocks.deferred.set(table, { resolve: () => undefined });
  let refetch: ReturnType<typeof useDashboardSnapshot>["refetch"];
  function RefreshConsumer() { const state = useDashboardSnapshot(); React.useEffect(() => { refetch = state.refetch; }, [state.refetch]); return <span>{state.snapshot?.daily.length ?? "pending"}</span>; }
  const node = document.createElement("div"); const root = createRoot(node);
  act(() => root.render(<DashboardDataProvider clientId="post-sync-race" tenantReady enabled><RefreshConsumer /></DashboardDataProvider>));
  await act(async () => Promise.resolve());
  const resolvers = held.map((table) => mocks.deferred.get(table)!.resolve);
  const freshRead = refetch!({ afterCurrent: true });
  mocks.deferred.clear();
  await act(async () => { resolvers.forEach((resolve) => resolve({ data: [{ metric_date: "2026-08-10" }], error: null })); await freshRead; });
  expect(mocks.calls).toHaveLength(8);
  expect(node.textContent).toBe("0");
  act(() => root.unmount());
});
