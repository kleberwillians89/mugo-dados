// @vitest-environment jsdom
import { afterEach, expect, test, vi } from "vitest";
vi.mock("./supabase", () => ({ isLocalAuthEnabled: () => true, getSupabaseBootstrapError: () => null, supabase: null }));
vi.mock("./activeClient", () => ({ getActiveClientId: () => "monthly-tenant", getActiveClientName: () => "fixture", getActiveClientConfigurationWarning: () => null }));
import { getMediaMonthly } from "./api";
afterEach(() => vi.unstubAllGlobals());
test("monthly envia janela e days reais 7/30/90, sem days=3650 implícito", async () => {
  const fetch = vi.fn(async () => new Response(JSON.stringify({ ok: true, months: [] }), { status: 200, headers: { "Content-Type": "application/json" } }));
  vi.stubGlobal("fetch", fetch);
  for (const [start, days] of [["2026-09-29", "7"], ["2026-09-06", "30"], ["2026-07-08", "90"]]) {
    await getMediaMonthly({ start, end: "2026-10-05" }, { clientId: "monthly-tenant", connectionId: "conn" });
    const url = new URL(String((fetch.mock.lastCall as unknown as [string])[0]), "https://fixture.invalid");
    expect(url.searchParams.get("start")).toBe(start);
    expect(url.searchParams.get("end")).toBe("2026-10-05");
    expect(url.searchParams.get("days")).toBe(days);
    expect(url.searchParams.get("client_id")).toBe("monthly-tenant");
    expect(url.searchParams.get("connection_id")).toBe("conn");
  }
});
