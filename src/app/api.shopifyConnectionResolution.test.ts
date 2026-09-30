// @vitest-environment jsdom

import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";

const tenant = vi.hoisted(() => ({ id: "amalie", name: "Amalie" }));

vi.mock("./supabase", () => ({
  isLocalAuthEnabled: () => true,
  getSupabaseBootstrapError: () => null,
  supabase: null,
}));

vi.mock("./activeClient", () => ({
  getActiveClientId: () => tenant.id,
  getActiveClientName: () => tenant.name,
  getActiveClientConfigurationWarning: () => null,
}));

import { getShopifyCustomers, getShopifyReport, startShopifyOAuth } from "./api";
import { getSelectedConnectionId, setSelectedConnectionId } from "./connectionState";

function jsonResponse(body: unknown, status = 200): Response {
  return new Response(JSON.stringify(body), {
    status,
    headers: { "Content-Type": "application/json" },
  });
}

function connectionsResponse(connections: unknown[]): Response {
  return jsonResponse({ ok: true, client_id: "amalie", connections });
}

const shopifyReportBody = {
  ok: true, client_id: "amalie", period: { start: "2026-08-01", end: "2026-08-08", days: 8 },
  summary: {}, trends: { daily: [] }, recent_orders: [], top_products: [], technical: {},
};
const shopifyCustomersBody = {
  ok: true, client_id: "amalie", period: { start: "2026-08-01", end: "2026-08-08", days: 8 },
  count: 0, summary: {}, items: [],
};

function urlOf(call: unknown): string {
  const [input] = call as [RequestInfo | URL];
  return typeof input === "string" ? input : input.toString();
}

