// @vitest-environment jsdom
import { afterEach, expect, test, vi } from "vitest";
vi.mock("./supabase", () => ({ isLocalAuthEnabled: () => true, getSupabaseBootstrapError: () => null, supabase: null }));
vi.mock("./activeClient", () => ({ getActiveClientId: () => "cura", getActiveClientName: () => "fixture", getActiveClientConfigurationWarning: () => null }));
import { getGa4Report } from "./api";
afterEach(() => vi.unstubAllGlobals());

const respond = (body: unknown) => vi.fn(async () => new Response(JSON.stringify(body), { status: 200, headers: { "Content-Type": "application/json" } }));

test("relatório GA4 traz compras por canal e mantém investimento/ROAS nulos quando não há vínculo seguro", async () => {
  const fetch = respond({
    ok: true, client_id: "cura", property_id: "p", period: { start: "2026-07-29", end: "2026-10-26", days: 90 },
    campaigns: [
      { campaign_name: "[CURAVINO] [Shopping] [Geral]", source: "google", medium: "cpc", source_medium: "google / cpc", sessions: 50,
        ecommerce_purchases: 4, purchase_revenue: 800, channel_group: "Paid Shopping", channel_group_label: "Shopping pago",
        channel_group_source: "ga4", investment: 200, investment_source: "google_ads", roas: 4 },
      { campaign_name: "(organic)", source: "google", medium: "organic", source_medium: "google / organic", sessions: 30,
        ecommerce_purchases: 1, purchase_revenue: 90, channel_group: "Organic Search", channel_group_label: "Busca orgânica",
        channel_group_source: "derivado", investment: null, investment_source: null, roas: null },
    ],
    acquisition: {
      has_purchases: true, notes: ["Receita atribuída pelo GA4"],
      channel_groups: [{ channel_group: "Paid Shopping", channel_group_label: "Shopping pago", channel_group_source: "ga4", sessions: 50, ecommerce_purchases: 4, purchase_revenue: 800 }],
    },
  });
  vi.stubGlobal("fetch", fetch);
  const report = await getGa4Report({ start: "2026-07-29", end: "2026-10-26", days: 90 }, { clientId: "cura" });
  const url = new URL(String((fetch.mock.lastCall as unknown as [string])[0]), "https://fixture.invalid");
  expect(url.searchParams.get("days")).toBe("90");
  expect(url.searchParams.get("client_id")).toBe("cura");
  expect(report.campaigns[0]).toMatchObject({ channel_group_label: "Shopping pago", investment: 200, investment_source: "google_ads", roas: 4 });
  expect(report.campaigns[1]).toMatchObject({ channel_group_source: "derivado", investment: null, investment_source: null, roas: null });
  expect(report.acquisition.has_purchases).toBe(true);
  expect(report.acquisition.channel_groups[0]).toMatchObject({ channel_group: "Paid Shopping", ecommerce_purchases: 4, purchase_revenue: 800 });
});

test("backend antigo, sem acquisition: estado vazio sem quebrar", async () => {
  vi.stubGlobal("fetch", respond({ ok: true, client_id: "cura", property_id: "p", campaigns: [{ campaign_name: "x", sessions: 3 }] }));
  const report = await getGa4Report(30, { clientId: "cura" });
  expect(report.acquisition).toEqual({ channel_groups: [], has_purchases: false, notes: [] });
  expect(report.campaigns[0]).toMatchObject({ investment: null, roas: null, channel_group: null });
});
