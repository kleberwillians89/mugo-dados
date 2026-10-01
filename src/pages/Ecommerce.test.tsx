// @vitest-environment jsdom
import { act } from "react";
import { createRoot } from "react-dom/client";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import type { ClientIntegrationConnection } from "../app/types";

globalThis.IS_REACT_ACT_ENVIRONMENT = true;

if (!window.localStorage) {
  const values = new Map<string, string>();
  Object.defineProperty(window, "localStorage", {
    value: {
      clear: () => values.clear(),
      getItem: (key: string) => values.get(key) ?? null,
      removeItem: (key: string) => values.delete(key),
      setItem: (key: string, value: string) => values.set(key, value),
      key: (index: number) => [...values.keys()][index] ?? null,
      get length() { return values.size; },
    },
  });
}

const tenant = vi.hoisted(() => ({ id: "roove", name: "Roove" }));
const api = vi.hoisted(() => ({
  getClientIntegrations: vi.fn(),
  syncFbitsConnection: vi.fn(),
  getFbitsOrdersSummary: vi.fn(),
  getFbitsOrders: vi.fn(),
  listGenericConnections: vi.fn(),
  getShopifyReport: vi.fn(),
  getShopifyCustomers: vi.fn(),
  syncShopifyConnection: vi.fn(),
}));
const shopifyRenders = vi.hoisted(() => ({ tenants: [] as string[] }));

vi.mock("../app/api", () => api);
vi.mock("../app/activeClient", () => ({
  getActiveClientId: () => tenant.id,
  getActiveClientName: () => tenant.name,
}));
const periodActions = vi.hoisted(() => ({
  setPeriod: vi.fn(), setPresetPeriod: vi.fn(), setCurrentMonthPeriod: vi.fn(), setMonthPeriod: vi.fn(), setDayPeriod: vi.fn(),
}));
vi.mock("../app/PeriodContext", () => ({
  usePeriod: () => ({ period: { start: "2026-09-01", end: "2026-09-30", days: 30 }, ...periodActions }),
}));
vi.mock("../components/Shell", () => ({
  default: ({ title, subtitle, right, children }: { title: string; subtitle?: string; right?: React.ReactNode; children: React.ReactNode }) => (
    <div><h1>{title}</h1><p data-testid="subtitle">{subtitle}</p><div>{right}</div>{children}</div>
  ),
}));
vi.mock("../components/dashboard/FbitsExecutiveDashboard", () => ({
  default: ({ data }: { data: { connected?: boolean; summary?: { pedidos: number } } | null }) => (
    <div data-testid="fbits-panel">FBITS painel · pedidos={data?.summary?.pedidos ?? "-"}</div>
  ),
}));
vi.mock("./Shopify", async () => {
  const { getActiveClientId } = await import("../app/activeClient");
  return {
    default: () => {
      shopifyRenders.tenants.push(getActiveClientId());
      return <div data-testid="shopify-page">Shopify dashboard</div>;
    },
  };
});

import Ecommerce from "./Ecommerce";

function entry(provider: string, overrides: Partial<ClientIntegrationConnection> = {}): ClientIntegrationConnection {
  return {
    provider, connection_id: `${provider}-1`, status: "connected", authorization_status: "valid",
    sync_status: null, account: {}, assets: {}, last_sync_at: null, last_successful_sync_at: null,
    last_error: null, updated_at: null, ...overrides,
  };
}

function integrations(clientId: string, connections: ClientIntegrationConnection[]) {
  return { ok: true, client_id: clientId, connections };
}

const fbitsSummary = (clientId: string, pedidos = 0) => ({
  ok: true, connected: true, client_id: clientId, period: { start: "2026-09-01", end: "2026-09-30" },
  summary: { receita_oficial: 0, pedidos, ticket_medio: 0, clientes: 0, produtos_vendidos: 0 },
});

let container: HTMLDivElement;
let root: ReturnType<typeof createRoot>;
const onOpenIntegrations = vi.fn();

async function render() {
  await act(async () => {
    root.render(
      <Ecommerce
        key={`ecommerce:${tenant.id}`}
        isAuthenticated
        onLogout={vi.fn()}
        onOpenDashboard={vi.fn()}
        onOpenGoogleReport={vi.fn()}
        onOpenIntegrations={onOpenIntegrations}
      />,
    );
  });
  await act(async () => { await Promise.resolve(); });
}

function button(text: string) {
  return [...container.querySelectorAll("button")].find((item) => item.textContent === text);
}

async function click(target: HTMLElement | undefined) {
  await act(async () => { target?.dispatchEvent(new MouseEvent("click", { bubbles: true })); });
  await act(async () => { await Promise.resolve(); });
}

