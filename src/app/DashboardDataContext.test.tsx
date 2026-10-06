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


test("daily e sources liberam KPI antes de campaigns/products lentos; cache no remount não fica vazio", async () => {
  const node = document.createElement("div"); let root = createRoot(node);
  for (const table of ["dashboard_campaign_metrics", "dashboard_product_metrics"]) mocks.deferred.set(table, { resolve: () => undefined });
  function Primary() { const model = useDashboardSnapshot(); return <span>{model.loading ? "loading" : `ready:${model.daily.length}:${model.snapshot?.secondaryLoading}`}</span>; }
  await act(async () => root.render(<DashboardDataProvider clientId="progressive-tenant" tenantReady enabled period={{start:"2026-08-04",end:"2026-08-10"}}><Primary /></DashboardDataProvider>));
  expect(node.textContent).toBe("ready:0:true");
  expect(mocks.calls).toHaveLength(4);
  const finish = [...mocks.deferred.values()].map(value => value.resolve);
  act(() => root.unmount()); root = createRoot(node);
  act(() => root.render(<DashboardDataProvider clientId="progressive-tenant" tenantReady enabled period={{start:"2026-08-04",end:"2026-08-10"}}><Primary /></DashboardDataProvider>));
  expect(node.textContent).toBe("ready:0:true");
  await act(async () => { finish.forEach(resolve => resolve({data:[],error:null})); });
  expect(node.textContent).toBe("ready:0:false");
  act(() => root.unmount());
});


test("troca de módulo demanda somente recurso necessário sem reler daily/sources", async () => {
  const node = document.createElement("div"); const root = createRoot(node);
  const props = { clientId: "resource-tenant", tenantReady: true, enabled: true, period: {start:"2026-08-04",end:"2026-08-10"} };
  await act(async () => root.render(<DashboardDataProvider {...props} resources="none"><Consumer /></DashboardDataProvider>));
  expect(mocks.calls).toEqual(["dashboard_daily_metrics", "dashboard_source_snapshots"]);
  await act(async () => root.render(<DashboardDataProvider {...props} resources="campaigns"><Consumer /></DashboardDataProvider>));
  expect(mocks.calls).toEqual(["dashboard_daily_metrics", "dashboard_source_snapshots", "dashboard_campaign_metrics"]);
  act(() => root.unmount());
});

test("campanhas rápidas não aguardam produtos; erro de produto preserva KPI e encerra loading", async () => {
  const node = document.createElement("div"); const root = createRoot(node);
  mocks.deferred.set("dashboard_product_metrics", { resolve: () => undefined });
  function Independent() {
    const model = useDashboardSnapshot();
    return <span>{model.loading ? "loading" : `ready:${model.snapshot?.campaignsLoaded}:${model.snapshot?.productsLoading}:${model.snapshot?.secondaryErrors?.join(",") || "none"}`}</span>;
  }
  await act(async () => root.render(<DashboardDataProvider clientId="secondary-error-tenant" tenantReady enabled><Independent /></DashboardDataProvider>));
  expect(node.textContent).toBe("ready:true:true:none");
  await act(async () => mocks.deferred.get("dashboard_product_metrics")!.resolve({data:null,error:{message:"fixture-error"}}));
  expect(node.textContent).toBe("ready:true:false:products");
  expect(mocks.calls).toHaveLength(4);
  act(() => root.unmount());
});
