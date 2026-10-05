// @vitest-environment jsdom
import { afterEach, expect, test, vi } from "vitest";

const tenant = vi.hoisted(() => ({ id: "vinhos" }));
vi.mock("./activeClient", () => ({
  getActiveClientId: () => tenant.id,
  getActiveClientConfigurationWarning: () => null,
}));
vi.mock("./supabase", () => ({
  isLocalAuthEnabled: () => false,
  supabase: null,
  getSupabaseBootstrapError: () => null,
}));

import { getCustomers, getCustomerDetail, setApiAccessToken } from "./api";
afterEach(() => { vi.unstubAllGlobals(); setApiAccessToken(undefined); });

test("Customer 360 usa os endpoints existentes e o tenant selecionado em todos os GETs", async () => {
  setApiAccessToken("sessao-ficticia-de-teste");
  const requests: { url: string; init: RequestInit }[] = [];
  vi.stubGlobal("fetch", vi.fn(async (url: string, init: RequestInit) => {
    requests.push({ url, init });
    return new Response(JSON.stringify({ ok: true }), { status: 200 });
  }));
  for (const id of ["vinhos", "roove", "ruah-parfums"]) {
    tenant.id = id;
    await getCustomers({ page: 2, pageSize: 25, search: "termo-teste" });
    await getCustomerDetail("chave-opaca");
    const [listing, detail] = requests.slice(-2);
    expect(listing.url).toContain("/api/customers?");
    expect(new URL(listing.url, "https://teste.invalid").searchParams.get("page")).toBe("2");
    expect(detail.url).toMatch(/\/api\/customers\/chave-opaca$/);
    for (const request of [listing, detail]) {
      const headers = new Headers(request.init.headers);
      expect(headers.get("X-Client-Id")).toBe(id);
      expect(headers.get("Authorization")).toBe("Bearer sessao-ficticia-de-teste");
      expect(request.init.method || "GET").toBe("GET");
    }
  }
});