function expectNoShopifyCalls() {
  expect(api.getShopifyReport).not.toHaveBeenCalled();
  expect(api.getShopifyCustomers).not.toHaveBeenCalled();
  expect(api.syncShopifyConnection).not.toHaveBeenCalled();
  expect(container.querySelector('[data-testid="shopify-page"]')).toBeNull();
}

function expectNoFbitsCalls() {
  expect(api.getFbitsOrdersSummary).not.toHaveBeenCalled();
  expect(api.getFbitsOrders).not.toHaveBeenCalled();
  expect(api.syncFbitsConnection).not.toHaveBeenCalled();
  expect(container.querySelector('[data-testid="fbits-panel"]')).toBeNull();
}

beforeEach(() => {
  tenant.id = "roove";
  tenant.name = "Roove";
  shopifyRenders.tenants = [];
  window.localStorage.clear();
  Object.values(api).forEach((fn) => fn.mockReset());
  onOpenIntegrations.mockReset();
  Object.values(periodActions).forEach((fn) => fn.mockReset());
  api.getFbitsOrdersSummary.mockImplementation(async () => fbitsSummary(tenant.id));
  api.getFbitsOrders.mockImplementation(async () => ({ ok: true, client_id: tenant.id, items: [] }));
  container = document.createElement("div");
  document.body.appendChild(container);
  root = createRoot(container);
});

afterEach(async () => {
  await act(async () => root.unmount());
  container.remove();
  window.localStorage.clear();
});

