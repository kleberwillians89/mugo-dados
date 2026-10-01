// @vitest-environment jsdom

import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";

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

const tenant = vi.hoisted(() => ({ id: "vinhos", name: "Curavino" }));

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

import { getClientIntegrations, getFbitsOrdersSummary, syncFbitsConnection, syncShopifyConnection } from "./api";

function jsonResponse(body: unknown, status = 200): Response {
  return new Response(JSON.stringify(body), { status, headers: { "Content-Type": "application/json" } });
}

function captureFetch() {
  const calls: { url: string; method: string; clientHeader: string | null }[] = [];
  const fetchMock = vi.fn(async (input: RequestInfo | URL, init?: RequestInit) => {
    const url = typeof input === "string" ? input : input.toString();
    calls.push({
      url,
      method: String(init?.method || "GET").toUpperCase(),
      clientHeader: new Headers(init?.headers).get("X-Client-Id"),
    });
    return jsonResponse({ ok: true, client_id: tenant.id, connections: [] });
  });
  vi.stubGlobal("fetch", fetchMock);
  return calls;
}

describe("sync de e-commerce sempre no tenant ativo e no provider certo", () => {
  beforeEach(() => {
    window.localStorage.clear();
  });

  afterEach(() => {
    vi.unstubAllGlobals();
    window.localStorage.clear();
  });

  it("11. syncFbitsConnection usa /api/clients/{tenant ativo}/fbits/sync", async () => {
    tenant.id = "vinhos";
    const calls = captureFetch();
    await syncFbitsConnection();
    expect(calls).toHaveLength(1);
    expect(calls[0].method).toBe("POST");
    expect(calls[0].url).toMatch(/\/api\/clients\/vinhos\/fbits\/sync$/);
    expect(calls[0].clientHeader).toBe("vinhos");
    expect(calls[0].url).not.toContain("shopify");
  });

  it("12. syncShopifyConnection usa a rota Shopify com X-Client-Id do tenant ativo", async () => {
    tenant.id = "roove";
    const calls = captureFetch();
    await syncShopifyConnection("shopify-roove", 30);
    expect(calls).toHaveLength(1);
    expect(calls[0].method).toBe("POST");
    expect(calls[0].url).toMatch(/\/api\/oauth\/shopify\/shopify-roove\/sync\?days=30$/);
    expect(calls[0].clientHeader).toBe("roove");
    expect(calls[0].url).not.toContain("fbits");
  });

  it("dashboard FBITS e contrato de integrações seguem o tenant ativo, sem client_id fixo", async () => {
    tenant.id = "vinhos";
    const calls = captureFetch();
    await getFbitsOrdersSummary({ start: "2026-09-01", end: "2026-09-30" });
    await getClientIntegrations();
    expect(calls[0].url).toContain("/api/fbits/dashboard");
    expect(calls[0].url).toContain("start=2026-09-01");
    expect(calls[0].url).toContain("end=2026-09-30");
    expect(calls[0].clientHeader).toBe("vinhos");
    expect(calls[1].url).toMatch(/\/api\/clients\/vinhos\/integrations$/);
    expect(calls[1].clientHeader).toBe("vinhos");

    tenant.id = "roove";
    await getClientIntegrations();
    expect(calls[2].url).toMatch(/\/api\/clients\/roove\/integrations$/);
    expect(calls[2].clientHeader).toBe("roove");
  });
});
