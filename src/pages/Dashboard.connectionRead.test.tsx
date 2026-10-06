// @vitest-environment jsdom
import React, { act } from "react";
import { createRoot } from "react-dom/client";
import { afterEach, beforeEach, expect, test, vi } from "vitest";
import { DashboardDataContext, type DashboardSnapshot } from "../app/DashboardDataContext";
import { clearDashboardCacheByPrefix, buildDashboardCacheKey, writeDashboardCache } from "../hooks/dashboard/cache";
const state = vi.hoisted(() => ({ tenant: "tenant-a", role: "viewer" }));
const api = vi.hoisted(() => ({ listClientConnections: vi.fn(), getClientIntegrations: vi.fn(), getMedia: vi.fn(), getComments: vi.fn(), getMediaMonthly: vi.fn(), getStories: vi.fn(), listGenericConnections: vi.fn(), getGa4Report: vi.fn() }));
vi.mock("../app/api", async original => ({ ...await original<typeof import("../app/api")>(), ...api }));
vi.mock("../app/activeClient", () => ({ getActiveClient: () => ({ id: state.tenant, role: state.role }), getActiveClientId: () => state.tenant, getActiveClientName: () => "Empresa", getActiveClientConfigurationWarning: () => null }));
vi.mock("../app/connectionState", () => ({ getActiveConnectionId: () => null, getSelectedConnectionId: () => null }));
vi.mock("../app/PeriodContext", () => ({ usePeriod: () => ({ period: { start: "2026-10-01", end: "2026-10-05" }, setPresetPeriod: vi.fn(), setCurrentMonthPeriod: vi.fn(), setMonthPeriod: vi.fn(), setDayPeriod: vi.fn() }) }));
vi.mock("../components/Shell", () => ({ default: ({ children }: { children: React.ReactNode }) => <div>{children}</div> }));
import Dashboard from "./Dashboard";
import GoogleAnalytics from "./GoogleAnalytics";
globalThis.IS_REACT_ACT_ENVIRONMENT = true;
let node: HTMLDivElement, root: ReturnType<typeof createRoot>;
const observers = new Map<Element, (entries: IntersectionObserverEntry[]) => void>();
const connection = (tenant: string) => ({ id: `${tenant}-organic`, client_id: tenant, platform: "instagram", connection_type: "organic", status: "connected" });
const snapshot = { daily: [{ client_id: "tenant-a", metric_date: "2026-10-01", instagram_reach: 144, instagram_interactions: 24 }], sources: [{ provider: "instagram" }], campaigns: [], products: [], fetchedAt: "fixture", queryCount: 4 } as unknown as DashboardSnapshot;
async function render(strict = false) {
  const page = <DashboardDataContext.Provider value={{ snapshot, loading: false, refreshing: false, error: null, refetch: async () => snapshot }}><Dashboard isAuthenticated /></DashboardDataContext.Provider>;
  await act(async () => root.render(strict ? <React.StrictMode>{page}</React.StrictMode> : page));
}
async function demand(id: string) {
  const element = node.querySelector(`[data-testid="${id}"]`)!;
  expect(element).toBeTruthy();
  await act(async () => observers.get(element)?.([{ isIntersecting: true } as IntersectionObserverEntry]));
}
beforeEach(() => {
  state.tenant = "tenant-a"; state.role = "viewer"; sessionStorage.clear(); observers.clear();
  for (const prefix of ["meta-connections", "summary-", "media-monthly", "client-integrations"]) clearDashboardCacheByPrefix(prefix);
  for (const mock of Object.values(api)) mock.mockReset();
  api.listClientConnections.mockImplementation(async (tenant: string) => ({ connections: [connection(tenant)] }));
  api.getClientIntegrations.mockResolvedValue({ connections: [] });
  api.getMedia.mockResolvedValue({ media: [], has_more: false });
  api.getComments.mockResolvedValue({ comments: [], total: 0, top_words: [] });
  api.getMediaMonthly.mockResolvedValue({ months: [] });
  vi.stubGlobal("IntersectionObserver", class { constructor(readonly callback: (entries: IntersectionObserverEntry[]) => void) {} observe(element: Element) { observers.set(element, this.callback); } disconnect() {} });
  node = document.createElement("div"); document.body.append(node); root = createRoot(node);
});
afterEach(() => { act(() => root.unmount()); node.remove(); vi.unstubAllGlobals(); });
test.each(["viewer", "client_admin"])("cache vazio: %s resolve uma vez e cada secundário aguarda demanda", async role => {
  state.role = role; await render(true);
  expect(node.textContent).toContain("144");
  expect(api.listClientConnections).toHaveBeenCalledExactlyOnceWith("tenant-a");
  expect(api.getClientIntegrations).toHaveBeenCalledTimes(role === "viewer" ? 0 : 1);
  expect(api.getMedia).not.toHaveBeenCalled(); expect(api.getComments).not.toHaveBeenCalled(); expect(api.getMediaMonthly).not.toHaveBeenCalled();
  await demand("organic-demand"); expect(api.getMedia).toHaveBeenCalledOnce(); expect(api.getComments).not.toHaveBeenCalled();
  await demand("comments-demand"); expect(api.getComments).toHaveBeenCalledOnce(); expect(api.getMedia).toHaveBeenCalledOnce();
  await demand("monthly-demand"); expect(api.getMediaMonthly).toHaveBeenCalledOnce();
  await render(true); expect(api.listClientConnections).toHaveBeenCalledOnce(); expect(api.getMedia).toHaveBeenCalledOnce();
});
test("cache preenchido reutiliza conexão sem descoberta", async () => {
  writeDashboardCache(buildDashboardCacheKey("meta-connections", { clientId: "tenant-a", extra: "dashboard" }), [connection("tenant-a")]);
  await render(); expect(api.listClientConnections).not.toHaveBeenCalled(); await demand("organic-demand");
  expect(api.getMedia.mock.calls[0][1].connectionId).toBe("tenant-a-organic");
});
test("troca de tenant ignora resolução anterior atrasada e usa somente conexão nova", async () => {
  let finish!: (value: unknown) => void;
  api.listClientConnections.mockImplementationOnce(() => new Promise(resolve => { finish = resolve; }));
  await render(); expect(node.textContent).toContain("144");
  state.tenant = "tenant-b"; await render();
  await act(async () => finish({ connections: [connection("tenant-a")] }));
  await demand("organic-demand");
  expect(api.listClientConnections.mock.calls.map(call => call[0])).toEqual(["tenant-a", "tenant-b"]);
  expect(api.getMedia.mock.calls[0][1]).toMatchObject({ clientId: "tenant-b", connectionId: "tenant-b-organic" });
});
test.each(["empty", "error"])("resolução %s termina sem loop e sem secundários", async outcome => {
  if (outcome === "empty") api.listClientConnections.mockResolvedValue({ connections: [] });
  else api.listClientConnections.mockRejectedValue(new Error("fixture"));
  await render(); await demand("organic-demand"); await render();
  expect(api.listClientConnections).toHaveBeenCalledOnce(); expect(api.getMedia).not.toHaveBeenCalled();
  if (outcome === "error") expect(node.textContent).toContain("Não foi possível resolver a conexão");
  expect(node.textContent).not.toContain("Carregando Instagram...");
});

test("viewer navega Meta→Google→Meta em StrictMode sem catálogo administrativo ou GA4 não configurado", async () => {
  api.listGenericConnections.mockResolvedValue({client_id:state.tenant,connections:[{provider:"ga4",status:"connected",capabilities:{ga4_configured:false}}]});
  await render(true);
  await act(async () => root.render(<React.StrictMode><DashboardDataContext.Provider value={{snapshot,loading:false,refreshing:false,error:null,refetch:async()=>snapshot}}><GoogleAnalytics isAuthenticated onLogout={vi.fn()} onOpenDashboard={vi.fn()} /></DashboardDataContext.Provider></React.StrictMode>));
  await act(async () => new Promise(resolve => setTimeout(resolve, 10)));
  expect(api.listGenericConnections).toHaveBeenCalledTimes(1);
  expect(api.getGa4Report).not.toHaveBeenCalled();
  await render(true);
  expect(api.getClientIntegrations).not.toHaveBeenCalled();
});