describe("Ecommerce — resolução do provider pela conexão do tenant ativo", () => {
  it("7/4. Roove com Shopify conectado (mesmo sem pedidos) → dashboard Shopify, nenhum endpoint FBITS", async () => {
    api.getClientIntegrations.mockResolvedValue(integrations("roove", [entry("meta"), entry("shopify")]));
    await render();
    expect(container.querySelector('[data-testid="shopify-page"]')).not.toBeNull();
    expect(shopifyRenders.tenants).toContain("roove");
    expectNoFbitsCalls();
  });

  it("8/3/6. vinhos com FBITS conectado e zero pedidos → dashboard FBITS pendente, nunca Shopify", async () => {
    tenant.id = "vinhos";
    tenant.name = "Curavino";
    api.getClientIntegrations.mockResolvedValue(
      integrations("vinhos", [entry("shopify", { status: "disconnected" }), entry("fbits", { connection_id: "fbits-vinhos" })]),
    );
    await render();
    expect(container.querySelector('[data-testid="fbits-panel"]')?.textContent).toContain("pedidos=0");
    expect(container.querySelector('[data-testid="subtitle"]')?.textContent).toContain("Fonte: FBITS");
    expect(container.textContent).toContain("FBITS conectado");
    expect(container.textContent).toContain("Aguardando primeira sincronização");
    expect(button("Sincronizar agora")).toBeTruthy();
    expect(container.textContent).not.toMatch(/Shopify não conectado|Conecte sua loja|Nenhuma integração/);
    expect(api.getFbitsOrdersSummary).toHaveBeenCalled();
    // Modo FBITS não reavalia conexões genéricas nem cai em Shopify.
    expect(api.listGenericConnections).not.toHaveBeenCalled();
    expectNoShopifyCalls();
  });

  it("5. nenhuma conexão de e-commerce → estado vazio com CTA para Integrações", async () => {
    api.getClientIntegrations.mockResolvedValue(integrations("roove", [entry("meta"), entry("fbits", { status: "disconnected" })]));
    await render();
    expect(container.textContent).toContain("Nenhuma integração de Ecommerce conectada");
    await click(button("Ir para Integrações"));
    expect(onOpenIntegrations).toHaveBeenCalledTimes(1);
    expectNoShopifyCalls();
    expectNoFbitsCalls();
  });

  it("11/13. Sincronizar agora (FBITS) chama somente o sync FBITS do tenant ativo", async () => {
    tenant.id = "vinhos";
    api.getClientIntegrations.mockResolvedValue(integrations("vinhos", [entry("fbits")]));
    api.syncFbitsConnection.mockResolvedValue({ ok: true, scheduled: true });
    await render();
    await click(button("Sincronizar agora"));
    expect(api.syncFbitsConnection).toHaveBeenCalledTimes(1);
    expect(container.textContent).toContain("Sincronização FBITS iniciada");
    // Recarrega as conexões sem desmontar a tela.
    expect(api.getClientIntegrations).toHaveBeenCalledTimes(2);
    expect(api.getFbitsOrdersSummary).toHaveBeenCalledTimes(2);
    expect(container.querySelector('[data-testid="fbits-panel"]')).not.toBeNull();
    expectNoShopifyCalls();
  });

  it("períodos rápidos atualizam o contexto sem reload da página", async () => {
    tenant.id = "vinhos";
    api.getClientIntegrations.mockResolvedValue(integrations("vinhos", [entry("fbits", { last_sync_at: "2026-09-30T12:00:00Z" })]));
    await render();
    await click(button("7 dias"));
    expect(periodActions.setPeriod).toHaveBeenLastCalledWith(expect.objectContaining({ end: expect.any(String) }));
    await click(button("30 dias"));
    expect(periodActions.setPeriod).toHaveBeenCalledTimes(2);
    await click(button("Este mês"));
    expect(periodActions.setPeriod).toHaveBeenCalledTimes(3);
    await click(button("Mês passado"));
    expect(periodActions.setPeriod).toHaveBeenCalledTimes(4);
    expect(container.textContent).toContain("Sincronizado em");
  });

  it("15. Shopify + FBITS conectados → pede escolha explícita, sem escolher pela ordem", async () => {
    api.getClientIntegrations.mockResolvedValue(integrations("roove", [entry("fbits"), entry("shopify")]));
    await render();
    expect(container.textContent).toContain("Mais de uma integração de Ecommerce está conectada");
    expectNoShopifyCalls();
    expectNoFbitsCalls();
    await click(button("Usar FBITS"));
    expect(container.querySelector('[data-testid="fbits-panel"]')).not.toBeNull();
    expectNoShopifyCalls();
  });

  it("15. escolha explícita de Shopify com duas conexões → somente Shopify", async () => {
    api.getClientIntegrations.mockResolvedValue(integrations("roove", [entry("shopify"), entry("fbits")]));
    await render();
    await click(button("Usar Shopify"));
    expect(container.querySelector('[data-testid="shopify-page"]')).not.toBeNull();
    expectNoFbitsCalls();
  });

  it("9. trocar Roove → vinhos recalcula: Shopify da Roove some e FBITS do vinhos aparece", async () => {
    api.getClientIntegrations.mockImplementation(async () =>
      tenant.id === "roove" ? integrations("roove", [entry("shopify")]) : integrations("vinhos", [entry("fbits")]),
    );
    await render();
    expect(container.querySelector('[data-testid="shopify-page"]')).not.toBeNull();

    tenant.id = "vinhos";
    tenant.name = "Curavino";
    await render();
    expect(container.querySelector('[data-testid="shopify-page"]')).toBeNull();
    expect(container.querySelector('[data-testid="fbits-panel"]')).not.toBeNull();
    expect(shopifyRenders.tenants).toEqual(["roove"]);
    expect(api.getFbitsOrdersSummary).toHaveBeenCalled();
    expect(api.getShopifyReport).not.toHaveBeenCalled();
  });

  it("10. trocar vinhos → Roove recalcula: FBITS some e Shopify da Roove aparece", async () => {
    api.getClientIntegrations.mockImplementation(async () =>
      tenant.id === "roove" ? integrations("roove", [entry("shopify")]) : integrations("vinhos", [entry("fbits")]),
    );
    tenant.id = "vinhos";
    await render();
    expect(container.querySelector('[data-testid="fbits-panel"]')).not.toBeNull();
    const fbitsCalls = api.getFbitsOrdersSummary.mock.calls.length;

    tenant.id = "roove";
    tenant.name = "Roove";
    await render();
    expect(container.querySelector('[data-testid="fbits-panel"]')).toBeNull();
    expect(container.querySelector('[data-testid="shopify-page"]')).not.toBeNull();
    expect(shopifyRenders.tenants).toEqual(["roove"]);
    expect(api.getFbitsOrdersSummary.mock.calls.length).toBe(fbitsCalls);
  });

  it("9. resposta atrasada do tenant anterior é descartada (sem estado stale)", async () => {
    let releaseRoove: (value: unknown) => void = () => undefined;
    api.getClientIntegrations.mockImplementation(() =>
      tenant.id === "roove"
        ? new Promise((resolve) => { releaseRoove = resolve; })
        : Promise.resolve(integrations("vinhos", [entry("fbits")])),
    );
    await render();
    tenant.id = "vinhos";
    await render();
    await act(async () => { releaseRoove(integrations("roove", [entry("shopify")])); await Promise.resolve(); });
    expect(container.querySelector('[data-testid="fbits-panel"]')).not.toBeNull();
    expect(container.querySelector('[data-testid="shopify-page"]')).toBeNull();
    expect(shopifyRenders.tenants).toEqual([]);
  });

  it("resposta de outro tenant não é usada para decidir o provider", async () => {
    tenant.id = "vinhos";
    api.getClientIntegrations.mockResolvedValue(integrations("roove", [entry("shopify")]));
    await render();
    expect(container.querySelector('[data-testid="shopify-page"]')).toBeNull();
    expect(container.textContent).toContain("A empresa ativa mudou");
    expectNoShopifyCalls();
  });
});
