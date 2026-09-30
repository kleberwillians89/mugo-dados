// @vitest-environment jsdom

import { afterEach, describe, expect, it, vi } from "vitest";

vi.mock("./supabase", () => ({
  isLocalAuthEnabled: () => true,
  getSupabaseBootstrapError: () => null,
  supabase: null,
}));

vi.mock("./activeClient", () => ({
  clearTenantBrowserState: () => {},
  getActiveClientId: () => "mugo",
  getActiveClientName: () => "Mugô",
  getActiveClientConfigurationWarning: () => null,
}));

import { syncClientMetaAdsAccount } from "./api";

afterEach(() => {
  vi.unstubAllGlobals();
});

describe("syncClientMetaAdsAccount — Sincronizar agora (Meta Ads)", () => {
  it("envia só a conexão e deixa o período canônico para o backend", async () => {
    const fetchMock = vi.fn(async () => new Response(JSON.stringify({ ok: true, code: "OK" }), {
      status: 200,
      headers: { "Content-Type": "application/json" },
    }));
    vi.stubGlobal("fetch", fetchMock);

    await syncClientMetaAdsAccount("paid-1");

    expect(fetchMock).toHaveBeenCalledTimes(1);
    const [input, init] = fetchMock.mock.calls[0] as unknown as [RequestInfo | URL, RequestInit];
    expect(String(input)).toContain("/api/clients/mugo/meta-ads/sync");
    expect(init.method).toBe("POST");
    const body = JSON.parse(String(init.body));
    expect(body).toEqual({ connection_id: "paid-1" });
    expect(String(init.body)).not.toContain("2026-07");
  });
});