describe("getShopifyReport/getShopifyCustomers — resolve connection_id sem depender só do localStorage", () => {
  beforeEach(() => {
    tenant.id = "amalie";
    tenant.name = "Amalie";
    window.localStorage.clear();
  });

  afterEach(() => {
    vi.unstubAllGlobals();
    window.localStorage.clear();
  });

  it("browser novo lê Shopify por tenant sem consultar ou persistir connection_id", async () => {
    const fetchMock = vi.fn(async (input: RequestInfo | URL) => {
      const url = String(input);
      if (url.includes("/api/connections")) {
        return connectionsResponse([
          { id: "8e1780ef-17b0-4b0a-843e-f8c323141412", client_id: "amalie", provider: "shopify", status: "connected", disconnected_at: null },
        ]);
      }
      if (url.includes("/api/shopify/report")) return jsonResponse(shopifyReportBody);
      return jsonResponse({}, 404);
    });
    vi.stubGlobal("fetch", fetchMock);

    expect(getSelectedConnectionId("amalie", "shopify")).toBeNull();
    await getShopifyReport({ start: "2026-08-01", end: "2026-08-08", days: 8 });

    const reportCall = fetchMock.mock.calls.find((call) => urlOf(call).includes("/api/shopify/report"));
    expect(reportCall).toBeDefined();
    expect(urlOf(reportCall)).not.toContain("connection_id=");
    expect(fetchMock.mock.calls.some((call) => urlOf(call).includes("/api/connections"))).toBe(false);
    expect(getSelectedConnectionId("amalie", "shopify")).toBeNull();
  });

  it("OAuth start envia domínio informado e X-Client-Id da Roove ativa", async () => {
    tenant.id = "roove";
    tenant.name = "Roove";
    const fetchMock = vi.fn(async () => jsonResponse({
      ok: true,
      client_id: "roove",
      shop_domain: "0vi1gx-ja.myshopify.com",
      authorization_url: "https://0vi1gx-ja.myshopify.com/admin/oauth/authorize",
    }));
    vi.stubGlobal("fetch", fetchMock);

    const response = await startShopifyOAuth("https://0vi1gx-ja.myshopify.com/");

    expect(response.authorization_url).toContain("/admin/oauth/authorize");
    const [input, init] = fetchMock.mock.calls[0] as unknown as [string, RequestInit];
    expect(input).toContain(
      "/api/oauth/shopify/start?shop=https%3A%2F%2F0vi1gx-ja.myshopify.com%2F"
    );
    expect(new Headers(init.headers).get("X-Client-Id")).toBe("roove");
  });

  it("mesma resolução para /api/shopify/customers", async () => {
    const fetchMock = vi.fn(async (input: RequestInfo | URL) => {
      const url = String(input);
      if (url.includes("/api/connections")) {
        return connectionsResponse([
          { id: "conn-unica", client_id: "amalie", provider: "shopify", status: "connected", disconnected_at: null },
        ]);
      }
      if (url.includes("/api/shopify/customers")) return jsonResponse(shopifyCustomersBody);
      return jsonResponse({}, 404);
    });
    vi.stubGlobal("fetch", fetchMock);

    await getShopifyCustomers({ start: "2026-08-01", end: "2026-08-08", days: 8 });

    const customersCall = fetchMock.mock.calls.find((call) => urlOf(call).includes("/api/shopify/customers"));
    expect(urlOf(customersCall)).not.toContain("connection_id=");
  });

  it("duas conexões Shopify ativas: nunca escolhe sozinho — connection_id fica ausente e o backend decide", async () => {
    const fetchMock = vi.fn(async (input: RequestInfo | URL) => {
      const url = String(input);
      if (url.includes("/api/connections")) {
        return connectionsResponse([
          { id: "conn-a", client_id: "amalie", provider: "shopify", status: "connected", disconnected_at: null },
          { id: "conn-b", client_id: "amalie", provider: "shopify", status: "connected", disconnected_at: null },
        ]);
      }
      if (url.includes("/api/shopify/report")) {
        return jsonResponse(
          { ok: false, code: "CONNECTION_SELECTION_REQUIRED", detail: "Selecione explicitamente a conexão antes de continuar." },
          409
        );
      }
      return jsonResponse({}, 404);
    });
    vi.stubGlobal("fetch", fetchMock);

    await expect(getShopifyReport({ start: "2026-08-01", end: "2026-08-08", days: 8 })).rejects.toBeTruthy();

    const reportCall = fetchMock.mock.calls.find((call) => urlOf(call).includes("/api/shopify/report"));
    expect(urlOf(reportCall)).not.toContain("connection_id=conn-a");
    expect(urlOf(reportCall)).not.toContain("connection_id=conn-b");
    expect(getSelectedConnectionId("amalie", "shopify")).toBeNull();
  });

  it("ponteiro local não interfere na leitura canônica por tenant", async () => {
    setSelectedConnectionId("amalie", "shopify", "conn-ja-selecionada");
    const fetchMock = vi.fn(async (input: RequestInfo | URL) => {
      const url = String(input);
      if (url.includes("/api/shopify/report")) return jsonResponse(shopifyReportBody);
      return jsonResponse({}, 404);
    });
    vi.stubGlobal("fetch", fetchMock);

    await getShopifyReport({ start: "2026-08-01", end: "2026-08-08", days: 8 });

    const calledConnectionsEndpoint = fetchMock.mock.calls.some((call) => urlOf(call).includes("/api/connections"));
    expect(calledConnectionsEndpoint).toBe(false);
    const reportCall = fetchMock.mock.calls.find((call) => urlOf(call).includes("/api/shopify/report"));
    expect(urlOf(reportCall)).not.toContain("connection_id=");
  });

  it("deduplica somente requests simultâneas do mesmo tenant e período", async () => {
    let release!: () => void;
    const gate = new Promise<void>((resolve) => { release = resolve; });
    const fetchMock = vi.fn(async () => {
      await gate;
      return jsonResponse(shopifyReportBody);
    });
    vi.stubGlobal("fetch", fetchMock);
    const period = { start: "2026-08-01", end: "2026-08-08", days: 8 };
    const first = getShopifyReport(period);
    const second = getShopifyReport(period);
    await vi.waitFor(() => expect(fetchMock).toHaveBeenCalledTimes(1));
    release();
    await Promise.all([first, second]);
    await getShopifyReport(period);
    expect(fetchMock).toHaveBeenCalledTimes(2);
  });
});
